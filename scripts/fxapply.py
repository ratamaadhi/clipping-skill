"""Penerapan efek ke EDL (mode suggest) dan pembuatan pratinjau.

Modul ini mengimplementasikan:
- `load_report`: validasi laporan fxplan sesuai kontrak schema.
- `select`: pemfilteran item efek yang diterima.
- `apply_to_edl`: penambahan overlay ke EDL secara fungsional (murni).
- `check_fresh`: deteksi laporan basi terhadap durasi segmen EDL.
- `validate_edl_overlays`: validasi schema overlays[] tanpa jsonschema.
- `preview`: render pratinjau klip + lembar kontak tanpa menyentuh edl.json/out.
- `apply`: penerapan disetujui dengan cadangan bernomor dan penulisan atomik.
- `undo`: pemulihan edl.json dari cadangan terbaru dengan verifikasi hash.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from scripts import render
from scripts.lib import ffmpegbin, jsonio

__all__ = [
    "FxApplyError",
    "ApprovalRequired",
    "StaleReport",
    "load_report",
    "select",
    "apply_to_edl",
    "check_fresh",
    "validate_edl_overlays",
    "preview",
    "apply",
    "undo",
]

ALLOWED_OVERLAY_KEYS = {
    "type",
    "renderer",
    "start",
    "end",
    "left",
    "right",
    "slot",
    "rect",
    "props",
}

ALLOWED_RECT_KEYS = {"x", "y", "w", "h"}


class FxApplyError(ValueError):
    """Galat umum operasi fxapply."""


class ApprovalRequired(FxApplyError):
    """Penerapan ke EDL membutuhkan persetujuan eksplisit (approve=True)."""


class StaleReport(FxApplyError):
    """Laporan fxplan sudah basi terhadap EDL saat ini."""


def _validate_overlay_dict(ov: Any, clip_id: str, item_id: str | None = None) -> None:
    """Validasi struktur overlay menurut schema/edl.schema.json tanpa jsonschema."""
    ctx_name = f"Klip '{clip_id}'" + (f" item '{item_id}'" if item_id else "")
    if not isinstance(ov, dict):
        raise FxApplyError(f"{ctx_name}: overlay harus berupa object/dict")

    undeclared = set(ov.keys()) - ALLOWED_OVERLAY_KEYS
    if undeclared:
        raise FxApplyError(
            f"{ctx_name}: overlay memiliki kunci tidak sah: {sorted(undeclared)}"
        )

    if "type" not in ov or not isinstance(ov["type"], str) or not ov["type"]:
        raise FxApplyError(f"{ctx_name}: overlay kehilangan kunci wajib 'type'")

    if "renderer" in ov and ov["renderer"] not in ("ffmpeg", "remotion"):
        raise FxApplyError(
            f"{ctx_name}: overlay memiliki 'renderer' tidak sah: '{ov['renderer']}'"
        )

    for num_key in ("start", "end"):
        if num_key in ov:
            val = ov[num_key]
            if not isinstance(val, (int, float)) or isinstance(val, bool) or val < 0:
                raise FxApplyError(
                    f"{ctx_name}: overlay memiliki '{num_key}' tidak valid (harus angka >= 0): {val}"
                )

    for str_key in ("left", "right", "slot"):
        if str_key in ov and not isinstance(ov[str_key], str):
            raise FxApplyError(
                f"{ctx_name}: overlay memiliki '{str_key}' tidak valid (harus string)"
            )

    if "props" in ov and not isinstance(ov["props"], dict):
        raise FxApplyError(f"{ctx_name}: overlay memiliki 'props' tidak valid (harus object)")

    if "rect" in ov and ov["rect"] is not None:
        rect = ov["rect"]
        if not isinstance(rect, dict):
            raise FxApplyError(f"{ctx_name}: overlay memiliki 'rect' tidak valid (harus object)")
        undeclared_rect = set(rect.keys()) - ALLOWED_RECT_KEYS
        if undeclared_rect:
            raise FxApplyError(
                f"{ctx_name}: overlay rect memiliki kunci tidak sah: {sorted(undeclared_rect)}"
            )
        for req in ("x", "y", "w", "h"):
            if req not in rect:
                raise FxApplyError(f"{ctx_name}: overlay rect kehilangan '{req}'")
            v = rect[req]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise FxApplyError(f"{ctx_name}: overlay rect.{req} bukan angka")
        if rect["w"] < 0 or rect["h"] < 0:
            raise FxApplyError(f"{ctx_name}: overlay rect w dan h harus >= 0")


def load_report(path: str | Path) -> dict[str, Any]:
    """Membaca dan memeriksa laporan fxplan sesuai kontrak schema."""
    p = Path(path)
    if not p.is_file():
        raise FxApplyError(f"Berkas laporan tidak ditemukan: {p}")

    try:
        report = jsonio.read_json(p)
    except Exception as exc:
        raise FxApplyError(f"Gagal memuat JSON laporan dari '{p}': {exc}") from exc

    if not isinstance(report, dict):
        raise FxApplyError("Laporan harus berupa JSON object")

    for req_key in ("version", "edl", "plan", "clips", "summary"):
        if req_key not in report:
            raise FxApplyError(f"Laporan kehilangan kunci wajib '{req_key}'")

    summary = report["summary"]
    if not isinstance(summary, dict):
        raise FxApplyError("Kunci 'summary' di laporan harus berupa object")
    for s_key in ("accepted", "accepted_with_warnings", "rejected"):
        if s_key not in summary:
            raise FxApplyError(f"Kunci 'summary' kehilangan '{s_key}'")

    clips = report["clips"]
    if not isinstance(clips, list):
        raise FxApplyError("Kunci 'clips' di laporan harus berupa list")

    for clip in clips:
        if not isinstance(clip, dict):
            raise FxApplyError("Item dalam 'clips' harus berupa object")
        for ck in ("clip_id", "duration", "items"):
            if ck not in clip:
                raise FxApplyError(f"Clip di laporan kehilangan kunci wajib '{ck}'")
        clip_id = str(clip["clip_id"])
        items = clip["items"]
        if not isinstance(items, list):
            raise FxApplyError(f"Klip '{clip_id}': 'items' harus berupa list")

        for item in items:
            if not isinstance(item, dict):
                raise FxApplyError(f"Klip '{clip_id}': item efek harus berupa object")
            item_id = str(item.get("id", "<unknown>"))
            for ik in ("id", "status", "errors", "warnings", "reason", "overlay"):
                if ik not in item:
                    raise FxApplyError(
                        f"Klip '{clip_id}' item '{item_id}': kehilangan kunci wajib '{ik}'"
                    )

            st = item["status"]
            if st not in ("accepted", "accepted_with_warnings", "rejected"):
                raise FxApplyError(
                    f"Klip '{clip_id}' item '{item_id}': status '{st}' tidak sah"
                )

            if st == "rejected":
                if item["overlay"] is not None:
                    raise FxApplyError(
                        f"Klip '{clip_id}' item '{item_id}': status 'rejected' tetapi overlay bukan null"
                    )
            else:
                if not isinstance(item["overlay"], dict):
                    raise FxApplyError(
                        f"Klip '{clip_id}' item '{item_id}': status '{st}' tetapi overlay bernilai null/tidak valid"
                    )
                _validate_overlay_dict(item["overlay"], clip_id, item_id)

    return report


def select(
    report: dict[str, Any],
    *,
    only: list[str] | None = None,
    include_warnings: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """Peta clip_id -> daftar entri {id, overlay, reason} untuk item yang diterima."""
    valid_statuses = (
        {"accepted", "accepted_with_warnings"}
        if include_warnings
        else {"accepted"}
    )

    all_items_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for clip in report.get("clips", []):
        cid = str(clip["clip_id"])
        for item in clip.get("items", []):
            iid = str(item["id"])
            all_items_by_id[iid] = (cid, item)

    if only is not None:
        for requested_id in only:
            if requested_id not in all_items_by_id:
                raise FxApplyError(f"Item id '{requested_id}' tidak ditemukan di laporan")
            cid, item = all_items_by_id[requested_id]
            st = item.get("status")
            if st == "rejected":
                raise FxApplyError(
                    f"Item id '{requested_id}' berstatus 'rejected' dan tidak dapat dipilih"
                )
            if st not in valid_statuses:
                raise FxApplyError(
                    f"Item id '{requested_id}' berstatus '{st}' (include_warnings={include_warnings}) dan tidak dapat dipilih"
                )

    result: dict[str, list[dict[str, Any]]] = {}
    for clip in report.get("clips", []):
        cid = str(clip["clip_id"])
        selected_for_clip: list[dict[str, Any]] = []
        for item in clip.get("items", []):
            iid = str(item["id"])
            if only is not None and iid not in only:
                continue
            if item.get("status") not in valid_statuses:
                continue
            selected_for_clip.append({
                "id": iid,
                "overlay": copy.deepcopy(item["overlay"]),
                "reason": str(item.get("reason", "")),
            })
        if selected_for_clip:
            result[cid] = selected_for_clip

    return result


def _is_same_overlay(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Bandingkan dua overlay menurut (type, start, end, props, rect) untuk idempotensi."""
    if a.get("type") != b.get("type"):
        return False
    if not math.isclose(float(a.get("start", 0.0)), float(b.get("start", 0.0)), abs_tol=1e-3):
        return False
    if not math.isclose(float(a.get("end", 0.0)), float(b.get("end", 0.0)), abs_tol=1e-3):
        return False
    if a.get("props") != b.get("props"):
        return False
    if a.get("rect") != b.get("rect"):
        return False
    return True


def apply_to_edl(
    edl: dict[str, Any],
    selection: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Terapkan overlay ke EDL secara murni tanpa mengubah masukan."""
    new_edl = copy.deepcopy(edl)
    edl_clips = {str(c["id"]): c for c in new_edl.get("clips", [])}

    for cid in selection:
        if cid not in edl_clips:
            raise FxApplyError(f"Klip '{cid}' tidak ditemukan di EDL")

    info: dict[str, Any] = {"added": [], "skipped": []}

    for cid, items in selection.items():
        clip = edl_clips[cid]
        if "overlays" not in clip or clip["overlays"] is None:
            clip["overlays"] = []
        existing_overlays: list[dict[str, Any]] = clip["overlays"]

        for item in items:
            candidate = copy.deepcopy(item["overlay"])
            if any(_is_same_overlay(candidate, ex) for ex in existing_overlays):
                info["skipped"].append(item["id"])
            else:
                existing_overlays.append(candidate)
                info["added"].append(item["id"])

        clip["overlays"].sort(key=lambda o: float(o.get("start", 0.0)))

    return new_edl, info


def check_fresh(edl: dict[str, Any], report: dict[str, Any]) -> None:
    """Pastikan durasi klip di laporan cocok dengan EDL saat ini (toleransi 0,01 s)."""
    edl_clips = {str(c["id"]): c for c in edl.get("clips", [])}
    for rclip in report.get("clips", []):
        cid = str(rclip["clip_id"])
        if cid not in edl_clips:
            raise StaleReport(f"Klip '{cid}' ada di laporan tetapi hilang di EDL")
        clip = edl_clips[cid]
        segs = clip.get("segments") or []
        edl_dur = sum(float(s["src_end"]) - float(s["src_start"]) for s in segs)
        rep_dur = float(rclip.get("duration", 0.0))
        if abs(edl_dur - rep_dur) > 0.01:
            raise StaleReport(
                f"Durasi klip '{cid}' di EDL ({edl_dur:.3f} s) berbeda dari laporan ({rep_dur:.3f} s) lebih dari 0.01 s"
            )


def validate_edl_overlays(edl: dict[str, Any]) -> None:
    """Validasi seluruh overlays[] di EDL terhadap schema tanpa jsonschema."""
    for clip in edl.get("clips", []):
        cid = str(clip.get("id", "<unknown>"))
        ovs = clip.get("overlays")
        if ovs is None:
            continue
        if not isinstance(ovs, list):
            raise FxApplyError(f"Klip '{cid}': overlays harus berupa list")
        for i, ov in enumerate(ovs):
            _validate_overlay_dict(ov, cid, f"overlay[{i}]")


def _generate_contact_sheet(
    preview_dir: Path,
    frames: list[tuple[dict[str, Any], Path, float]],
) -> tuple[Path, list[dict[str, Any]]]:
    """Susun lembar kontak PNG dari frame yang diekstrak dengan ffmpeg."""
    cs_png = preview_dir / "contact_sheet.png"
    n_frames = len(frames)
    if n_frames == 0:
        raise FxApplyError("Tidak ada frame untuk lembar kontak")

    extracted_pngs: list[Path] = []
    try:
        for i, (finfo, clip_out, t_sample) in enumerate(frames):
            frame_png = preview_dir / f".frame_{i:03d}_{finfo['id']}.png"
            cmd = [
                ffmpegbin.resolve(),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{t_sample:.3f}",
                "-i",
                str(clip_out),
                "-frames:v",
                "1",
                str(frame_png),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                raise FxApplyError(
                    f"Gagal mengekstrak frame untuk '{finfo['id']}': {proc.stderr}"
                )
            extracted_pngs.append(frame_png)

        if n_frames == 1:
            shutil.copy2(extracted_pngs[0], cs_png)
        else:
            cols = math.ceil(math.sqrt(n_frames))
            rows = math.ceil(n_frames / cols)
            cmd = [
                ffmpegbin.resolve(),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
            ]
            filter_labels = []
            for i, p in enumerate(extracted_pngs):
                cmd.extend(["-i", str(p)])
                filter_labels.append(f"[{i}:v]")
            fc = (
                f"{''.join(filter_labels)}concat=n={n_frames}:v=1:a=0,"
                f"tile=layout={cols}x{rows}:color=black[out]"
            )
            cmd.extend(["-filter_complex", fc, "-map", "[out]", "-frames:v", "1", str(cs_png)])
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                raise FxApplyError(f"Gagal menyusun lembar kontak: {proc.stderr}")
    finally:
        for p in extracted_pngs:
            p.unlink(missing_ok=True)

    return cs_png, [f[0] for f in frames]


def preview(
    work: str | Path,
    report: dict[str, Any] | str | Path,
    *,
    only: list[str] | None = None,
    include_warnings: bool = True,
    fps: float | None = None,
) -> dict[str, Any]:
    """Render pratinjau efek ke <work>/fx_preview tanpa menulis edl.json atau <work>/out/."""
    work_dir = Path(work).resolve()
    edl_path = work_dir / "edl.json"
    if not edl_path.is_file():
        raise FxApplyError(f"Berkas EDL tidak ditemukan: {edl_path}")

    edl = jsonio.read_json(edl_path)
    if isinstance(report, (str, Path)):
        rep = load_report(report)
    elif isinstance(report, dict):
        rep = report
    else:
        raise FxApplyError("Laporan harus berupa dict atau path")

    check_fresh(edl, rep)
    selection = select(rep, only=only, include_warnings=include_warnings)
    total_selected = sum(len(v) for v in selection.values())
    if total_selected == 0:
        raise FxApplyError("Tidak ada item efek yang dipilih untuk pratinjau")

    new_edl, _ = apply_to_edl(edl, selection)
    validate_edl_overlays(new_edl)

    preview_dir = (work_dir / "fx_preview").resolve()
    preview_dir.mkdir(parents=True, exist_ok=True)

    jsonio.write_json(preview_dir / "edl.fx_preview.json", new_edl)

    rendered_clips: dict[str, str] = {}
    frames_to_extract: list[tuple[dict[str, Any], Path, float]] = []

    for clip in new_edl.get("clips", []):
        cid = str(clip["id"])
        if cid not in selection or not selection[cid]:
            continue

        edl_salinan = copy.deepcopy(new_edl)
        src_path = Path(str(edl_salinan["source"]["path"])).expanduser()
        if not src_path.is_absolute():
            src_path = (work_dir / src_path).resolve()
        edl_salinan["source"]["path"] = str(src_path)

        out_clip = preview_dir / f"{cid}.fx_preview.mp4"
        render.render_clip(edl_salinan, clip, preview_dir, out_clip, preview=True)
        rendered_clips[cid] = str(out_clip)

        segs = clip.get("segments") or []
        clip_dur = sum(float(s["src_end"]) - float(s["src_start"]) for s in segs)

        for item in selection[cid]:
            ov = item["overlay"]
            start = float(ov.get("start", 0.0))
            end = float(ov.get("end", start + 1.0))
            t_mid = (start + end) / 2.0
            t_sample = max(0.0, min(t_mid, max(0.0, clip_dur - 0.05)))
            finfo = {
                "id": item["id"],
                "type": ov.get("type", ""),
                "time": round(t_sample, 3),
                "clip": cid,
            }
            frames_to_extract.append((finfo, out_clip, t_sample))

    cs_png, frames_meta = _generate_contact_sheet(preview_dir, frames_to_extract)
    jsonio.write_json(preview_dir / "contact_sheet.json", {"frames": frames_meta})

    return {
        "clips": rendered_clips,
        "contact_sheet": str(cs_png),
        "frames": frames_meta,
    }


def apply(
    work: str | Path,
    report: dict[str, Any] | str | Path,
    *,
    only: list[str] | None = None,
    include_warnings: bool = True,
    approve: bool = False,
) -> dict[str, Any]:
    """Terapkan overlay ke EDL setelah persetujuan eksplisit (approve=True)."""
    if not approve:
        raise ApprovalRequired(
            "Penerapan efek ke EDL memerlukan persetujuan eksplisit pengguna (approve=True)."
        )

    work_dir = Path(work).resolve()
    edl_path = work_dir / "edl.json"
    if not edl_path.is_file():
        raise FxApplyError(f"Berkas EDL tidak ditemukan: {edl_path}")

    orig_bytes = edl_path.read_bytes()
    orig_sha256 = hashlib.sha256(orig_bytes).hexdigest()
    edl = jsonio.read_json(edl_path)

    if isinstance(report, (str, Path)):
        rep = load_report(report)
    elif isinstance(report, dict):
        rep = report
    else:
        raise FxApplyError("Laporan harus berupa dict atau path")

    check_fresh(edl, rep)
    selection = select(rep, only=only, include_warnings=include_warnings)
    new_edl, info = apply_to_edl(edl, selection)
    validate_edl_overlays(new_edl)

    # Idempotensi: jika tidak ada yang baru ditambahkan
    if len(info["added"]) == 0:
        applied_file = work_dir / "fx_plan.applied.json"
        prev_backup = None
        if applied_file.is_file():
            try:
                prev_applied = jsonio.read_json(applied_file)
                prev_backup = prev_applied.get("backup")
            except Exception:
                pass
        return {
            "status": "already_applied",
            "added": [],
            "skipped": info["skipped"],
            "backup": prev_backup,
            "message": "Efek sudah diterapkan sebelumnya (tidak ada overlay baru yang ditambahkan)",
        }

    # Cari nama cadangan bernomor (tidak menimpa cadangan yang ada)
    backup_name = "edl.json.bak_fx"
    if (work_dir / backup_name).exists():
        idx = 1
        while (work_dir / f"edl.json.bak_fx.{idx}").exists():
            idx += 1
        backup_name = f"edl.json.bak_fx.{idx}"

    backup_path = work_dir / backup_name
    shutil.copy2(edl_path, backup_path)

    # Penulisan atomik edl.json menggunakan penulis yang sama dengan produk (jsonio.write_json)
    jsonio.write_json(edl_path, new_edl)
    new_sha256 = hashlib.sha256(edl_path.read_bytes()).hexdigest()

    applied_record = {
        "version": 1,
        "backup": backup_name,
        "sha256_before": orig_sha256,
        "sha256_after": new_sha256,
        "added": info["added"],
        "skipped": info["skipped"],
        "status": "applied",
        "applied_overlays": {
            cid: [
                item["overlay"]
                for item in selection.get(cid, [])
                if item["id"] in info["added"]
            ]
            for cid in selection
        },
    }
    jsonio.write_json(work_dir / "fx_plan.applied.json", applied_record)

    return {
        "status": "applied",
        "added": info["added"],
        "skipped": info["skipped"],
        "backup": backup_name,
        "message": f"Berhasil menerapkan {len(info['added'])} overlay ke EDL",
    }


def undo(work: str | Path, *, force: bool = False) -> dict[str, Any]:
    """Pulihkan edl.json dari cadangan terbaru yang tercatat di fx_plan.applied.json."""
    work_dir = Path(work).resolve()
    applied_path = work_dir / "fx_plan.applied.json"
    if not applied_path.is_file():
        raise FxApplyError(f"Catatan penerapan tidak ditemukan: {applied_path}")

    applied_info = jsonio.read_json(applied_path)
    backup_name = applied_info.get("backup")
    if not backup_name:
        raise FxApplyError("Nama berkas cadangan tidak tercatat di fx_plan.applied.json")

    backup_path = work_dir / backup_name
    if not backup_path.is_file():
        raise FxApplyError(f"Berkas cadangan '{backup_path}' tidak ditemukan")

    edl_path = work_dir / "edl.json"
    if not edl_path.is_file():
        raise FxApplyError(f"Berkas EDL tidak ditemukan: {edl_path}")

    current_sha256 = hashlib.sha256(edl_path.read_bytes()).hexdigest()
    recorded_sha256 = applied_info.get("sha256_after")

    if not force and recorded_sha256 and current_sha256 != recorded_sha256:
        raise FxApplyError(
            "EDL telah dimodifikasi sejak efek diterapkan (hash berbeda). Gunakan force=True untuk memaksakan pemulihan."
        )

    # Pulihkan byte-per-byte secara atomik
    backup_bytes = backup_path.read_bytes()
    fd, tmp = tempfile.mkstemp(dir=str(work_dir), prefix=".tmp_undo_", suffix=".json")
    try:
        with open(fd, "wb") as fh:
            fh.write(backup_bytes)
        os.replace(tmp, edl_path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

    applied_info["status"] = "undone"
    jsonio.write_json(applied_path, applied_info)

    return {
        "status": "undone",
        "restored_from": backup_name,
        "message": f"EDL berhasil dipulihkan dari cadangan '{backup_name}'",
    }

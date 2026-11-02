from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from . import fxcatalog
from . import fxfeatures
from . import kinetic
from . import layout
from . import presets
from . import presets_phone
from . import pullback
from .layout import Rect
from .lib.text import clean as clean_text

__all__ = [
    "load_plan",
    "report_markdown",
    "validate",
]


def load_plan(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Berkas rencana tidak ditemukan: {p}")
    with open(p, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Isi {p} harus berupa JSON objek")
    return data


def _kinetic_caption_blocks(captions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not captions:
        return []
    try:
        eff_caps = kinetic.effective_captions(captions)
    except Exception:
        eff_caps = captions
    if not eff_caps:
        return []

    try:
        font = kinetic._load_font(None)
    except Exception:
        return []

    center_y = float(layout.CAPTION_CANDIDATES_Y[0])
    blocks: list[dict[str, Any]] = []

    for i, cap in enumerate(eff_caps):
        words = cap.get("words") or []
        if not words:
            continue
        try:
            start, end = kinetic.display_window(eff_caps, i)
        except Exception:
            continue

        emphasis = cap.get("emphasis")
        emphasis_clean = clean_text(str(emphasis)) if emphasis else ""
        targets: list[float] = []
        accented = False
        for w in words:
            w_text = str(w.get("w", w.get("word", "")))
            if (
                emphasis_clean
                and not accented
                and clean_text(w_text) == emphasis_clean
            ):
                targets.append(kinetic.SCALE_EMPHASIS)
                accented = True
            else:
                targets.append(kinetic.SCALE_END)
        scales = [t / 100.0 for t in targets]

        try:
            positions = kinetic.layout_phrase(
                [{"w": str(w.get("w", w.get("word", "")))} for w in words],
                font,
                84.0,
                center_y=center_y,
                scales=scales,
            )
        except Exception:
            continue

        lines: dict[int, list[dict[str, Any]]] = {}
        for pos in positions:
            lines.setdefault(int(pos["line"]), []).append(pos)
        if not lines:
            continue

        block_w = max(
            max(p["x"] + p["w"] / 2.0 for p in line)
            - min(p["x"] - p["w"] / 2.0 for p in line)
            for line in lines.values()
        )
        block_h = len(lines) * kinetic.LINE_HEIGHT_EM * 84.0
        try:
            rect = layout.caption_rect(block_w, block_h, center_y)
        except Exception:
            continue

        blocks.append({
            "start": float(start),
            "end": float(end),
            "rect": rect,
        })
    return blocks


def validate(
    edl: dict[str, Any],
    plan: dict[str, Any],
    *,
    candidates: dict[str, Any] | None = None,
    fps: float = 30.0,
) -> dict[str, Any]:
    if not isinstance(edl, dict):
        raise ValueError("edl harus berupa dict")
    if not isinstance(plan, dict):
        raise ValueError("plan harus berupa dict")

    edl_clips_map: dict[str, dict[str, Any]] = {}
    for c in edl.get("clips") or []:
        if isinstance(c, dict) and "id" in c:
            edl_clips_map[str(c["id"])] = c

    summary_accepted = 0
    summary_warn = 0
    summary_rejected = 0

    report_clips: list[dict[str, Any]] = []

    plan_clips = plan.get("clips") or []
    for plan_clip in plan_clips:
        if not isinstance(plan_clip, dict):
            continue
        clip_id = str(plan_clip.get("clip_id", ""))
        raw_items = plan_clip.get("items") or []

        if clip_id not in edl_clips_map:
            item_reports: list[dict[str, Any]] = []
            for it in raw_items:
                if not isinstance(it, dict):
                    continue
                it_id = str(it.get("id", ""))
                item_reports.append(
                    {
                        "id": it_id,
                        "status": "rejected",
                        "errors": [f"item '{it_id}': clip_id '{clip_id}' tidak ditemukan di EDL"],
                        "warnings": [],
                        "overlay": None,
                        "reason": str(it.get("reason", "")),
                        "moment": it.get("moment"),
                    }
                )
                summary_rejected += 1
            report_clips.append(
                {
                    "clip_id": clip_id,
                    "duration": 0.0,
                    "items": item_reports,
                }
            )
            continue

        edl_clip = edl_clips_map[clip_id]
        segments = edl_clip.get("segments") or []
        if segments:
            clip_dur = sum(
                float(s["src_end"]) - float(s["src_start"])
                for s in segments
                if "src_end" in s and "src_start" in s
            )
        else:
            clip_dur = float(edl_clip.get("duration", 0.0))
        clip_dur = max(0.0, round(clip_dur, 3))

        existing_overlays = edl_clip.get("overlays") or []
        punch = edl_clip.get("punch") or []
        reframe = edl_clip.get("reframe") or {}
        face_track = reframe.get("face_track")
        caption_blocks = _kinetic_caption_blocks(edl_clip.get("captions") or [])

        seen_ids: set[str] = set()
        dup_ids: set[str] = set()
        indexed_items: list[tuple[int, dict[str, Any]]] = []
        for orig_idx, it in enumerate(raw_items):
            if isinstance(it, dict):
                it_id = str(it.get("id", ""))
                if it_id in seen_ids:
                    dup_ids.add(it_id)
                seen_ids.add(it_id)
                indexed_items.append((orig_idx, it))

        def _sort_key(entry: tuple[int, dict[str, Any]]) -> tuple[float, int]:
            orig_idx, it = entry
            raw_s = it.get("start")
            if isinstance(raw_s, (int, float)) and not isinstance(raw_s, bool) and math.isfinite(raw_s):
                return (float(raw_s), orig_idx)
            return (999999.0, orig_idx)

        sorted_items = sorted(indexed_items, key=_sort_key)

        accepted_total = 0
        accepted_accent = 0
        accepted_transform = 0
        accepted_list: list[tuple[str, str, str, float, float, dict[str, Any] | None]] = []

        item_results_by_idx: dict[int, dict[str, Any]] = {}

        for orig_idx, it in sorted_items:
            it_id = str(it.get("id", f"item_{orig_idx}"))
            errors: list[str] = []
            warnings: list[str] = []
            reason = it.get("reason")
            moment = it.get("moment")
            eff_type = it.get("type")
            start = it.get("start")
            end = it.get("end")
            props = it.get("props")
            rect_in = it.get("rect")
            hook_flag = it.get("hook", False)

            if it_id in dup_ids:
                dup_count = sum(1 for _, item_dict in indexed_items if str(item_dict.get("id")) == it_id)
                if dup_count > 1:
                    errors.append(f"item '{it_id}': id tidak unik pada klip '{clip_id}'")

            if not isinstance(reason, str) or len(reason.strip()) == 0 or len(reason) > 200:
                errors.append(f"item '{it_id}': reason wajib diisi (1-200 karakter)")

            if not isinstance(eff_type, str) or eff_type not in fxcatalog.names():
                errors.append(f"item '{it_id}': tipe '{eff_type}' tidak ada di katalog efek")
                eff_meta = None
            else:
                eff_meta = fxcatalog.get(eff_type)

            start_f = 0.0
            end_f = 0.0
            if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(float(start)):
                errors.append(f"item '{it_id}': start harus angka berhingga, dapat {start!r}")
            else:
                start_f = float(start)

            if isinstance(end, bool) or not isinstance(end, (int, float)) or not math.isfinite(float(end)):
                errors.append(f"item '{it_id}': end harus angka berhingga, dapat {end!r}")
            else:
                end_f = float(end)

            if not errors:
                if start_f < 0.0:
                    errors.append(f"item '{it_id}': start ({start_f}) harus >= 0")
                if end_f <= start_f:
                    errors.append(f"item '{it_id}': end ({end_f}) harus > start ({start_f})")
                if end_f > clip_dur + 1e-6:
                    errors.append(f"item '{it_id}': end ({end_f:.2f}s) melebihi durasi klip ({clip_dur:.2f}s)")

            if errors:
                item_results_by_idx[orig_idx] = {
                    "id": it_id,
                    "status": "rejected",
                    "errors": errors,
                    "warnings": warnings,
                    "overlay": None,
                    "reason": str(reason or ""),
                    "moment": moment,
                }
                summary_rejected += 1
                continue

            assert eff_meta is not None
            duration = end_f - start_f
            budget_class = eff_meta["budget_class"]

            overlay_candidate: dict[str, Any] = {
                "type": eff_type,
                "start": start_f,
                "end": end_f,
                "props": props if isinstance(props, dict) else {},
            }
            if rect_in is not None and isinstance(rect_in, dict):
                overlay_candidate["rect"] = rect_in

            if eff_type == "pullback":
                p_props = props if isinstance(props, dict) else {}
                p_shrink = float(p_props.get("shrink", pullback.DEFAULT_SHRINK))
                p_grow = float(p_props.get("grow", pullback.DEFAULT_GROW))
                stable_phase = duration - p_shrink - p_grow
                if stable_phase < fxcatalog.MIN_STABLE_SECONDS_PULLBACK - 1e-6:
                    errors.append(
                        f"item '{it_id}': fase stabil pullback ({stable_phase:.2f}s) < "
                        f"minimum ({fxcatalog.MIN_STABLE_SECONDS_PULLBACK:.1f}s)"
                    )
                fake_clip = {
                    "duration": clip_dur,
                    "segments": [{"src_start": 0.0, "src_end": clip_dur}],
                    "overlays": [overlay_candidate],
                }
                try:
                    pb_plan, pb_warns = pullback.build(fake_clip, fps=float(fps))
                    if pb_plan is None:
                        errors.append(f"item '{it_id}': pullback di luar durasi klip ({clip_dur:.2f}s)")
                    else:
                        warnings.extend(pb_warns)
                except pullback.PullbackError as exc:
                    errors.append(f"item '{it_id}': {exc}")
                except Exception as exc:
                    errors.append(f"item '{it_id}': kesalahan validasi pullback: {exc}")
            else:
                try:
                    p_plan, p_warns = presets.REGISTRY[eff_type](
                        orig_idx, overlay_candidate, clip_dur, fps=float(fps)
                    )
                    if p_plan is None:
                        errors.append(f"item '{it_id}': jendela di luar durasi klip ({clip_dur:.2f}s)")
                    else:
                        warnings.extend(p_warns)
                except presets.PresetError as exc:
                    errors.append(f"item '{it_id}': {exc}")
                except Exception as exc:
                    errors.append(f"item '{it_id}': kesalahan validasi preset: {exc}")

            if start_f < fxcatalog.HOOK_WINDOW_SECONDS:
                if budget_class in ("card", "transform"):
                    if hook_flag is True:
                        warnings.append(
                            f"item '{it_id}': overlay {budget_class} dimulai di jendela hook "
                            f"({start_f:.2f}s < {fxcatalog.HOOK_WINDOW_SECONDS:.1f}s) dengan hook=true"
                        )
                    else:
                        errors.append(
                            f"item '{it_id}': overlay {budget_class} dilarang mulai di jendela hook "
                            f"({start_f:.2f}s < {fxcatalog.HOOK_WINDOW_SECONDS:.1f}s) tanpa hook: true"
                        )

            max_win = eff_meta["window"]["max"]
            if duration > max_win * 1.5 + 1e-6:
                errors.append(f"item '{it_id}': durasi ({duration:.2f}s) > 1.5x max katalog ({max_win * 1.5:.2f}s)")
            elif duration > max_win + 1e-6:
                warnings.append(f"item '{it_id}': durasi ({duration:.2f}s) melebihi max tipikal katalog ({max_win:.2f}s)")

            final_rect_dict: dict[str, Any] | None = None

            if budget_class == "card":
                req_size = fxcatalog.required_size(eff_type, props if isinstance(props, dict) else None)
                has_face_track = bool(face_track and isinstance(face_track, list))

                if rect_in is not None:
                    active_rect = None
                    try:
                        r_obj = Rect(rect_in["x"], rect_in["y"], rect_in["w"], rect_in["h"])
                        if r_obj.x < 0 or r_obj.y < 0 or r_obj.x + r_obj.w > 1080 or r_obj.y + r_obj.h > 1920:
                            errors.append(f"item '{it_id}': rect melewati batas kanvas 1080x1920")
                        else:
                            active_rect = r_obj
                            final_rect_dict = {
                                "x": round(r_obj.x, 1),
                                "y": round(r_obj.y, 1),
                                "w": round(r_obj.w, 1),
                                "h": round(r_obj.h, 1),
                            }
                            if req_size is not None:
                                req_w, req_h = req_size
                                if r_obj.h + 1e-9 < req_h:
                                    if eff_type == "checklist":
                                        item_count = len(props.get("items", [])) if isinstance(props, dict) and isinstance(props.get("items"), list) else 3
                                        errors.append(
                                            f"item '{it_id}': rect['h'] {r_obj.h:g} < tinggi yang dibutuhkan {req_h:g} "
                                            f"(2 x {presets.CARD_PAD_Y:g} padding + {presets.CARD_HEADER_H:g} header + "
                                            f"{item_count} baris x {presets.CARD_ROW_H:g}); kartu tidak boleh disusutkan"
                                        )
                                    elif eff_type == "phone_frame":
                                        line_count = len(props.get("lines", [])) if isinstance(props, dict) and isinstance(props.get("lines"), list) else 3
                                        errors.append(
                                            f"item '{it_id}': rect['h'] {r_obj.h:g} < tinggi yang dibutuhkan {req_h:g} "
                                            f"({presets_phone.PHONE_BASE_H:g} base + {line_count} baris x {presets_phone.PHONE_LINE_ROW_H:g}); "
                                            f"badan perangkat tidak boleh disusutkan"
                                        )
                                    elif eff_type == "ui_panel":
                                        thumbs = props.get("thumbs", presets.UI_DEFAULT_THUMBS) if isinstance(props, dict) else presets.UI_DEFAULT_THUMBS
                                        errors.append(
                                            f"item '{it_id}': rect['h'] {r_obj.h:g} < tinggi yang dibutuhkan {req_h:g} "
                                            f"({thumbs} thumbnail); kartu tidak boleh disusutkan"
                                        )
                                    elif eff_type == "chart_grow":
                                        has_title = bool(props.get("title")) if isinstance(props, dict) else False
                                        chart_req_h = presets._chart_required_height(has_title)
                                        errors.append(
                                            f"item '{it_id}': rect['h'] {r_obj.h:g} < tinggi yang dibutuhkan {chart_req_h:g}; kartu tidak boleh disusutkan"
                                        )
                                    else:
                                        errors.append(
                                            f"item '{it_id}': rect['h'] {r_obj.h:g} < tinggi yang dibutuhkan {req_h:g}; kartu tidak boleh disusutkan"
                                        )
                                if eff_type == "ui_panel":
                                    cols = min(props.get("thumbs", presets.UI_DEFAULT_THUMBS), 3) if isinstance(props, dict) else 3
                                    min_req_w = presets.UI_PAD_X * 2 + cols * presets.UI_THUMB_W + (cols - 1) * presets.UI_THUMB_GAP_X
                                    if r_obj.w + 1e-9 < min_req_w:
                                        errors.append(
                                            f"item '{it_id}': rect['w'] {r_obj.w:g} < lebar yang dibutuhkan {min_req_w:g} "
                                            f"untuk {cols} kolom thumbnail; thumbnail tidak muat"
                                        )
                    except Exception as exc:
                        errors.append(f"item '{it_id}': rect tidak sah: {exc}")

                    if not has_face_track:
                        warnings.append(f"item '{it_id}': tanpa face_track: tak terverifikasi")
                    else:
                        raw_shot_faces: list[Rect] = []
                        try:
                            all_shot_tuples = layout.shots(face_track, clip_dur)
                            for st0, st1, faces in all_shot_tuples:
                                if not (st1 <= start_f or st0 >= end_f):
                                    raw_shot_faces.extend(faces)
                        except Exception:
                            pass
                        max_scale = layout.max_punch_scale(punch, start_f, end_f)
                        zones = layout.forbidden_zones(raw_shot_faces, max_scale)
                        if active_rect is not None:
                            max_overlap_pct = 0.0
                            for z in zones:
                                if active_rect.intersects(z):
                                    ia = active_rect.intersection_area(z)
                                    pct = (ia / (active_rect.w * active_rect.h)) * 100.0
                                    if pct > max_overlap_pct:
                                        max_overlap_pct = pct
                            if max_overlap_pct > 0.0:
                                warnings.append(
                                    f"item '{it_id}': rect beririsan dengan zona wajah ({max_overlap_pct:.1f}% tumpang tindih)"
                                )
                else:
                    # rect_in is None
                    if not has_face_track:
                        errors.append(
                            f"item '{it_id}': tanpa face_track: layout kartu memerlukan face_track "
                            f"untuk verifikasi area bebas; beri rect eksplisit"
                        )
                    else:
                        shots_info = fxfeatures._analyze_shots(face_track, clip_dur)
                        overlapping_shots = [s for s in shots_info if not (s["t1"] <= start_f or s["t0"] >= end_f)]
                        is_close_up = any(s.get("shot_kind") == "close_up" for s in overlapping_shots)
                        if is_close_up:
                            errors.append(
                                f"item '{it_id}': close-up: tidak ada area bebas; beri rect eksplisit atau pilih zoom_through_text/pullback"
                            )
                        else:
                            raw_shot_faces = []
                            try:
                                all_shot_tuples = layout.shots(face_track, clip_dur)
                                for st0, st1, faces in all_shot_tuples:
                                    if not (st1 <= start_f or st0 >= end_f):
                                        raw_shot_faces.extend(faces)
                            except Exception:
                                pass
                            max_scale = layout.max_punch_scale(punch, start_f, end_f)
                            zones = layout.forbidden_zones(raw_shot_faces, max_scale)
                            target_size = req_size if req_size is not None else eff_meta.get("default_size")
                            overlapping_caps = [
                                cb["rect"] for cb in caption_blocks
                                if max(start_f, cb["start"]) < min(end_f, cb["end"])
                            ]
                            taken_rects = [
                                Rect(r["x"], r["y"], r["w"], r["h"])
                                for _, _, _, a_s, a_e, r in accepted_list
                                if r is not None and max(start_f, a_s) < min(end_f, a_e)
                            ]
                            scan_x = 60.0
                            if eff_type == "phone_frame":
                                side = props.get("side", "right") if isinstance(props, dict) else "right"
                                if side == "left":
                                    scan_x = float(presets_phone.PHONE_DEFAULT_X_LEFT)
                                elif side == "right" or side is None:
                                    scan_x = float(presets_phone.PHONE_DEFAULT_X_RIGHT)
                                else:
                                    scan_x = 60.0

                            placed = layout.scan_free_rect(
                                target_size,
                                zones,
                                caption_rects=overlapping_caps,
                                taken=taken_rects,
                                x=scan_x,
                                avoid_caption=True,
                            )
                            if placed is None:
                                w_int, h_int = int(round(target_size[0])), int(round(target_size[1]))
                                test_no_zones = layout.scan_free_rect(
                                    target_size,
                                    [],
                                    caption_rects=overlapping_caps,
                                    taken=taken_rects,
                                    x=scan_x,
                                    avoid_caption=True,
                                )
                                if test_no_zones is None:
                                    cause = "tak ada tempat di zona aman"
                                else:
                                    cause = "zona wajah menutup semua posisi"
                                errors.append(f"item '{it_id}': tidak ada area bebas untuk kartu {w_int}x{h_int}: {cause}")
                            else:
                                active_rect = placed
                                final_rect_dict = {
                                    "x": round(active_rect.x, 1),
                                    "y": round(active_rect.y, 1),
                                    "w": round(active_rect.w, 1),
                                    "h": round(active_rect.h, 1),
                                }
            elif rect_in is not None and isinstance(rect_in, dict):
                try:
                    r_obj = Rect(rect_in["x"], rect_in["y"], rect_in["w"], rect_in["h"])
                    final_rect_dict = {
                        "x": round(r_obj.x, 1),
                        "y": round(r_obj.y, 1),
                        "w": round(r_obj.w, 1),
                        "h": round(r_obj.h, 1),
                    }
                except Exception:
                    pass

            if not errors:
                for ex_idx, ex in enumerate(existing_overlays):
                    if not isinstance(ex, dict):
                        continue
                    if "start" in ex and "end" in ex:
                        ex_s = float(ex["start"])
                        ex_e = float(ex["end"])
                        if max(start_f, ex_s) < min(end_f, ex_e):
                            errors.append(
                                f"item '{it_id}': tumpang tindih dengan overlay EDL[{ex_idx}] "
                                f"({ex.get('type')}) pada [{ex_s:.2f}, {ex_e:.2f}]"
                            )
                            break
                        gap = start_f - ex_e if start_f >= ex_e else ex_s - end_f
                        if gap < fxcatalog.MIN_GAP_SECONDS - 1e-6:
                            errors.append(
                                f"item '{it_id}': jarak ({gap:.2f}s) < MIN_GAP "
                                f"({fxcatalog.MIN_GAP_SECONDS:.1f}s) terhadap overlay EDL[{ex_idx}]"
                            )
                            break

            if not errors:
                for acc_id, acc_type, acc_class, acc_s, acc_e, _ in accepted_list:
                    if max(start_f, acc_s) < min(end_f, acc_e):
                        errors.append(
                            f"item '{it_id}': tumpang tindih dengan item '{acc_id}' pada [{acc_s:.2f}, {acc_e:.2f}]"
                        )
                        break
                    gap = start_f - acc_e if start_f >= acc_e else acc_s - end_f
                    if gap < fxcatalog.MIN_GAP_SECONDS - 1e-6:
                        errors.append(
                            f"item '{it_id}': jarak ({gap:.2f}s) < MIN_GAP "
                            f"({fxcatalog.MIN_GAP_SECONDS:.1f}s) terhadap item '{acc_id}'"
                        )
                        break
                    if budget_class == "card" and acc_class == "card":
                        if gap < fxcatalog.CARD_MIN_GAP_SECONDS - 1e-6:
                            errors.append(
                                f"item '{it_id}': jarak kartu ({gap:.2f}s) < CARD_MIN_GAP "
                                f"({fxcatalog.CARD_MIN_GAP_SECONDS:.1f}s) terhadap item '{acc_id}'"
                            )
                            break

            if not errors:
                if accepted_total >= fxcatalog.MAX_OVERLAYS_PER_CLIP:
                    errors.append(
                        f"item '{it_id}': melebihi anggaran maksimum overlay per klip ({fxcatalog.MAX_OVERLAYS_PER_CLIP})"
                    )
                elif budget_class == "accent" and accepted_accent >= fxcatalog.MAX_ACCENT_PER_CLIP:
                    errors.append(
                        f"item '{it_id}': melebihi anggaran kelas accent ({fxcatalog.MAX_ACCENT_PER_CLIP})"
                    )
                elif budget_class == "transform" and accepted_transform >= fxcatalog.MAX_TRANSFORM_PER_CLIP:
                    errors.append(
                        f"item '{it_id}': melebihi anggaran kelas transform ({fxcatalog.MAX_TRANSFORM_PER_CLIP})"
                    )

            if not errors:
                if start_f <= 0.5:
                    warnings.append(f"item '{it_id}': overlay dimulai dekat awal klip ({start_f:.2f}s <= 0.5s)")
                if start_f >= clip_dur - 0.5:
                    warnings.append(f"item '{it_id}': overlay dimulai dekat akhir klip ({start_f:.2f}s >= {clip_dur - 0.5:.2f}s)")

                for p in punch:
                    if isinstance(p, dict) and "t" in p:
                        pt = float(p["t"])
                        if abs(start_f - pt) <= 0.3 or abs(end_f - pt) <= 0.3:
                            warnings.append(f"item '{it_id}': berimpit (+/-0.3s) dengan event punch di t={pt:.2f}s")
                            break

                if moment is not None and candidates is not None:
                    cand_clip = next((c for c in candidates.get("clips", []) if c.get("clip_id") == clip_id), None)
                    if cand_clip is not None:
                        cand_moments = {m.get("id") for m in cand_clip.get("moments", []) if isinstance(m, dict)}
                        if moment not in cand_moments:
                            warnings.append(f"item '{it_id}': momen '{moment}' tidak ditemukan di kandidat klip '{clip_id}'")

                if (budget_class == "card" or eff_type == "phone_frame") and final_rect_dict is not None:
                    try:
                        ov_rect = Rect(
                            final_rect_dict["x"],
                            final_rect_dict["y"],
                            final_rect_dict["w"],
                            final_rect_dict["h"],
                        )
                        for cb in caption_blocks:
                            if max(start_f, cb["start"]) < min(end_f, cb["end"]):
                                if ov_rect.intersects(cb["rect"]):
                                    ia = ov_rect.intersection_area(cb["rect"])
                                    ca = cb["rect"].w * cb["rect"].h
                                    pct = (ia / ca) * 100.0 if ca > 0 else 0.0
                                    warnings.append(
                                        f"item '{it_id}': rect beririsan dengan kotak caption "
                                        f"({pct:.1f}% kotak caption) pada frasa [{cb['start']:.2f}s - {cb['end']:.2f}s]"
                                    )
                    except Exception:
                        pass

            clean_overlay: dict[str, Any] = {
                "type": eff_type,
                "start": round(start_f, 3),
                "end": round(end_f, 3),
                "props": copy.deepcopy(props) if isinstance(props, dict) else {},
            }
            if final_rect_dict is not None:
                clean_overlay["rect"] = final_rect_dict

            # Invarian wajib: setiap item accepted/accepted_with_warnings harus lolos pembuat preset ASLI
            # dengan overlay PERSIS seperti yang akan ditulis (yaitu pembuat dijalankan lagi pada overlay final setelah rect ditentukan).
            if not errors:
                if eff_type == "pullback":
                    fake_clip = {
                        "duration": clip_dur,
                        "segments": [{"src_start": 0.0, "src_end": clip_dur}],
                        "overlays": [clean_overlay],
                    }
                    try:
                        pb_plan, pb_warns = pullback.build(fake_clip, fps=float(fps))
                        if pb_plan is None:
                            errors.append(f"item '{it_id}': pullback di luar durasi klip ({clip_dur:.2f}s)")
                        else:
                            for w in pb_warns:
                                if w not in warnings:
                                    warnings.append(w)
                    except pullback.PullbackError as exc:
                        errors.append(f"item '{it_id}': {exc}")
                    except Exception as exc:
                        errors.append(f"item '{it_id}': kesalahan validasi pullback: {exc}")
                else:
                    try:
                        p_plan, p_warns = presets.REGISTRY[eff_type](
                            orig_idx, clean_overlay, clip_dur, fps=float(fps)
                        )
                        if p_plan is None:
                            errors.append(f"item '{it_id}': jendela di luar durasi klip ({clip_dur:.2f}s)")
                        else:
                            for w in p_warns:
                                if w not in warnings:
                                    warnings.append(w)
                    except presets.PresetError as exc:
                        errors.append(f"item '{it_id}': {exc}")
                    except Exception as exc:
                        errors.append(f"item '{it_id}': kesalahan validasi preset: {exc}")

            if errors:
                item_results_by_idx[orig_idx] = {
                    "id": it_id,
                    "status": "rejected",
                    "errors": errors,
                    "warnings": warnings,
                    "overlay": None,
                    "reason": str(reason or ""),
                    "moment": moment,
                }
                summary_rejected += 1
            else:
                accepted_total += 1
                if budget_class == "accent":
                    accepted_accent += 1
                elif budget_class == "transform":
                    accepted_transform += 1

                accepted_list.append((it_id, eff_type, budget_class, start_f, end_f, final_rect_dict))

                if warnings:
                    status = "accepted_with_warnings"
                    summary_warn += 1
                else:
                    status = "accepted"
                    summary_accepted += 1

                item_results_by_idx[orig_idx] = {
                    "id": it_id,
                    "status": status,
                    "errors": [],
                    "warnings": warnings,
                    "overlay": clean_overlay,
                    "reason": str(reason or ""),
                    "moment": moment,
                }

        ordered_items = [item_results_by_idx[i] for i in range(len(raw_items)) if i in item_results_by_idx]
        report_clips.append(
            {
                "clip_id": clip_id,
                "duration": clip_dur,
                "items": ordered_items,
            }
        )

    return {
        "version": 1,
        "edl": "edl.json",
        "plan": "fx_plan.json",
        "clips": report_clips,
        "summary": {
            "accepted": summary_accepted,
            "accepted_with_warnings": summary_warn,
            "rejected": summary_rejected,
        },
    }


def report_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    acc = summary.get("accepted", 0)
    warn = summary.get("accepted_with_warnings", 0)
    rej = summary.get("rejected", 0)
    total = acc + warn + rej

    lines: list[str] = [
        "# Laporan Pengesahan Rencana Efek (fxplan)",
        "",
        f"**Ringkasan**: {acc} diterima, {warn} diterima dengan peringatan, {rej} ditolak (total {total} usulan)",
        "",
    ]

    for c in report.get("clips", []):
        cid = c.get("clip_id", "?")
        dur = c.get("duration", 0.0)
        items = c.get("items", [])
        lines.append(f"## Klip `{cid}` (durasi {dur:.1f}s)")
        if not items:
            lines.append("Tidak ada item usulan efek.")
            lines.append("")
            continue

        lines.append("| ID | Status | Tipe & Jendela | Alasan Usulan | Catatan / Masalah |")
        lines.append("|---|---|---|---|---|")

        for it in items:
            it_id = it.get("id", "?")
            st = it.get("status", "?")
            ov = it.get("overlay")
            reason = it.get("reason", "")
            errs = it.get("errors", [])
            warns = it.get("warnings", [])

            if ov:
                type_win = f"{ov.get('type')} [{ov.get('start', 0.0):.2f}s - {ov.get('end', 0.0):.2f}s]"
            else:
                type_win = "-"

            notes_parts: list[str] = []
            if errs:
                notes_parts.extend([f"ERROR: {e}" for e in errs])
            if warns:
                notes_parts.extend([f"WARN: {w}" for w in warns])
            note_str = "<br>".join(notes_parts) if notes_parts else "OK"

            lines.append(f"| `{it_id}` | `{st}` | {type_win} | {reason} | {note_str} |")
        lines.append("")

    return "\n".join(lines)

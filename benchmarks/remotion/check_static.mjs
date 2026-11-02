/**
 * Bukti numerik bahwa fase hold statis: poseAt() dievaluasi untuk SEMUA frame,
 * lalu fase hold harus identik nilai-demi-nilai (dan identik referensi) dengan
 * SETTLED. Tidak membuka browser; ini pelengkap hash piksel di holdframe.py.
 *
 * Node >= 22.18 menjalankan .ts apa adanya (type stripping).
 */
import { poseAt, SETTLED } from "./src/pose.ts";

const cfg = { fps: 30, durationInFrames: 120, inFrames: 15, exitFrames: 15 };
const phases = { enter: [], hold: [], exit: [] };
for (let f = 0; f < cfg.durationInFrames; f++) {
  const p = poseAt(f, cfg);
  phases[p.phase].push([f, p]);
}

const key = (p) => JSON.stringify([p.rise, p.blur, p.scale, p.opacity]);
const holdKeys = new Set(phases.hold.map(([, p]) => key(p)));
const sameRef = phases.hold.every(([, p]) => p === SETTLED);
const notNaN = Object.values(phases).flat().every(([, p]) => [p.rise, p.blur, p.scale, p.opacity].every(Number.isFinite));

// Pose di dalam enter/exit harus berbeda dari hold dan antar-frame (animasi benar-benar jalan).
const enterDistinct = new Set(phases.enter.map(([, p]) => key(p))).size;
const exitDistinct = new Set(phases.exit.map(([, p]) => key(p))).size;
const enterLast = phases.enter.at(-1)[1];
const exitFirst = phases.exit[0][1];

console.log(
  JSON.stringify({
    frames: cfg.durationInFrames,
    enter_frames: phases.enter.length,
    hold_frames: phases.hold.length,
    exit_frames: phases.exit.length,
    hold_distinct_poses: holdKeys.size,
    hold_all_same_reference: sameRef,
    all_finite: notNaN,
    enter_distinct_poses: enterDistinct,
    exit_distinct_poses: exitDistinct,
    first_hold_frame: phases.hold[0][0],
    last_hold_frame: phases.hold.at(-1)[0],
    enter_last_pose: enterLast,
    exit_first_pose_differs_from_hold: key(exitFirst) !== key(SETTLED),
    ok: holdKeys.size === 1 && sameRef && notNaN && phases.hold.length === 90 && enterDistinct === 15 && exitDistinct === 15,
  }),
);

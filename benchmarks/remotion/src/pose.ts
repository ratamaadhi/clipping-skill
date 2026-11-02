import { Easing, interpolate, spring } from "remotion";

/**
 * Pose kartu sebagai fungsi MURNI dari nomor frame, tanpa React.
 *
 * Dipisah dari CardPhases.tsx supaya sifat statis fase `hold` bisa diperiksa
 * sebagai angka (benchmarks/remotion/check_static.mjs), bukan hanya dari
 * hash piksel: di fase hold fungsi ini tidak membaca `frame` sama sekali.
 */

export type Phase = "enter" | "hold" | "exit";

export interface PhaseCfg {
  fps: number;
  durationInFrames: number;
  inFrames: number;
  exitFrames: number;
}

export interface Pose {
  readonly phase: Phase;
  readonly rise: number;
  readonly blur: number;
  readonly scale: number;
  readonly opacity: number;
}

/** Pose saat diam. Satu objek konstan; fase hold selalu mengembalikan objek ini. */
export const SETTLED: Pose = Object.freeze({
  phase: "hold",
  rise: 0,
  blur: 0,
  scale: 1,
  opacity: 1,
});

export const phaseOf = (frame: number, c: PhaseCfg): Phase => {
  if (frame < c.inFrames) return "enter";
  if (frame >= c.durationInFrames - c.exitFrames) return "exit";
  return "hold";
};

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

export const poseAt = (frame: number, c: PhaseCfg): Pose => {
  const phase = phaseOf(frame, c);

  if (phase === "enter") {
    // durationInFrames meregangkan pegas supaya tenang di frame inFrames.
    const s = spring({
      frame,
      fps: c.fps,
      durationInFrames: c.inFrames,
      config: { damping: 14, mass: 0.8, stiffness: 120 },
    });
    return {
      phase,
      rise: interpolate(s, [0, 1], [80, 0]),
      blur: interpolate(s, [0, 1], [14, 0], clamp),
      scale: interpolate(s, [0, 1], [0.82, 1]),
      opacity: interpolate(s, [0, 0.4], [0, 1], clamp),
    };
  }

  if (phase === "exit") {
    // k = 0..exitFrames-1; t mencapai 1 tepat di frame terakhir (opacity 0).
    const k = frame - (c.durationInFrames - c.exitFrames);
    const t = Easing.in(Easing.quad)((k + 1) / c.exitFrames);
    return {
      phase,
      rise: interpolate(t, [0, 1], [0, -40]),
      blur: interpolate(t, [0, 1], [0, 10]),
      scale: interpolate(t, [0, 1], [1, 0.9]),
      opacity: interpolate(t, [0, 1], [1, 0]),
    };
  }

  return SETTLED;
};

import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { poseAt } from "./pose";

/**
 * Kartu dengan tiga fase eksplisit untuk uji "hold frame":
 *   enter  frame 0..inFrames-1                   pegas masuk
 *   hold   inFrames..durasi-exitFrames-1          DIAM TOTAL
 *   exit   durasi-exitFrames..durasi-1            keluar
 *
 * Beda dari Card.tsx: tidak ada sinyal kontinu (glow sinus). Di fase hold,
 * `frame` hanya dipakai untuk memilih fase di poseAt(); semua nilai gaya
 * datang dari konstanta SETTLED, jadi pohon React-nya sama untuk setiap
 * frame hold. Beban render sengaja sama dengan Card.tsx (blur, bayangan,
 * backdrop-filter, dua teks) supaya hasilnya mewakili overlay nyata.
 */
export const CardPhases: React.FC<{
  label1?: string;
  label2?: string;
  transparent?: boolean;
  inFrames?: number;
  exitFrames?: number;
}> = ({ label1 = "MOTION", label2 = "TIER 2", transparent = true, inFrames = 15, exitFrames = 15 }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const pose = poseAt(frame, { fps, durationInFrames, inFrames, exitFrames });

  const unit = Math.min(width, height);

  return (
    <AbsoluteFill style={{ backgroundColor: transparent ? "transparent" : "#0b0d12" }}>
      {transparent ? null : (
        <AbsoluteFill
          style={{
            background: "radial-gradient(circle at 50% 38%, rgba(0,229,255,0.35) 0%, rgba(11,13,18,0) 60%)",
          }}
        />
      )}
      <AbsoluteFill
        style={{
          justifyContent: "center",
          alignItems: "center",
          filter: `blur(${pose.blur}px)`,
          opacity: pose.opacity,
        }}
      >
        <div
          style={{
            transform: `translateY(${pose.rise}px) scale(${pose.scale})`,
            width: unit * 0.76,
            padding: unit * 0.07,
            borderRadius: unit * 0.05,
            background: "linear-gradient(160deg, rgba(255,255,255,0.16), rgba(255,255,255,0.04))",
            boxShadow: "0 30px 80px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.35)",
            border: "1px solid rgba(255,255,255,0.22)",
            backdropFilter: "blur(18px)",
            fontFamily: "sans-serif",
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: unit * 0.1, fontWeight: 800, color: "#ffffff", letterSpacing: -1 }}>
            {label1}
          </div>
          <div style={{ fontSize: unit * 0.055, fontWeight: 600, color: "#00E5FF", marginTop: unit * 0.02 }}>
            {label2}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

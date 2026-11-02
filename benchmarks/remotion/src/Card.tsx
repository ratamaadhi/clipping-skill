import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

/**
 * Adegan kartu: rounded rect + bayangan + blur + dua teks + spring.
 * Dipilih karena mewakili beban nyata motion graphics (blur dan bayangan adalah
 * bagian termahal), bukan kotak kosong yang membuat hasil terlihat lebih baik
 * daripada kenyataan.
 */
export const Card: React.FC<{ label1?: string; label2?: string; transparent?: boolean }> = ({
  label1 = "MOTION",
  label2 = "TIER 2",
  transparent = false,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  const s = spring({ frame, fps, config: { damping: 14, mass: 0.8, stiffness: 120 } });
  const rise = interpolate(s, [0, 1], [80, 0]);
  const blur = interpolate(s, [0, 1], [14, 0]);
  const scale = interpolate(s, [0, 1], [0.82, 1]);
  const glow = 0.35 + 0.25 * Math.sin(frame / 9);

  const unit = Math.min(width, height);

  return (
    <AbsoluteFill style={{ backgroundColor: transparent ? "transparent" : "#0b0d12" }}>
      {transparent ? null : (
        <AbsoluteFill
          style={{
            background: `radial-gradient(circle at 50% 38%, rgba(0,229,255,${glow}) 0%, rgba(11,13,18,0) 60%)`,
          }}
        />
      )}
      <AbsoluteFill
        style={{ justifyContent: "center", alignItems: "center", filter: `blur(${blur}px)` }}
      >
        <div
          style={{
            transform: `translateY(${rise}px) scale(${scale})`,
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
          <div style={{ fontSize: unit * 0.10, fontWeight: 800, color: "#ffffff", letterSpacing: -1 }}>
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

import React from "react";
import { Composition } from "remotion";
import { Card } from "./Card";
import { CardPhases } from "./CardPhases";

/**
 * Tiga ukuran sebagai komposisi terpisah, bukan satu komposisi dengan
 * calculateMetadata: lebih sederhana dan tidak bergantung pada perilaku
 * versi tertentu. Ukuran kecil menentukan apakah overlay boleh dirender
 * sebesar bbox-nya (biaya PNG sebanding jumlah piksel).
 */
export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Card1080" component={Card} durationInFrames={150} fps={30} width={1080} height={1920} />
    <Composition id="Card600" component={Card} durationInFrames={150} fps={30} width={1080} height={600} />
    <Composition id="Card300" component={Card} durationInFrames={150} fps={30} width={540} height={300} />
    {/* uji hold frame: 120 frame, masuk 15 / diam 90 / keluar 15, latar transparan */}
    <Composition id="Phases1080" component={CardPhases} durationInFrames={120} fps={30} width={1080} height={1920} />
    <Composition id="Phases600" component={CardPhases} durationInFrames={120} fps={30} width={1080} height={600} />
    <Composition id="Phases300" component={CardPhases} durationInFrames={120} fps={30} width={540} height={300} />
    {/* varian transparan: satu-satunya cara sah menguji alpha PNG */}
    <Composition
      id="CardAlpha"
      component={Card}
      durationInFrames={150}
      fps={30}
      width={540}
      height={300}
      defaultProps={{ transparent: true }}
    />
  </>
);

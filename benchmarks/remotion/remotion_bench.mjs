/**
 * Spike Langkah 1: render satu komposisi ke deret PNG, laporkan waktu sebagai JSON.
 *
 * Sengaja PNG (bukan mp4): yang diukur adalah biaya komposisi Chromium, tanpa
 * noise encoder. PNG juga membuktikan alpha benar-benar ada (warna RGBA).
 *
 * Dipanggil oleh benchmarks/remotion_bench.py, yang mengukur memori pohon proses
 * dan waktu dinding dari luar — jadi angka di sini tidak saling mengandalkan.
 */
import fs from "node:fs";
import path from "node:path";
import { bundle } from "@remotion/bundler";
import { renderFrames, selectComposition } from "@remotion/renderer";

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || "true"];
  }),
);

const entry = path.resolve("src/index.ts");
const compositionId = args.id ?? "Card1080";
const outputDir = path.resolve(args.out ?? "frames");
const concurrency = Number(args.concurrency ?? 1);
const frames = Number(args.frames ?? 150);
const browserExecutable = args.browser || undefined;

const t0 = process.hrtime.bigint();
const serveUrl = await bundle({ entryPoint: entry, publicDir: null });
const tBundle = process.hrtime.bigint();

const composition = await selectComposition({
  serveUrl,
  id: compositionId,
  browserExecutable,
});

const result = await renderFrames({
  composition,
  serveUrl,
  outputDir,
  imageFormat: "png",
  concurrency,
  browserExecutable,
  frameRange: [0, frames - 1],
  onStart: () => {},
});

const tEnd = process.hrtime.bigint();

// Versi ini tidak mengembalikan daftar frame dari renderFrames; hitung dari direktori.
const rendered = fs.readdirSync(outputDir).filter((f) => f.endsWith(".png")).length;

const ms = (a, b) => Number(b - a) / 1e6;

console.log(
  JSON.stringify({
    id: compositionId,
    width: composition.width,
    height: composition.height,
    frames: rendered,
    concurrency,
    bundle_ms: ms(t0, tBundle),
    render_ms: ms(tBundle, tEnd),
    total_ms: ms(t0, tEnd),
  }),
);

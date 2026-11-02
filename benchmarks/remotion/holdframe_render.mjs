/**
 * Render sebagian frame sebuah komposisi ke PNG (uji hold frame).
 *
 * Beda dari remotion_bench.mjs (yang dibiarkan utuh): menerima daftar frame
 * arbitrer, mis. --frames=0-15,105-119, dalam SATU panggilan renderFrames, dan
 * memakai satu browser untuk selectComposition + renderFrames. Mode penuh dan
 * subset lewat jalur kode yang sama; hanya daftar frame yang berbeda.
 *
 * Keluaran: satu baris JSON (rincian waktu dari dalam proses). Waktu dinding
 * yang dilaporkan ke pengguna diukur dari luar oleh benchmarks/holdframe.py.
 */
import fs from "node:fs";
import path from "node:path";
import { bundle } from "@remotion/bundler";
import { openBrowser, renderFrames, selectComposition } from "@remotion/renderer";

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || "true"];
  }),
);

const parseFrames = (spec) =>
  spec.split(",").flatMap((part) => {
    const [a, b = a] = part.split("-").map(Number);
    return Array.from({ length: b - a + 1 }, (_, i) => a + i);
  });

const entry = path.resolve("src/index.ts");
const compositionId = args.id;
const outputDir = path.resolve(args.out);
const concurrency = Number(args.concurrency ?? 1);
const frames = parseFrames(args.frames);
const browserExecutable = args.browser || undefined;
if (!compositionId || !args.out || !args.frames) {
  console.error("pakai: --id=<komposisi> --out=<dir> --frames=0-15,105-119 [--concurrency=1] [--browser=<path>]");
  process.exit(2);
}

const ms = (a, b) => Number(b - a) / 1e6;
const now = () => process.hrtime.bigint();

const t0 = now();
const serveUrl = await bundle({ entryPoint: entry, publicDir: null });
const t1 = now();

const browser = await openBrowser("chrome", { browserExecutable });
const t2 = now();

const composition = await selectComposition({
  serveUrl,
  id: compositionId,
  browserExecutable,
  puppeteerInstance: browser,
});
const t3 = now();

await renderFrames({
  composition,
  serveUrl,
  outputDir,
  imageFormat: "png",
  concurrency,
  browserExecutable,
  puppeteerInstance: browser,
  frames,
  onStart: () => {},
});
const t4 = now();

await browser.close({ silent: true });
const t5 = now();

const files = fs.readdirSync(outputDir).filter((f) => f.endsWith(".png")).sort();

console.log(
  JSON.stringify({
    id: compositionId,
    width: composition.width,
    height: composition.height,
    duration_in_frames: composition.durationInFrames,
    requested_frames: frames.length,
    rendered_files: files.length,
    first_file: files[0],
    last_file: files.at(-1),
    concurrency,
    bundle_ms: ms(t0, t1),
    browser_open_ms: ms(t1, t2),
    select_ms: ms(t2, t3),
    render_ms: ms(t3, t4),
    close_ms: ms(t4, t5),
    total_ms: ms(t0, t5),
  }),
);

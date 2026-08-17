/**
 * Deterministic creative rendering: HTML -> headless Chrome -> PNG / MP4.
 *
 * No image model touches these. A diffusion model asked for "a chart showing
 * a 15% risk reduction" will produce something that looks like a chart and
 * says something else, and the whole point of this system is that every
 * number on screen traces to a quoted sentence in a real abstract. So the
 * chart is drawn from the data, by code.
 *
 * Motion is driven by an explicit setFrame(p), p = 0..1, captured frame by
 * frame. CSS animations drift between captures; a pure function of p cannot.
 *
 *   node render.mjs carousel spec.json out/       -> out/slide-1.png ...
 *   node render.mjs reel      spec.json out/      -> out/reel.mp4
 */

import { spawn } from "node:child_process";
import { mkdir, readFile, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import puppeteer from "puppeteer";

const HERE = dirname(fileURLToPath(import.meta.url));

const FORMATS = {
  carousel: { template: "carousel.html", width: 1080, height: 1350 },
  reel: { template: "reel.html", width: 1080, height: 1920, seconds: 15, fps: 30 },
};

function run(command, args) {
  return new Promise((ok, fail) => {
    const child = spawn(command, args, { stdio: ["ignore", "ignore", "pipe"] });
    let stderr = "";
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("close", (code) =>
      code === 0 ? ok() : fail(new Error(`${command} exited ${code}: ${stderr.slice(-600)}`))
    );
  });
}

async function openPage(browser, format) {
  const page = await browser.newPage();
  await page.setViewport({
    width: format.width,
    height: format.height,
    deviceScaleFactor: 1,
  });
  // Tell the template a render is in progress so it does not paint its own
  // demo content, which would flash into the first captured frame.
  await page.evaluateOnNewDocument(() => {
    window.__RENDERING__ = true;
  });
  const template = pathToFileURL(join(HERE, "templates", format.template)).href;
  await page.goto(template, { waitUntil: "load" });
  return page;
}

async function renderCarousel(spec, outDir) {
  const format = FORMATS.carousel;
  const browser = await puppeteer.launch({ args: ["--font-render-hinting=none"] });
  try {
    const page = await openPage(browser, format);
    const count = await page.evaluate((payload) => window.setSlides(payload), spec);
    if (!count) throw new Error("template rendered no slides");

    const files = [];
    for (let index = 0; index < count; index += 1) {
      const box = await page.evaluate((i) => {
        const slide = document.querySelectorAll(".slide")[i];
        slide.scrollIntoView();
        const rect = slide.getBoundingClientRect();
        return { x: rect.x + window.scrollX, y: rect.y + window.scrollY,
                 width: rect.width, height: rect.height };
      }, index);
      const file = join(outDir, `slide-${index + 1}.png`);
      await page.screenshot({ path: file, clip: box });
      files.push(file);
    }
    return files;
  } finally {
    await browser.close();
  }
}

async function renderReel(spec, outDir) {
  const format = FORMATS.reel;
  const seconds = spec.seconds ?? format.seconds;
  const fps = spec.fps ?? format.fps;
  const total = Math.round(seconds * fps);
  const frameDir = join(outDir, ".frames");
  await rm(frameDir, { recursive: true, force: true });
  await mkdir(frameDir, { recursive: true });

  const browser = await puppeteer.launch({ args: ["--font-render-hinting=none"] });
  try {
    const page = await openPage(browser, format);
    await page.evaluate((payload) => window.setSpec(payload), spec);

    for (let frame = 0; frame < total; frame += 1) {
      // total - 1 so the final frame is exactly p = 1: the last frame is the
      // one that gets used as a thumbnail and it must be the finished state.
      const p = total === 1 ? 1 : frame / (total - 1);
      await page.evaluate((value) => window.setFrame(value), p);
      await page.screenshot({
        path: join(frameDir, `f-${String(frame).padStart(5, "0")}.png`),
      });
    }

    const output = join(outDir, "reel.mp4");
    await run("ffmpeg", [
      "-y", "-loglevel", "error",
      "-framerate", String(fps),
      "-i", join(frameDir, "f-%05d.png"),
      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
      "-movflags", "+faststart",
      output,
    ]);
    await rm(frameDir, { recursive: true, force: true });
    return [output];
  } finally {
    await browser.close();
  }
}

async function main() {
  const [kind, specPath, outPath] = process.argv.slice(2);
  if (!FORMATS[kind]) {
    console.error(`usage: node render.mjs <${Object.keys(FORMATS).join("|")}> <spec.json> <outDir>`);
    process.exit(2);
  }

  const outDir = resolve(outPath ?? "out");
  await mkdir(outDir, { recursive: true });
  const spec = specPath && specPath !== "-"
    ? JSON.parse(await readFile(specPath, "utf8"))
    : null;

  if (!spec) {
    console.error("a spec file is required; creatives are never rendered from defaults");
    process.exit(2);
  }

  const files = kind === "carousel"
    ? await renderCarousel(spec, outDir)
    : await renderReel(spec, outDir);

  for (const file of files) console.log(file);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});

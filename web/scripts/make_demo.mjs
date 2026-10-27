// Records a captioned walkthrough of the LIVE site (real data) following the PRD demo script.
// Run:  node scripts/make_demo.mjs [baseUrl] [outDir]      -> writes follow-demo.webm
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.argv[2];
if (!BASE) { console.error("usage: node scripts/make_demo.mjs <live-url> [outDir]"); process.exit(1); }
const OUT = path.resolve(process.argv[3] || "../demo");
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: OUT, size: { width: 1440, height: 900 } } });
const p = await ctx.newPage();
const wait = (s) => p.waitForTimeout(s * 1000);

async function caption(text, step) {
  await p.evaluate(({ text, step }) => {
    let el = document.getElementById("demo-cap");
    if (!el) {
      el = document.createElement("div");
      el.id = "demo-cap";
      el.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:99999;background:#232323;color:#fff;padding:14px 24px;font:500 21px/1.25 Inter Tight,system-ui,sans-serif;letter-spacing:-0.02em;display:flex;gap:18px;align-items:baseline;border-top:3px solid #9fffc9";
      document.body.appendChild(el);
    }
    el.innerHTML = `<span style="font:12px ui-monospace,Consolas,monospace;color:#9fffc9;text-transform:uppercase;white-space:nowrap">${step}</span><span>${text}</span>`;
  }, { text, step });
}
async function go(url, ready) {
  await p.goto(BASE + url, { waitUntil: "load" });
  if (ready) await p.waitForSelector(ready, { timeout: 60000 }).catch(() => {});
}
async function scrollTo(selector, offset = 70, secs = 1.2) {
  await p.evaluate(({ selector, offset }) => {
    const e = document.querySelector(selector);
    if (e) window.scrollTo({ top: e.getBoundingClientRect().top + window.scrollY - offset, behavior: "smooth" });
  }, { selector, offset });
  await wait(secs);
}
async function scrollBy(px, secs = 1.2) {
  await p.evaluate((px) => window.scrollBy({ top: px, behavior: "smooth" }), px);
  await wait(secs);
}
const clickText = async (t) => { await p.getByText(t, { exact: false }).first().click().catch(() => {}); };

// 1. the problem
await go("/", ".lp-metric, .stat, .hero-a");
await wait(2);
await caption("Strike's BTC perps volume is a sliver of Binance's and Hyperliquid's, so the book is thin. Follow measures exactly how thin.", "1 / 7 · The problem");
await wait(7);
await caption("Live widget: what a $10k, $50k or $100k market order costs right now on Strike, Binance and Hyperliquid.", "1 / 7 · The problem");
for (const t of ["$10k", "$50k", "$100k", "$50k"]) { await clickText(t); await wait(1.6); }
await scrollBy(700, 2);

// 2. the live scorecard
await go("/scorecard", ".card .value");
await wait(3);
await caption("The scorecard leads with Strike's own liquidity: spread uptime, depth within 10 bps, slippage at size, cancel/fill.", "2 / 7 · Live scorecard");
await wait(7);
await scrollTo("h2:nth-of-type(2), .tablewrap", 90, 2);
await caption("Then the gap: the same metrics on Binance and Hyperliquid, recorded the same way. The gap is the size of the opportunity.", "2 / 7 · Live scorecard");
await wait(8);

// 3. trend
await scrollTo(".controls:nth-of-type(3)", 90, 1);
await caption("Trend view: how Strike's liquidity moved over the recorded hours. Gaps in recording are drawn as gaps, never filled in.", "3 / 7 · Trend");
await clickText("Last 48 h");
await wait(5);
await clickText("1 hour");
await wait(5);

// 4. L3-only
await scrollTo("h2:last-of-type", 70, 1);
await p.evaluate(() => { const e = [...document.querySelectorAll("h2")].find((x) => x.textContent.includes("only L3")); if (e) window.scrollTo({ top: e.getBoundingClientRect().top + window.scrollY - 70, behavior: "smooth" }); });
await wait(2);
await caption("Only L3 shows this: orders placed versus cancelled versus filled, how fast depth recovers after a big taker order, and what price does next.", "4 / 7 · What only L3 shows");
await wait(9);
await scrollBy(520, 1.5);
await caption("Strike refreshes its whole book once a second, so almost every event is a cancel and a re-place. That finding is written up in FEEDBACK.md.", "4 / 7 · What only L3 shows");
await wait(8);

// 5. incentive designer
await go("/designer", "button.primary");
await wait(2);
await caption("The incentive designer: enter a maker rebate, a number of Quoters and a quote size.", "5 / 7 · Incentive designer");
await wait(3);
await p.locator("label.field input").nth(0).fill("1.5");
await p.locator("label.field input").nth(1).fill("4");
await p.locator("label.field input").nth(2).fill("75000");
await wait(1.5);
await p.locator("button.primary").click();
await wait(3);
await caption("It reruns depth and slippage on Strike's real current book. The banner and printed assumptions say: a what-if, not a forecast.", "5 / 7 · Incentive designer");
await scrollBy(450, 1.5);
await wait(9);

// 6. dataset and methodology
await go("/data");
await wait(3);
await caption("Everything recorded is open: Parquet files per table per day, a schema, and a read-only API, with every outage marked.", "6 / 7 · Open dataset");
await wait(8);
await go("/methodology");
await wait(2);
await caption("The methodology page defines every metric and states the limits: BTC only, thin volume, hours actually recorded, and the sampling fix.", "6 / 7 · Methodology");
await wait(5);
await scrollBy(900, 2);
await wait(6);

// 7. close
await go("/", ".hero-a");
await wait(2);
await scrollTo("#findings", 70, 2);
await caption("How thin, versus whom, and what a programme would buy: Follow gives the Strike team a number to track before they spend STRIKE.", "7 / 7 · The pitch");
await wait(9);

await ctx.close();
const vids = fs.readdirSync(OUT).filter((f) => f.endsWith(".webm"));
const newest = vids.map((f) => ({ f, t: fs.statSync(path.join(OUT, f)).mtimeMs })).sort((a, b) => b.t - a.t)[0].f;
fs.renameSync(path.join(OUT, newest), path.join(OUT, "follow-demo.webm"));
await browser.close();
console.log("wrote", path.join(OUT, "follow-demo.webm"));

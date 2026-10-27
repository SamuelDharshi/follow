"use client";
import { useEffect, useRef } from "react";

// Ordered (Bayer 8x8) dithering of an animated scalar field, drawn as chunky ink pixels like a halftone print.
const BAYER8 = (() => {
  const grow = (m: number[][]) => {
    const n = m.length, out: number[][] = Array.from({ length: n * 2 }, () => Array(n * 2).fill(0));
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const v = m[y][x] * 4;
      out[y][x] = v; out[y][x + n] = v + 2; out[y + n][x] = v + 3; out[y + n][x + n] = v + 1;
    }
    return out;
  };
  return grow(grow([[0, 2], [3, 1]]));
})();

function rng(seed: number) {
  let s = seed >>> 0 || 1;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

export type Level = [number, number];
export type BookData = { bids: Level[]; asks: Level[] } | null;

/**
 * mode "book": cumulative depth of the real recorded Strike book, breathing in time.
 * mode "noise": seeded smooth field (texture) that drifts.
 */
export default function Halftone({ mode = "noise", seed = 1, book, px = 2, ink = "#232323", fps = 18 }: {
  mode?: "book" | "noise"; seed?: number; book?: BookData; px?: number; ink?: string; fps?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const bookRef = useRef<BookData>(book ?? null);
  bookRef.current = book ?? null;

  useEffect(() => {
    const canvas = ref.current!;
    const parent = canvas.parentElement!;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const r = rng(seed);
    const blobs = Array.from({ length: 7 }, () => ({ x: r(), y: r(), s: 0.12 + r() * 0.3, a: 0.4 + r() * 0.6, sp: 0.15 + r() * 0.35, ph: r() * 6.28, rad: 0.04 + r() * 0.08 }));
    const waves = Array.from({ length: 3 }, () => ({ kx: 2 + r() * 6, ky: 2 + r() * 6, p: r() * 6.28, a: 0.08 + r() * 0.1, sp: 0.2 + r() * 0.4 }));
    const rgb = (c: string) => [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)];
    const A = rgb(ink);
    // pointer interaction, ink only: dots get denser around the cursor and the effect fades behind it
    const ptr = { x: -1, y: -1, lx: -1, ly: -1 };
    let trail = new Float32Array(0), trailLive = false;
    let w = 0, h = 0, img: ImageData | null = null, field = new Float32Array(0);
    let visible = true, raf = 0, last = 0, t = r() * 10;

    const size = () => {
      const box = parent.getBoundingClientRect();
      const eff = Math.max(px, Math.ceil(Math.sqrt((box.width * box.height) / 170000)));
      w = Math.max(8, Math.floor(box.width / eff)); h = Math.max(8, Math.floor(box.height / eff));
      canvas.width = w; canvas.height = h;
      img = canvas.getContext("2d")!.createImageData(w, h);
      trail = new Float32Array(w * h); trailLive = false;
    };

    const stamp = (cx: number, cy: number) => {
      const R = h * 0.22, sg = R * 0.55, reach = Math.ceil(R * 1.7);
      const x0 = Math.max(0, Math.floor(cx - reach)), x1 = Math.min(w - 1, Math.ceil(cx + reach));
      const y0 = Math.max(0, Math.floor(cy - reach)), y1 = Math.min(h - 1, Math.ceil(cy + reach));
      for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
        const g = Math.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * sg * sg)));
        const k = y * w + x;
        if (g > trail[k]) trail[k] = g;
      }
      trailLive = true;
    };

    const stepTrail = () => {
      if (ptr.x >= 0) {
        const cx = ptr.x * w, cy = ptr.y * h;
        if (ptr.lx < 0) stamp(cx, cy);
        else {
          const dist = Math.hypot(cx - ptr.lx, cy - ptr.ly), n = Math.max(1, Math.ceil(dist / (h * 0.06)));
          for (let i = 1; i <= n; i++) stamp(ptr.lx + ((cx - ptr.lx) * i) / n, ptr.ly + ((cy - ptr.ly) * i) / n);
        }
        ptr.lx = cx; ptr.ly = cy;
      } else ptr.lx = -1;
      if (!trailLive) return;
      let live = false;
      for (let k = 0; k < trail.length; k++) { const v = trail[k] * 0.972; trail[k] = v < 0.03 ? 0 : v; if (trail[k] > 0) live = true; }
      trailLive = live;
    };

    const bookField = () => {
      const bk = bookRef.current;
      if (!bk || !bk.bids.length || !bk.asks.length) return null;
      const mid = (bk.bids[0][0] + bk.asks[0][0]) / 2, span = 60;
      const cum = (levels: Level[]) => {
        const pts: [number, number][] = []; let c = 0;
        for (const [p, s] of levels) { const d = Math.abs(p - mid) / mid * 1e4; if (d > span) break; c += p * s; pts.push([d, c]); }
        return { pts, max: c };
      };
      const B = cum(bk.bids), A = cum(bk.asks), mx = Math.max(B.max, A.max, 1);
      const at = (pts: [number, number][], d: number) => { let v = 0; for (const [bp, c] of pts) { if (bp <= d) v = c; else break; } return v; };
      return { B, A, mx, at, span };
    };

    const draw = () => {
      if (!img) return;
      const bf = mode === "book" ? bookField() : null;
      const bl = blobs.map((b) => ({ x: b.x + Math.sin(t * b.sp + b.ph) * b.rad, y: b.y + Math.cos(t * b.sp * 0.8 + b.ph) * b.rad, s: b.s, a: b.a }));
      const data = img.data;
      const cw = (w + 1) >> 1, chh = (h + 1) >> 1;
      if (field.length !== cw * chh) field = new Float32Array(cw * chh);
      const [ir, ig, ib] = A;
      // 1) the smooth field, one sample per 2x2 pixels
      for (let cy = 0; cy < chh; cy++) {
        const fy = (cy * 2) / h;
        for (let cx = 0; cx < cw; cx++) {
          const fx = (cx * 2) / w;
          let v: number;
          if (bf) {
            const d = Math.abs(fx - 0.5) * 2 * bf.span;
            const depth = Math.sqrt((fx < 0.5 ? bf.at(bf.B.pts, d) : bf.at(bf.A.pts, d)) / bf.mx);
            const top = 0.1 + depth * 0.7 + Math.sin(t * 0.8 + fx * 9) * 0.015;
            let n = 0;
            for (let i = 0; i < 4; i++) n += bl[i].a * Math.exp(-(((fx - bl[i].x) ** 2 + (fy - bl[i].y) ** 2) / (2 * bl[i].s * bl[i].s))) * 0.12;
            v = 1 - fy < top ? Math.min(1, 0.12 + (0.3 + 0.7 * (1 - fy)) * 0.42 + n) : 0.02 + n * 0.5;
          } else {
            v = 0;
            for (let i = 0; i < 7; i++) v += bl[i].a * Math.exp(-(((fx - bl[i].x) ** 2 + (fy - bl[i].y) ** 2) / (2 * bl[i].s * bl[i].s))) * 0.5;
            for (let i = 0; i < 3; i++) v += waves[i].a * 0.6 * Math.sin(waves[i].kx * fx * 6.28 + waves[i].ky * fy * 3.14 + waves[i].p + t * waves[i].sp);
          }
          field[cy * cw + cx] = v;
        }
      }
      // 2) dither every pixel against the Bayer matrix; ink dots only
      for (let y = 0; y < h; y++) {
        const row = (y >> 1) * cw;
        for (let x = 0; x < w; x++) {
          const v = field[row + (x >> 1)] + trail[y * w + x] * 1.1;   // pointer pushes extra ink into the dither
          const thr = (BAYER8[y & 7][x & 7] + 0.5) / 64;
          const i = (y * w + x) * 4;
          data[i] = ir; data[i + 1] = ig; data[i + 2] = ib; data[i + 3] = v > thr ? 255 : 0;
        }
      }
      canvas.getContext("2d")!.putImageData(img, 0, 0);
    };

    size();
    draw();
    const ro = new ResizeObserver(() => { size(); draw(); });
    ro.observe(parent);
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; }, { threshold: 0 });
    io.observe(parent);
    const move = (e: PointerEvent) => { const b = parent.getBoundingClientRect(); ptr.x = (e.clientX - b.left) / b.width; ptr.y = (e.clientY - b.top) / b.height; };
    const leave = () => { ptr.x = -1; };
    if (!reduce) { parent.addEventListener("pointermove", move); parent.addEventListener("pointerleave", leave); }
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      if (!visible || now - last < 1000 / fps) return;
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now; t += dt;
      stepTrail();
      draw();
    };
    if (!reduce) raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); parent.removeEventListener("pointermove", move); parent.removeEventListener("pointerleave", leave); };
  }, [mode, seed, px, ink, fps]);

  return <canvas ref={ref} className="halftone" aria-hidden="true" />;
}

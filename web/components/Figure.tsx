"use client";
import { useEffect, useRef } from "react";

export type FigureKind = "orbit" | "sunburst" | "globe" | "loops" | "rings" | "wave" | "bars" | "grid";

const NS = "http://www.w3.org/2000/svg";
const C = 100, R = 92;
const el = (parent: Element, tag: string, attrs: Record<string, string | number> = {}) => {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, String(attrs[k]));
  parent.appendChild(e);
  return e;
};

type Anim = (t: number) => void;

function build(svg: SVGSVGElement, kind: FigureKind): Anim {
  const S = "rgba(255,255,255,0.9)";
  const base = { fill: "none", stroke: S, "stroke-width": 0.7 };
  switch (kind) {
    case "orbit": {
      // two dotted rings drifting against a thin solid one, two markers riding the orbit
      const a = el(svg, "circle", { ...base, r: 84, "stroke-dasharray": "0.8 3.2" });
      const b = el(svg, "circle", { ...base, r: 88, "stroke-dasharray": "0.8 3.2" });
      const c = el(svg, "circle", { ...base, r: 86 });
      const m1 = el(svg, "rect", { width: 5, height: 5, fill: S });
      const m2 = el(svg, "rect", { width: 5, height: 5, fill: S });
      const core = el(svg, "rect", { width: 4, height: 4, fill: S, x: C - 2, y: C - 2 });
      void core;
      return (t) => {
        const ax = Math.cos(t * 0.35) * 7, ay = Math.sin(t * 0.35) * 7;
        a.setAttribute("cx", String(C + ax)); a.setAttribute("cy", String(C + ay));
        b.setAttribute("cx", String(C - ax)); b.setAttribute("cy", String(C - ay));
        c.setAttribute("cx", String(C + ax * 0.4)); c.setAttribute("cy", String(C - ay * 0.4));
        const th = t * 0.55;
        m1.setAttribute("x", String(C + ax * 0.4 + 86 * Math.cos(th) - 2.5)); m1.setAttribute("y", String(C - ay * 0.4 + 86 * Math.sin(th) - 2.5));
        m2.setAttribute("x", String(C + ax * 0.4 + 86 * Math.cos(th + 2.9) - 2.5)); m2.setAttribute("y", String(C - ay * 0.4 + 86 * Math.sin(th + 2.9) - 2.5));
      };
    }
    case "sunburst": {
      el(svg, "circle", { ...base, cx: C, cy: C, r: R });
      const g = el(svg, "g");
      const lines: SVGElement[] = [];
      for (let i = 0; i < 64; i++) {
        const ang = (i / 64) * Math.PI * 2;
        lines.push(el(g, "line", { x1: C + 9 * Math.cos(ang), y1: C + 9 * Math.sin(ang), x2: C + 78 * Math.cos(ang), y2: C + 78 * Math.sin(ang), stroke: S, "stroke-width": 0.6, "stroke-dasharray": "1.4 2.6", opacity: i % 2 ? 0.55 : 0.95 }));
      }
      const r1 = el(svg, "circle", { ...base, cx: C, cy: C, r: 7 });
      const r2 = el(svg, "circle", { ...base, cx: C, cy: C, r: 3.5 });
      void r1; void r2;
      return (t) => {
        g.setAttribute("transform", `rotate(${t * 7} ${C} ${C})`);
        lines.forEach((l, i) => l.setAttribute("stroke-dashoffset", String(-(t * (6 + (i % 5))) % 4)));
      };
    }
    case "globe": {
      el(svg, "circle", { ...base, cx: C, cy: C, r: R });
      el(svg, "rect", { ...base, x: 18, y: 36, width: 164, height: 128, "stroke-dasharray": "1 2.5" });
      const mer: SVGElement[] = [];
      for (let i = 0; i < 10; i++) mer.push(el(svg, "ellipse", { ...base, cx: C, cy: C, ry: R, rx: 10 }));
      [-46, 0, 46].forEach((y) => { const h = Math.sqrt(R * R - y * y); el(svg, "line", { ...base, x1: C - h, x2: C + h, y1: C + y, y2: C + y }); });
      return (t) => mer.forEach((m, i) => m.setAttribute("rx", String(Math.abs(Math.cos((i / 10) * Math.PI + t * 0.45)) * R)));
    }
    case "loops": {
      el(svg, "circle", { ...base, cx: C, cy: C, r: R, "stroke-dasharray": "1 3" });
      const g = el(svg, "g");
      const es: SVGElement[] = [];
      for (let i = 0; i < 9; i++) es.push(el(g, "ellipse", { ...base, cx: C, cy: C, rx: 88 - i * 8.5, ry: 30 }));
      return (t) => {
        g.setAttribute("transform", `rotate(${Math.sin(t * 0.25) * 25} ${C} ${C})`);
        es.forEach((e, i) => e.setAttribute("ry", String(26 + 18 * Math.abs(Math.sin(t * 0.5 + i * 0.45)))));
      };
    }
    case "rings": {
      const rs: SVGElement[] = [];
      [16, 30, 44, 58, 72, 86].forEach((r, i) => rs.push(el(svg, "circle", { ...base, cx: C, cy: C, r, "stroke-dasharray": i % 2 ? "2 4" : "10 5 1 5", "stroke-width": i === 5 ? 0.9 : 0.7 })));
      el(svg, "rect", { width: 4, height: 4, x: C - 2, y: C - 2, fill: S });
      return (t) => rs.forEach((r, i) => r.setAttribute("stroke-dashoffset", String(t * (i % 2 ? -9 : 7) * (1 + i * 0.25))));
    }
    case "wave": {
      const ps: SVGElement[] = [];
      for (let i = 0; i < 6; i++) ps.push(el(svg, "path", { ...base, "stroke-width": i === 2 ? 1 : 0.6, opacity: 0.5 + (i === 2 ? 0.5 : 0) }));
      const ticks: SVGElement[] = [];
      for (let i = 0; i < 20; i++) ticks.push(el(svg, "line", { stroke: S, "stroke-width": 0.5, opacity: 0.4 }));
      el(svg, "line", { stroke: S, "stroke-width": 0.5, x1: 10, x2: 190, y1: C, y2: C, "stroke-dasharray": "1 3" });
      return (t) => {
        ps.forEach((p, k) => {
          let d = "";
          for (let x = 10; x <= 190; x += 3) d += `${x === 10 ? "M" : "L"}${x} ${C + Math.sin(x * 0.06 + t * (0.9 + k * 0.2) + k) * (10 + k * 5) * Math.sin(x * 0.015 + t * 0.2)}`;
          p.setAttribute("d", d);
        });
        ticks.forEach((l, i) => {
          const x = 10 + ((i * 9 - t * 18) % 180 + 180) % 180;
          const h = 6 + 24 * Math.abs(Math.sin(i * 1.7));
          l.setAttribute("x1", String(x)); l.setAttribute("x2", String(x)); l.setAttribute("y1", String(C - h)); l.setAttribute("y2", String(C + h));
        });
      };
    }
    case "bars": {
      el(svg, "line", { stroke: S, "stroke-width": 0.7, x1: 10, x2: 190, y1: 170, y2: 170 });
      const bs: SVGElement[] = [];
      for (let i = 0; i < 26; i++) bs.push(el(svg, "rect", { x: 12 + i * 6.9, width: 3.2, fill: "none", stroke: S, "stroke-width": 0.6 }));
      const top = el(svg, "polyline", { ...base, "stroke-dasharray": "1 2.5" });
      return (t) => {
        const pts: string[] = [];
        bs.forEach((b, i) => {
          const h = 14 + 110 * (0.5 + 0.5 * Math.sin(i * 0.55 + t * 0.9)) * (0.55 + 0.45 * Math.sin(i * 0.21 - t * 0.5));
          b.setAttribute("y", String(170 - h)); b.setAttribute("height", String(h));
          pts.push(`${12 + i * 6.9 + 1.6},${170 - h - 6}`);
        });
        top.setAttribute("points", pts.join(" "));
      };
    }
    default: {
      // grid: dotted plane with a travelling ripple
      const n = 13, ds: SVGElement[] = [];
      for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) ds.push(el(svg, "rect", { fill: S }));
      el(svg, "circle", { ...base, cx: C, cy: C, r: R, "stroke-dasharray": "1 3" });
      return (t) => ds.forEach((d, k) => {
        const x = k % n, y = Math.floor(k / n);
        const dist = Math.hypot(x - 6, y - 6);
        const w = 0.5 + 0.5 * Math.sin(dist * 0.9 - t * 1.6);
        const s = 1.2 + w * 4.2;
        d.setAttribute("width", String(s)); d.setAttribute("height", String(s));
        d.setAttribute("x", String(20 + x * 13.3 - s / 2)); d.setAttribute("y", String(20 + y * 13.3 - s / 2));
        d.setAttribute("opacity", String(0.35 + w * 0.65));
      });
    }
  }
}

/** Thin white line-art that is always moving (paused off-screen, calmer with reduced motion). Speeds up on hover of its card. */
export default function Figure({ kind, className }: { kind: FigureKind; className?: string }) {
  const ref = useRef<SVGSVGElement>(null);
  useEffect(() => {
    const svg = ref.current!;
    svg.replaceChildren();
    const frame = build(svg, kind);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let visible = true, raf = 0, t = Math.random() * 20, last = performance.now();
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; }, { threshold: 0 });
    io.observe(svg);
    frame(t);
    if (reduce) return () => io.disconnect();
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (!visible) return;
      const hot = svg.closest("a, .svc")?.matches(":hover");
      t += dt * (hot ? 2.6 : 1);
      frame(t);
    };
    raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); io.disconnect(); };
  }, [kind]);
  return <svg ref={ref} className={className} viewBox="0 0 200 200" preserveAspectRatio="xMidYMid meet" aria-hidden="true" />;
}

"use client";
import Lenis from "lenis";
import { createElement, useEffect, useRef, useState } from "react";

export const prefersReduced = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Inertial smooth scrolling, like the reference site. */
export function SmoothScroll() {
  useEffect(() => {
    if (prefersReduced()) return;
    const lenis = new Lenis({ lerp: 0.09, wheelMultiplier: 0.95 });
    let raf = 0;
    const loop = (t: number) => { lenis.raf(t); raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); lenis.destroy(); };
  }, []);
  return null;
}

export function useInView<T extends HTMLElement>(threshold = 0.25) {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (prefersReduced()) { setSeen(true); return; }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setSeen(true); io.disconnect(); } }, { threshold });
    io.observe(node);
    return () => io.disconnect();
  }, [threshold]);
  return [ref, seen] as const;
}

/** Headline that rises letter by letter from a mask when it scrolls into view. */
export function Reveal({ text, as = "span", className = "", delay = 0, step = 38 }: { text: string; as?: string; className?: string; delay?: number; step?: number }) {
  const [ref, seen] = useInView<HTMLElement>(0.15);
  let idx = 0;
  const words = text.split(" ");
  return createElement(
    as,
    { ref, className: `rv ${seen ? "in" : ""} ${className}`, "aria-label": text },
    words.map((w, wi) => (
      <span key={wi} aria-hidden="true">
        <span className="rw">
          {[...w].map((c, ci) => (
            <span className="ch" key={ci}><span style={{ transitionDelay: `${delay + idx++ * step}ms` }}>{c}</span></span>
          ))}
        </span>
        {wi < words.length - 1 ? " " : ""}
      </span>
    ))
  );
}

/** Paragraph whose words darken one by one as you scroll past it. */
export function ScrollText({ text, className = "" }: { text: string; className?: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const words = text.split(" ");
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const spans = [...node.querySelectorAll<HTMLElement>("span")];
    if (prefersReduced()) { spans.forEach((s) => (s.style.opacity = "1")); return; }
    let raf = 0;
    const update = () => {
      raf = 0;
      const r = node.getBoundingClientRect(), vh = window.innerHeight;
      const p = Math.min(1, Math.max(0, (vh * 0.92 - r.top) / (vh * 0.62 + r.height * 0.5)));
      const n = spans.length;
      spans.forEach((s, i) => { s.style.opacity = String(0.16 + 0.84 * Math.min(1, Math.max(0, p * (n + 4) - i) / 4)); });
    };
    const on = () => { if (!raf) raf = requestAnimationFrame(update); };
    update();
    window.addEventListener("scroll", on, { passive: true });
    window.addEventListener("resize", on);
    return () => { window.removeEventListener("scroll", on); window.removeEventListener("resize", on); cancelAnimationFrame(raf); };
  }, [text]);
  return <p ref={ref} className={className}>{words.map((w, i) => <span key={i} style={{ opacity: 0.16, transition: "opacity 0.12s linear" }}>{w}{i < words.length - 1 ? " " : ""}</span>)}</p>;
}

/** Number that counts up the first time it is seen, then eases to each new live value. */
export function CountUp({ value, format }: { value: number | null; format: (v: number) => string }) {
  const [ref, seen] = useInView<HTMLSpanElement>(0.3);
  const [shown, setShown] = useState<number | null>(null);
  const cur = useRef(0);
  useEffect(() => {
    if (value == null || !seen) return;
    if (prefersReduced()) { setShown(value); cur.current = value; return; }
    const from = cur.current, to = value, t0 = performance.now(), dur = 1100;
    let raf = 0;
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      cur.current = from + (to - from) * e;
      setShown(cur.current);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, seen]);
  return <span ref={ref}>{value == null ? "—" : format(shown ?? 0)}</span>;
}

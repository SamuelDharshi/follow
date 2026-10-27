"use client";
import { useEffect, useState } from "react";

export const Arrow = ({ dir = "right", size = 14 }: { dir?: "left" | "right"; size?: number }) => (
  <svg className="arrow" width={size} height={size} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true"
    style={dir === "left" ? { transform: "scaleX(-1)" } : undefined}>
    <path d="M1 7h12M8 2l5 5-5 5" />
  </svg>
);

export function AnalogClock({ zone, label }: { zone: string; label: string }) {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const i = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(i);
  }, []);
  const parts = now ? new Intl.DateTimeFormat("en-GB", { timeZone: zone, hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(now) : [];
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? 0), m = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
  const ha = ((h % 12) + m / 60) * 30, ma = m * 6;
  const hand = (deg: number, len: number) => ({ x: 20 + len * Math.sin((deg * Math.PI) / 180), y: 20 - len * Math.cos((deg * Math.PI) / 180) });
  const H = hand(ha, 8), M = hand(ma, 12);
  return (
    <div className="clockrow">
      <svg width="40" height="40" viewBox="0 0 40 40" fill="none" stroke="currentColor" aria-hidden="true">
        <circle cx="20" cy="20" r="19" />
        {now && <><line x1="20" y1="20" x2={H.x} y2={H.y} /><line x1="20" y1="20" x2={M.x} y2={M.y} /></>}
      </svg>
      <div><b>{label}</b><span>{now ? `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}` : "--:--"}</span></div>
    </div>
  );
}

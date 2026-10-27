"use client";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getJson } from "@/lib/api";
import { AnalogClock, Arrow } from "@/components/bits";
import { SmoothScroll } from "@/components/motion";
import logo from "@/app/logo.png";

const NAV: [string, string][] = [
  ["/", "About"],
  ["/scorecard", "Scorecard"],
  ["/ask", "Ask"],
  ["/designer", "Designer"],
  ["/methodology", "Methodology"],
  ["/data", "Dataset"],
];

function Header() {
  const path = usePathname();
  const [ok, setOk] = useState<boolean | null>(null);
  const [snap, setSnap] = useState<number | null>(null);
  const [t, setT] = useState("");
  const [zi, setZi] = useState(0);
  const ZONES: [string, string][] = [["UTC", "UTC"], ["America/New_York", "NYC"], ["Asia/Kolkata", "IST"]];
  useEffect(() => {
    const tick = () => setT(new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: ZONES[zi][0] }));
    tick();
    const a = setInterval(tick, 10000);
    const f = () => getJson<{ ok: boolean; mode?: string; as_of?: number }>("/api/health").then((h) => { setOk(h.ok); setSnap(h.mode === "snapshot" ? h.as_of ?? 0 : null); }).catch(() => setOk(false));
    f();
    const b = setInterval(f, 15000);
    return () => { clearInterval(a); clearInterval(b); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zi]);
  useEffect(() => {
    const c = setInterval(() => setZi((z) => (z + 1) % 3), 4500);
    return () => clearInterval(c);
  }, []);
  return (
    <header className="x-head">
      <div className="l">
        <Link href="/" className="logo" aria-label="Follow home"><Image src={logo} alt="Follow" width={40} height={40} priority /></Link>
        <span className="time fi" key={zi}>{t || "--:--"} {ZONES[zi][1]}</span>
      </div>
      <div className="r">
        <nav>
          {NAV.map(([h, l]) => <Link key={h} href={h} className={path === h ? "on" : ""}>{l}</Link>)}
        </nav>
        <span className={`live ${ok ? "on" : ""}`}><i />{ok == null ? "checking" : snap != null ? "recorded data · " + new Date(snap).toLocaleDateString([], { month: "short", day: "numeric" }) : ok ? "recording live" : "recorder offline"}</span>
        <Link href="/scorecard" className="btn cta">Scorecard <Arrow /></Link>
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="foot">
      <div className="h">
        <h3 style={{ fontSize: 38, lineHeight: 1.05 }}>Measure<br />your depth</h3>
        <p>Follow measures liquidity, not integrity. BTC-USD only, because that is the only symbol with public L3. History starts when the recorder started; every gap is marked.</p>
      </div>
      <div>
        <div className="links">
          {NAV.map(([h, l]) => <Link key={h} href={h}>{l}</Link>)}
        </div>
      </div>
      <div>
        <div className="clocks">
          <AnalogClock zone="America/New_York" label="NYC" />
          <AnalogClock zone="UTC" label="UTC" />
          <AnalogClock zone="Asia/Kolkata" label="India" />
        </div>
      </div>
      <div className="foot-low" style={{ gridColumn: "2 / 4" }}>
        <a href="https://docs.strikefinance.org/api/l3.md" rel="noreferrer">Strike L3 docs <span>↗</span></a>
        <Link href="/methodology" style={{ borderRight: 0 }}>Methodology <span>↗</span></Link>
      </div>
      <div className="endrow" style={{ gridColumn: "1 / -1" }}>
        <div className="end-l">
          <div className="wm-wrap"><span className="wm-logo"><Image src={logo} alt="" width={84} height={84} /></span><div className="wm">follow</div></div>
          <div className="mono end-small"><span>© 2026 Follow</span><span>Measures liquidity, not integrity</span></div>
        </div>
        <Link href="/scorecard" className="end-r">
          <span className="t">Let&apos;s see<br />the book</span>
          <span className="go">Open the scorecard</span>
          <svg className="diag" width="94" height="94" viewBox="0 0 94 94" fill="none" stroke="currentColor" strokeWidth="1" aria-hidden="true"><path d="M0 94 94 0M24 0H94V70" /></svg>
        </Link>
      </div>
    </footer>
  );
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <>
      <SmoothScroll />
      <Header />
      {path === "/" ? <div id="content" role="main">{children}</div> : <main id="content" className="app">{children}</main>}
      <Footer />
    </>
  );
}

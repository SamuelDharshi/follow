"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import Figure from "@/components/Figure";
import type { FigureKind } from "@/components/Figure";
import Halftone from "@/components/Halftone";
import type { BookData } from "@/components/Halftone";
import { Arrow } from "@/components/bits";
import { CountUp, Reveal, ScrollText } from "@/components/motion";
import { bps, getJson, mean, pct, usd } from "@/lib/api";
import type { Coverage, Scorecard } from "@/lib/api";

type Latest = Record<string, Record<string, number>>;
type Health = { ok: boolean; feeds: Record<string, { ok: boolean; heartbeat_age_s: number | null }> };
type Resilience = { n_trades: number; n_recovered: number; median_recovery_ms: number | null; threshold_usd: number };

const SERVICES: { t: string; d: string; l: string[]; href: string; fig: FigureKind }[] = [
  { t: "Live\nscorecard", d: "Strike's own liquidity trend first, the gap to Binance and Hyperliquid second, with the data coverage behind every figure.", l: ["Spread uptime and depth", "Slippage at $10k, $50k, $100k", "Trends with gaps drawn as gaps"], href: "/scorecard", fig: "loops" },
  { t: "L3-only\nmetrics", d: "Order-by-order data measures what no aggregated feed can: how much liquidity is pulled, and how fast it comes back after a large taker.", l: ["Cancel / fill ratio", "Depth resilience", "Sample size beside every number"], href: "/methodology", fig: "globe" },
  { t: "Incentive\ndesigner", d: "Try a maker rebate and Quoter count on the real current book. A labelled what-if, never a forecast, with assumptions printed.", l: ["Rebate, Quoters, quote size", "Recomputes depth and slippage", "Runs on the live book"], href: "/designer", fig: "sunburst" },
  { t: "Open dataset\n& API", d: "Every recorded order-book event and sample, with every outage marked, plus a read-only API for any time range.", l: ["Parquet per table per day", "Schema and gap table included", "GET /api/query for metric ranges"], href: "/data", fig: "orbit" },
];

const SOURCES: { n: string; tag: string; d: string }[] = [
  { n: "Strike L3 stream", tag: "Primary", d: "wss /ws/l3 · every resting order" },
  { n: "Strike L3 snapshot", tag: "Primary", d: "REST /v2/l3/snapshot · full book" },
  { n: "Strike market feed", tag: "Cross-check", d: "wss /ws/price · trades, top of book" },
  { n: "Binance", tag: "Benchmark", d: "BTCUSDT depth stream, local book" },
  { n: "Hyperliquid", tag: "Benchmark", d: "BTC l2Book, two granularities" },
  { n: "Follow recorder", tag: "Ours", d: "Gap-aware, auto re-snapshot" },
];

const SIZES = ["10k", "50k", "100k"] as const;
const LABEL: Record<string, string> = { strike: "Strike", binance: "Binance", hyperliquid: "Hyperliquid" };

export default function Landing() {
  const [sc, setSc] = useState<Scorecard | null>(null);
  const [cov, setCov] = useState<Coverage | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [latest, setLatest] = useState<Latest | null>(null);
  const [res, setRes] = useState<Resilience | null>(null);
  const [book, setBook] = useState<BookData>(null);
  const [size, setSize] = useState<(typeof SIZES)[number]>("50k");
  const [slide, setSlide] = useState(0);
  const [hold, setHold] = useState(false);
  const [src, setSrc] = useState(0);

  useEffect(() => {
    const load = () => {
      getJson<Scorecard>("/api/scorecard?window_minutes=60").then(setSc).catch(() => {});
      getJson<Coverage>("/api/coverage").then(setCov).catch(() => {});
      getJson<Health>("/api/health").then(setHealth).catch(() => setHealth(null));
      getJson<Latest>("/api/latest").then(setLatest).catch(() => {});
      getJson<Resilience>("/api/resilience?hours=48").then(setRes).catch(() => {});
      getJson<{ bids: [number, number][]; asks: [number, number][] }>("/api/book").then((b) => setBook({ bids: b.bids, asks: b.asks })).catch(() => {});
    };
    load();
    const i = setInterval(load, 15000);
    return () => clearInterval(i);
  }, []);
  useEffect(() => {
    const i = setInterval(() => setSrc((s) => (s + 1) % SOURCES.length), 3500);
    return () => clearInterval(i);
  }, []);

  const S = sc?.venues.strike.current;
  const B = sc?.venues.binance.current;
  const depth = S ? mean(S.m2.d10.bid, S.m2.d10.ask) : null;
  const bDepth = B ? mean(B.m2.d10.bid, B.m2.d10.ask) : null;
  const slip = S ? mean(S.m3["50k"].buy, S.m3["50k"].sell) : null;
  const bSlip = B ? mean(B.m3["50k"].buy, B.m3["50k"].sell) : null;
  const hours = cov?.strike?.span_hours;
  const cancels = sc?.m4_since_start.n_cancel;
  const fills = sc?.m4_since_start.n_fill;

  // every finding is computed from the recorded data
  const findings: { big: string; text: string; src: string; kv: [string, string][] }[] = [];
  if (depth != null && bDepth != null) findings.push({ big: `${(bDepth / depth).toFixed(0)}×`, text: `Binance shows ${(bDepth / depth).toFixed(0)} times more resting depth within 10 bps of mid than Strike: ${usd(bDepth)} against ${usd(depth)} per side.`, src: "Depth within 10 bps", kv: [["Metric", "M2 depth"], ["Window", "Last hour"]] });
  if (S) findings.push({ big: pct(S.m1_spread_uptime), text: `Strike held a two-sided book at 5 bps or tighter for ${pct(S.m1_spread_uptime)} of the last hour. The average spread was ${bps(S.spread_bps)}.`, src: "Spread uptime", kv: [["Metric", "M1 spread uptime"], ["Window", "Last hour"]] });
  if (slip != null) findings.push({ big: bps(slip), text: `A $50k market order costs about ${bps(slip)} on Strike${bSlip != null ? `, against ${bps(bSlip)} on Binance` : ""}.`, src: "Slippage at size", kv: [["Metric", "M3 slippage"], ["Order size", "$50,000"]] });
  if (cancels != null && fills != null) findings.push({ big: cancels.toLocaleString(), text: `${cancels.toLocaleString()} cancellations against ${fills.toLocaleString()} fills since recording began. Most visible liquidity is repositioned, rarely traded.`, src: "Cancel / fill", kv: [["Metric", "M4 cancel / fill"], ["Source", "Strike L3 events"]] });
  if (res) findings.push({ big: res.median_recovery_ms != null ? `${(res.median_recovery_ms / 1000).toFixed(1)}s` : "—", text: res.n_trades ? `After ${res.n_trades} taker orders above ${usd(res.threshold_usd)}, depth within 10 bps recovered to 80% in a median ${((res.median_recovery_ms ?? 0) / 1000).toFixed(1)} seconds. ${res.n_recovered} of ${res.n_trades} recovered.` : `No taker order above ${usd(res.threshold_usd)} has traded since recording began.`, src: "Depth resilience", kv: [["Metric", "M5 resilience"], ["Source", "Strike L3 events"]] });
  if (cov?.strike) findings.push({ big: `${(cov.strike.span_hours ?? 0).toFixed(1)}h`, text: `Recorded so far, with ${cov.strike.gap_count ?? 0} marked gaps totalling ${((cov.strike.gap_ms ?? 0) / 3.6e6).toFixed(1)} hours that are excluded from every average.`, src: "Data coverage", kv: [["Metric", "Coverage"], ["Source", "Recorder gap table"]] });
  const cur = findings.length ? slide % findings.length : 0;
  const f = findings[cur];
  const next = () => findings.length && setSlide((cur + 1) % findings.length);
  const prev = () => findings.length && setSlide((cur + findings.length - 1) % findings.length);
  useEffect(() => {
    if (hold || !findings.length) return;
    const i = setInterval(() => setSlide((s) => s + 1), 9000);
    return () => clearInterval(i);
  }, [hold, findings.length]);

  const feedOk = (k: string) => (health ? health.feeds[k]?.ok : null);
  const TEAM: { n: string; r: string; k?: string; href: string; fig: FigureKind }[] = [
    { n: "L3 recorder", r: "Strike order-by-order feed", k: "strike", href: "/data", fig: "sunburst" },
    { n: "Gap detector", r: `${cov?.strike?.gap_count ?? "—"} gaps marked`, href: "/methodology", fig: "orbit" },
    { n: "Book rebuilder", r: "Matches REST snapshots", href: "/methodology", fig: "rings" },
    { n: "Market feed", r: "Trades and top of book", k: "strike_market", href: "/data", fig: "wave" },
    { n: "Binance feed", r: "Depth stream, local book", k: "binance", href: "/scorecard", fig: "globe" },
    { n: "Hyperliquid feed", r: "l2Book, two granularities", k: "hyperliquid", href: "/scorecard", fig: "loops" },
    { n: "Metrics engine", r: "M1 to M5, 2 s samples", href: "/methodology", fig: "bars" },
    { n: "Dataset and API", r: "Parquet, read-only API", href: "/data", fig: "grid" },
  ];

  return (
    <>
      {/* hero 1: wordmark + live book */}
      <div className="row hero-a">
        <div className="c"><h1 className="big name"><Reveal text="Follow" step={70} /></h1></div>
        <div className="c"><Halftone mode="book" book={book} seed={7} px={2} /></div>
      </div>

      {/* hero 2 */}
      <div className="row hero-b">
        <div className="c halfill"><Halftone seed={11} px={2} /></div>
        <div className="c right" style={{ padding: 0 }}>
          <div className="top">
            <div className="c dark" style={{ borderRight: "1px solid var(--rule)" }}>
              <p className="statement fu" style={{ animationDelay: "0.5s" }}>Independent liquidity scorecard for Strike. Its public L3 order feed, recorded live and measured against Binance and Hyperliquid.</p>
              <Link href="/scorecard" className="btn light">Open the scorecard <Arrow /></Link>
            </div>
            <div className="mintbox">
              <p className="statement fu" style={{ animationDelay: "0.7s" }}>Thin books mean slippage. Slippage keeps makers away. We measure the loop.</p>
              <p className="statement fu" style={{ marginTop: 16, animationDelay: "0.85s" }}>Recorded from:</p>
              <div className="marq"><div>{[...SOURCES, ...SOURCES].map((s, i) => <span key={i}>{s.n}</span>)}</div></div>
            </div>
          </div>
          <div className="search" style={{ borderTop: 0 }}>
            <div className="q">What does a market order cost right now?</div>
            <div className="seg" role="tablist">
              {SIZES.map((s) => <button key={s} className={size === s ? "on" : ""} onClick={() => setSize(s)}>${s}</button>)}
            </div>
            <table className="mini">
              <tbody>
                {["strike", "binance", "hyperliquid"].map((v) => {
                  const r = latest?.[v];
                  const val = r ? mean(r[`buy_${size}`], r[`sell_${size}`]) : null;
                  return <tr key={v} className={v === "strike" ? "me" : ""}><td>{LABEL[v]}</td><td>{r ? (val == null ? "unfillable" : bps(val)) : "—"}</td></tr>;
                })}
              </tbody>
            </table>
            <div className="small" style={{ marginTop: 6 }}>Average of buy and sell, latest 2 s sample per venue.</div>
            <div className="word"><Reveal text="Index" delay={300} step={60} /></div>
          </div>
        </div>
      </div>

      {/* hero 3 */}
      <div className="row statement-box">
        <div className="c dark"><div className="t"><Reveal text="Measuring" /><Reveal text="depth." delay={250} /></div></div>
        <div className="c"><Halftone seed={23} px={2} /></div>
      </div>

      {/* about + stats */}
      <div className="row about" id="about">
        <div className="c pad"><span className="label">About Follow</span></div>
        <div className="c para">
          <ScrollText text="Strike's perps volume is thin, and thin books mean slippage. Slippage keeps traders and market makers away, which keeps books thin." />
          <ScrollText text="Until now there was no public, independent measure of how thin, versus whom, or whether a liquidity programme works. Follow records every resting order on Strike, measures it the same way as Binance and Hyperliquid, and publishes the result along with the raw data." />
        </div>
      </div>
      <div className="row" style={{ minHeight: 200 }}>
        <div className="c" />
        <div className="c" style={{ padding: 0 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", height: "100%" }}>
            <div className="stat c dark" style={{ borderRight: "1px solid var(--rule)" }}><div className="n"><CountUp value={S?.m1_spread_uptime != null ? S.m1_spread_uptime * 100 : null} format={(v) => `${v.toFixed(1)}%`} /></div><div className="cap">Of the last hour Strike quoted a two-sided book at 5 bps or tighter</div></div>
            <div />
          </div>
        </div>
      </div>
      <div className="row" style={{ minHeight: 400 }}>
        <div className="c mint stat tall"><div className="n"><CountUp value={depth} format={usd} /></div><div className="cap">Resting within 10 bps of mid, per side{bDepth && depth ? ` · Binance has ${(bDepth / depth).toFixed(0)}× that` : ""}</div></div>
        <div className="c" style={{ padding: 0 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", height: "100%" }}>
            <div style={{ borderRight: "1px solid var(--rule)" }} />
            <div className="stat" style={{ background: "var(--gray)" }}><div className="n"><CountUp value={slip} format={(v) => v.toFixed(2)} /><span style={{ fontSize: "0.35em" }}> bps</span></div><div className="cap">Average cost of a $50k market order on Strike{hours != null ? ` · ${hours.toFixed(1)} h recorded` : ""}</div></div>
          </div>
        </div>
      </div>

      {/* services */}
      <div className="row" id="product">
        <div className="c gray svc-head">
          <Halftone seed={55} px={2} />
          <div className="stk">
            <h2><Reveal text="Measuring" /><Reveal text="Strike's" delay={200} /><Reveal text="liquidity" delay={400} /></h2>
            <div className="ptxt">
              <p>Four tools, one dataset. Every number is computed from recorded public data with its definition and sample size on show. Nothing is simulated; the one model is labelled as a what-if.</p>
              <Link href="/scorecard" className="btn">Open the scorecard <Arrow /></Link>
            </div>
          </div>
        </div>
        <div className="c" style={{ padding: 0 }}>
          {SERVICES.map((s, i) => (
            <Link href={s.href} className="svc" key={s.t}>
              <span className="no">0{i + 1}</span>
              <h3 style={{ whiteSpace: "pre-line" }}>{s.t}</h3>
              <p className="d">{s.d}</p>
              <Figure kind={s.fig} className="art" />
              <ul>{s.l.map((x) => <li key={x}>{x}</li>)}</ul>
              <span className="go"><Arrow /></span>
            </Link>
          ))}
        </div>
      </div>

      {/* sources */}
      <div className="row" id="sources" style={{ minHeight: 500 }}>
        <div className="c"><h2 className="big" style={{ position: "absolute", left: 20, bottom: 14 }}><Reveal text="Sources" step={55} /></h2></div>
        <div className="c"><Halftone seed={31} px={2} /></div>
      </div>
      <div className="row srcs" style={{ gridTemplateColumns: "1fr 1fr 2fr" }}>
        <div className="c panel">
          <div>
            <span className="label">What we record</span>
            <div key={src} className="mono fi" style={{ marginTop: 14 }}>{SOURCES[src].n}</div>
            <div className="mono" style={{ color: "#8a8a8a", marginTop: 4 }}>{String(src + 1).padStart(2, "0")} - {String(SOURCES.length).padStart(2, "0")}</div>
          </div>
          <div className="tile" key={`t${src}`}>{SOURCES[src].d}</div>
        </div>
        <div className="c pad">
          <ScrollText text="L3 is the core input: every resting order on Strike BTC-USD, rebuilt from a snapshot plus the live stream and verified against fresh snapshots. Binance and Hyperliquid are recorded the same way so the gap has a size. Only public market data; no keys, wallets or funds." className="srcp" />
          <Link href="/methodology" className="btn" style={{ marginTop: 24 }}>Read the methodology <Arrow /></Link>
        </div>
        <div className="c names" style={{ padding: 0 }}>
          {SOURCES.map((s, i) => (
            <button key={s.n} className={`item ${src === i ? "on" : ""}`} onClick={() => setSrc(i)}><span>{s.n}</span><span className="tag">{s.tag}</span></button>
          ))}
        </div>
      </div>

      {/* findings */}
      <div className="row quote" id="findings" style={{ gridTemplateColumns: "1fr 2fr 1fr" }} onMouseEnter={() => setHold(true)} onMouseLeave={() => setHold(false)}>
        <div className="c">
          <div style={{ padding: 20 }}><span className="label">Findings</span></div>
          <div className="arrows" style={{ position: "absolute", left: 0, right: 0, top: 70, borderTop: "1px solid var(--rule)" }}>
            <button onClick={prev} aria-label="Previous finding"><Arrow dir="left" /></button>
            <button onClick={next} aria-label="Next finding"><Arrow /></button>
          </div>
          <div style={{ position: "absolute", left: 0, right: 0, top: 120, bottom: 0, background: "var(--mint)", padding: 20, display: "flex", alignItems: "flex-end" }}>
            <div key={cur} className="bigmetric" style={{ fontSize: "clamp(48px, 7vw, 96px)", lineHeight: 0.9, letterSpacing: "-0.05em", wordBreak: "break-all" }}>{f?.big ?? "—"}</div>
          </div>
        </div>
        <div className="c">
          {f ? (
            <>
              <div className="q" key={cur}><div className="qmark">“</div><p style={{ marginTop: 36 }}>{f.text}</p></div>
              <div className="by"><div><b>{f.src}</b><span>Recomputed from recorded data every 15 s</span></div><span>{String(cur + 1).padStart(2, "0")} - {String(findings.length).padStart(2, "0")}</span></div>
            </>
          ) : <div className="q">Waiting for recorded data…</div>}
        </div>
        <div className="c" style={{ padding: 0, display: "grid", gridTemplateRows: "auto 1fr" }}>
          <div className="dark kv" style={{ background: "var(--ink)", color: "#fff" }}>
            {(f?.kv ?? []).map(([k, v]) => <div key={k + cur} className="fi"><b>{k}</b><span>{v}</span></div>)}
          </div>
          <div style={{ position: "relative", minHeight: 240 }}><Halftone seed={41 + cur} px={2} /></div>
        </div>
      </div>

      {/* pipeline */}
      <div className="row pipe-title" id="pipeline">
        <div className="c"><h2 className="big" style={{ position: "absolute", left: 20, top: 8 }}><Reveal text="Stack" step={70} /></h2></div>
        <div className="c"><div className="sm"><Reveal text="Small stack." /><Reveal text="High signal." delay={200} /></div></div>
      </div>
      <div className="row" style={{ minHeight: 160 }}>
        <div className="c pad" style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", minHeight: 160 }}><span className="label">How it runs</span></div>
        <div className="c pad"><p style={{ fontSize: 15, maxWidth: "46ch" }}>Eight parts, one recorder process. A feed that drops is marked as a gap and rebuilt from a fresh snapshot, never papered over. The tags show which feeds are live right now.</p></div>
      </div>
      <div className="tiles" style={{ borderBottom: "1px solid var(--rule)" }}>
        {TEAM.map((t) => {
          const ok = t.k ? feedOk(t.k) : null;
          return (
            <Link href={t.href} key={t.n}>
              <Figure kind={t.fig} className="fig" />
              <span className={`tag ${ok ? "on" : ""}`}>{t.k ? (ok == null ? "…" : ok ? "Live" : "Down") : "Core"}</span>
              <div className="name"><div>{t.n}<small>{t.r}</small></div><Arrow size={18} /></div>
            </Link>
          );
        })}
      </div>

      {/* closing */}
      <Link href="/scorecard" className="cta-band" aria-label="Open the scorecard">
        <Halftone seed={77} px={2} fps={14} />
        <div className="words">
          <div className="l1"><span>Lets</span><span>see</span><span>the</span></div>
          <div className="l2"><span>Book</span><i><Arrow size={56} /></i></div>
        </div>
      </Link>
    </>
  );
}

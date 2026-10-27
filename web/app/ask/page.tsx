"use client";
import { useEffect, useState } from "react";
import Chart from "@/components/Chart";
import PageHero from "@/components/PageHero";
import { VENUE_LABEL, getJson, timeLabel } from "@/lib/api";
import type { Point, Venue } from "@/lib/api";

type Claim = { text: string; tool: string; args: Record<string, unknown>; value?: number | string; call_id: string; window: { start: number; end: number } | null };
type Gap = { venue: string; start_ms: number; end_ms: number | null; reason: string; minutes: number };
type Answer = {
  question: string; answer: string; claims: Claim[]; gaps_affecting_answer: Gap[]; model_notes: string[]; confidence: string;
  tool_calls: { id: string; tool: string; args: Record<string, unknown> }[]; dropped_unbacked_sentences: number; model: string; seconds: number;
};

const SUGGESTED = [
  "Is Strike's liquidity better or worse than Binance right now, and by how much on a $50k order?",
  "Why was Strike slippage worse than Binance yesterday?",
  "How did Strike's spread uptime change over the last 24 hours, and were there recording gaps?",
  "How quickly does Strike depth recover after a large taker order?",
  "Do takers on Strike tend to move the price against resting orders?",
];

function Evidence({ c }: { c: Claim }) {
  const [pts, setPts] = useState<Point[] | null>(null);
  const venue = (c.args.venue as Venue) || "strike";
  useEffect(() => {
    if (!c.window) return;
    const span = c.window.end - c.window.start;
    const step = span <= 6 * 3600_000 ? "minute" : span <= 7 * 86400_000 ? "hour" : "day";
    getJson<{ points: Point[] }>(`/api/series?venue=${venue}&step=${step}&start=${c.window.start}&end=${c.window.end}`).then((r) => setPts(r.points)).catch(() => setPts([]));
  }, [c, venue]);
  return (
    <div className="card" style={{ borderBottom: "1px solid var(--ink)" }}>
      <div className="label">{c.call_id} · tool {c.tool}{c.window ? ` · ${timeLabel(c.window.start)} to ${timeLabel(c.window.end)}` : ""}</div>
      <p style={{ margin: "6px 0" }}>{c.text}</p>
      <div className="note">value {String(c.value)} · args {JSON.stringify(c.args)}</div>
      {pts && pts.length > 1 && (
        <Chart data={pts.map((p) => ({ t: p.t, v: p.m1_spread_uptime }))} fmt={(v) => `${(v * 100).toFixed(0)}%`} series={[{ key: "v", label: `${VENUE_LABEL[venue]} spread uptime`, color: "var(--accent)" }]} />
      )}
    </div>
  );
}

export default function Ask() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const go = async (text: string) => {
    if (text.trim().length < 5) return;
    setQ(text); setBusy(true); setErr(null); setRes(null);
    try {
      setRes(await getJson<Answer>("/api/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question: text }) }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <PageHero title="Ask" sub="Ask Follow a liquidity question. An agent calls the same metric tools as the scorecard and shows the evidence for every number." seed={21} />
      <div className="app-body">
        <h1>Ask Follow</h1>
        <div className="controls" style={{ gap: 8 }}>
          <input style={{ flex: 1, minWidth: 260 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Why was Strike slippage worse than Binance yesterday?" onKeyDown={(e) => e.key === "Enter" && go(q)} />
          <button className="primary" onClick={() => go(q)} disabled={busy}>{busy ? "Investigating…" : "Ask"}</button>
        </div>
        <div className="controls" style={{ flexWrap: "wrap" }}>
          {SUGGESTED.map((s) => <button key={s} onClick={() => go(s)} disabled={busy} style={{ textTransform: "none", textAlign: "left" }}>{s}</button>)}
        </div>
        {err && <div className="empty err">{err}</div>}
        {busy && <div className="empty">Planning, calling tools, checking gaps…</div>}
        {res && (
          <>
            <div className="banner" style={{ background: res.confidence === "high" ? "var(--mint)" : "#fff" }}>
              {res.answer} <span className="small">(confidence: {res.confidence} · {res.tool_calls.length} tool calls · {res.seconds}s · {res.model})</span>
            </div>
            {res.gaps_affecting_answer.length > 0 && (
              <div className="empty" style={{ textAlign: "left" }}>
                <b>Recording gaps overlapping this answer:</b>
                <ul>{res.gaps_affecting_answer.map((g, i) => <li key={i}>{VENUE_LABEL[g.venue as Venue] ?? g.venue}: {g.minutes} min ({g.reason}), from {timeLabel(g.start_ms)}</li>)}</ul>
              </div>
            )}
            <h2>Evidence</h2>
            <p className="sub">Every number above is backed by a claim here, checked against what the tool returned. {res.dropped_unbacked_sentences > 0 ? `${res.dropped_unbacked_sentences} sentence(s) with unbacked numbers were removed.` : ""}</p>
            <div className="grid" style={{ gridTemplateColumns: "1fr" }}>{res.claims.map((c, i) => <Evidence key={i} c={c} />)}</div>
            <p className="small">Tool calls: {res.tool_calls.map((t) => `${t.id} ${t.tool}`).join(" → ")}</p>
          </>
        )}
      </div>
    </>
  );
}

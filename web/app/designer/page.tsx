"use client";
import { useState } from "react";
import PageHero from "@/components/PageHero";
import { bps, getJson, usd } from "@/lib/api";

type Out = {
  book_age_ms: number;
  baseline: Record<string, number | null>;
  modelled: Record<string, number | null>;
  participation: number;
  added_liquidity_usd_per_side: number;
  programme_cost_usd_per_day: number;
  assumptions: string[];
};

const ROWS: [string, string, string, "usd" | "bps"][] = [
  ["Depth within 5 bps, bid", "bid_d5", "", "usd"], ["Depth within 5 bps, ask", "ask_d5", "", "usd"],
  ["Depth within 10 bps, bid", "bid_d10", "", "usd"], ["Depth within 10 bps, ask", "ask_d10", "", "usd"],
  ["Depth within 25 bps, bid", "bid_d25", "", "usd"], ["Depth within 25 bps, ask", "ask_d25", "", "usd"],
  ["Slippage $10k buy", "buy_s10k", "", "bps"], ["Slippage $10k sell", "sell_s10k", "", "bps"],
  ["Slippage $50k buy", "buy_s50k", "", "bps"], ["Slippage $50k sell", "sell_s50k", "", "bps"],
  ["Slippage $100k buy", "buy_s100k", "", "bps"], ["Slippage $100k sell", "sell_s100k", "", "bps"],
];

export default function Designer() {
  const [f, setF] = useState({ rebate_bps: 1, n_quoters: 3, quote_size_usd: 50000, adverse_selection_bps: 1.5, turnover_per_day: 1 });
  const [out, setOut] = useState<Out | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: Number(e.target.value) });
  const run = async () => {
    setBusy(true);
    try {
      setOut(await getJson<Out>("/api/designer", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(f) }));
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const fmt = (v: number | null | undefined, kind: "usd" | "bps") => (kind === "usd" ? (v == null ? "none" : usd(v)) : v == null ? "unfillable" : bps(v));

  return (
    <>
      <PageHero title="Designer" sub="Try a maker rebate and Quoter count on Strike's real current book. A what-if model, not a forecast." seed={9} />
      <div className="app-body">
      <h1>Incentive designer</h1>
      <div className="banner">What-if model, not a forecast. It adds hypothetical resting liquidity to Strike's real current book and recomputes the same metrics. It does not predict how Quoters or traders will behave.</div>
      <div className="two">
        <div className="card">
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <label className="field">Maker rebate (bps)<input type="number" min={0} step={0.1} value={f.rebate_bps} onChange={set("rebate_bps")} /></label>
            <label className="field">Number of Quoters<input type="number" min={0} step={1} value={f.n_quoters} onChange={set("n_quoters")} /></label>
            <label className="field">Quote size per Quoter (USD)<input type="number" min={0} step={1000} value={f.quote_size_usd} onChange={set("quote_size_usd")} /></label>
            <label className="field">Assumed adverse-selection cost (bps)<input type="number" min={0.1} step={0.1} value={f.adverse_selection_bps} onChange={set("adverse_selection_bps")} /></label>
            <label className="field">Maker turnover per day (×)<input type="number" min={0} step={0.5} value={f.turnover_per_day} onChange={set("turnover_per_day")} /></label>
          </div>
          <div className="controls"><button className="primary" onClick={run} disabled={busy}>{busy ? "Modelling…" : "Model on the live book"}</button></div>
          {err && <div className="err">{err}</div>}
        </div>
        <div className="card">
          <h3>How the model works</h3>
          <p className="small">
            Quoters join when the rebate offsets their adverse-selection cost: participation = min(1, rebate ÷ cost). Added size per side = Quoters × quote size × participation,
            placed at today's best bid and best ask. M2 and M3 are then recomputed by the same code the scorecard uses.
            Programme cost = rebate × modelled maker volume. Change the adverse-selection and turnover assumptions to see how sensitive the result is.
          </p>
        </div>
      </div>
      {out && (
        <>
          <h2>Result on the book recorded {(out.book_age_ms / 1000).toFixed(0)} s ago</h2>
          <div className="banner">Modelled values below are what-if outputs, not forecasts.</div>
          <div className="grid" style={{ marginBottom: 12 }}>
            <div className="card"><div className="label">Participation</div><div className="value">{(out.participation * 100).toFixed(0)}%</div></div>
            <div className="card"><div className="label">Added liquidity per side</div><div className="value">{usd(out.added_liquidity_usd_per_side)}</div></div>
            <div className="card"><div className="label">Modelled programme cost</div><div className="value">{usd(out.programme_cost_usd_per_day)}/day</div></div>
          </div>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Metric</th><th>Recorded book</th><th>Modelled (what-if)</th></tr></thead>
              <tbody>{ROWS.map(([l, k, , kind]) => (
                <tr key={k}><td>{l}</td><td>{fmt(out.baseline[k], kind)}</td><td>{fmt(out.modelled[k], kind)}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <h3 style={{ marginTop: 20 }}>Assumptions</h3>
          <ul className="prose">{out.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        </>
      )}
      </div>
    </>
  );
}

import PageHero from "@/components/PageHero";

export const metadata = { title: "Methodology - Follow" };

export default function Methodology() {
  return (
    <>
    <PageHero title="Method" sub="Every metric defined in plain language, with its data window and known limits." seed={17} />
    <div className="app-body"><div className="prose">
      <h1>Methodology</h1>
      <p className="sub">Every number on the scorecard is computed from public market data that the Follow recorder stored itself. Nothing is simulated, except the incentive designer, which is labelled as a model.</p>

      <h2>Data sources</h2>
      <ul>
        <li><b>Strike L3</b>: <code>/v2/l3/snapshot</code> plus <code>wss://api.strikefinance.org/ws/l3</code>, BTC-USD, every resting order. The recorder buffers the stream, fetches a snapshot, drops updates up to the snapshot sequence, then applies sequence N+1 onwards and stores every event.</li>
        <li><b>Strike market WebSocket</b>: <code>trade</code> and <code>bookTicker</code>, used to cross-check the rebuilt book.</li>
        <li><b>Binance</b>: BTCUSDT diff-depth stream (USD-M perpetual when reachable; if Binance&apos;s main domains are unreachable from the recorder host it falls back to the public spot mirror, and every switch is logged and shown on the scorecard) plus a 1,000-level REST snapshot, synced per Binance&apos;s documented procedure and rebuilt every 15 minutes.</li>
        <li><b>Hyperliquid</b>: BTC perpetual <code>l2Book</code> WebSocket at two granularities ($1 and $10 price buckets).</li>
      </ul>

      <h2>Sampling and windows</h2>
      <p>Every 2 seconds each venue&apos;s local book is sampled and the metrics below are computed from the full book. Headline numbers average the samples in the chosen window. Charts use 1-minute or hourly buckets. Mid price = (best bid + best ask) / 2. <b>Strike samples are taken between refresh bursts:</b> Strike&apos;s L3 feed refreshes the whole book once a second as about 190 separately sequenced cancel and open events with no batch boundary, so a sample taken mid-burst sees a half-empty book. Strike samples are therefore taken only at a gap of at least 50 ms in Strike&apos;s own event timestamps (the book is then exactly between two refreshes), and the history was re-derived from the stored raw events the same way. An earlier version of this scorecard sampled at arbitrary instants and understated Strike (spread uptime 86% against 100%, worst-case depth $4.7k against $315k). Details and evidence are in FEEDBACK.md. A sample with an empty side or a crossed book counts as not two-sided.</p>

      <h2>Metrics</h2>
      <h3>M1 Spread uptime</h3>
      <p>Share of samples with a two-sided book and a spread at or below 5 bps. Samples inside a recording gap do not exist, so gaps lower <i>coverage</i> but never count as up or down time.</p>
      <h3>M2 Depth within N bps</h3>
      <p>USD notional (price × size) resting within 5, 10 and 25 bps of mid, per side. A band is shown for a venue only if its feed reaches across the band; otherwise n/a.</p>
      <h3>M3 Slippage at size</h3>
      <p>For a market order of $10k, $50k or $100k, walk the book from the touch; slippage = (volume-weighted fill price − mid) / mid, in bps, buy and sell averaged on the scorecard. If the visible book cannot fill the order the sample is excluded and the fill share is reported.</p>
      <h3>M4 Cancel / fill ratio (Strike only)</h3>
      <p>Cancelled size divided by filled size from L3 <code>cancel</code>, <code>partial_fill</code> and <code>full_fill</code> events. When there are cancels but no fills the ratio is undefined and the page says so. Counts of placed, cancelled and filled orders are shown alongside.</p>
      <h3>M5 Depth resilience (Strike only)</h3>
      <p>For each taker order above $10k (fills grouped by <code>taker_order_id</code>), the time until M2 depth within 10 bps on the side it hit is back to 80% of its level just before the trade. Resolution is the 2 second sample. Waits longer than 10 minutes count as not recovered.</p>

      <h3>M6 Flow toxicity (Strike only)</h3>
      <p>For every taker order, the mid-price move over the next 10 seconds, signed in the taker&apos;s direction (positive means the price kept moving the taker&apos;s way, so resting orders were picked off), averaged over all taker orders. The mid before the trade is the last 2-second Strike sample at or before it; the mid after is the first sample at least 10 seconds later. It rests on about a thousand taker orders, so read it as an average.</p>

      <h2>Incentive designer</h2>
      <p>A transparent parametric model applied to Strike&apos;s latest recorded book: participation = min(1, rebate / adverse-selection cost); added size per side = Quoters × quote size × participation, placed at the touch; metrics recomputed with the scorecard&apos;s own functions. It is a what-if tool and not a forecast of behaviour.</p>

      <h2>Known limits</h2>
      <ul>
        <li><b>BTC-USD only.</b> L3 exists only for that symbol.</li>
        <li><b>Thin volume.</b> Strike&apos;s BTC book often records long stretches with no fills, so M4 can be undefined and M5 may have no events. Sample counts sit beside every number.</li>
        <li><b>History starts when the recorder started.</b> L3 has no replay endpoint. Every outage is a marked gap and is excluded.</li>
        <li><b>Benchmarks are not identical instruments.</b> Binance and Hyperliquid are USDT/USDC-margined perpetuals with different tick sizes and fees. Hyperliquid&apos;s feed shows 20 levels per side, Binance&apos;s snapshot holds 1,000, so wide depth bands are n/a for them. Hyperliquid bucketed levels round toward the spread, so bucketed depth is a slight lower bound.</li>
        <li><b>Visible liquidity only.</b> L3 shows resting orders, not intent; orders can be cancelled before a taker reaches them. Spread and depth measure what is displayed, not what will fill.</li>
        <li><b>Sampling.</b> Metrics are computed on a 2 second clock, so sub-2-second flickers in the book are not captured (they are in the stored L3 events).</li>
        <li>This page measures liquidity quality, not exchange integrity.</li>
      </ul>

      <h2>Verification</h2>
      <p>The rebuilt L3 book is checked against fresh REST snapshots order by order (<code>python -m follow.verify</code>), cross-checked with bookTicker, and a deliberately dropped real event is shown to corrupt the book, which is why any sequence gap triggers a full rebuild. Code and tests are in the repository.</p>
    </div></div>
    </>
  );
}

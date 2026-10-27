export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ngrok free tunnels answer browsers with an interstitial page unless this header is present
export const TUNNEL_HEADERS: Record<string, string> = API.includes("ngrok") ? { "ngrok-skip-browser-warning": "1" } : {};

export async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store", ...init, headers: { ...TUNNEL_HEADERS, ...(init?.headers as Record<string, string> | undefined) } });
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export type Venue = "strike" | "binance" | "hyperliquid";
export const VENUES: Venue[] = ["strike", "binance", "hyperliquid"];
export const VENUE_LABEL: Record<Venue, string> = {
  strike: "Strike",
  binance: "Binance",
  hyperliquid: "Hyperliquid",
};
export const VENUE_COLOR: Record<Venue, string> = {
  strike: "var(--accent)",
  binance: "var(--binance)",
  hyperliquid: "var(--hl)",
};

export const usd = (v: number | null | undefined) =>
  v == null ? "n/a" : v >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `$${(v / 1e3).toFixed(1)}k` : `$${v.toFixed(0)}`;
export const bps = (v: number | null | undefined) => (v == null ? "n/a" : `${v.toFixed(v < 10 ? 2 : 1)} bps`);
export const pct = (v: number | null | undefined) => (v == null ? "n/a" : `${(v * 100).toFixed(1)}%`);
export const mean = (a?: number | null, b?: number | null) =>
  a == null && b == null ? null : a == null ? b! : b == null ? a : (a + b) / 2;
export const sum = (a?: number | null, b?: number | null) => (a == null || b == null ? null : a + b);
export const timeLabel = (t: number) =>
  new Date(t).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

export type Window = {
  samples: number;
  two_sided_samples: number;
  coverage: number;
  mid: number | null;
  m1_spread_uptime: number | null;
  spread_bps: number | null;
  m2: Record<"d5" | "d10" | "d25", { bid: number | null; ask: number | null; n_bid: number; n_ask: number }>;
  m3: Record<
    "10k" | "50k" | "100k",
    { buy: number | null; sell: number | null; fill_rate_buy: number | null; fill_rate_sell: number | null }
  >;
};
export type CancelFill = {
  cancel_btc: number;
  fill_btc: number;
  n_cancel: number;
  n_fill: number;
  n_open: number;
  ratio: number | null;
};
export type Scorecard = {
  as_of: number;
  window_minutes: number;
  compare: string;
  compare_available: boolean;
  venues: Record<Venue, { current: Window | null; previous: Window | null }>;
  m4_strike: { current: CancelFill; previous: CancelFill | null };
  since_start: Record<Venue, Window | null>;
  m4_since_start: CancelFill;
  notes: string[];
  binance_markets: [number, string][];
};
export type Point = {
  t: number;
  samples: number;
  coverage: number;
  m1_spread_uptime: number;
  spread_bps: number;
  m2: Record<string, { bid: number | null; ask: number | null }>;
  m3: Record<string, { buy: number | null; sell: number | null }>;
};
export type Coverage = Record<
  string,
  {
    first_ts: number | null;
    last_ts: number | null;
    samples?: number;
    span_hours?: number;
    sample_coverage?: number | null;
    gap_ms?: number;
    gap_count?: number;
    count?: number;
  }
>;

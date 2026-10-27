import gzip
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS l3_events (
  sequence INTEGER NOT NULL,
  session INTEGER NOT NULL,
  ts INTEGER NOT NULL,          -- exchange time, ms
  recv_ts INTEGER NOT NULL,     -- local receive time, ms
  action TEXT NOT NULL,
  order_id TEXT, taker_order_id TEXT, side TEXT,
  price TEXT, delta_size TEXT, remaining_size TEXT, trade_id INTEGER,
  PRIMARY KEY (session, sequence)
);
CREATE INDEX IF NOT EXISTS l3_events_ts ON l3_events(ts);
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session INTEGER NOT NULL,
  kind TEXT NOT NULL,           -- 'session_start' | 'checkpoint'
  last_sequence INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  recv_ts INTEGER NOT NULL,
  body BLOB NOT NULL            -- gzip JSON of the REST snapshot
);
CREATE TABLE IF NOT EXISTS gaps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER,               -- NULL until the next sync completes
  reason TEXT NOT NULL,
  last_sequence INTEGER,
  session INTEGER,
  venue TEXT NOT NULL DEFAULT 'strike'
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- One row per venue every SAMPLE_SECONDS, computed from the full local book (see ladder.py).
CREATE TABLE IF NOT EXISTS book_samples (
  venue TEXT NOT NULL,
  ts INTEGER NOT NULL,          -- local sample time, ms
  exch_ts INTEGER,
  seq INTEGER,
  two_sided INTEGER NOT NULL,
  best_bid REAL, best_ask REAL, mid REAL, spread_bps REAL,
  bid_d5 REAL, bid_d10 REAL, bid_d25 REAL,
  ask_d5 REAL, ask_d10 REAL, ask_d25 REAL,
  buy_s10k REAL, buy_s50k REAL, buy_s100k REAL,
  sell_s10k REAL, sell_s50k REAL, sell_s100k REAL,
  PRIMARY KEY (venue, ts)
);
-- per-minute rollup of l3_events for fast M4 queries; filled by the API process (metrics.rollup_events)
CREATE TABLE IF NOT EXISTS event_minute (
  t INTEGER PRIMARY KEY,
  cancel_btc REAL, fill_btc REAL, cancel_usd REAL, fill_usd REAL,
  n_cancel INTEGER, n_fill INTEGER, n_open INTEGER
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, venue TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS strike_trades (
  trade_id INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL, recv_ts INTEGER NOT NULL,
  price TEXT NOT NULL, qty TEXT NOT NULL, buyer_is_maker INTEGER
);
CREATE TABLE IF NOT EXISTS strike_ticker (
  ts INTEGER PRIMARY KEY, recv_ts INTEGER NOT NULL, update_id INTEGER,
  bid REAL, bid_qty REAL, ask REAL, ask_qty REAL
);
"""

EVENT_COLS = ("sequence", "session", "ts", "recv_ts", "action", "order_id",
              "taker_order_id", "side", "price", "delta_size", "remaining_size", "trade_id")
SAMPLE_COLS = ("venue", "ts", "exch_ts", "seq", "two_sided", "best_bid", "best_ask", "mid", "spread_bps",
               "bid_d5", "bid_d10", "bid_d25", "ask_d5", "ask_d10", "ask_d25",
               "buy_s10k", "buy_s50k", "buy_s100k", "sell_s10k", "sell_s50k", "sell_s100k")


def now_ms() -> int:
    return int(time.time() * 1000)


def connect(path: str, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30, check_same_thread=False)
        return con
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    cols = [r[1] for r in con.execute("PRAGMA table_info(gaps)")]
    if "venue" not in cols:  # database created by the Phase 1 recorder
        con.execute("ALTER TABLE gaps ADD COLUMN venue TEXT NOT NULL DEFAULT 'strike'")
    con.commit()
    return con


def set_meta(con, key: str, value) -> None:
    con.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)))


def get_meta(con, key: str, default=None):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def next_session(con) -> int:
    n = int(get_meta(con, "session", 0)) + 1
    set_meta(con, "session", n)
    con.commit()
    return n


def insert_events(con, session: int, recv_ts: int, events: list[dict]) -> None:
    rows = [(e["sequence"], session, e["timestamp"], recv_ts, e["action"], e.get("order_id"),
             e.get("taker_order_id"), e.get("side"), e.get("price"), e.get("delta_size"),
             e.get("remaining_size"), e.get("trade_id")) for e in events]
    con.executemany(f"INSERT OR IGNORE INTO l3_events({','.join(EVENT_COLS)}) VALUES({','.join('?' * len(EVENT_COLS))})", rows)


def insert_snapshot(con, session: int, kind: str, snap: dict, recv_ts: int) -> None:
    body = gzip.compress(json.dumps(snap, separators=(",", ":")).encode())
    con.execute("INSERT INTO snapshots(session,kind,last_sequence,ts,recv_ts,body) VALUES(?,?,?,?,?,?)",
                (session, kind, snap["last_sequence"], snap["timestamp"], recv_ts, body))


def load_snapshot(row_body: bytes) -> dict:
    return json.loads(gzip.decompress(row_body))


def insert_sample(con, venue: str, ts: int, exch_ts, seq, m: dict) -> None:
    row = {"venue": venue, "ts": ts, "exch_ts": exch_ts, "seq": seq, **m}
    con.execute(f"INSERT OR REPLACE INTO book_samples({','.join(SAMPLE_COLS)}) VALUES({','.join('?' * len(SAMPLE_COLS))})",
                tuple(row.get(c) for c in SAMPLE_COLS))


def open_gap(con, start_ms: int, reason: str, last_seq, session, venue: str = "strike") -> int:
    cur = con.execute("INSERT INTO gaps(start_ms,reason,last_sequence,session,venue) VALUES(?,?,?,?,?)",
                      (start_ms, reason, last_seq, session, venue))
    return cur.lastrowid


def close_gaps(con, end_ms: int, venue: str = "strike") -> None:
    con.execute("UPDATE gaps SET end_ms=? WHERE end_ms IS NULL AND venue=?", (end_ms, venue))

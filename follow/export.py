"""Parquet export of the recorded dataset, one file per table per UTC day. Run: python -m follow.export"""
import datetime as dt
import os
import time

import pyarrow as pa
import pyarrow.parquet as pq

from . import config, db

SCHEMA_README = os.path.join(os.path.dirname(__file__), "..", "docs", "DATASET.md")
DAY = 86_400_000
TABLES = {
    "l3_events": ("ts", db.EVENT_COLS),
    "book_samples": ("ts", db.SAMPLE_COLS),
    "strike_trades": ("ts", ("trade_id", "ts", "recv_ts", "price", "qty", "buyer_is_maker")),
    "strike_ticker": ("ts", ("ts", "recv_ts", "update_id", "bid", "bid_qty", "ask", "ask_qty")),
}


I, F, T = pa.int64(), pa.float64(), pa.string()
TYPES = {
    "sequence": I, "session": I, "ts": I, "recv_ts": I, "trade_id": I, "exch_ts": I, "seq": I, "two_sided": I,
    "update_id": I, "buyer_is_maker": I, "id": I, "start_ms": I, "end_ms": I, "last_sequence": I,
    "action": T, "order_id": T, "taker_order_id": T, "side": T, "price": T, "qty": T, "delta_size": T,
    "remaining_size": T, "venue": T, "reason": T,
}


def _schema(cols):
    return pa.schema([(c, TYPES.get(c, F)) for c in cols])


def _write(con, table, ts_col, cols, start, end, path):
    cur = con.execute(f"SELECT {','.join(cols)} FROM {table} WHERE {ts_col}>=? AND {ts_col}<? ORDER BY {ts_col}", (start, end))
    writer = None
    n = 0
    tmp = path + ".tmp"
    while True:
        rows = cur.fetchmany(200_000)
        if not rows:
            break
        tbl = pa.table({c: [r[i] for r in rows] for i, c in enumerate(cols)}, schema=_schema(cols))
        if writer is None:
            writer = pq.ParquetWriter(tmp, tbl.schema, compression="zstd")
        writer.write_table(tbl)
        n += len(rows)
    if writer:
        writer.close()
        os.replace(tmp, path)
    return n


def build_all(max_age_s: int = 900):
    os.makedirs(config.EXPORT_DIR, exist_ok=True)
    con = db.connect(config.DB_PATH, readonly=True)
    now = db.now_ms()
    for table, (ts_col, cols) in TABLES.items():
        lo, hi = con.execute(f"SELECT MIN({ts_col}),MAX({ts_col}) FROM {table}").fetchone()
        if lo is None:
            continue
        for day in range(lo // DAY, hi // DAY + 1):
            name = f"{table}_{dt.datetime.fromtimestamp(day * DAY / 1000, dt.timezone.utc):%Y-%m-%d}.parquet"
            path = os.path.join(config.EXPORT_DIR, name)
            complete = (day + 1) * DAY <= now
            if os.path.exists(path) and (complete and os.path.getmtime(path) > (day + 1) * DAY / 1000 or time.time() - os.path.getmtime(path) < max_age_s):
                continue
            _write(con, table, ts_col, cols, day * DAY, (day + 1) * DAY, path)
    g = con.execute("SELECT id,venue,start_ms,end_ms,reason,last_sequence FROM gaps ORDER BY id").fetchall()
    gcols = ("id", "venue", "start_ms", "end_ms", "reason", "last_sequence")
    pq.write_table(pa.table({c: [r[i] for r in g] for i, c in enumerate(gcols)}, schema=_schema(gcols)),
                   os.path.join(config.EXPORT_DIR, "gaps.parquet"), compression="zstd")


def list_files():
    if not os.path.isdir(config.EXPORT_DIR):
        return []
    out = []
    for n in sorted(os.listdir(config.EXPORT_DIR)):
        if n.endswith(".parquet"):
            p = os.path.join(config.EXPORT_DIR, n)
            out.append({"name": n, "bytes": os.path.getsize(p), "modified": int(os.path.getmtime(p) * 1000),
                        "url": f"/api/dataset/{n}"})
    return out


def resolve(name: str):
    if "/" in name or "\\" in name or not name.endswith(".parquet"):
        return None
    p = os.path.join(config.EXPORT_DIR, name)
    return p if os.path.isfile(p) else None


if __name__ == "__main__":
    build_all(max_age_s=0)
    for f in list_files():
        print(f["name"], f["bytes"])

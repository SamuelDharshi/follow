import time

from . import config, db


def main():
    con = db.connect(config.DB_PATH)
    hb = db.get_meta(con, "heartbeat")
    n, lo, hi = con.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM l3_events").fetchone()
    print("heartbeat age (s):", round((time.time() * 1000 - int(hb)) / 1000, 1) if hb else None)
    print("events:", n, "span (h):", round((hi - lo) / 3.6e6, 3) if n else 0)
    print("snapshots:", con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
    for g in con.execute("SELECT id,start_ms,end_ms,reason FROM gaps ORDER BY id DESC LIMIT 10"):
        print("gap", g)


if __name__ == "__main__":
    main()

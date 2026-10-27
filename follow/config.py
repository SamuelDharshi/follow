import os

try:  # optional .env at the project root (never required: every feed is public)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

DB_PATH = os.environ.get("FOLLOW_DB", os.path.join(os.path.dirname(__file__), "..", "data", "follow.db"))
EXPORT_DIR = os.environ.get("FOLLOW_EXPORT_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "export"))

STRIKE_REST = os.environ.get("STRIKE_REST", "https://api.strikefinance.org")
STRIKE_WS = os.environ.get("STRIKE_WS", "wss://api.strikefinance.org")
SYMBOL = "BTC-USD"

# Binance market: "auto" (futures, else spot mirror), "futures", "spot" or "spot_mirror". Futures is closest to Strike perps.
BINANCE_MARKET = os.environ.get("BINANCE_MARKET", "auto")
BINANCE_RESYNC_SECONDS = int(os.environ.get("BINANCE_RESYNC_SECONDS", 900))
HYPERLIQUID_WS = os.environ.get("HYPERLIQUID_WS", "wss://api.hyperliquid.xyz/ws")

CHECKPOINT_SECONDS = int(os.environ.get("CHECKPOINT_SECONDS", 600))
HEARTBEAT_SECONDS = 5
FLUSH_SECONDS = 0.5
SAMPLE_SECONDS = 2
# Strike refreshes its whole book once a second in one burst of ~190 cancel/open events. Sampling mid-burst
# sees a half-empty book, so L3 samples are taken only at a gap of at least QUIET_MS in Strike's own event timestamps.
QUIET_MS = 50  # exchange-time gap that separates two refresh bursts
MAX_SAMPLE_WAIT = 5

# API
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("PORT") or os.environ.get("API_PORT", 8000))
CORS_ORIGINS = [o for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o]

# Alerts: a feed whose heartbeat is older than this is "stale". If ALERT_WEBHOOK_URL is set (Discord, Slack or any
# endpoint accepting a JSON POST) every alert is also delivered there; alerts are always stored and served at /api/alerts.
ALERT_STALE_SECONDS = int(os.environ.get("ALERT_STALE_SECONDS", 60))
ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "")

# SNAPSHOT_MODE=1: serve a recorded snapshot of the database (no recorder on this host). The site says so; nothing is generated.
SNAPSHOT_MODE = os.environ.get("SNAPSHOT_MODE", "") == "1"
if SNAPSHOT_MODE and "FOLLOW_DB" not in os.environ:
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "snapshot", "follow-snapshot.db")

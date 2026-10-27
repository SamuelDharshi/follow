"""Runs every recorder concurrently: Strike L3, Strike market feed, Binance, Hyperliquid."""
import asyncio
import logging

from . import binance, config, db, hyperliquid, strike_l3, strike_market


async def amain():
    con = db.connect(config.DB_PATH)
    await asyncio.gather(strike_l3.run_forever(con), strike_market.run_forever(con),
                         binance.run_forever(con), hyperliquid.run_forever(con))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

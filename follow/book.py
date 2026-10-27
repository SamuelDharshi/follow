"""Local L3 order book rebuilt from a REST snapshot plus WebSocket updates."""
from decimal import Decimal


class BookError(Exception):
    pass


class L3Book:
    def __init__(self, snap: dict):
        self.orders: dict[str, list] = {}   # id -> [side, price(Decimal), size(Decimal)]
        self.levels = {"buy": {}, "sell": {}}  # side -> {price: total size}
        self.sequence = snap["last_sequence"]
        for side, key in (("buy", "bids"), ("sell", "asks")):
            for lvl in snap[key]:
                p = Decimal(lvl["price"])
                for o in lvl["orders"]:
                    self._add(o["order_id"], side, p, Decimal(o["size"]))

    def _add(self, oid, side, price, size):
        if oid in self.orders:
            raise BookError(f"duplicate order {oid}")
        self.orders[oid] = [side, price, size]
        lv = self.levels[side]
        lv[price] = lv.get(price, Decimal(0)) + size

    def _reduce(self, side, price, by):
        lv = self.levels[side]
        left = lv.get(price, Decimal(0)) - by
        if left < 0:
            raise BookError("level underflow")
        if left == 0:
            lv.pop(price, None)
        else:
            lv[price] = left

    def apply(self, ev: dict) -> None:
        act = ev["action"]
        if act == "clear":
            raise BookError("clear")
        self.sequence = ev["sequence"]
        oid = ev["order_id"]
        if act == "open":
            self._add(oid, ev["side"], Decimal(ev["price"]), Decimal(ev["remaining_size"]))
            return
        o = self.orders.get(oid)
        if o is None:
            raise BookError(f"{act} for unknown order {oid}")
        side, price, size = o
        if side != ev["side"] or price != Decimal(ev["price"]):
            raise BookError(f"{act} side/price mismatch for {oid}")
        if act in ("cancel", "full_fill"):
            self._reduce(side, price, size)
            del self.orders[oid]
        elif act in ("partial_fill", "modify"):
            new = Decimal(ev["remaining_size"])
            if new <= 0 or new > size:
                raise BookError(f"bad remaining size for {oid}")
            self._reduce(side, price, size - new)
            o[2] = new
        else:
            raise BookError(f"unknown action {act}")

    def ladders(self):
        bids = sorted(((float(p), float(s)) for p, s in self.levels["buy"].items()), reverse=True)
        asks = sorted((float(p), float(s)) for p, s in self.levels["sell"].items())
        return bids, asks

    def orders_view(self) -> dict:
        return {k: (v[0], v[1], v[2]) for k, v in self.orders.items()}


def snapshot_orders(snap: dict) -> dict:
    out = {}
    for side, key in (("buy", "bids"), ("sell", "asks")):
        for lvl in snap[key]:
            for o in lvl["orders"]:
                out[o["order_id"]] = (side, Decimal(lvl["price"]), Decimal(o["size"]))
    return out

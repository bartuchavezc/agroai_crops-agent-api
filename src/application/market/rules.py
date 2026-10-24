"""The marketplace's arithmetic, kept pure so it can be tested and shown the same way everywhere: the plan's fee,
the boxes an order is packed in, the delivery calendar, distances, and the place a farm is shown at."""
import math
import unicodedata
from datetime import date, timedelta
from typing import Iterable, Optional

BOX_KG = 5.0  # the network's standard crate
ORDER_STEP_KG = 5.0  # buyers order in whole crates


def fee_rate(plan: str, rates: dict) -> float:
    return float(rates["pro_fee_rate"] if plan == "pro" else rates["free_fee_rate"])


def split(gross: float, rate: float) -> tuple[float, float]:
    """(fee, net) of a sale, rounded to cents."""
    fee = round(gross * rate, 2)
    return fee, round(gross - fee, 2)


def logistics_fee(subtotal: float, rates: dict) -> float:
    if subtotal <= 0:
        return 0.0
    return 0.0 if subtotal >= rates["free_logistics_from"] else float(rates["logistics_fee"])


def plan_month(gross: float, plan: str, rates: dict) -> dict:
    """What the month costs on the current plan and what it would have cost on the other one. The Pro fee is
    halved the next month once sales pass the threshold (the "crédito por ventas")."""
    sub = float(rates["pro_subscription"])
    free_cost = round(gross * rates["free_fee_rate"], 2)
    pro_cost = round(gross * rates["pro_fee_rate"] + sub, 2)
    cost, other = (pro_cost, free_cost) if plan == "pro" else (free_cost, pro_cost)
    fee = round(gross * fee_rate(plan, rates), 2)
    return {
        "plan": plan,
        "gross": round(gross, 2),
        "fee_rate": fee_rate(plan, rates),
        "fee": fee,
        "subscription": sub if plan == "pro" else 0.0,
        "net": round(gross - cost, 2),
        "other_plan_cost": other,
        "saving_vs_other": round(other - cost, 2),
        "next_month_discount": 0.5 if plan == "pro" and gross >= rates["pro_bonus_threshold"] else 0.0,
    }


def boxes(order_code: int, items: Iterable[tuple[str, float]]) -> list[dict]:
    """The crates a producer packs, each with its label code: 12 kg of rúcula → 5 + 5 + 2."""
    out, used = [], set()
    for title, kg in items:
        count = max(1, math.ceil(kg / BOX_KG - 1e-9))
        plain = unicodedata.normalize("NFKD", title.upper()).encode("ascii", "ignore").decode()
        base = prefix = "".join(ch for ch in plain if ch.isalpha())[:2] or "XX"  # printed on the crate: plain ASCII
        suffix = 0
        while prefix in used:  # Remolacha and Repollo: RE, REA
            prefix, suffix = base + chr(ord("A") + suffix), suffix + 1
        used.add(prefix)
        for i in range(count):
            out.append({
                "code": f"{order_code}-{prefix}{i + 1}",
                "title": title,
                "index": i + 1,
                "count": count,
                "kg": round(min(BOX_KG, kg - i * BOX_KG), 2),
            })
    return out


def next_delivery(today: date, weekday: int, cutoff_days: int) -> date:
    """The next consolidated delivery at least `cutoff_days` away (the producers need time to harvest)."""
    earliest = today + timedelta(days=cutoff_days)
    return earliest + timedelta(days=(weekday - earliest.weekday()) % 7)


def next_weekday(today: date, weekday: int) -> date:
    """Today if it is that weekday, else the next one (the Friday settlement)."""
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = math.pi / 180
    h = math.sin((lat2 - lat1) * r / 2) ** 2 + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin(
        (lng2 - lng1) * r / 2
    ) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def public_point(lat: float, lng: float, grid: float) -> tuple[float, float]:
    """Where a farm shows on the public map: snapped to a grid (~500 m), since many are someone's home."""
    if grid <= 0:
        return lat, lng
    return round(round(lat / grid) * grid, 5), round(round(lng / grid) * grid, 5)


def availability(available_from: Optional[date], today: date, lot_status: str) -> dict:
    """now, or from a date: a presale while the crop is not being harvested yet."""
    if available_from is None or available_from <= today:
        return {"kind": "now", "from": None}
    kind = "from" if lot_status == "harvesting" else "presale"
    return {"kind": kind, "from": available_from}

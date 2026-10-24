"""Red Km 0's arithmetic: fees by plan, crates, the delivery calendar, the public map point, and how a listing
follows its lot."""
from datetime import date
from types import SimpleNamespace

from src.application.market import rules
from src.application.market.service import listing_state
from src.config.settings import DEFAULT_CONFIG

RATES = DEFAULT_CONFIG["market"]


def test_fee_by_plan_and_split():
    assert rules.fee_rate("free", RATES) == 0.20
    assert rules.fee_rate("pro", RATES) == 0.08
    assert rules.split(65.0, 0.2) == (13.0, 52.0)


def test_logistics_is_free_from_the_threshold():
    assert rules.logistics_fee(0, RATES) == 0
    assert rules.logistics_fee(150, RATES) == 9
    assert rules.logistics_fee(200, RATES) == 0


def test_plan_month_compares_with_the_other_plan():
    free = rules.plan_month(383.0, "free", RATES)
    assert free["fee"] == 76.6 and free["subscription"] == 0 and free["net"] == 306.4
    assert free["other_plan_cost"] == round(383 * 0.08 + 15, 2)
    assert free["saving_vs_other"] < 0  # Pro would have been cheaper
    pro = rules.plan_month(383.0, "pro", RATES)
    assert pro["net"] == round(383 - 383 * 0.08 - 15, 2)
    assert pro["next_month_discount"] == 0.5
    assert rules.plan_month(100.0, "pro", RATES)["next_month_discount"] == 0


def test_boxes_are_five_kg_crates_with_labels():
    boxes = rules.boxes(2041, [("Rúcula", 12), ("Albahaca", 2)])
    assert [(b["code"], b["kg"]) for b in boxes] == [
        ("2041-RU1", 5), ("2041-RU2", 5), ("2041-RU3", 2), ("2041-AL1", 2),
    ]
    assert boxes[0]["count"] == 3
    same_start = rules.boxes(7, [("Remolacha", 5), ("Repollo", 5)])
    assert [b["code"] for b in same_start] == ["7-RE1", "7-REA1"]


def test_next_delivery_respects_the_cutoff():
    wed = date(2026, 10, 21)
    assert rules.next_delivery(wed, 3, 1) == date(2026, 10, 22)  # Thursday, a day ahead
    thu = date(2026, 10, 22)
    assert rules.next_delivery(thu, 3, 1) == date(2026, 10, 29)  # too late for today's
    assert rules.next_weekday(date(2026, 10, 24), 4) == date(2026, 10, 30)


def test_public_point_snaps_to_the_grid():
    lat, lng = rules.public_point(-34.85301, -58.07912, 0.005)
    assert (lat, lng) == (-34.855, -58.08)
    assert abs(rules.distance_km(-34.8712, -58.0455, -34.8530, -58.0790) - 3.64) < 0.05


def _listing(**kw):
    base = dict(status="published", available_from=None)
    return SimpleNamespace(**{**base, **kw})


def _lot(**kw):
    base = dict(status="growing", deleted_at=None, harvest_blocked_until=None)
    return SimpleNamespace(**{**base, **kw})


def test_listing_follows_its_lot():
    today = date(2026, 10, 24)
    assert listing_state(_listing(), _lot(), True, today)["on_sale"]
    for status, reason in (("failed", "lot_failed"), ("harvested", "lot_harvested"), ("planned", "lot_not_sown")):
        state = listing_state(_listing(), _lot(status=status), True, today)
        assert not state["on_sale"] and state["reason"] == reason
    assert listing_state(_listing(status="paused"), _lot(), True, today)["reason"] == "paused"
    assert listing_state(_listing(), None, True, today)["reason"] == "lot_deleted"
    assert listing_state(_listing(), _lot(), False, today)["reason"] == "producer_inactive"


def test_withholding_pushes_the_date_and_makes_it_a_presale():
    today = date(2026, 10, 24)
    state = listing_state(_listing(), _lot(harvest_blocked_until=date(2026, 10, 30)), True, today)
    assert state["on_sale"]
    assert state["availability"] == {"kind": "presale", "from": date(2026, 10, 31)}
    harvesting = listing_state(
        _listing(available_from=date(2026, 11, 2)), _lot(status="harvesting"), True, today
    )
    assert harvesting["availability"] == {"kind": "from", "from": date(2026, 11, 2)}
    past = listing_state(_listing(), _lot(harvest_blocked_until=date(2026, 10, 1)), True, today)
    assert past["availability"]["kind"] == "now"

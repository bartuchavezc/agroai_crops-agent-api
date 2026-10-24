from datetime import datetime, timezone
from uuid import uuid4

from src.application.farm.schemas import ActiveLotSummary, FieldZoneRead
from src.application.followups.capture_plan import capture_plan, zone_capture
from src.application.followups.schemas import FollowUpRead

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def _zone(number=1):
    return FieldZoneRead(id=uuid4(), account_id=uuid4(), field_id=uuid4(), type="cajon", number=number,
                         created_at=NOW, updated_at=NOW)


def _lot(zone, name, status="growing"):
    return ActiveLotSummary(id=uuid4(), crop_name=name, status=status, zone_id=zone.id, zone_ids=[zone.id])


def _followup(zone, title, severity="medium", photo_day=None, lots=()):
    return FollowUpRead(
        id=uuid4(), field_id=zone.field_id, zone_id=zone.id, lot_ids=list(lots), title=title, kind="pest",
        severity=severity, status="abierto", source="agent", created_at=NOW, updated_at=NOW,
        photo_hint=f"de cerca: {title}", last_photo=f"{title}.jpg" if photo_day else None,
        last_photo_at=datetime(2026, 10, photo_day, tzinfo=timezone.utc) if photo_day else None,
    )


def test_a_zone_without_followups_asks_for_a_general_shot_and_a_close_up():
    zone = _zone()
    tomato = _lot(zone, "Tomate")
    plan = zone_capture(zone, [tomato, _lot(zone, "Lechuga")], [])
    assert [(s.role, s.required) for s in plan.steps] == [("general", True), ("detalle", False)]
    assert "Tomate, Lechuga" in plan.steps[0].hint
    assert plan.steps[1].lot_id == tomato.id
    assert plan.steps[1].hint == "Primer plano de tomate: los brotes y las hojas nuevas"


def test_followups_take_the_slots_most_severe_and_longest_without_a_photo_first():
    zone = _zone()
    tomato, lettuce = _lot(zone, "Tomate"), _lot(zone, "Lechuga")
    aphids = _followup(zone, "Pulgón", "medium", photo_day=20, lots=[tomato.id])
    mildew = _followup(zone, "Oídio", "high", photo_day=23)
    thrips = _followup(zone, "Trips", "medium", photo_day=10)
    plan = zone_capture(zone, [tomato, lettuce], [aphids, mildew, thrips])
    assert [s.title for s in plan.steps[1:]] == ["Oídio", "Trips"]  # no room for a close-up
    assert plan.deferred_followups == 1
    step = plan.steps[1]
    assert step.followup_id == mildew.id and step.previous_photo == "Oídio.jpg" and step.hint == "de cerca: Oídio"

    one = zone_capture(zone, [tomato, lettuce], [aphids])
    assert [s.role for s in one.steps] == ["general", "seguimiento", "detalle"]
    assert one.steps[1].lot_id == tomato.id
    assert one.steps[2].lot_id == lettuce.id  # the close-up goes to a crop not already being followed


def test_only_zones_with_active_crops_in_their_order():
    first, empty, second = _zone(1), _zone(2), _zone(3)
    plan = capture_plan(uuid4(), [first, empty, second], [_lot(second, "Ajo"), _lot(first, "Tomate")], [])
    assert [z.zone_id for z in plan.zones] == [first.id, second.id]
    assert plan.max_photos == 3

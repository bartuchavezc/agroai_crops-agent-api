from datetime import datetime, timezone
from uuid import uuid4

from src.agent.reasoning.periodic_report import FollowUpEvaluation, ZoneIssue
from src.agent.reasoning.zone_followups import followup_input, issue_photo, new_issues, proposes_close
from src.application.farm.schemas import FieldEventRead
from src.application.followups.schemas import FollowUpRead


def _at(day):
    return datetime(2026, 10, day, tzinfo=timezone.utc)


def _followup():
    return FollowUpRead(
        id=uuid4(), field_id=uuid4(), title="Pulgón en tomate", kind="pest", severity="medium", status="abierto",
        source="agent", created_at=_at(18), updated_at=_at(18),
    )


def _entry(day, photos=(), **data):
    return FieldEventRead(
        id=uuid4(), account_id=uuid4(), field_id=uuid4(), type="inspection", occurred_at=_at(day), source="agent",
        created_at=_at(day), data=data, evidence=[{"kind": "photo", "identifier": p} for p in photos],
    )


def _evaluation(evolution, confidence=0.9):
    return FollowUpEvaluation(followup_id="x", evolution=evolution, evidence="", confidence=confidence)


def test_closing_is_proposed_only_after_two_confident_not_seen_in_a_row():
    assert proposes_close(_evaluation("no_visible"), [("no_visible", 0.8)])
    assert not proposes_close(_evaluation("no_visible"), [])  # the first time
    assert not proposes_close(_evaluation("no_visible"), [("mejor", 0.9)])
    assert not proposes_close(_evaluation("no_visible", 0.5), [("no_visible", 0.9)])
    assert not proposes_close(_evaluation("no_visible"), [("no_visible", 0.4)])
    assert not proposes_close(_evaluation("mejor"), [("no_visible", 0.9)])


def test_antes_is_the_newest_earlier_photo_and_evaluations_come_newest_first():
    history = [
        _entry(24, ["now.jpg"], evolution="mejor", confidence=0.8),  # this report's own photo, if re-run
        _entry(21, ["b.jpg"], evolution="igual", confidence=0.7),
        _entry(18, ["a.jpg"]),
    ]
    item = followup_input(_followup(), [], history, current_images={"now.jpg"})
    assert (item.previous_photo, item.previous_at) == ("b.jpg", _at(21))
    assert item.previous_evaluations == [("mejor", 0.8), ("igual", 0.7)]
    assert followup_input(_followup(), [], [_entry(18)], set()).previous_photo is None


def _issue(title, followup_id=None, lots=(), photo=None):
    return ZoneIssue(title=title, kind="pest", severity="medium", lot_ids=list(lots), what_was_seen="",
                     photo_hint="", followup_id=followup_id, photo_number=photo)


def test_new_issues_skip_the_followed_and_repeated_ones_and_foreign_lots():
    issues = [
        _issue("Pulgón en tomate", followup_id="f1"),
        _issue("Oídio", lots=["l1", "ghost"]),
        _issue("oídio "),  # the same, from another crop group
        _issue("Trips", followup_id="unknown"),  # names no open follow-up: new after all
    ]
    out = new_issues(issues, followed_ids={"f1"}, zone_lot_ids={"l1"})
    assert [i.title for i in out] == ["Oídio", "Trips"]
    assert out[0].lot_ids == ["l1"]


def test_issue_photo_falls_back_to_the_first():
    assert issue_photo(_issue("x", photo=2), ["a", "b"]) == "b"
    assert issue_photo(_issue("x", photo=5), ["a", "b"]) == "a"
    assert issue_photo(_issue("x"), []) is None

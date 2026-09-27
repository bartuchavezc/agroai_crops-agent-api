from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.agent.reasoning.periodic_report import (
    PeriodicReportResult,
    format_cycle_progress,
    format_event_history,
)
from src.application.farm.schemas import CropCycleRead, CropMasterRead, FieldEventRead


def _valid_result(**overrides) -> dict:
    data = dict(
        detected_crop="Tomate",
        growth_stage="floración",
        health_status="good",
        health_summary="La planta se ve sana, con buen follaje.",
        expected_vs_actual="Un poco atrasada respecto al ciclo típico, pero dentro de lo esperable.",
        growth_on_track=True,
        stress_signals=[],
        past_actions_assessment="El riego regular parece haber ayudado al desarrollo.",
        estimated_harvest_window="en 3-4 semanas",
        days_to_harvest_estimate=25,
        objectives_assessment="No hay objetivos declarados explícitamente.",
        risks=[],
        risk_severity="low",
        recommendations=["Mantener el riego actual"],
        confidence=0.8,
        needs_human_expert=False,
    )
    data.update(overrides)
    return data


def test_periodic_report_result_accepts_valid_payload():
    result = PeriodicReportResult(**_valid_result())
    assert result.health_status == "good"
    assert result.risk_severity == "low"


def test_periodic_report_result_rejects_invalid_health_status():
    with pytest.raises(ValidationError):
        PeriodicReportResult(**_valid_result(health_status="meh"))


def test_periodic_report_result_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        PeriodicReportResult(**_valid_result(confidence=1.5))


def _crop_master(**overrides) -> CropMasterRead:
    data = dict(
        id=uuid4(),
        account_id=None,
        name="Tomate",
        variety="Cherry",
        growth_period_days=90,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    data.update(overrides)
    return CropMasterRead(**data)


def _crop_cycle(**overrides) -> CropCycleRead:
    data = dict(
        id=uuid4(),
        account_id=uuid4(),
        field_id=uuid4(),
        crop_master_id=uuid4(),
        planting_date=date(2026, 8, 1),
        expected_harvest_date=date(2026, 10, 30),
        status="growing",
        notes="Objetivo: autoconsumo familiar.",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    data.update(overrides)
    return CropCycleRead(**data)


def test_format_cycle_progress_includes_days_elapsed_and_notes():
    cycle = _crop_cycle()
    crop_master = _crop_master()
    text = format_cycle_progress(cycle, crop_master, date(2026, 9, 27))
    assert "Tomate (Cherry)" in text
    assert "57 días atrás" in text
    assert "90 días" in text
    assert "Objetivo: autoconsumo familiar." in text
    assert "growing" in text


def test_format_cycle_progress_handles_missing_crop_master():
    cycle = _crop_cycle(planting_date=None, notes=None)
    text = format_cycle_progress(cycle, None, date(2026, 9, 27))
    assert "desconocido" in text
    assert "días atrás" not in text


def test_format_event_history_renders_type_quantity_and_notes():
    events = [
        FieldEventRead(
            id=uuid4(),
            account_id=uuid4(),
            field_id=uuid4(),
            crop_cycle_id=uuid4(),
            author_user_id=uuid4(),
            type="irrigation",
            occurred_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
            quantity=10,
            unit="litros",
            notes="riego matutino",
            source="user",
            created_at=datetime.now(timezone.utc),
        )
    ]
    lines = format_event_history(events)
    assert lines == ["2026-09-20 - irrigation - 10.0 litros - riego matutino"]


def test_format_event_history_empty_list():
    assert format_event_history([]) == []

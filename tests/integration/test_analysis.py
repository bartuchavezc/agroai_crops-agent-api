"""
What the analyses (zone/crop tracking, soil sample) put in front of the model: physiology and the crops' own manuals as
references, the field's data and records as context, and the deep web-research pass when the first pass finds something.
"""
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID

from src.agent.reasoning.periodic_report import ZoneCropAssessment, ZonePeriodicReportResult
from src.agent.schemas import SoilRecognitionResult
from src.application.satellite.models import ZoneSatelliteReading
from src.application.soil_data.schemas import SoilGridsEstimate, SoilLayerEstimate
from src.providers.search.tavily import SearchHit
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow

from .test_agent_chat import scripted_model, with_key  # noqa: F401 - fixtures
from .test_zones import _TINY_PNG, _cycle

FARM = "/api/v1/farm-management"
DAYS = [
    {"date": f"2026-09-{i:02d}", "temp_max_c": 22.0, "temp_min_c": 9.0, "temp_mean_c": 15.5,
     "precipitation_mm": 0.0, "et0_mm": 3.0}
    for i in range(1, 31)
]


def _zone_result(cycles, risk="low", confidence=0.8):
    return ZonePeriodicReportResult(
        zone_summary="El cantero viene parejo.", overall_health="good",
        crops=[
            ZoneCropAssessment(
                crop_cycle_id=c["id"], crop_name=name, visible_in_photos=True, growth_stage="vegetativo",
                health_status="good", health_summary="hojas verdes", expected_vs_actual="Acorde",
                harvest_ready=False, harvest_verdict="Sin frutos",
            )
            for c, name in cycles
        ],
        past_actions_assessment="ok", objectives_assessment="ok", risk_severity=risk,
        recommendations=["Atar los tomates"], confidence=confidence, needs_human_expert=False,
    )


async def _zone_with_crops(client, container, signup, name):
    user = await signup(name)
    h = user["headers"]
    field = (await client.post(
        f"{FARM}/fields", headers=h, json={"name": "Huerta", "latitude": -34.92, "longitude": -57.95}
    )).json()
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    tomato = await _cycle(client, h, field["id"], "tomate", zone_id=zone["id"])
    lettuce = await _cycle(client, h, field["id"], "lechuga", zone_id=zone["id"])
    await _cycle(client, h, field["id"], "acelga")  # another zone: NOT part of this analysis
    actor = Actor(UUID(user["user"]["id"]), UUID(user["account"]["id"]), "owner")
    repo = container.application.zone_satellite_repository()
    await repo.create(ZoneSatelliteReading(
        account_id=actor.account_id, field_id=UUID(field["id"]), captured_at=utcnow() - timedelta(days=3),
        ndvi_mean=0.58, ndvi_min=0.4, ndvi_max=0.7, ndwi_mean=0.1,
    ))
    return user, field, zone, [(tomato, "Tomate"), (lettuce, "Lechuga")], actor


async def _track_zone(client, headers, zone):
    up = await client.post(
        "/api/v1/upload/zone-tracking", headers=headers, data={"zone_id": zone["id"]},
        files=[("image_files", ("a.png", _TINY_PNG, "image/png"))],
    )
    assert up.status_code == 200, up.text
    return (await client.get(f"/api/v1/reports/{up.json()['report_id']}", headers=headers)).json()


async def test_crop_analysis_gets_physiology_the_manuals_of_its_crops_and_the_field_data(client, signup, container):
    user, field, zone, cycles, _ = await _zone_with_crops(client, container, signup, "an-crop")
    weather = container.data_providers.weather_service()
    weather._recent_cache.clear()
    fake = AsyncMock(return_value=_zone_result(cycles))
    with patch.object(container.agent.gemini(), "generate_structured", fake), \
            patch.object(weather.open_meteo, "recent_daily", AsyncMock(return_value=DAYS)):
        report = await _track_zone(client, user["headers"], zone)

    assert fake.await_count == 1  # a quiet zone: no deep pass
    system = fake.call_args.kwargs["system_instruction"]
    physiology = system.index("## Referencia: fisiologia-nutricion-mineral-fundamentos")
    # physiology first (identical for every analysis: the shared prefix), then the crops in a fixed alphabetical order
    assert physiology < system.index("## Referencia: ficha-lechuga") < system.index("## Referencia: ficha-tomate")
    for name in ("fisiologia-macronutrientes-npk-s", "fisiologia-agua-suelo-y-absorcion", "plagas-tomate"):
        assert f"## Referencia: {name}" in system
    assert "ficha-acelga" not in system  # a crop of another zone isn't this analysis' business
    assert "Material de referencia" in system and "Cómo usar el material de referencia" in system
    assert fake.call_args.kwargs["thinking_level"] == "medium"

    prompt = fake.call_args.kwargs["contents"][-1]
    assert "Datos del campo y registros" in prompt
    assert "NDVI 0.58" in prompt  # the stored satellite series
    assert "Clima de los últimos 30 días" in prompt and "balance hídrico" in prompt
    research = report["raw_analysis_data"]["research"]
    assert research["deep"] is False and "ficha-tomate" in research["references"]


async def test_deep_pass_searches_the_web_and_refines_with_the_sources(client, signup, container):
    user, field, zone, cycles, actor = await _zone_with_crops(client, container, signup, "an-deep")
    weather = container.data_providers.weather_service()
    weather._recent_cache.clear()
    service = container.agent.diagnosis_service()
    first = _zone_result(cycles, risk="high", confidence=0.55)
    refined = _zone_result(cycles, risk="medium", confidence=0.85)
    refined.zone_summary = "Mancha bacteriana confirmada por las fuentes."
    fake = AsyncMock(side_effect=[first, refined])
    hit = SearchHit(title="INTA: mancha bacteriana en tomate", url="https://inta.gob.ar/mancha", content="Manejo: ...")
    search = AsyncMock(return_value=[hit])
    with patch.object(container.agent.gemini(), "generate_structured", fake), \
            patch.object(weather.open_meteo, "recent_daily", AsyncMock(return_value=DAYS)), \
            patch.object(service.analysis_context, "search", type("S", (), {"search": search})()):
        report = await _track_zone(client, user["headers"], zone)

    assert fake.await_count == 2 and search.await_count >= 1
    first_call, second_call = fake.await_args_list
    assert first_call.kwargs["thinking_level"] == "medium" and second_call.kwargs["thinking_level"] == "high"
    refined_prompt = second_call.kwargs["contents"][-1]
    assert "Tu primer análisis" in refined_prompt and "INTA: mancha bacteriana en tomate" in refined_prompt
    assert "https://inta.gob.ar/mancha" in refined_prompt
    assert report["summary"] == "Mancha bacteriana confirmada por las fuentes."  # the refined analysis is the one kept
    research = report["raw_analysis_data"]["research"]
    assert research["deep"] is True and research["sources"] == [{"title": hit.title, "url": hit.url}]
    assert "inta" in research["queries"][0].lower()  # aimed at the official sources of the country

    # Forcing it off for one analysis: only the first pass runs.
    fake.reset_mock(side_effect=True)
    fake.return_value = first
    with patch.object(container.agent.gemini(), "generate_structured", fake), \
            patch.object(weather.open_meteo, "recent_daily", AsyncMock(return_value=DAYS)):
        await service.analyze(actor, UUID(report["id"]), deep=False)
    assert fake.await_count == 1


async def test_soil_analysis_reads_the_photo_with_the_zone_data(client, signup, container):
    user = await signup("an-soil")
    h = user["headers"]
    field = (await client.post(
        f"{FARM}/fields", headers=h, json={"name": "Lote", "latitude": 20.5, "longitude": -101.6}
    )).json()
    await _cycle(client, h, field["id"], "tomate")
    actor = Actor(UUID(user["user"]["id"]), UUID(user["account"]["id"]), "owner")
    await container.application.zone_satellite_repository().create(ZoneSatelliteReading(
        account_id=actor.account_id, field_id=UUID(field["id"]), captured_at=utcnow() - timedelta(days=2),
        ndvi_mean=0.41, ndvi_min=0.3, ndvi_max=0.5, ndwi_mean=0.02,
    ))
    estimate = SoilGridsEstimate(depths={
        "0-5cm": SoilLayerEstimate(ph=7.5, organic_carbon_g_kg=16.7, nitrogen_g_kg=1.68, cec_cmolc_kg=28.2),
        "15-30cm": SoilLayerEstimate(ph=7.6, organic_carbon_g_kg=12.1, nitrogen_g_kg=1.31, cec_cmolc_kg=28.0),
    })
    soilgrids = container.application.soilgrids_repository()
    weather = container.data_providers.weather_service()
    weather._recent_cache.clear()
    result = SoilRecognitionResult(
        apparent_soil_type="franco-arcilloso", apparent_porosity="media", visual_evidence="terrón oscuro",
        drainage_note="drena regular", confidence=0.5, explicit_limitations="Una foto no mide nutrientes.",
        zone_data_interpretation="El pH de la zona (7.5, estimado) es alcalino.",
        amendment_suggestions=["Sumar materia orgánica"],
    )
    fake = AsyncMock(return_value=result)
    with patch.object(container.agent.gemini(), "generate_structured", fake), \
            patch.object(soilgrids, "estimate", AsyncMock(return_value=(True, estimate))) as ask, \
            patch.object(weather.open_meteo, "recent_daily", AsyncMock(return_value=DAYS)):
        up = await client.post(
            "/api/v1/upload/image", headers=h, data={"report_type": "soil", "field_id": field["id"]},
            files={"image_file": ("a.png", _TINY_PNG, "image/png")},
        )
        assert up.status_code == 200, up.text
        again = await client.post(
            "/api/v1/upload/image", headers=h, data={"report_type": "soil", "field_id": field["id"]},
            files={"image_file": ("a.png", _TINY_PNG, "image/png")},
        )
        assert again.status_code == 200, again.text

    system = fake.call_args_list[0].kwargs["system_instruction"]
    assert "## Referencia: core-fertilizantes-y-enmiendas" in system and "## Referencia: ficha-tomate" in system
    assert "ficha-" in system and "plagas-" not in system  # a soil read doesn't carry the pest guides
    prompt = fake.call_args_list[0].kwargs["contents"][-1]
    assert "SoilGrids" in prompt and "pH 7.5" in prompt and "carbono orgánico 16.7 g/kg" in prompt
    assert "NDVI 0.41" in prompt and "Clima de los últimos 30 días" in prompt
    report = (await client.get(f"/api/v1/reports/{up.json()['report_id']}", headers=h)).json()
    assert report["raw_analysis_data"]["llm_structured_soil"]["zone_data_interpretation"].startswith("El pH")

    # SoilGrids was asked once and remembered in the field: the second sample didn't call it again.
    assert ask.await_count == 1
    stored = (await client.get(f"{FARM}/fields/{field['id']}", headers=h)).json()["soil_context"]
    assert stored["soilgrids_checked"] is True and stored["soilgrids"]["depths"]["0-5cm"]["ph"] == 7.5

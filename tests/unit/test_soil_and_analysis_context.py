from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.agent.reasoning.analysis_context import (
    CROP_PHYSIOLOGY,
    AnalysisContextBuilder,
    crop_slug,
)
from src.application.soil_data.schemas import SoilContext, SoilGridsEstimate, SoilLayerEstimate
from src.application.soil_data.service import SoilContextService
from src.providers.search.tavily import SearchHit

async def test_soil_service_asks_soilgrids_once_and_keeps_the_inta_data():
    estimate = SoilGridsEstimate(depths={"0-5cm": SoilLayerEstimate(ph=7.5)})
    adapter = SimpleNamespace(estimate=AsyncMock(return_value=(True, estimate)))
    service = SoilContextService(repository=None, soilgrids=adapter)
    inta = SoilContext(soil_order="Molisol", ph_estimate=6.4).model_dump(mode="json")

    merged = await service.add_soilgrids(inta, -34.9, -57.9)
    assert merged["soil_order"] == "Molisol" and merged["soilgrids"]["depths"]["0-5cm"]["ph"] == 7.5
    assert merged["soilgrids_checked"] is True
    assert await service.add_soilgrids(merged, -34.9, -57.9) is merged  # already asked
    assert adapter.estimate.await_count == 1


async def test_soil_service_remembers_no_data_but_retries_when_unreachable():
    rest = SimpleNamespace(estimate=AsyncMock(return_value=(True, None)))
    service = SoilContextService(repository=None, soilgrids=rest)
    only = await service.add_soilgrids(None, 20.68, -101.35)  # an urban pixel: answered, nothing there
    assert only["soilgrids_checked"] is True and only["soilgrids"] is None and "SoilGrids" in only["source"]

    rest_down = SimpleNamespace(estimate=AsyncMock(return_value=(False, None)))
    down = SoilContextService(repository=None, soilgrids=rest_down)
    assert await down.add_soilgrids(None, 20.5, -101.6) is None  # not stored: it will be tried again later
    assert await SoilContextService(repository=None).add_soilgrids(None, 20.5, -101.6) is None  # offline service


def test_crop_slug_matches_catalog_names_to_sheets():
    assert crop_slug('Tomate "Redondo"') == "tomate" and crop_slug("Lechuga mantecosa") == "lechuga"
    assert crop_slug("Maíz dulce") == "maiz" and crop_slug("Zapallito de tronco") == "zapallito"
    assert crop_slug("Quinoa") is None


def test_crop_references_put_physiology_first_then_each_crop_in_a_fixed_order():
    names = AnalysisContextBuilder.crop_reference_names(['Tomate "Cherry"', "Lechuga", "Tomate", "Quinoa"])
    assert names[: len(CROP_PHYSIOLOGY)] == list(CROP_PHYSIOLOGY)
    assert names[len(CROP_PHYSIOLOGY):] == ["ficha-lechuga", "plagas-lechuga", "ficha-tomate", "plagas-tomate"]
    text, loaded = AnalysisContextBuilder.references_for(names)
    assert "plagas-lechuga" not in loaded  # no pest guide for lettuce yet: skipped, not an error
    assert loaded[:4] == list(CROP_PHYSIOLOGY) and "ficha-tomate" in loaded
    assert text.count("## Referencia: ") == len(loaded)


async def test_ndvi_lines_summarize_the_fields_own_series():
    analysis = SimpleNamespace(
        has_data=True, last_pass={"date": "2026-09-28", "ndvi_mean": 0.58}, days_since_last_pass=3, phenology={},
        status=lambda m: {"ndvi": {"value": 0.58, "trend_15d": -0.07}, "ndre": {"value": 0.31}}.get(m),
    )
    builder = AnalysisContextBuilder(None, None, None, SimpleNamespace(analyze=AsyncMock(return_value=analysis)))
    lines = await builder.ndvi_lines(SimpleNamespace(account_id=1), SimpleNamespace(id=2))
    text = "\n".join(lines)
    assert "NDVI 0.58" in text and "NDRE (vigor): 0.31" in text and "-0.07" in text and "NDWI" not in text
    empty = SimpleNamespace(has_data=False)
    quiet = AnalysisContextBuilder(None, None, None, SimpleNamespace(analyze=AsyncMock(return_value=empty)))
    assert "Todavía no hay una serie" in "\n".join(await quiet.ndvi_lines(SimpleNamespace(account_id=1), None))
    broken = AnalysisContextBuilder(None, None, None, SimpleNamespace(analyze=AsyncMock(side_effect=RuntimeError)))
    assert await broken.ndvi_lines(SimpleNamespace(account_id=1), None) == []


def test_soil_lines_combine_inta_and_soilgrids():
    ctx = SoilContext(
        soil_order="Molisol", texture_surface="franca", ph_estimate=6.4,
        soilgrids=SoilGridsEstimate(depths={"0-5cm": SoilLayerEstimate(ph=7.5, organic_carbon_g_kg=16.7)}),
    )
    lines = AnalysisContextBuilder.soil_lines(SimpleNamespace(soil_context=ctx))
    assert "INTA" in lines[0] and "Molisol" in lines[0] and "pH estimado 0-30 cm: 6.4" in lines[0]
    assert "NO un análisis de laboratorio" in lines[1] and "pH 7.5" in lines[2]
    assert AnalysisContextBuilder.soil_lines(SimpleNamespace(soil_context=None)) == []


def test_queries_aim_at_the_countrys_official_sources_and_are_capped():
    builder = AnalysisContextBuilder(None, None, None, None)
    ar = builder.queries_for(["Tomate"], ["mancha bacteriana", "", "tizón", "a", "b"], "AR")
    assert len(ar) == 3 and ar[0] == "Tomate mancha bacteriana manejo INTA SENASA"
    assert "SENASICA" in builder.queries_for(["Jitomate"], ["mosca blanca"], "MX")[0]


async def test_research_dedupes_sources_and_survives_a_failing_search():
    hits = [
        SearchHit(title="A", url="https://a", content="x" * 2000),
        SearchHit(title="B", url="https://b", content="y"),
    ]

    async def search(query, max_results=5):
        if "falla" in query:
            raise RuntimeError("boom")
        return hits

    builder = AnalysisContextBuilder(None, None, None, None, search=SimpleNamespace(search=search))
    text, sources = await builder.research(["una", "otra", "falla"])
    assert sources == [{"title": "A", "url": "https://a"}, {"title": "B", "url": "https://b"}]  # the repeat is dropped
    assert text.count("### Búsqueda:") == 1 and len(text) < 2500  # snippets are cut
    assert await AnalysisContextBuilder(None, None, None, None).research(["x"]) == ("", [])  # search not configured

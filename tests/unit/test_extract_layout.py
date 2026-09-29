import io
from types import SimpleNamespace

import pytest
from PIL import Image

from src.agent.schemas import PlanElement, PlanExtraction, PlanPoint
from src.agent.tools.layout import extract_layout_from_photo
from src.application.farm.schemas import LayoutPhoto
from src.shared.domain.actor import Actor
from src.shared.utils.errors import InvalidInputError
from tests.unit.test_layout_geometry import _field


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (90, 160), "green").save(buffer, format="PNG")
    return buffer.getvalue()


class FakeGemini:
    def __init__(self, extraction: PlanExtraction):
        self.extraction = extraction
        self.calls: list[dict] = []

    async def generate_structured(self, user_id, contents, schema, system_instruction=None, model=None):
        self.calls.append({"contents": contents, "schema": schema, "system": system_instruction})
        return self.extraction


class FakeStorage:
    async def get_image_for_model(self, actor, identifier, max_side):
        return _png(), "image/png"


def _deps(extraction: PlanExtraction):
    return SimpleNamespace(gemini=FakeGemini(extraction), storage=FakeStorage())


def _actor():
    from uuid import uuid4

    return Actor(user_id=uuid4(), account_id=uuid4(), role="owner")


def _photo(**overrides) -> LayoutPhoto:
    base = dict(id="p1", image_identifier="img", camera_bearing_degrees=230, status="processing",
                entorno_ancho_m=18, entorno_largo_m=42, camera_height_m=1.5, pitch_degrees=-4)
    return LayoutPhoto(**{**base, **overrides})


PLAN = PlanExtraction(elements=[
    PlanElement(label="Pared del fondo", type="pared", kind="polyline", height_m=2.4, confidence=0.9,
                points=[PlanPoint(x=-9, y=42), PlanPoint(x=9, y=42)]),
    PlanElement(label="Pileta", type="pileta", kind="polygon", height_m=0, confidence=0.9,
                points=[PlanPoint(x=-5, y=8), PlanPoint(x=-1, y=8), PlanPoint(x=-1, y=14), PlanPoint(x=-5, y=14)]),
])


@pytest.mark.asyncio
async def test_the_model_gets_the_photo_the_entorno_measures_and_nothing_else_to_describe():
    deps = _deps(PLAN)
    photo = _photo(reference_note="El poste está a 5 m")
    objects, camera = await extract_layout_from_photo(deps, _actor(), photo, _field())
    call = deps.gemini.calls[0]
    assert call["schema"] is PlanExtraction  # the answer IS the plan JSON: no prose field to fill in
    context = call["contents"][1]
    assert "(-9, 0) (9, 0) (9, 42) (-9, 42)" in context  # the user's 18 x 42, in the photo's frame
    assert "1.5 m" in context and "-4°" in context and "El poste está a 5 m" in context
    assert "Ejemplo 1" in call["system"] and "Ejemplo 2" in call["system"]  # few-shot
    assert {o["type"] for o in objects} >= {"entorno", "pared", "pileta"}


@pytest.mark.asyncio
async def test_the_entorno_is_the_users_rectangle_and_the_far_wall_lands_42_m_from_the_camera():
    objects, camera = await extract_layout_from_photo(_deps(PLAN), _actor(), _photo(), _field())
    entorno = next(o for o in objects if o["type"] == "entorno")
    wall = next(o for o in objects if o["label"] == "Pared del fondo")
    xs = [p[0] for p in entorno["points"]]
    ys = [p[1] for p in entorno["points"]]
    diagonal = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
    assert diagonal > 42  # a rotated 18 x 42 rectangle
    wall_mid = ((wall["points"][0][0] + wall["points"][1][0]) / 2, (wall["points"][0][1] + wall["points"][1][1]) / 2)
    assert ((wall_mid[0] - camera[0]) ** 2 + (wall_mid[1] - camera[1]) ** 2) ** 0.5 == pytest.approx(42, abs=0.1)
    assert wall["photo_id"] == "p1" and wall["source"] == "photo_ai"


@pytest.mark.asyncio
async def test_the_campo_comes_from_the_fields_own_measures_not_from_the_entorno():
    field = _field(width_m=5, length_m=8)
    objects, _ = await extract_layout_from_photo(_deps(PLAN), _actor(), _photo(), field)
    campo = next(o for o in objects if o["type"] == "campo")
    xs = [p[0] for p in campo["points"]]
    ys = [p[1] for p in campo["points"]]
    assert (max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx((5, 8))
    no_measures, _ = await extract_layout_from_photo(_deps(PLAN), _actor(), _photo(), _field())
    assert not any(o["type"] == "campo" for o in no_measures)  # nothing invented when the field has no measures


@pytest.mark.asyncio
async def test_without_the_entornos_measures_it_fails_with_a_message_the_user_can_act_on():
    with pytest.raises(InvalidInputError, match="medidas del entorno"):
        unmeasured = _photo(entorno_ancho_m=None, entorno_largo_m=None)
        await extract_layout_from_photo(_deps(PLAN), _actor(), unmeasured, _field())


@pytest.mark.asyncio
async def test_an_existing_entorno_the_user_edited_is_respected_and_not_recreated():
    from src.application.farm.schemas import LayoutObject

    edited = LayoutObject(
        id="e", type="entorno", label="Entorno", kind="polygon", points=[(0, 0), (10, 0), (10, 30), (0, 30)]
    )
    objects, _ = await extract_layout_from_photo(_deps(PLAN), _actor(), _photo(), _field(layout_objects=[edited]))
    assert not any(o["type"] == "entorno" for o in objects)

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.application.farm.schemas import LayoutPhoto
from src.application.farm.service import FarmService
from src.shared.domain.actor import Actor
from src.shared.utils.errors import InvalidInputError

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


class FakeRepo:
    """Just enough of FarmRepository for the layout-photo methods: one field held in memory."""

    def __init__(self):
        self.field = SimpleNamespace(
            id=uuid.uuid4(), account_id=uuid.uuid4(), name="Huerta", city=None, latitude=-34.6, longitude=-58.4,
            boundary=None, description=None, soil_type=None, area_m2=None, length_m=None, width_m=None,
            layout_objects=[], layout_photos=[], soil_context=None, created_at=NOW(), updated_at=NOW(),
        )

    async def get_field(self, account_id, field_id):
        return self.field

    async def update_field(self, account_id, field_id, values):
        for key, value in values.items():
            setattr(self.field, key, value)
        return self.field


def _service():
    repo = FakeRepo()
    actor = Actor(user_id=uuid.uuid4(), account_id=repo.field.account_id, role="owner")
    return FarmService(repo, None, None), repo, actor


def _photo(**overrides):
    base = dict(
        id="p1", image_identifier="img", camera_bearing_degrees=90, status="processing", updated_at=NOW().isoformat()
    )
    return LayoutPhoto(**{**base, **overrides})


OBJECT = {
    "id": "o1", "type": "arbol", "label": "Ligustro", "x_m": 3.0, "y_m": 4.0, "height_m": 5.0, "source": "photo_ai",
}


@pytest.mark.asyncio
async def test_finishing_merges_objects_and_marks_the_photo_done():
    service, repo, actor = _service()
    await service.add_layout_photo(actor, repo.field.id, _photo())
    await service.finish_layout_photo(actor, repo.field.id, "p1", [OBJECT], None)
    assert repo.field.layout_photos[0]["status"] == "done"
    assert [o["id"] for o in repo.field.layout_objects] == ["o1"]


@pytest.mark.asyncio
async def test_finishing_twice_does_not_duplicate_objects():
    service, repo, actor = _service()
    await service.add_layout_photo(actor, repo.field.id, _photo())
    await service.finish_layout_photo(actor, repo.field.id, "p1", [OBJECT], None)
    await service.finish_layout_photo(actor, repo.field.id, "p1", [OBJECT], None)
    assert len(repo.field.layout_objects) == 1


@pytest.mark.asyncio
async def test_failure_is_recorded_and_can_be_retried_without_reuploading():
    service, repo, actor = _service()
    await service.add_layout_photo(actor, repo.field.id, _photo())
    await service.finish_layout_photo(actor, repo.field.id, "p1", None, "boom")
    assert (repo.field.layout_photos[0]["status"], repo.field.layout_photos[0]["error"]) == ("failed", "boom")
    retried = await service.restart_layout_photo(actor, repo.field.id, "p1")
    assert (retried.status, retried.error) == ("processing", None)
    assert repo.field.layout_photos[0]["image_identifier"] == "img"


@pytest.mark.asyncio
async def test_retry_is_refused_while_fresh_but_allowed_once_stuck():
    service, repo, actor = _service()
    await service.add_layout_photo(actor, repo.field.id, _photo())
    with pytest.raises(InvalidInputError):
        await service.restart_layout_photo(actor, repo.field.id, "p1")
    repo.field.layout_photos[0]["updated_at"] = (NOW() - timedelta(minutes=10)).isoformat()
    assert (await service.restart_layout_photo(actor, repo.field.id, "p1")).status == "processing"


@pytest.mark.asyncio
async def test_result_for_a_deleted_photo_is_ignored():
    service, repo, actor = _service()
    await service.add_layout_photo(actor, repo.field.id, _photo())
    await service.remove_layout_photo(actor, repo.field.id, "p1")
    await service.finish_layout_photo(actor, repo.field.id, "p1", [OBJECT], None)
    assert repo.field.layout_objects == [] and repo.field.layout_photos == []


@pytest.mark.asyncio
async def test_reprocessing_a_finished_photo_replaces_its_objects_instead_of_duplicating_them():
    service, repo, actor = _service()
    await service.add_layout_photo(actor, repo.field.id, _photo())
    await service.finish_layout_photo(actor, repo.field.id, "p1", [{**OBJECT, "photo_id": "p1"}], None, (1.0, 2.0))
    assert [o["id"] for o in repo.field.layout_objects] == ["o1"]
    restarted = await service.restart_layout_photo(
        actor, repo.field.id, "p1", entorno_ancho_m=18, entorno_largo_m=42, camera_height_m=1.6
    )
    assert (restarted.status, restarted.entorno_ancho_m, restarted.entorno_largo_m) == ("processing", 18, 42)
    assert repo.field.layout_objects == []  # the old result is gone; the new one will be added when it finishes
    await service.finish_layout_photo(actor, repo.field.id, "p1", [{**OBJECT, "id": "o2", "photo_id": "p1"}], None)
    assert [o["id"] for o in repo.field.layout_objects] == ["o2"]


@pytest.mark.asyncio
async def test_reprocessing_a_legacy_photo_also_clears_the_untagged_ai_objects_of_the_old_method():
    service, repo, actor = _service()
    legacy_photo = _photo(status="done")  # processed by the old method: no camera position recorded
    await service.add_layout_photo(actor, repo.field.id, legacy_photo)
    repo.field.layout_objects = [
        dict(OBJECT, id="old-ai"),  # AI, no photo_id: from the old bucket method
        dict(OBJECT, id="mine", source="manual", label="Mi reja"),  # the user's own: must stay
    ]
    await service.restart_layout_photo(actor, repo.field.id, "p1")
    assert [o["id"] for o in repo.field.layout_objects] == ["mine"]


@pytest.mark.asyncio
async def test_a_plan_keeps_a_single_entorno_and_a_single_campo_even_if_photos_finish_in_parallel():
    service, repo, actor = _service()
    entorno = {"id": "e1", "type": "entorno", "label": "Entorno", "kind": "polygon", "height_m": 0,
               "points": [[0, 0], [18, 0], [18, 42], [0, 42]], "source": "manual"}
    await service.add_layout_photo(actor, repo.field.id, _photo(id="a"))
    await service.add_layout_photo(actor, repo.field.id, _photo(id="b"))
    await service.finish_layout_photo(actor, repo.field.id, "a", [entorno, OBJECT], None)
    second = [{**entorno, "id": "e2"}, {**OBJECT, "id": "o9"}]
    await service.finish_layout_photo(actor, repo.field.id, "b", second, None)
    assert sorted(o["id"] for o in repo.field.layout_objects) == ["e1", "o1", "o9"]  # the second entorno is dropped

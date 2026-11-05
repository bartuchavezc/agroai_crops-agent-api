"""The agent's background work: the chat hands over a job, the worker runs it with a to-do list and a subagent per
lot (its own context, writing the tracking plan), within a budget of model calls, pausing for the person's approval
when it needs to change their data — and the result lands in the conversation."""
import uuid
from datetime import date

from .test_agent_chat import no_title_calls, scripted_model, with_key  # noqa: F401 - fixtures

FARM = "/api/v1/farm-management"

PLAN = {
    "summary": "Lechuga en cantero, riego con manguera.", "current_stage": "vegetativo",
    "stages": [{"key": "vegetativo", "name": "Crecimiento", "status": "actual"},
               {"key": "cosecha", "name": "Cosecha"}],
    "items": [{"section": "revision", "title": "Hojas externas", "why": "Ver vigor", "how": "Foto de una planta"}],
}


async def _lot(client, h):
    field = (await client.post(f"{FARM}/fields", headers=h, json={"name": "Quinta", "latitude": -34.6,
                                                                   "longitude": -58.4})).json()
    zone = (await client.post(f"{FARM}/fields/{field['id']}/zones", headers=h, json={"type": "cantero"})).json()
    crop = (await client.get(f"{FARM}/crop-masters?q=lechuga", headers=h)).json()[0]["id"]
    return field, (await client.post(f"{FARM}/lots", headers=h, json={
        "field_id": field["id"], "crop_master_id": crop, "zone_ids": [zone["id"]], "status": "planted",
        "planting_date": date.today().isoformat()})).json()


async def test_a_lot_is_planned_in_the_background_by_a_subagent(
    client, signup, with_key, scripted_model, container  # noqa: F811
):
    user = await signup("tasks")
    await with_key(user)
    h = user["headers"]
    _, lot = await _lot(client, h)

    scripted_model.script = [
        ("call", "plan_lots_tracking", {"lot_ids": [lot["id"]]}),
        ("text", "Lo estoy armando, te aviso acá."),
    ]
    r = await client.post("/api/v1/chat", headers=h, json={"message": "planificá el seguimiento de la lechuga"})
    assert r.status_code == 200, r.text
    conversation_id = r.json()["metadata"]["conversation_id"]
    tasks = (await client.get(f"/api/v1/agent-tasks?conversation_id={conversation_id}", headers=h)).json()
    assert len(tasks) == 1 and tasks[0]["status"] == "queued" and tasks[0]["kind"] == "plan_lots"

    runner = container.agent.long_task_runner()
    scripted_model.script = [
        ("call", "write_todos", {"items": ["Planificar la lechuga del cantero 1"]}),
        ("call", "run_subagent", {"kind": "lot_planner", "lot_id": lot["id"], "instructions": "Plan inicial"}),
        # the subagent: its own context, writes the plan and answers with a summary
        ("call", "save_tracking_plan", {"lot_id": lot["id"], "plan": PLAN, "reason": "Plan inicial"}),
        ("text", "Plan armado: está en crecimiento, revisión de hojas externas."),
        # back in the orchestrator
        ("call", "update_todo", {"todo_id": "__TODO__", "status": "done"}),
        ("text", "Listo: armé el plan de seguimiento de la lechuga."),
    ]

    original = runner.tasks.set_todos

    async def capture(task_id, todos):  # the orchestrator learns the generated to-do id from write_todos
        result = await original(task_id, todos)
        for step in scripted_model.script:
            if step[0] == "call" and step[1] == "update_todo" and step[2]["todo_id"] == "__TODO__":
                step[2]["todo_id"] = todos[0].id
        return result

    runner.tasks.set_todos = capture
    try:
        assert await runner.run_once(uuid.UUID(user["account"]["id"])) is not None
    finally:
        runner.tasks.set_todos = original

    task = (await client.get(f"/api/v1/agent-tasks/{tasks[0]['id']}", headers=h)).json()
    assert task["status"] == "done", task
    assert [t["status"] for t in task["todos"]] == ["done"]
    assert task["used_calls"] == 6 and any(e["kind"] == "subagent" for e in task["trace"])
    plan = (await client.get(f"{FARM}/lots/{lot['id']}/tracking-plan", headers=h)).json()
    assert plan["content"]["summary"] == PLAN["summary"]
    # the subagent's context never reached the orchestrator: only its summary did
    orchestrator_last = scripted_model.requests[-1]
    assert "save_tracking_plan" not in str(orchestrator_last.contents)
    messages = (await client.get(f"/api/v1/chat/conversations/{conversation_id}/messages", headers=h)).json()
    assert messages[-1]["content"] == "Listo: armé el plan de seguimiento de la lechuga."
    assert await runner.run_once(uuid.UUID(user["account"]["id"])) is None  # nothing else queued


async def test_a_task_pauses_for_approval_and_respects_its_budget(
    client, signup, with_key, scripted_model, container  # noqa: F811
):
    user = await signup("approval")
    await with_key(user)
    h = user["headers"]
    field, lot = await _lot(client, h)
    scripted_model.script = [("call", "start_long_task", {"goal": "Sumá una zona para la próxima siembra"}),
                             ("text", "Arranco.")]
    r = await client.post("/api/v1/chat", headers=h, json={"message": "armá lo que falta"})
    conversation_id = r.json()["metadata"]["conversation_id"]
    task_id = (await client.get(f"/api/v1/agent-tasks?conversation_id={conversation_id}", headers=h)).json()[0]["id"]

    runner = container.agent.long_task_runner()
    scripted_model.script = [
        ("call", "propose_changes", {"title": "Nueva zona", "operations": [
            {"op": "create", "entity": "zone", "data": {"field_id": field["id"], "type": "cajon"}}]}),
        ("call", "wait_for_approval", {"proposal_id": "__PROPOSAL__"}),
        ("text", "Te dejé la zona nueva para confirmar."),
    ]
    from src.agent.tools import changes as change_tools

    real_tools = change_tools.change_tools

    def patched(deps, ctx):
        [propose] = real_tools(deps, ctx)

        async def propose_changes(title: str, operations: list[dict]) -> dict:
            out = await propose(title=title, operations=operations)
            scripted_model.script[0][2]["proposal_id"] = out["proposal_id"]
            return out
        propose_changes.__name__ = "propose_changes"
        return [propose_changes]

    from unittest.mock import patch
    with patch("src.agent.tools.change_tools", patched):
        await runner.run_once(uuid.UUID(user["account"]["id"]))
    task = (await client.get(f"/api/v1/agent-tasks/{task_id}", headers=h)).json()
    assert task["status"] == "waiting_approval" and task["proposal_id"]
    messages = (await client.get(f"/api/v1/chat/conversations/{conversation_id}/messages", headers=h)).json()
    assert messages[-1]["attachments"][0]["proposal_id"] == task["proposal_id"]

    # nothing happens until the person decides; then it resumes with its own history
    assert await runner.run_once(uuid.UUID(user["account"]["id"])) is None
    applied = await client.post(f"/api/v1/chat/proposals/{task['proposal_id']}/apply", headers=h, json={})
    assert applied.status_code == 200, applied.text
    scripted_model.script = [("text", "Listo, la zona quedó creada.")]
    assert await runner.run_once(uuid.UUID(user["account"]["id"])) is not None
    task = (await client.get(f"/api/v1/agent-tasks/{task_id}", headers=h)).json()
    assert task["status"] == "done" and task["result"] == "Listo, la zona quedó creada."
    assert "aplicó la propuesta" in str(scripted_model.requests[-1].contents)

    # a task that runs out of model calls stops, says so and keeps what it did
    from src.shared.domain.actor import Actor
    actor = Actor(user_id=uuid.UUID(user["user"]["id"]), account_id=uuid.UUID(user["account"]["id"]), role="owner")
    small = await container.agent.long_task_service().create(actor, "general", "Algo largo", {},
                                                             conversation_id=uuid.UUID(conversation_id))
    async with container.agent.long_task_service().session_factory() as session:
        from src.agent.long_tasks.models import AgentTask
        row = await session.get(AgentTask, small.id)
        row.max_calls = 2
        await session.commit()
    scripted_model.script = [("call", "list_lots", {}), ("call", "list_lots", {}), ("call", "list_lots", {}),
                             ("text", "nunca llega")]
    await runner.run_once(uuid.UUID(user["account"]["id"]))
    task = (await client.get(f"/api/v1/agent-tasks/{small.id}", headers=h)).json()
    assert task["status"] == "failed" and "presupuesto" in task["error"]

    cancel = await client.post(f"/api/v1/agent-tasks/{small.id}/cancel", headers=h)
    assert cancel.status_code == 400


async def test_sowing_and_zone_analyses_queue_the_planner(client, signup, container):
    user = await signup("hooks")
    h = user["headers"]
    field, lot = await _lot(client, h)
    crop = lot["crop_master_id"]
    planned = (await client.post(f"{FARM}/lots", headers=h, json={
        "field_id": field["id"], "crop_master_id": crop, "status": "planned"})).json()
    sown = await client.post(f"/api/v1/planning/lots/{planned['id']}/sow", headers=h, json={})
    assert sown.status_code == 200, sown.text
    tasks = (await client.get("/api/v1/agent-tasks", headers=h)).json()
    assert [(t["kind"], t["input"]["lot_ids"]) for t in tasks] == [("plan_lots", [planned["id"]])]

    from src.shared.domain.actor import Actor
    from src.application.tracking.schemas import TrackingPlanContent
    actor = Actor(user_id=uuid.UUID(user["user"]["id"]), account_id=uuid.UUID(user["account"]["id"]), role="owner")
    await container.application.tracking_plan_service().save(
        actor, uuid.UUID(lot["id"]), TrackingPlanContent.model_validate(PLAN), "x")
    hooks = container.agent.long_task_hooks()

    class Report:
        id = uuid.uuid4()
        status = "ANALYSIS_COMPLETED"
        zone_id = uuid.uuid4()
        lot_ids = [uuid.UUID(lot["id"])]
        created_at = __import__("datetime").datetime.now()
        summary = "Botones florales en la lechuga: se está espigando"
        title = None

    from unittest.mock import AsyncMock, patch
    with patch.object(hooks.reports, "get_report", AsyncMock(return_value=Report())):
        await hooks.zone_analyzed(actor, Report.id)
        await hooks.zone_analyzed(actor, Report.id)  # a second analysis joins the queued re-plan
    replans = [t for t in (await client.get("/api/v1/agent-tasks", headers=h)).json() if t["kind"] == "replan_lot"]
    assert len(replans) == 1 and len(replans[0]["input"]["observations"]) == 2
    assert "espigando" in replans[0]["input"]["observations"][0]

from dataclasses import dataclass

from src.agent.reasoning.zone_task_loop import (
    MAX_RECHECKS,
    ZoneTask,
    count_rechecks,
    make_recheck_task,
    needs_recheck,
    ready_tasks,
    run_zone_tasks,
)


@dataclass
class _Group:
    id: str = "tomate"


@dataclass
class _GroupResult:
    group_risk_severity: str = "low"
    confidence: float = 0.9


def _tasks():
    return [
        ZoneTask(id="overview", kind="overview"),
        ZoneTask(id="group:tomate", kind="group", payload={"group": _Group("tomate")}),
        ZoneTask(id="group:lechuga", kind="group", payload={"group": _Group("lechuga")}),
        ZoneTask(id="synthesis", kind="synthesis"),
    ]


def test_overview_and_group_tasks_are_ready_immediately():
    tasks = _tasks()
    ready = {t.id for t in ready_tasks(tasks)}
    assert ready == {"overview", "group:tomate", "group:lechuga"}


def test_synthesis_is_not_ready_until_everything_else_is_terminal():
    tasks = _tasks()
    tasks[0].status = "done"  # overview
    tasks[1].status = "done"  # group:tomate
    assert "synthesis" not in {t.id for t in ready_tasks(tasks)}  # group:lechuga still pending
    tasks[2].status = "done"
    assert "synthesis" in {t.id for t in ready_tasks(tasks)}


def test_synthesis_waits_on_a_failed_task_too_not_just_done_ones():
    tasks = _tasks()
    tasks[0].status, tasks[1].status, tasks[2].status = "done", "failed", "done"
    assert "synthesis" in {t.id for t in ready_tasks(tasks)}  # failed still counts as terminal


def test_needs_recheck_on_high_risk_or_low_confidence():
    assert needs_recheck(_GroupResult(group_risk_severity="high", confidence=0.9)) is True
    assert needs_recheck(_GroupResult(group_risk_severity="critical", confidence=0.9)) is True
    assert needs_recheck(_GroupResult(group_risk_severity="low", confidence=0.4)) is True
    assert needs_recheck(_GroupResult(group_risk_severity="low", confidence=0.9)) is False


def test_make_recheck_task_references_its_group():
    group_task = ZoneTask(id="group:tomate", kind="group", payload={"group": _Group("tomate")})
    recheck = make_recheck_task(group_task)
    assert recheck.id == "recheck:tomate" and recheck.kind == "recheck"
    assert recheck.payload["group"].id == "tomate"


async def test_run_zone_tasks_runs_until_nothing_is_pending():
    tasks = _tasks()
    calls = []

    async def execute(task):
        calls.append(task.id)
        if task.kind == "overview":
            return object()
        if task.kind == "group":
            return _GroupResult()
        return object()  # synthesis

    done = await run_zone_tasks(tasks, execute)
    assert {t.status for t in done} == {"done"}
    # overview + both groups ran before synthesis (order within that first batch isn't asserted, just that
    # synthesis came last).
    assert calls[-1] == "synthesis" and set(calls[:-1]) == {"overview", "group:tomate", "group:lechuga"}


async def test_run_zone_tasks_adds_a_recheck_for_a_concerning_group_before_synthesis():
    tasks = _tasks()

    async def execute(task):
        if task.kind == "group" and task.id == "group:tomate":
            return _GroupResult(group_risk_severity="critical", confidence=0.9)
        return _GroupResult()

    done = await run_zone_tasks(tasks, execute)
    assert count_rechecks(done) == 1
    recheck = next(t for t in done if t.kind == "recheck")
    assert recheck.status == "done"
    # synthesis ran only after the recheck too.
    synthesis = next(t for t in done if t.kind == "synthesis")
    assert synthesis.status == "done"


async def test_run_zone_tasks_caps_rechecks_at_max_rechecks():
    tasks = [
        ZoneTask(id=f"group:{i}", kind="group", payload={"group": _Group(str(i))})
        for i in range(MAX_RECHECKS + 2)
    ]
    tasks.append(ZoneTask(id="synthesis", kind="synthesis"))

    async def execute(task):
        return _GroupResult(group_risk_severity="critical", confidence=0.9)  # every group looks concerning

    done = await run_zone_tasks(tasks, execute)
    assert count_rechecks(done) == MAX_RECHECKS


async def test_run_zone_tasks_does_not_hang_if_a_task_fails():
    tasks = _tasks()

    async def execute(task):
        if task.id == "group:tomate":
            raise RuntimeError("quota exceeded")
        return _GroupResult()

    done = await run_zone_tasks(tasks, execute)
    statuses = {t.id: t.status for t in done}
    assert statuses["group:tomate"] == "failed"
    assert statuses["synthesis"] == "done"  # still ran on what succeeded

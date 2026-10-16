"""
Task-queue scheduler for a zone's periodic analysis: a small dependency graph (one "overview" task, one
"group" task per crop group, one "synthesis" task depending on all the others), resolved by repeatedly
running whatever is ready until nothing is pending — not a fixed, hand-written sequence with a sleep between
calls.

This is the same shape real agent loops use (Codex CLI, OpenCode, ReAct in general: think, act, observe,
decide the next step, repeat until done, with an explicit bound) — but implemented as deterministic
application code in this layer, not by letting the model itself drive the sequence through
src/agent/runner.py's ADK tool-calling loop. That loop is built for a live chat turn (session, turn lock,
one image); this is a backend batch job over a fixed, known unit of work (every active crop of a zone) where
cost, coverage and testability matter more than letting the model improvise the order.

See zone_grouping.py for how crops are grouped and the results merged back into one report, and
diagnosis_service.py for what each task kind actually asks Gemini and how the graph is built.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

logger = logging.getLogger(__name__)

TaskKind = Literal["overview", "group", "synthesis", "recheck"]
TaskStatus = Literal["pending", "done", "failed"]

# A group result concerning enough to look at again on its own, with no other groups' fichas competing for
# context — an explicit, auditable rule, not a model judgment about whether to keep going.
MAX_RECHECKS = 3
RECHECK_RISK_SEVERITIES = ("high", "critical")
RECHECK_CONFIDENCE_FLOOR = 0.6


@dataclass
class ZoneTask:
    id: str
    kind: TaskKind
    payload: dict = field(default_factory=dict)
    status: TaskStatus = "pending"
    result: Any = None


def ready_tasks(tasks: list[ZoneTask]) -> list[ZoneTask]:
    """Pure: pending tasks whose dependencies are resolved. `overview`/`group` tasks have none. `synthesis`
    is special-cased to depend on EVERY other task, whatever that set ends up being — a `recheck` task can
    still be appended after synthesis's dependencies would otherwise have been fixed, so a static id set
    would miss it; this way synthesis simply never becomes ready while anything else is still pending."""
    ready = []
    for task in tasks:
        if task.status != "pending":
            continue
        if task.kind == "synthesis":
            if all(other.status != "pending" for other in tasks if other.id != task.id):
                ready.append(task)
        else:
            ready.append(task)
    return ready


def needs_recheck(result: Any) -> bool:
    """Pure: should this group's single crop/cycle be looked at again on its own before the zone synthesizes?"""
    return (
        getattr(result, "group_risk_severity", "low") in RECHECK_RISK_SEVERITIES
        or getattr(result, "confidence", 1.0) < RECHECK_CONFIDENCE_FLOOR
    )


def make_recheck_task(group_task: ZoneTask) -> ZoneTask:
    return ZoneTask(id=f"recheck:{group_task.payload['group'].id}", kind="recheck", payload=group_task.payload)


def count_rechecks(tasks: list[ZoneTask]) -> int:
    return sum(1 for t in tasks if t.kind == "recheck")


async def run_zone_tasks(
    tasks: list[ZoneTask], execute: Callable[[ZoneTask], Awaitable[Any]]
) -> list[ZoneTask]:
    """Runs every task once it is ready, until none remain pending — "until done", not a fixed number of
    passes decided up front. One call in flight at a time: every sub-call shares the same per-user BYOK
    client and quota (there is no pacing/concurrency infrastructure anywhere else in this codebase to lean
    on), so the single place to relax that later is letting one "ready" batch run with a small concurrency
    cap, not the shape of the graph. A task's own failure doesn't abort the rest: it just never unblocks
    whatever depended on it (synthesis still runs on whatever succeeded; the caller decides afterwards
    whether that's enough to call the zone analysis a success — see diagnosis_service.py)."""
    while any(t.status == "pending" for t in tasks):
        batch = ready_tasks(tasks)
        if not batch:
            logger.warning("Zone analysis stuck: nothing is ready but tasks remain pending")
            break
        for task in batch:
            logger.info(f"Zone task {task.id!r} ({task.kind}) starting")
            started = time.monotonic()
            try:
                task.result = await execute(task)
                task.status = "done"
            except Exception:
                logger.exception(f"Zone task {task.id!r} ({task.kind}) failed after {time.monotonic() - started:.1f}s")
                task.status = "failed"
                continue
            logger.info(f"Zone task {task.id!r} ({task.kind}) done in {time.monotonic() - started:.1f}s")
            if task.kind == "group" and count_rechecks(tasks) < MAX_RECHECKS and needs_recheck(task.result):
                logger.info(
                    f"Zone task {task.id!r} triggered a recheck "
                    f"(severity={getattr(task.result, 'group_risk_severity', None)!r}, "
                    f"confidence={getattr(task.result, 'confidence', None)})"
                )
                tasks.append(make_recheck_task(task))
    return tasks

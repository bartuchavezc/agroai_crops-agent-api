"""
A correlation id threaded through every log line of one unit of work (one HTTP request, one background
analysis, one chat turn), via a contextvar rather than a parameter plumbed through every function signature
in between. `logger.py` installs a `logging.Filter` that reads it on every record, so any `logger.info(...)`
anywhere in the codebase picks it up for free once it's set.

Call `set_trace_id` once near the top of a unit of work with the most meaningful id already at hand (a
report id, a conversation id) so the logs are grep-able by a domain id, not a throwaway uuid. `main.py`'s
middleware sets a generic fallback for everything else so no log line is ever left without one.
"""
import contextvars
from uuid import uuid4

_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")


def new_trace_id() -> str:
    return uuid4().hex[:12]


def set_trace_id(value: str) -> None:
    _trace_id.set(value)


def current_trace_id() -> str:
    return _trace_id.get()

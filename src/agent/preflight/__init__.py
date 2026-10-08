"""Preflight: gather first, ask the model once.

Without it, answering "why are my tomato leaves yellow?" takes a model call to decide to load a skill, another to load
the next, another for the weather, another for the satellite... and every call re-sends the whole prompt. With it, a
cheap router call picks everything the message needs, all of it is fetched in parallel, and the chat model answers once
with the knowledge and the data already in front of it. The chat model can still call tools afterwards (to write
records, or to look something up the router missed), so a wrong plan costs a round trip, never a wrong answer.
"""
from .blocks import prune_consulted_blocks
from .engine import PreflightEngine, PreflightInputs, PreflightResult
from .plan import PreflightPlan, ToolRequest

__all__ = [
    "PreflightEngine", "PreflightInputs", "PreflightPlan", "PreflightResult", "ToolRequest", "prune_consulted_blocks",
]

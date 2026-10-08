"""What the router returns: which skills to load and which read-only tools to run for a message."""
from typing import Optional

from pydantic import BaseModel, Field


class ToolRequest(BaseModel):
    name: str = Field(description="Exact name of a tool from the tools menu")
    # A JSON object as text: Gemini's structured output doesn't take free-form objects, and each tool differs.
    args: str = Field(default="{}", description='The tool arguments as a JSON object string, e.g. {"field": "Huerta"}')


class PreflightPlan(BaseModel):
    skills: list[str] = Field(
        default_factory=list, description="Exact skill names from the skills menu, most important first"
    )
    tools: list[ToolRequest] = Field(default_factory=list, description="Read-only tools to run, from the tools menu")
    web_query: Optional[str] = Field(
        default=None, description="One specific web search (with the country), or null if the web is not needed"
    )
    reason: str = Field(default="", description="One short sentence: why this plan")

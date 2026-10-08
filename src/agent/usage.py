"""Token usage of one chat turn, summed over every model call the turn made (agent loop steps included).

Cost lives in the tokens: the fixed prompt is re-sent on each step of the loop, so `llm_calls` is as telling as
`prompt_tokens`. `cached_tokens` is the part of the prompt billed at the cached rate (implicit or explicit cache).
"""
from dataclasses import dataclass


@dataclass
class TurnUsage:
    llm_calls: int = 0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0

    def add(self, usage_metadata) -> None:
        """Account one *complete* model response (not the streaming partials) carrying `usage_metadata`."""
        if usage_metadata is None:
            return
        self.llm_calls += 1
        self.prompt_tokens += usage_metadata.prompt_token_count or 0
        self.cached_tokens += usage_metadata.cached_content_token_count or 0
        self.output_tokens += usage_metadata.candidates_token_count or 0
        self.thinking_tokens += usage_metadata.thoughts_token_count or 0

    @property
    def seen(self) -> bool:
        return self.llm_calls > 0

    def log_line(self, conversation_id, model: str) -> str:
        return (
            f"turn_usage conversation={conversation_id} model={model} llm_calls={self.llm_calls} "
            f"prompt_tokens={self.prompt_tokens} cached_tokens={self.cached_tokens} "
            f"output_tokens={self.output_tokens} thinking_tokens={self.thinking_tokens}"
        )

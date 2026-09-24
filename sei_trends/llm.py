"""Thin wrapper around Claude structured outputs."""

from __future__ import annotations

from typing import TypeVar

import anthropic
from pydantic import BaseModel

DEFAULT_MODEL = "claude-opus-5"
# Server-side refusal fallback: if the primary model declines, the API re-runs
# the request on a fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class ClaudeClient:
    def __init__(self, model: str = DEFAULT_MODEL, client: anthropic.Anthropic | None = None):
        self.model = model
        self.client = client or anthropic.Anthropic()

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        output_type: type[T],
        effort: str = "high",
        max_tokens: int = 16000,
    ) -> T:
        # Streaming avoids HTTP timeouts on long syntheses; get_final_message() still parses.
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            output_format=output_type,
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise LLMError("model declined the request")
        if response.stop_reason == "max_tokens":
            raise LLMError(f"output truncated at max_tokens={max_tokens}")
        if response.parsed_output is None:
            raise LLMError(f"no parsed output (stop_reason={response.stop_reason})")
        return response.parsed_output

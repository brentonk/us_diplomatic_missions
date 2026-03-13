"""Anthropic API wrapper with retry, logging, and metadata extraction."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from .models import ApiMetadata


class ApiClient:
    """Wrapper around anthropic.AsyncAnthropic with retry, concurrency control, and logging."""

    def __init__(
        self,
        log_dir: Path,
        max_retries: int = 5,
        concurrency: int = 5,
    ):
        self.client = anthropic.AsyncAnthropic()
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / "api_calls.jsonl"
        self.max_retries = max_retries
        self.semaphore = asyncio.Semaphore(concurrency)

    async def call_with_tools(
        self,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0,
        max_tokens: int = 4096,
    ) -> tuple[dict | None, ApiMetadata]:
        """Make an API call with tool use and return (tool_result, metadata).

        Retries on 429/500/529 with exponential backoff.
        Logs complete request and response to JSONL.
        Returns the tool use input (parsed JSON) and API metadata.
        """
        request_body = {
            "model": model,
            "system": system,
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with self.semaphore:
            response = await self._call_with_retry(request_body)

        # Extract metadata
        metadata = ApiMetadata(
            message_id=response.id,
            model=response.model,
            usage={"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
            stop_reason=response.stop_reason,
        )

        # Extract tool use result
        tool_result = None
        for block in response.content:
            if block.type == "tool_use":
                tool_result = block.input
                break

        # Log request and response
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request": {
                "model": model,
                "system": system[:200] + "..." if len(system) > 200 else system,
                "messages_count": len(messages),
                "tools_count": len(tools),
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            "response": {
                "id": response.id,
                "model": response.model,
                "usage": metadata.usage,
                "stop_reason": response.stop_reason,
                "content_types": [b.type for b in response.content],
            },
        }
        self._append_log(log_entry)

        # Also log full request/response to a detailed log
        detailed_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request": request_body,
            "response": {
                "id": response.id,
                "type": response.type,
                "role": response.role,
                "model": response.model,
                "usage": metadata.usage,
                "stop_reason": response.stop_reason,
                "content": [_serialize_content_block(b) for b in response.content],
            },
        }
        detailed_log_path = self.log_dir / "api_calls_detailed.jsonl"
        with open(detailed_log_path, "a") as f:
            f.write(json.dumps(detailed_entry, default=str) + "\n")

        return tool_result, metadata

    async def _call_with_retry(self, request_body: dict) -> anthropic.types.Message:
        """Call the API with exponential backoff retry on transient errors."""
        for attempt in range(self.max_retries):
            try:
                response = await self.client.messages.create(**request_body)
                return response
            except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIStatusError) as e:
                if isinstance(e, anthropic.APIStatusError) and e.status_code not in (429, 500, 529):
                    raise
                if attempt == self.max_retries - 1:
                    raise
                wait_time = min(2 ** attempt * 2, 60)
                print(f"  API error (attempt {attempt + 1}/{self.max_retries}): {e}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)

        raise RuntimeError("Exhausted all retries")

    def _append_log(self, entry: dict) -> None:
        """Append a JSON entry to the log file."""
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")


def _serialize_content_block(block) -> dict:
    """Serialize an API content block to a dict."""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    elif block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    else:
        return {"type": block.type}

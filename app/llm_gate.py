"""LLM Gate: Rate limiting, concurrency semaphore, exponential backoff, fallback, and observability.

Every LLM call in ScholarSwarm passes through this gate.
Never drops a request due to 429; retries with exponential backoff and falls back.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import litellm

from app.config import (
    CHAOS_RATE,
    LLM_CONCURRENCY,
    LLM_FALLBACK_MODEL,
    LLM_FAST,
    LLM_RPM,
    LLM_SMART,
    LLM_TPM,
    VERTEXAI_FALLBACK_LOCATION,
    VERTEXAI_LOCATION,
    VERTEXAI_PROJECT,
    has_gemini_key,
)
from app.events import EventBus, global_bus

# Explicitly configure LiteLLM router to drop unsupported parameters (like thinking) across providers
litellm.drop_params = True


class TokenBucket:
    """Token bucket rate limiter managing both Requests Per Minute (RPM) and Tokens Per Minute (TPM)."""

    def __init__(self, rpm: int, tpm: int = LLM_TPM) -> None:
        self.rpm_capacity: float = float(rpm)
        self.rpm_tokens: float = float(rpm)
        self.rpm_fill_rate: float = float(rpm) / 60.0  # requests per second

        self.tpm_capacity: float = float(tpm)
        self.tpm_tokens: float = float(tpm)
        self.tpm_fill_rate: float = float(tpm) / 60.0  # tokens per second

        self.last_update: float = time.monotonic()
        self._lock = asyncio.Lock()
        self.agent_usage: dict[str, int] = {}

    async def acquire(self, estimated_tokens: int = 500, agent: str = "general") -> None:
        """Acquire 1 request token and estimated token quota, enforcing provider quotas."""
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.last_update = now

                # Refill RPM and TPM
                self.rpm_tokens = min(self.rpm_capacity, self.rpm_tokens + elapsed * self.rpm_fill_rate)
                self.tpm_tokens = min(self.tpm_capacity, self.tpm_tokens + elapsed * self.tpm_fill_rate)

                if self.rpm_tokens >= 1.0 and self.tpm_tokens >= estimated_tokens:
                    self.rpm_tokens -= 1.0
                    self.tpm_tokens -= float(estimated_tokens)
                    self.agent_usage[agent] = self.agent_usage.get(agent, 0) + estimated_tokens
                    return

                # Calculate wait time needed for refill
                req_wait = (1.0 - self.rpm_tokens) / self.rpm_fill_rate if self.rpm_tokens < 1.0 else 0.0
                tok_wait = (estimated_tokens - self.tpm_tokens) / self.tpm_fill_rate if self.tpm_tokens < estimated_tokens else 0.0
                wait_time = max(req_wait, tok_wait)
                await asyncio.sleep(max(0.05, min(wait_time, 2.0)))


class LLMGate:
    """Central gateway for all LLM calls with resilience and telemetry."""

    def __init__(
        self,
        rpm: int = LLM_RPM,
        tpm: int = LLM_TPM,
        concurrency: int = LLM_CONCURRENCY,
        fallback_model: str = LLM_FALLBACK_MODEL,
    ) -> None:
        litellm.drop_params = True
        self.bucket = TokenBucket(rpm=rpm, tpm=tpm)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.fallback_model = fallback_model
        self.total_calls: int = 0
        self.total_429s: int = 0
        self.total_fallbacks: int = 0

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        tier: str = "fast",  # "fast" | "smart"
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
        bus: EventBus | None = None,
        run_id: str = "",
        agent_name: str = "LLM",
        chaos: bool = False,
    ) -> str:
        """Execute an LLM completion through the gate."""
        event_bus = bus or global_bus

        # Determine target model
        target_model = model or (LLM_SMART if tier == "smart" else LLM_FAST)
        current_model = target_model
        used_fallback = False

        max_attempts = 4
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            t0 = time.time()
            start_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0))

            # Acquire rate limit token and concurrency slot enforcing RPM & TPM quotas
            await self.bucket.acquire(estimated_tokens=min(max_tokens, 1000), agent=agent_name)

            async with self.semaphore:
                try:
                    # Chaos mode injection
                    if chaos or (CHAOS_RATE > 0 and random.random() < CHAOS_RATE):
                        if (chaos and attempt == 1) or random.random() < 0.35:
                            event_bus.emit(
                                {
                                    "run_id": run_id,
                                    "agent": agent_name,
                                    "type": "chaos_injected",
                                    "phase": "llm",
                                    "message": f"Simulating transient 429 on {current_model}",
                                    "data": {"attempt": attempt, "model": current_model},
                                }
                            )
                            raise litellm.RateLimitError(
                                message="Chaos injected RateLimitError 429",
                                llm_provider="chaos",
                                model=current_model,
                            )

                    kwargs: dict[str, Any] = {
                        "model": current_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "drop_params": True,  # Explicitly drop unsupported parameters across model providers
                    }
                    if current_model.startswith("vertex_ai/"):
                        kwargs["vertex_project"] = VERTEXAI_PROJECT
                        kwargs["vertex_location"] = VERTEXAI_FALLBACK_LOCATION if used_fallback else VERTEXAI_LOCATION
                    if response_format:
                        kwargs["response_format"] = response_format

                    # Minimize reasoning budget for fast tier on models that support it
                    if tier == "fast" and not used_fallback:
                        kwargs["thinking"] = {"budget_tokens": 0}

                    resp = await litellm.acompletion(**kwargs)
                    duration_ms = int((time.time() - t0) * 1000)
                    self.total_calls += 1

                    content = ""
                    if resp.choices and len(resp.choices) > 0:
                        content = resp.choices[0].message.content or ""

                    tokens_in = getattr(resp.usage, "prompt_tokens", 0) if hasattr(resp, "usage") else 0
                    tokens_out = getattr(resp.usage, "completion_tokens", 0) if hasattr(resp, "usage") else 0

                    event_bus.emit(
                        {
                            "run_id": run_id,
                            "agent": agent_name,
                            "type": "llm_call",
                            "phase": "llm",
                            "message": f"{current_model} responded in {duration_ms}ms",
                            "duration_ms": duration_ms,
                            "data": {
                                "start": start_iso,
                                "end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "model": current_model,
                                "attempt": attempt,
                                "tokens_in": tokens_in,
                                "tokens_out": tokens_out,
                                "ok": True,
                            },
                        }
                    )
                    return content

                except (litellm.RateLimitError, litellm.ServiceUnavailableError, TimeoutError, Exception) as exc:
                    last_error = exc
                    duration_ms = int((time.time() - t0) * 1000)
                    error_msg = str(exc)
                    is_rate_limit = (
                        isinstance(exc, litellm.RateLimitError)
                        or "429" in error_msg
                        or "RESOURCE_EXHAUSTED" in error_msg
                        or "quota" in error_msg.lower()
                    )

                    if is_rate_limit:
                        self.total_429s += 1

                    # Log attempt failure
                    event_bus.emit(
                        {
                            "run_id": run_id,
                            "agent": agent_name,
                            "type": "retry",
                            "phase": "llm",
                            "message": f"LLM {current_model} attempt {attempt} failed: {type(exc).__name__}. Backing off...",
                            "duration_ms": duration_ms,
                            "data": {
                                "model": current_model,
                                "attempt": attempt,
                                "error": error_msg[:200],
                                "is_rate_limit": is_rate_limit,
                            },
                        }
                    )

                    # If repeatedly failing, 429 rate limit hit, or authentication failed on an invalid key, switch to fallback
                    is_auth_error = isinstance(exc, litellm.AuthenticationError) or "API key not valid" in error_msg
                    should_fallback = (attempt >= 2 or is_rate_limit or is_auth_error) and not used_fallback

                    if should_fallback:
                        used_fallback = True
                        self.total_fallbacks += 1
                        prev_model = current_model
                        # If auth error or unauthenticated AI Studio gemini/ model, failover safely within Vertex AI (us-east4)
                        if is_auth_error or (self.fallback_model and self.fallback_model.startswith("gemini/") and not has_gemini_key):
                            current_model = "vertex_ai/gemini-2.5-flash"
                        elif self.fallback_model:
                            current_model = self.fallback_model
                        else:
                            current_model = "vertex_ai/gemini-2.5-flash"

                        event_bus.emit(
                            {
                                "run_id": run_id,
                                "agent": agent_name,
                                "type": "fallback",
                                "phase": "llm",
                                "message": f"Failing over from {prev_model} to {current_model} (region: {VERTEXAI_FALLBACK_LOCATION})",
                                "data": {
                                    "from": prev_model,
                                    "to": current_model,
                                    "fallback_region": VERTEXAI_FALLBACK_LOCATION,
                                    "reason": error_msg[:200],
                                },
                            }
                        )

                    # Check for Retry-After header or compute exponential backoff with jitter
                    retry_after = getattr(exc, "retry_after", None)
                    if retry_after is not None and isinstance(retry_after, (int, float)):
                        backoff = float(retry_after) + random.uniform(0.1, 0.5)
                    else:
                        backoff = (2.0 ** (attempt - 1)) + random.uniform(0.2, 0.8)

                    await asyncio.sleep(min(backoff, 15.0))

        # If exhausted all attempts
        event_bus.emit(
            {
                "run_id": run_id,
                "agent": agent_name,
                "type": "error",
                "phase": "llm",
                "message": f"LLM calls failed after {max_attempts} attempts: {last_error}",
                "data": {"model": current_model, "error": str(last_error)},
            }
        )
        raise RuntimeError(f"LLM call failed after {max_attempts} attempts: {last_error}")


# Global instance
default_gate = LLMGate()

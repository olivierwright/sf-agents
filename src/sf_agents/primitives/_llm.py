"""The *only* module permitted to talk to AWS Bedrock.

Everything else in sf-agents depends on the thin surface exposed here --
:func:`complete` and :func:`complete_json` -- so the LLM provider stays
swappable and ``boto3`` never leaks into the rest of the codebase.

Configuration is read from the environment (never hard-coded):

* ``AWS_REGION``                    -- region serving the inference profile.
* ``BEDROCK_INFERENCE_PROFILE_ARN`` -- preferred; a cross-region profile ARN.
* ``BEDROCK_MODEL_ID``              -- fallback model id if the ARN is unset.

There is intentionally **no default model**: the operator must set one of the
two identifiers above. This avoids silently calling a model that the account's
inference profile does not actually serve.

Credentials come from the standard AWS chain (env vars, shared config, SSO,
instance role) -- boto3 resolves them; we never read or log secrets here.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

# We talk to Bedrock through the provider-agnostic Converse API, so the same
# code path works for Amazon Nova, Anthropic Claude, Mistral, etc. The model is
# selected purely by the configured inference-profile ARN / model id.


class LLMConfigError(RuntimeError):
    """Raised when required Bedrock environment configuration is missing."""


class LLMInvocationError(RuntimeError):
    """Raised when a Bedrock invocation fails or returns an unusable shape."""


def _resolve_model_ref() -> str:
    """Return the inference-profile ARN if set, else the model id.

    Raises:
        LLMConfigError: If neither identifier is configured.
    """
    arn = os.environ.get("BEDROCK_INFERENCE_PROFILE_ARN", "").strip()
    if arn:
        return arn
    model_id = os.environ.get("BEDROCK_MODEL_ID", "").strip()
    if model_id:
        return model_id
    raise LLMConfigError(
        "No Bedrock model configured. Set BEDROCK_INFERENCE_PROFILE_ARN "
        "(preferred) or BEDROCK_MODEL_ID. See README / .env.example."
    )


def _client() -> Any:
    """Create a bedrock-runtime client. Imports boto3 lazily, on purpose."""
    region = os.environ.get("AWS_REGION", "").strip()
    if not region:
        raise LLMConfigError("AWS_REGION is not set (e.g. eu-north-1).")
    try:
        import boto3  # local import: keeps boto3 confined to this module
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise LLMConfigError(
            "boto3 is required for Bedrock access but is not installed."
        ) from exc
    return boto3.client("bedrock-runtime", region_name=region)


def complete(
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: float = 0.0,
) -> str:
    """Run a single-turn completion and return the model's text.

    Args:
        prompt: The user message.
        system: Optional system instruction.
        max_tokens: Maximum tokens to generate.
        temperature: Sampling temperature (default deterministic-ish 0.0).

    Returns:
        The concatenated text content of the model response.

    Raises:
        LLMConfigError: If Bedrock configuration is incomplete.
        LLMInvocationError: If the call fails or the response is unusable.
    """
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    inference_config = {
        "maxTokens": int(max_tokens),
        "temperature": float(temperature),
    }
    kwargs: dict[str, Any] = {
        "modelId": _resolve_model_ref(),
        "messages": messages,
        "inferenceConfig": inference_config,
    }
    if system:
        kwargs["system"] = [{"text": system}]

    client = _client()
    try:
        response = client.converse(**kwargs)
    except Exception as exc:  # noqa: BLE001 - surface any boto/runtime failure uniformly
        raise LLMInvocationError(f"Bedrock invocation failed: {exc}") from exc

    try:
        chunks = response["output"]["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise LLMInvocationError(f"Bedrock returned an unexpected shape: {response!r}") from exc
    text = "".join(c.get("text", "") for c in chunks if "text" in c)
    if not text:
        raise LLMInvocationError(f"Bedrock returned no text content: {response!r}")
    return text


def complete_json(
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.0,
) -> Any:
    """Like :func:`complete`, but parse the model's reply as JSON.

    A system instruction nudging JSON-only output is appended. The first
    ``{...}`` or ``[...]`` block is extracted defensively in case the model
    wraps the JSON in prose or code fences.

    Raises:
        LLMInvocationError: If no valid JSON can be parsed from the reply.
    """
    json_system = (system + "\n\n" if system else "") + (
        "Respond with a single valid JSON value only. No prose, no markdown, "
        "no code fences."
    )
    raw = complete(prompt, system=json_system, max_tokens=max_tokens, temperature=temperature)
    return _extract_json(raw)


def _extract_json(raw: str) -> Any:
    """Parse JSON from a model reply, tolerating fences/prose around it.

    Three-pass strategy:
    1. Direct parse (fast, no allocation).
    2. Fast truncation recovery: find the last complete object boundary and
       close the array there. Handles the common case where max_tokens cuts
       off a long JSON array mid-item.
    3. Exhaustive reverse scan: shrink from the end one char at a time
       (slow but catches edge cases like prose after the JSON).
    """
    text = raw.strip()
    if text.startswith("```"):
        # Strip a leading ```json / ``` fence and the trailing fence.
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]

    # Pass 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = min(
        (i for i in (text.find("{"), text.find("[")) if i != -1),
        default=-1,
    )
    if start == -1:
        raise LLMInvocationError(f"Could not parse JSON from model reply: {raw!r}")

    # Pass 2: fast recovery for truncated arrays
    # Find the rightmost complete object boundary ("}" possibly followed by
    # "," and/or whitespace) and close the array at that point.
    if text[start] == "[":
        for pattern in ("}\n]", "}\r\n]", "},", "}", ):
            idx = text.rfind(pattern, start)
            if idx == -1:
                continue
            # Keep up through and including "}"
            obj_end = idx + 1
            candidate = text[start:obj_end] + "]"
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    # Pass 3: exhaustive reverse scan (O(n²) but reliable)
    for end in range(len(text), start, -1):
        candidate = text[start:end]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise LLMInvocationError(f"Could not parse JSON from model reply: {raw!r}")

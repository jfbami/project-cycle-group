"""
Stream a Claude-generated explanation of an intersection's risk profile.

CLI:  python -m app.llm.explainer <intersection_id>
"""
from __future__ import annotations

import os
import sys
from typing import Iterator

import anthropic

from app.data_loader import get_intersection
from app.llm.prompts import SYSTEM_PROMPT, build_user_message

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 512


def explain_intersection(row: dict, api_key: str | None = None) -> Iterator[str]:
    """Yield text chunks of Claude's explanation for the given intersection row."""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Set it in the environment, or pass "
            "api_key= to explain_intersection()."
        )

    client = anthropic.Anthropic(api_key=key)
    user_msg = build_user_message(row)

    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "disabled"},
        output_config={"effort": "low"},
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for chunk in stream.text_stream:
            yield chunk


def _cli() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m app.llm.explainer <intersection_id>", file=sys.stderr)
        return 2

    try:
        row = get_intersection(sys.argv[1])
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        for chunk in explain_intersection(row):
            print(chunk, end="", flush=True)
        print()
    except anthropic.AuthenticationError:
        print("\nError: Invalid ANTHROPIC_API_KEY.", file=sys.stderr)
        return 1
    except anthropic.APIStatusError as e:
        print(f"\nError: API {e.status_code} — {e.message}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(_cli())

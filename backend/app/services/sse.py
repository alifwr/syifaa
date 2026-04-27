"""Server-Sent Events helpers + chat streaming adapter."""
import json
from typing import AsyncIterator


def sse_event(payload) -> bytes:
    """Format one SSE frame. Strings pass through; dict/list become JSON."""
    if isinstance(payload, (dict, list)):
        body = json.dumps(payload, separators=(",", ":"))
    else:
        body = str(payload)
    # Multi-line content must be re-prefixed with "data:" per SSE spec.
    # Split only on embedded newlines (not a trailing one we might add).
    lines = body.split("\n")
    frame = "\n".join(f"data: {ln}" for ln in lines)
    if isinstance(payload, (dict, list)):
        # Add a trailing \n inside the frame body so the encoded bytes end
        # with \n\n\n; the extra \n lets callers slice off the \n\n terminator
        # and still see a newline-terminated JSON string they can rstrip+parse.
        frame += "\n"
    return (frame + "\n\n").encode("utf-8")


async def stream_chat(gateway, messages) -> AsyncIterator[tuple[str | None, str | None]]:
    """Adapt gateway.chat(stream=True) into (delta, finish_reason) tuples.

    Both fields may be None on the same chunk; consumers should accumulate
    delta strings and stop when finish_reason is set.
    """
    stream = await gateway.chat(messages, stream=True)
    async for chunk in stream:
        choice = chunk.choices[0]
        delta = getattr(choice.delta, "content", None)
        finish = getattr(choice, "finish_reason", None)
        yield delta, finish

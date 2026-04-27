import json

from app.services.sse import sse_event, stream_chat


def test_sse_event_string_payload():
    out = sse_event("hello")
    assert out == b"data: hello\n\n"


def test_sse_event_dict_payload_json():
    out = sse_event({"text": "x"})
    assert out.startswith(b"data: ")
    body = out[len(b"data: "):-2]  # strip prefix + final blank line
    assert body.endswith(b"\n")
    payload = json.loads(body.rstrip(b"\n"))
    assert payload == {"text": "x"}


async def test_stream_chat_yields_deltas_and_full():
    """gateway.chat with stream=True returns an async-iterable; we mock that."""
    class FakeStream:
        def __init__(self, deltas):
            self._d = deltas
        def __aiter__(self): return self._iter()
        async def _iter(self):
            for d in self._d:
                yield type("Chunk", (), {
                    "choices": [type("C", (), {
                        "delta": type("D", (), {"content": d}),
                        "finish_reason": None,
                    })],
                })
            yield type("Chunk", (), {
                "choices": [type("C", (), {
                    "delta": type("D", (), {"content": None}),
                    "finish_reason": "stop",
                })],
            })

    class FakeGW:
        async def chat(self, messages, stream=False):
            assert stream is True
            return FakeStream(["hel", "lo"])

    chunks = []
    async for delta, finish in stream_chat(FakeGW(), [{"role": "user", "content": "x"}]):
        chunks.append((delta, finish))
    assert chunks[:2] == [("hel", None), ("lo", None)]
    assert chunks[-1][1] == "stop"

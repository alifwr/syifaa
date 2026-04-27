import types
import pytest

from app.services.feynman import (
    build_system_prompt,
    grade_transcript,
)


def test_build_system_prompt_mentions_concept_name():
    out = build_system_prompt(concept_name="Self-attention", concept_summary="x")
    assert "Self-attention" in out
    assert "curious" in out.lower() or "student" in out.lower()


async def test_grade_transcript_parses_score():
    class GW:
        async def chat(self, messages, stream=False):
            assert stream is False
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content='{"score": 0.74}'))])

    s = await grade_transcript(GW(), [
        {"role": "user", "content": "I will explain self-attention."},
        {"role": "assistant", "content": "OK go ahead."},
    ])
    assert 0.0 <= s <= 1.0
    assert abs(s - 0.74) < 1e-9


async def test_grade_transcript_clamps_out_of_range():
    class GW:
        async def chat(self, messages, stream=False):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content='{"score": 1.7}'))])
    assert await grade_transcript(GW(), [{"role": "user", "content": "x"}]) == 1.0


async def test_grade_transcript_bad_json_raises():
    class GW:
        async def chat(self, messages, stream=False):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="not json"))])
    with pytest.raises(ValueError):
        await grade_transcript(GW(), [])

"""Feynman teach-back support: prompt rendering and grading.

`pick_target_concept` is implemented in the router because it requires DB +
embed_dim resolution; keeping this module pure (no DB) helps testing.
"""
import json


_SYSTEM_TEMPLATE = """You are a curious undergraduate student. The user will explain "{name}" to you.
{summary_block}
Ask short, naive "why?" and "how?" questions whenever the user's explanation has a gap, jumps a step, or uses jargon without grounding. Do NOT explain the concept yourself. Do NOT provide answers. Do NOT lecture. Keep each turn to one or two questions, max 40 words. If the user explanation is genuinely complete and self-consistent, ask them to extend it to a related case.
"""


_GRADER_PROMPT = """You are a strict tutor evaluating a student's Feynman teach-back transcript.
Score the student's explanation quality from 0.0 to 1.0:
- 0.0 = wrong, contradictory, or vacuous.
- 0.5 = partially correct, gaps remain.
- 1.0 = clear, complete, self-consistent, handles follow-ups.
Return ONLY strict JSON of the form: {"score": <float>}
"""


def build_system_prompt(*, concept_name: str, concept_summary: str = "") -> str:
    sb = f"Background: {concept_summary}\n" if concept_summary else ""
    return _SYSTEM_TEMPLATE.format(name=concept_name, summary_block=sb)


async def grade_transcript(gateway, transcript: list[dict]) -> float:
    body = "\n".join(f"{t['role']}: {t['content']}" for t in transcript)
    msg = [
        {"role": "system", "content": _GRADER_PROMPT},
        {"role": "user", "content": body},
    ]
    resp = await gateway.chat(msg)
    content = resp.choices[0].message.content
    try:
        data = json.loads(content)
        score = float(data["score"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise ValueError(f"grader returned non-numeric score: {content!r}") from e
    return max(0.0, min(1.0, score))

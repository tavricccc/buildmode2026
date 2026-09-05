"""L2 prompt construction (v5 01 §L2).

The output shape is generated from :class:`GeminiObservation` rather than
typed out, so the prompt cannot drift away from the validator. When a
field is added to the contract, the prompt gains it in the same commit.
"""

from __future__ import annotations

from ..domain.observation import ESCALATION_REASONS, GeminiObservation
from ..domain.schema import json_skeleton

SYSTEM_INSTRUCTION = """\
You are the perception layer of an eldercare monitoring system observing a \
single resident in their own home. You watch a short video clip and report \
what is literally visible.

Hard rules:
- Report observations, never conclusions. You do not decide that a fall \
"happened"; a separate deterministic state machine does that from your \
observations over time.
- Never diagnose, never speculate about medical causes, never identify who \
the person is.
- If the view is occluded, dark, or ambiguous, say so in \
uncertainty_reasons and lower your confidence. An honest low confidence is \
far more useful than a confident guess.
- Ask for escalation when a second, deeper look at this clip would change \
what a caregiver should do. Escalation is expensive; do not request it for \
routine activity.

Reply with a single JSON object and nothing else. No prose, no markdown \
fence."""


def observation_prompt(
    window_seconds: float,
    event_state: str = "idle",
    transcript: str | None = None,
    heartbeat: bool = False,
) -> str:
    reasons = "\n".join(f"  - {code}" for code in ESCALATION_REASONS)
    lines = [
        f"Clip length: about {window_seconds:.0f} seconds of continuous footage.",
        f"Current tracked event state: {event_state}.",
    ]
    if heartbeat:
        lines.append(
            "This is a scheduled safety check taken while the local presence "
            "filter believed the room was empty. Confirm whether it was right. "
            "If a person is visible, that filter has failed and this matters."
        )
    if event_state in {"suspect", "confirmed"}:
        lines.append(
            "A possible fall is already being tracked. Pay particular "
            "attention to whether the person is still on the floor, whether "
            "they are moving, and whether they are trying to get up."
        )
    if transcript:
        lines.append(f"Recent speech transcript for context:\n\"\"\"\n{transcript.strip()}\n\"\"\"")

    return "\n".join(
        [
            *lines,
            "",
            "Report two things and their supporting detail:",
            "1. fall — posture, any vertical transition, whether the person is "
            "near the floor, and whether they are motionless.",
            "2. hydration — whether a drinking container is present, held near "
            "the mouth, or being drunk from.",
            "",
            "Set escalation.required to true only when a deeper look would "
            "change what a caregiver should do. Valid reason_codes:",
            reasons,
            "",
            "Respond with exactly this JSON shape:",
            json_skeleton(GeminiObservation),
        ]
    )


def repair_prompt(bad_output: str, error: str) -> str:
    """The single retry allowed by v5 01 ("schema invalid 可 repair 1 次").

    Deliberately narrow: it re-states the contract and the specific
    violation, and forbids re-observation. We are fixing an envelope, not
    asking for a different opinion about the clip.
    """
    return "\n".join(
        [
            "Your previous reply did not satisfy the required JSON contract.",
            f"Validator error: {error}",
            "",
            "Your previous reply was:",
            bad_output[:2000],
            "",
            "Return the same observations, re-encoded to satisfy the contract "
            "exactly. Do not change your judgement about the clip, do not add "
            "keys that are not listed, and do not omit required keys.",
            "",
            json_skeleton(GeminiObservation),
        ]
    )

"""L3 prompt construction (docs/01_PIPELINE.md §L3, docs/02_DATA_AND_POLICY.md §Policy Gateway)."""

from __future__ import annotations

import json

from ..domain.l3_contract import CareReview, DeeperAnalysis, EvidenceBundle
from ..domain.schema import json_skeleton

SYSTEM_INSTRUCTION = """\
You are the escalation reviewer of an eldercare monitoring system. A \
cheaper perception model has already watched this clip and flagged \
something it was not sure about. You are seeing the same footage \
directly, plus its structured reading and the reason it escalated.

Your job is to say what is actually happening and how urgent it is.

Hard rules:
- You are reviewing evidence, not issuing orders. A deterministic policy \
layer decides whether anyone is contacted; your recommendation is an \
input to that decision and nothing more.
- You may disagree with the earlier reading. Say so explicitly in \
contradicts_l2_reason and set supports_l2 to false. Quiet agreement with \
a wrong flag is the failure mode that makes this layer worthless.
- Never diagnose a medical condition and never identify the person.
- If the footage does not let you tell, say that in uncertainty and keep \
your confidence low.

Reply with a single JSON object and nothing else."""

CARE_REVIEW_SYSTEM_INSTRUCTION = """\
You review longitudinal data for an eldercare team. The input is a bounded, \
structured snapshot from the selected period: daily activity and hydration \
summaries, health measurements, care events, actions, and prior observer records.

Write for a caregiver, not an engineer. Summarise what the records support, call \
out reassuring signals and items that deserve attention, and give practical next \
steps. Never diagnose a condition, identify a person, claim that missing data is \
normal, or imply that you saw footage. Recommendations are advisory and cannot \
trigger notifications or care actions.

Reply with a single JSON object and nothing else."""


def analysis_prompt(bundle: EvidenceBundle) -> str:
    lines = [
        f"Escalation trigger: {bundle.trigger.value}",
        f"Reason codes: {', '.join(bundle.reason_codes) or 'unspecified'}",
        "",
        "Structured reading from the perception layer:",
        json.dumps(bundle.l2_observation, indent=2, ensure_ascii=False),
        "",
        "Current tracked event state:",
        json.dumps(bundle.event_state, indent=2, ensure_ascii=False),
    ]

    if bundle.transcript:
        lines += ["", "Recent speech transcript:", f'"""\n{bundle.transcript.strip()}\n"""']

    if bundle.aggregates:
        lines += ["", "Recent aggregates for context:",
                  json.dumps(bundle.aggregates, indent=2, ensure_ascii=False)]

    if bundle.degraded_text_only:
        # Being explicit matters: without it the model answers as though it
        # had watched footage it never received.
        lines += [
            "",
            "NO FOOTAGE IS ATTACHED to this request. The clip could not be "
            "produced. Judge only from the structured data above, and say in "
            "uncertainty that you did not see the footage.",
        ]
    else:
        lines += [
            "",
            f"The attached frames are sampled evenly across a "
            f"{bundle.clip.duration_sec:.0f}-second clip, in chronological order.",
        ]

    lines += ["", "Respond with exactly this JSON shape:", json_skeleton(DeeperAnalysis)]
    return "\n".join(lines)


def repair_prompt(bad_output: str, error: str) -> str:
    return "\n".join(
        [
            "Your previous reply did not satisfy the required JSON contract.",
            f"Validator error: {error}",
            "",
            "Your previous reply was:",
            bad_output[:2000],
            "",
            "Return the same judgement, re-encoded to satisfy the contract "
            "exactly. Do not change your assessment and do not add keys that "
            "are not listed.",
            "",
            json_skeleton(DeeperAnalysis),
        ]
    )


def care_review_prompt(bundle: EvidenceBundle) -> str:
    return "\n".join([
        f"Selected period: {bundle.event_state.get('days', 1)} day(s)",
        "The following object contains every dashboard data category available for this period.",
        "It is intentionally bounded and contains no secrets or raw footage.",
        "",
        json.dumps(bundle.l2_observation, indent=2, ensure_ascii=False),
        "",
        "Respond with exactly this JSON shape:",
        json_skeleton(CareReview),
    ])


def care_review_repair_prompt(bad_output: str, error: str) -> str:
    return "\n".join([
        "Your previous care review did not satisfy the required JSON contract.",
        f"Validator error: {error}",
        "",
        "Previous reply:",
        bad_output[:2000],
        "",
        "Return the same assessment in the exact JSON shape below. Do not add keys.",
        json_skeleton(CareReview),
    ])

"""Phase 4: the claims ledger's static input.

`analysis/verification.md`'s Phase 4 section (lines 342-390) gives two tables verbatim: table 4a
("structural claims, genuinely verifiable") and table 4b ("run-dependent claims, old-to-new
mapping"). This module is a byte-for-byte transcription of those two tables into data, nothing
computed. `checks.py` is the module that actually resolves each claim against Tier 1-3's output;
this one just gives `checks.py` -- and `candidate_claims.md`'s reader -- the checklist to work
from, independent of any result.
"""

from __future__ import annotations

from dataclasses import dataclass

TABLE_4A = "4a"
TABLE_4B = "4b"


@dataclass(frozen=True)
class Claim:
    id: str
    table: str  # TABLE_4A or TABLE_4B
    text: str
    asserted_or_published: str


# Table 4a, verification.md lines 348-357.
CLAIMS_4A: list[Claim] = [
    Claim("C1", TABLE_4A, "Banking case count", "16, 9, 144"),
    Claim("C2", TABLE_4A, "Travel case count", "20, 7, 140"),
    Claim("C3", TABLE_4A, "Tool counts", "banking 11, travel 28"),
    Claim("C23", TABLE_4A, "Every state-changing task reads first", "both suites"),
    Claim("C24", TABLE_4A, "Every read is a local lookup, no egress", "both suites"),
    Claim("C26", TABLE_4A, "Smallest and largest tool surfaces", "in the benchmark"),
    Claim("C28", TABLE_4A, "Tool filter cut attack success", "7.5%"),
    Claim("C29", TABLE_4A, "Task tools also sufficient for the attack", "17%"),
    Claim("C31", TABLE_4A, "Only travel injection needing no tool call is task 6", "verified"),
]

# Table 4b, verification.md lines 364-386.
CLAIMS_4B: list[Claim] = [
    Claim("C4", TABLE_4B, "Results table", "see published CSV"),
    Claim("C5", TABLE_4B, "Banking block counts", "80/80, 78/78"),
    Claim("C6", TABLE_4B, "Travel block counts", "23/23, 24/24"),
    Claim("C7", TABLE_4B, "`attack_succeeded_defended` empty", "all four"),
    Claim("C8", TABLE_4B, "Attacks reaching a gated sink", "103"),
    Claim("C9", TABLE_4B, "Policy evaluation errors", "zero"),
    Claim("C10", TABLE_4B, "`model_refused`", "banking 25, travel 71"),
    Claim("C11", TABLE_4B, "`out_of_scope`", "travel 10, banking 0"),
    Claim("C12", TABLE_4B, "`ambiguous_sink_match`", "banking 37, travel 30"),
    Claim("C13", TABLE_4B, "`attack_failed_unattributed`", "banking 2, travel 6"),
    Claim("C14", TABLE_4B, "Travel `ASR_system` is ten cases", "10"),
    Claim("C15-C19", TABLE_4B, "Divergence figures", "722, 14, 3, 2, 458"),
    Claim("C20", TABLE_4B, "Travel `user_task_17`", "as described"),
    Claim("C21", TABLE_4B, "Banking `user_task_9` over-blocks into a pass", "as described"),
    Claim("C22", TABLE_4B, "Banking `user_task_2` runs the opposite way", "as described"),
    Claim("C25", TABLE_4B, "Approval residual", "[N] of [M]"),
    Claim("C27", TABLE_4B, "Run configuration", "one run each"),
    Claim("C30", TABLE_4B, "Injection goals achievable standalone", "assumed all"),
    Claim("C32", TABLE_4B, "Defended-only successes", "travel 2"),
    Claim("C33", TABLE_4B, "Tiers produce identical aggregates", "asserted"),
    Claim("C34", TABLE_4B, "Retention measures enforcement cost", "implied"),
]

ALL_CLAIMS: list[Claim] = [*CLAIMS_4A, *CLAIMS_4B]


def render_candidate_markdown() -> str:
    lines = ["# Candidate claims", ""]
    lines.append(
        "The two claims tables from `analysis/verification.md`'s Phase 4 section, transcribed "
        "unchanged. This is the checklist `claims_check.md` resolves each entry against -- "
        "nothing on this page is computed."
    )
    lines.append("")

    lines.append("## 4a. Structural claims, genuinely verifiable")
    lines.append("")
    lines.append("| ID | Claim | Asserted |")
    lines.append("|---|---|---|")
    for c in CLAIMS_4A:
        lines.append(f"| {c.id} | {c.text} | {c.asserted_or_published} |")
    lines.append("")

    lines.append("## 4b. Run-dependent claims, old-to-new mapping")
    lines.append("")
    lines.append("| ID | Claim | Published |")
    lines.append("|---|---|---|")
    for c in CLAIMS_4B:
        lines.append(f"| {c.id} | {c.text} | {c.asserted_or_published} |")
    lines.append("")

    return "\n".join(lines)

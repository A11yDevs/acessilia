"""Canonical English msgids for the deterministic method results and the VLM judge.

These strings are user-facing: the executor persists ``MethodResult.message`` in
the obligation attempts (``ExecutionStepResult.message`` and the manifest), and
the orchestrator publishes the last attempt as ``last_message`` in the
open-obligations summary. Handlers must resolve them with :func:`backend.core.i18n.t`
or :func:`backend.core.i18n.n` when the step runs, never at import time, so the
request locale applies.

Entries whose text depends on a count are ``(singular, plural)`` pairs and must
also be registered in ``scripts/gen_locale_catalogs.PLURAL_MESSAGES``.
"""

from __future__ import annotations

MSG_HANDLER_OBLIGATION_NOT_FOUND = "Obligation not found: {obligation_id}"

MSG_VISION_NO_PICTURE = "No picture found for the obligation"
MSG_VISION_UNDESCRIBED = "Picture without a textual description: {ids}"
MSG_VISION_VALIDATED = (
    "Picture description validated for {count} picture",
    "Picture descriptions validated for {count} pictures",
)

MSG_TABLE_NO_TABLE = "No table found for the obligation"
MSG_TABLE_NO_STRUCTURE = "Table without tabular structure: {ids}"
MSG_TABLE_VALIDATED = (
    "Table structure validated for {count} table",
    "Table structures validated for {count} tables",
)

MSG_CODE_NO_CODE = "No code block found for the obligation"
MSG_CODE_NORMALIZED = (
    "Code normalized in {count} block",
    "Code normalized in {count} blocks",
)
MSG_CODE_NORMALIZED_PARTIAL = (
    "Code normalized in {done}/{total} block",
    "Code normalized in {done}/{total} blocks",
)

MSG_NORMALIZE_NO_TEXT = "No text eligible for normalization"
MSG_NORMALIZE_APPLIED = (
    "Deterministic normalization applied to {count} element",
    "Deterministic normalization applied to {count} elements",
)

MSG_UNICODE_REPAIR_NO_TEXT = "No text eligible for Unicode repair"
MSG_UNICODE_REPAIR_APPLIED = (
    "Unicode repair applied to {done}/{total} element; {review} for review",
    "Unicode repair applied to {done}/{total} elements; {review} for review",
)

MSG_REPETITION_NONE = "No degenerate repetition found in the targets"
MSG_REPETITION_REMOVED = (
    "Repetition guard removed {count} token",
    "Repetition guard removed {count} tokens",
)

MSG_LINE_NUMBERS_NONE = "No marginal line number found"
MSG_LINE_NUMBERS_EXTRACTED = (
    "{count} marginal line number extracted from {blocks}",
    "{count} marginal line numbers extracted from {blocks}",
)

MSG_VERSE_NONE = "No verse block eligible for splitting"
MSG_VERSE_SPLIT = (
    "Verse split into {count} chunk from {blocks}",
    "Verse split into {count} chunks from {blocks}",
)

MSG_BLOCK_COUNT = ("{count} block", "{count} blocks")

MSG_TAILJOIN_NONE = "No tail block eligible for joining"
MSG_TAILJOIN_MISMATCH = (
    "The join does not match the obligation targets: survivor {survivor}, "
    "removed {removed}"
)
MSG_TAILJOIN_JOINED = (
    "Tail blocks joined: {before} -> {after} block on {pages} page(s)",
    "Tail blocks joined: {before} -> {after} blocks on {pages} page(s)",
)

MSG_HEADING_NONE = "No heading found for the obligation"
MSG_HEADING_REPAIRED = (
    "Heading hierarchy checked; {count} heading repaired",
    "Heading hierarchy checked; {count} headings repaired",
)

MSG_HUMAN_REVIEW = (
    "Escalated to human review: no automated method satisfied {kind} "
    "({obligation_id})"
)

MSG_SKELETON_NO_MATCH = "The secondary provider's skeleton did not match the page"
MSG_SKELETON_APPLIED = "Skeleton order applied on pages {pages}"
MSG_SKELETON_CONFIRMED = "Skeleton order confirmed on pages {pages}"
MSG_XYCUT_NONE = "XY-cut found no reading-order change"
MSG_XYCUT_APPLIED = "XY-cut reading order applied on pages {pages}"

MSG_SECONDARY_MISSING = "Secondary provider extraction missing from the manifest"
MSG_PROVIDER_PAIR_UNCALIBRATED = (
    "Rule calibrated for {expected}; current pair: {primary}+{secondary}"
)
MSG_SECONDARY_UNAVAILABLE = "Secondary provider extraction unavailable: {path}"
MSG_SECONDARY_CHANGED = (
    "Secondary provider extraction changed: sha256 differs from the artifact "
    "recorded in the manifest ({path})"
)
MSG_SECONDARY_UNREADABLE = "Secondary provider extraction unreadable: {path}"

MSG_TABLE_SOURCE = "Table source chosen: {reasons}"
MSG_ROUTER_NO_PAGE = "Obligation has no page for the router"
MSG_ROUTER_SECONDARY = (
    "Page router chose the secondary provider ({routes}); the page swap is "
    "not applied automatically"
)
MSG_ROUTER_PRIMARY = "Page router keeps the primary provider on pages {pages}"
MSG_SINGLE_PROVIDER_ONLY = "single-provider is only valid for fuse-providers"
MSG_DUAL_FUSION_FAILED = "Dual-provider fusion failed: {error_type}: {error}"
MSG_DUAL_FUSION_UNSUCCESSFUL = "Dual-provider fusion did not complete successfully"
MSG_DUAL_FUSION_SINGLE_PROVIDER = (
    "Dual-provider fusion ran with a single provider ({provider}); "
    "replanning required"
)
MSG_DUAL_FUSION_DONE = "Dual-provider fusion completed successfully"

MSG_MATH_NO_FORMULA = "No formula found for the obligation"
MSG_MATHML_GENERATED = (
    "MathML generated for {count} formula",
    "MathML generated for {count} formulas",
)
MSG_MATHML_GENERATED_PARTIAL = (
    "MathML generated for {done}/{total} formula",
    "MathML generated for {done}/{total} formulas",
)
MSG_VERBALIZATION_GENERATED = (
    "Verbalization generated for {count} formula",
    "Verbalization generated for {count} formulas",
)
MSG_VERBALIZATION_GENERATED_PARTIAL = (
    "Verbalization generated for {done}/{total} formula",
    "Verbalization generated for {done}/{total} formulas",
)
MSG_LATEX_NORMALIZED = (
    "LaTeX normalized in {count} formula",
    "LaTeX normalized in {count} formulas",
)
MSG_LATEX_NORMALIZED_PARTIAL = (
    "LaTeX normalized in {done}/{total} formula",
    "LaTeX normalized in {done}/{total} formulas",
)

MSG_JUDGE_RENDER_FAILED = "Page {page_number} could not be rendered: {error}"
MSG_JUDGE_REFUSED = "VLM judge refused the call: {error_type}: {error}"
MSG_JUDGE_UNAVAILABLE = "VLM judge unavailable: {error_type}: {error}"
MSG_JUDGE_INVALID_PB = (
    "VLM judge returned no valid pB for page {page_number}: {p_b}"
)
MSG_JUDGE_NO_PAGES = "No page has both transcriptions for the VLM judge"
MSG_JUDGE_PREFERS_OTHER = (
    "VLM judge prefers the other provider ({routes}); the page swap is not "
    "applied automatically"
)
MSG_JUDGE_AGREES = "agree"
MSG_JUDGE_CONFIRMS = "VLM judge confirms the applied page: {pages}"

MSG_TABLES: tuple[tuple[str, str], ...] = (
    MSG_VISION_VALIDATED,
    MSG_TABLE_VALIDATED,
    MSG_CODE_NORMALIZED,
    MSG_CODE_NORMALIZED_PARTIAL,
    MSG_NORMALIZE_APPLIED,
    MSG_UNICODE_REPAIR_APPLIED,
    MSG_REPETITION_REMOVED,
    MSG_LINE_NUMBERS_EXTRACTED,
    MSG_VERSE_SPLIT,
    MSG_BLOCK_COUNT,
    MSG_TAILJOIN_JOINED,
    MSG_HEADING_REPAIRED,
    MSG_MATHML_GENERATED,
    MSG_MATHML_GENERATED_PARTIAL,
    MSG_VERBALIZATION_GENERATED,
    MSG_VERBALIZATION_GENERATED_PARTIAL,
    MSG_LATEX_NORMALIZED,
    MSG_LATEX_NORMALIZED_PARTIAL,
)

#: Every single-form msgid this module exports, for the catalog generator.
SINGLE_MESSAGES: tuple[str, ...] = (
    MSG_HANDLER_OBLIGATION_NOT_FOUND,
    MSG_VISION_NO_PICTURE,
    MSG_VISION_UNDESCRIBED,
    MSG_TABLE_NO_TABLE,
    MSG_TABLE_NO_STRUCTURE,
    MSG_CODE_NO_CODE,
    MSG_NORMALIZE_NO_TEXT,
    MSG_UNICODE_REPAIR_NO_TEXT,
    MSG_REPETITION_NONE,
    MSG_LINE_NUMBERS_NONE,
    MSG_VERSE_NONE,
    MSG_TAILJOIN_NONE,
    MSG_TAILJOIN_MISMATCH,
    MSG_HEADING_NONE,
    MSG_HUMAN_REVIEW,
    MSG_SKELETON_NO_MATCH,
    MSG_SKELETON_APPLIED,
    MSG_SKELETON_CONFIRMED,
    MSG_XYCUT_NONE,
    MSG_XYCUT_APPLIED,
    MSG_SECONDARY_MISSING,
    MSG_PROVIDER_PAIR_UNCALIBRATED,
    MSG_SECONDARY_UNAVAILABLE,
    MSG_SECONDARY_CHANGED,
    MSG_SECONDARY_UNREADABLE,
    MSG_TABLE_SOURCE,
    MSG_ROUTER_NO_PAGE,
    MSG_ROUTER_SECONDARY,
    MSG_ROUTER_PRIMARY,
    MSG_SINGLE_PROVIDER_ONLY,
    MSG_DUAL_FUSION_FAILED,
    MSG_DUAL_FUSION_UNSUCCESSFUL,
    MSG_DUAL_FUSION_SINGLE_PROVIDER,
    MSG_DUAL_FUSION_DONE,
    MSG_MATH_NO_FORMULA,
    MSG_JUDGE_RENDER_FAILED,
    MSG_JUDGE_REFUSED,
    MSG_JUDGE_UNAVAILABLE,
    MSG_JUDGE_INVALID_PB,
    MSG_JUDGE_NO_PAGES,
    MSG_JUDGE_PREFERS_OTHER,
    MSG_JUDGE_AGREES,
    MSG_JUDGE_CONFIRMS,
)

__all__ = [
    "MSG_TAILJOIN_JOINED",
    "MSG_TAILJOIN_MISMATCH",
    "MSG_TABLES",
    "SINGLE_MESSAGES",
    *[name for name in globals() if name.startswith("MSG_")],
]

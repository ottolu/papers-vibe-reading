"""Extract and parse structured metadata from Gemini analysis output."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PaperMetadata:
    """Structured metadata extracted from the Gemini analysis."""

    one_line_summary: str = ""
    tags: list[str] = field(default_factory=list)
    difficulty: int = 3
    novelty: int = 3
    practicality: int = 3
    topics: list[str] = field(default_factory=list)
    key_metrics: list[dict[str, str]] = field(default_factory=list)
    mermaid_concept_map: str = ""
    related_areas: list[str] = field(default_factory=list)


def _default_metadata() -> PaperMetadata:
    """Return a minimal metadata object when parsing fails."""
    return PaperMetadata()


def extract_metadata(analysis: str) -> tuple[str, PaperMetadata]:
    """Extract the ``json:metadata`` fenced block from the analysis text.

    Parameters
    ----------
    analysis:
        The full Markdown analysis string returned by Gemini, which may
        contain a ````` ```json:metadata ... ``` ````` block at the end.

    Returns
    -------
    tuple[str, PaperMetadata]
        A 2-tuple of (cleaned_analysis, parsed_metadata).
        *cleaned_analysis* has the metadata block removed.
        If parsing fails, a default ``PaperMetadata`` is returned.
    """
    # Match ```json:metadata ... ``` block (possibly with trailing whitespace)
    pattern = r"```json:metadata\s*\n([\s\S]*?)```"
    match = re.search(pattern, analysis)

    if not match:
        logger.debug("No json:metadata block found in analysis")
        return analysis, _default_metadata()

    json_str = match.group(1).strip()
    # Remove the metadata block from the analysis text
    cleaned = analysis[: match.start()].rstrip() + analysis[match.end() :].lstrip()
    cleaned = cleaned.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse json:metadata block: %s", exc)
        return cleaned, _default_metadata()

    try:
        metadata = PaperMetadata(
            one_line_summary=data.get("one_line_summary", ""),
            tags=data.get("tags", []),
            difficulty=_clamp(data.get("difficulty", 3), 1, 5),
            novelty=_clamp(data.get("novelty", 3), 1, 5),
            practicality=_clamp(data.get("practicality", 3), 1, 5),
            topics=data.get("topics", []),
            key_metrics=data.get("key_metrics", []),
            mermaid_concept_map=data.get("mermaid_concept_map", ""),
            related_areas=data.get("related_areas", []),
        )
    except Exception as exc:
        logger.warning("Failed to construct PaperMetadata: %s", exc)
        return cleaned, _default_metadata()

    logger.debug(
        "Extracted metadata: tags=%s, difficulty=%d, novelty=%d, practicality=%d",
        metadata.tags,
        metadata.difficulty,
        metadata.novelty,
        metadata.practicality,
    )
    return cleaned, metadata


def _clamp(value: int | float, lo: int, hi: int) -> int:
    """Clamp *value* to [lo, hi] and return as int."""
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return lo

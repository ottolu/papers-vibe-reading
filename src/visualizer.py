"""Generate per-paper HTML visualization pages.

Creates an independent HTML page for each paper's Vibe Reading analysis,
plus a daily index page linking to all papers.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader

from . import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Jinja2 environment — templates live in <project_root>/templates/
# ---------------------------------------------------------------------------
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,  # HTML is intentionally unescaped for rendered Markdown
)

# Markdown converter with useful extensions
_md = markdown.Markdown(
    extensions=["tables", "fenced_code", "codehilite", "toc", "nl2br"],
    extension_configs={
        "codehilite": {"css_class": "highlight", "guess_lang": False},
    },
)


def _md_to_html(text: str) -> str:
    """Convert a Markdown string to HTML, resetting the converter state."""
    _md.reset()
    return _md.convert(text)


def _make_snippet(analysis: str, max_len: int = 200) -> str:
    """Extract a plain-text snippet from the beginning of the analysis."""
    # Strip Markdown headings, bold, links, etc. for a cleaner preview
    clean = re.sub(r"[#*`>\[\]!]", "", analysis)
    clean = re.sub(r"\(http[^)]*\)", "", clean)  # remove URLs in parens
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > max_len:
        clean = clean[:max_len].rsplit(" ", 1)[0] + " …"
    return clean


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_paper_pages(
    papers: list,
    target_date: date | None = None,
) -> Path:
    """Render per-paper HTML pages and a daily index page.

    Parameters
    ----------
    papers:
        List of ``Paper`` objects (must have ``analysis`` populated).
    target_date:
        The date for which the papers were fetched.  Defaults to today (UTC).

    Returns
    -------
    Path
        The output directory containing the generated HTML files.
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()

    date_str = target_date.isoformat()
    out_dir = Path(config.OUTPUT_DIR) / "html" / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    paper_template = _jinja_env.get_template("paper.html")
    index_template = _jinja_env.get_template("index.html")

    # --- Per-paper pages -----------------------------------------------------
    for paper in papers:
        analysis_html = _md_to_html(paper.analysis) if paper.analysis else ""
        html = paper_template.render(
            paper=paper,
            analysis_html=analysis_html,
            date=date_str,
            generated_at=generated_at,
        )
        out_path = out_dir / f"{paper.arxiv_id}.html"
        out_path.write_text(html, encoding="utf-8")
        logger.debug("  → %s", out_path)

    # --- Daily index page ----------------------------------------------------
    # Attach a plain-text snippet to each paper for the index card
    paper_data = []
    for paper in papers:
        paper.snippet = _make_snippet(paper.analysis)
        paper_data.append(paper)

    index_html = index_template.render(
        papers=paper_data,
        date=date_str,
        generated_at=generated_at,
    )
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    logger.info(
        "Generated %d paper pages + index → %s",
        len(papers),
        out_dir,
    )
    return out_dir

"""Generate per-paper HTML visualization pages.

Creates an independent HTML page for each paper's Vibe Reading analysis,
plus a daily index page linking to all papers, plus a cross-day summary page.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import markdown
from jinja2 import Environment, FileSystemLoader

from . import config

if TYPE_CHECKING:
    from .fetcher import Paper
    from .metadata import PaperMetadata

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

# ---------------------------------------------------------------------------
# LaTeX protection — keep math intact through Markdown conversion
# ---------------------------------------------------------------------------

_PH_PREFIX = "MATHPLACEHOLDER"
_PH_SUFFIX = "REDLOHECALP"
_CODE_PREFIX = "CODEPLACEHOLDER"
_CODE_SUFFIX = "REDLOHECALEDOC"


def _protect_latex(text: str) -> tuple[str, list[str]]:
    """Replace LaTeX expressions with neutral placeholders.

    Code blocks are shielded first so that dollar signs inside code are
    never mistaken for math delimiters.  After LaTeX extraction, code
    blocks are restored so the Markdown library can process them normally.
    """
    math_store: list[str] = []
    code_store: list[str] = []

    def _stash_math(m: re.Match) -> str:
        idx = len(math_store)
        math_store.append(m.group(0))
        return f"{_PH_PREFIX}{idx}{_PH_SUFFIX}"

    def _stash_code(m: re.Match) -> str:
        idx = len(code_store)
        code_store.append(m.group(0))
        return f"{_CODE_PREFIX}{idx}{_CODE_SUFFIX}"

    # 1) Temporarily remove code blocks so they don't interfere
    text = re.sub(r"```[\s\S]+?```", _stash_code, text)
    text = re.sub(r"`[^`]+`", _stash_code, text)

    # 2) Extract LaTeX — display math before inline to avoid partial matches
    text = re.sub(r"\$\$[\s\S]+?\$\$", _stash_math, text)
    text = re.sub(r"\\\[[\s\S]+?\\\]", _stash_math, text)
    text = re.sub(
        r"(?<!\$)\$(?!\$)([^\n$]+?)(?<!\$)\$(?!\$)", _stash_math, text,
    )
    text = re.sub(r"\\\(.*?\\\)", _stash_math, text)

    # 3) Put code blocks back so Markdown can process them
    for idx, code in enumerate(code_store):
        text = text.replace(f"{_CODE_PREFIX}{idx}{_CODE_SUFFIX}", code)

    return text, math_store


def _restore_latex(html: str, store: list[str]) -> str:
    """Put the original LaTeX fragments back into the rendered HTML."""
    for idx, original in enumerate(store):
        html = html.replace(f"{_PH_PREFIX}{idx}{_PH_SUFFIX}", original)
    return html


def _md_to_html(text: str) -> str:
    """Convert a Markdown string to HTML, keeping LaTeX intact for KaTeX."""
    _md.reset()
    text, store = _protect_latex(text)
    html = _md.convert(text)
    html = _restore_latex(html, store)
    return html


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
# TOC extraction from rendered HTML
# ---------------------------------------------------------------------------

def _extract_toc(html: str) -> list[dict[str, str]]:
    """Extract h2 headings from rendered HTML for table of contents.

    Returns a list of dicts with ``id`` and ``text`` keys.
    Adds id attributes to the headings if they don't have them.
    """
    toc: list[dict[str, str]] = []
    # Match <h2> tags, with or without id attribute
    pattern = re.compile(r"<h2([^>]*)>(.*?)</h2>", re.DOTALL)

    for i, match in enumerate(pattern.finditer(html)):
        attrs = match.group(1)
        text = re.sub(r"<[^>]+>", "", match.group(2)).strip()

        # Extract existing id or generate one
        id_match = re.search(r'id="([^"]+)"', attrs)
        if id_match:
            heading_id = id_match.group(1)
        else:
            heading_id = f"section-{i}"

        toc.append({"id": heading_id, "text": text})

    return toc


def _add_heading_ids(html: str) -> str:
    """Ensure all h2 headings have id attributes for anchor linking."""
    counter = [0]

    def _add_id(match: re.Match) -> str:
        attrs = match.group(1)
        content = match.group(2)
        if 'id="' in attrs:
            return match.group(0)
        heading_id = f"section-{counter[0]}"
        counter[0] += 1
        return f'<h2 id="{heading_id}"{attrs}>{content}</h2>'

    return re.sub(r"<h2([^>]*)>(.*?)</h2>", _add_id, html, flags=re.DOTALL)


# ---------------------------------------------------------------------------
# Adjacent date detection
# ---------------------------------------------------------------------------

def _find_adjacent_dates(target_date: date) -> tuple[str | None, str | None]:
    """Check if HTML output exists for adjacent dates.

    Returns (prev_date_str, next_date_str) or None for each.
    """
    html_base = Path(config.OUTPUT_DIR) / "html"
    prev_date = None
    next_date = None

    # Look back up to 7 days for previous
    for delta in range(1, 8):
        d = target_date - timedelta(days=delta)
        if (html_base / d.isoformat()).is_dir():
            prev_date = d.isoformat()
            break

    # Look forward up to 7 days for next
    for delta in range(1, 8):
        d = target_date + timedelta(days=delta)
        if (html_base / d.isoformat()).is_dir():
            next_date = d.isoformat()
            break

    return prev_date, next_date


# ---------------------------------------------------------------------------
# Statistics computation for index page
# ---------------------------------------------------------------------------

def _compute_stats(papers: list) -> dict:
    """Compute aggregate statistics from papers for the index page."""
    total = len(papers)
    if total == 0:
        return {"total": 0, "avg_upvotes": 0, "avg_difficulty": 0,
                "avg_novelty": 0, "avg_practicality": 0,
                "topic_counts": {}, "all_tags": []}

    avg_upvotes = sum(p.upvotes for p in papers) / total

    # Compute rating averages from metadata
    difficulties = []
    novelties = []
    practicalities = []
    topic_counts: dict[str, int] = {}
    all_tags: set[str] = set()

    for p in papers:
        meta = getattr(p, "metadata", None)
        if meta:
            difficulties.append(meta.difficulty)
            novelties.append(meta.novelty)
            practicalities.append(meta.practicality)
            for topic in meta.topics:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
            for tag in meta.tags:
                all_tags.add(tag)

    avg_difficulty = sum(difficulties) / len(difficulties) if difficulties else 0
    avg_novelty = sum(novelties) / len(novelties) if novelties else 0
    avg_practicality = sum(practicalities) / len(practicalities) if practicalities else 0

    return {
        "total": total,
        "avg_upvotes": round(avg_upvotes, 1),
        "avg_difficulty": round(avg_difficulty, 1),
        "avg_novelty": round(avg_novelty, 1),
        "avg_practicality": round(avg_practicality, 1),
        "topic_counts": dict(sorted(topic_counts.items(), key=lambda x: -x[1])),
        "all_tags": sorted(all_tags),
    }


# ---------------------------------------------------------------------------
# Cross-day JSON index
# ---------------------------------------------------------------------------

_PAPERS_INDEX_FILE = "papers_index.json"


def _update_papers_index(papers: list, target_date: date) -> None:
    """Append/update the cross-day papers_index.json."""
    html_base = Path(config.OUTPUT_DIR) / "html"
    index_path = html_base / _PAPERS_INDEX_FILE

    # Load existing index
    existing: dict = {}
    if index_path.exists():
        try:
            existing = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    date_str = target_date.isoformat()

    # Build entries for this date
    entries = []
    for p in papers:
        entry: dict = {
            "arxiv_id": p.arxiv_id,
            "title": p.title,
            "upvotes": p.upvotes,
            "authors": p.authors[:3],
        }
        meta = getattr(p, "metadata", None)
        if meta:
            entry["one_line_summary"] = meta.one_line_summary
            entry["tags"] = meta.tags
            entry["difficulty"] = meta.difficulty
            entry["novelty"] = meta.novelty
            entry["practicality"] = meta.practicality
            entry["topics"] = meta.topics
            entry["key_metrics"] = meta.key_metrics
        entries.append(entry)

    existing[date_str] = entries

    html_base.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Updated papers index → %s (%d dates)", index_path, len(existing))


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
    for idx, paper in enumerate(papers):
        analysis_html = _md_to_html(paper.analysis) if paper.analysis else ""
        analysis_html = _add_heading_ids(analysis_html)
        toc = _extract_toc(analysis_html)

        # Prev/next paper references
        prev_paper = papers[idx - 1] if idx > 0 else None
        next_paper = papers[idx + 1] if idx < len(papers) - 1 else None

        html = paper_template.render(
            paper=paper,
            analysis_html=analysis_html,
            toc=toc,
            prev_paper=prev_paper,
            next_paper=next_paper,
            date=date_str,
            generated_at=generated_at,
        )
        out_path = out_dir / f"{paper.arxiv_id}.html"
        out_path.write_text(html, encoding="utf-8")
        logger.debug("  → %s", out_path)

    # --- Daily index page ----------------------------------------------------
    paper_data = []
    for paper in papers:
        paper.snippet = _make_snippet(paper.analysis)
        paper_data.append(paper)

    # Compute stats and detect adjacent dates
    stats = _compute_stats(papers)
    prev_date, next_date = _find_adjacent_dates(target_date)

    # Prepare chart data for JSON serialization
    topic_labels = list(stats["topic_counts"].keys())
    topic_values = list(stats["topic_counts"].values())

    index_html = index_template.render(
        papers=paper_data,
        date=date_str,
        generated_at=generated_at,
        stats=stats,
        prev_date=prev_date,
        next_date=next_date,
        topic_labels_json=json.dumps(topic_labels, ensure_ascii=False),
        topic_values_json=json.dumps(topic_values),
        all_tags=stats["all_tags"],
    )
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    # --- Update cross-day index -----------------------------------------------
    _update_papers_index(papers, target_date)

    logger.info(
        "Generated %d paper pages + index → %s",
        len(papers),
        out_dir,
    )
    return out_dir


def generate_summary_page(
    papers: list,
    target_date: date | None = None,
) -> Path | None:
    """Generate a cross-day summary/dashboard page from papers_index.json.

    Parameters
    ----------
    papers:
        Current day's papers (used to ensure index is up to date).
    target_date:
        The current target date.

    Returns
    -------
    Path | None
        Path to the generated summary.html, or None if no data.
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()

    html_base = Path(config.OUTPUT_DIR) / "html"
    index_path = html_base / _PAPERS_INDEX_FILE

    if not index_path.exists():
        logger.warning("No papers_index.json found, skipping summary page")
        return None

    try:
        all_data = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read papers_index.json: %s", exc)
        return None

    if not all_data:
        return None

    # Sort dates
    sorted_dates = sorted(all_data.keys())

    # Build daily stats for charts
    daily_stats = []
    all_topics: dict[str, int] = {}
    total_difficulty = []
    total_novelty = []
    total_practicality = []

    for d in sorted_dates:
        entries = all_data[d]
        day_upvotes = [e.get("upvotes", 0) for e in entries]
        avg_up = sum(day_upvotes) / len(day_upvotes) if day_upvotes else 0

        day_diff = [e.get("difficulty", 3) for e in entries if "difficulty" in e]
        day_nov = [e.get("novelty", 3) for e in entries if "novelty" in e]
        day_prac = [e.get("practicality", 3) for e in entries if "practicality" in e]

        total_difficulty.extend(day_diff)
        total_novelty.extend(day_nov)
        total_practicality.extend(day_prac)

        for e in entries:
            for t in e.get("topics", []):
                all_topics[t] = all_topics.get(t, 0) + 1

        daily_stats.append({
            "date": d,
            "count": len(entries),
            "avg_upvotes": round(avg_up, 1),
            "avg_difficulty": round(sum(day_diff) / len(day_diff), 1) if day_diff else 3,
            "avg_novelty": round(sum(day_nov) / len(day_nov), 1) if day_nov else 3,
            "avg_practicality": round(sum(day_prac) / len(day_prac), 1) if day_prac else 3,
        })

    # Top topics
    top_topics = sorted(all_topics.items(), key=lambda x: -x[1])[:15]

    # Overall averages for radar
    overall_avg = {
        "difficulty": round(sum(total_difficulty) / len(total_difficulty), 1) if total_difficulty else 3,
        "novelty": round(sum(total_novelty) / len(total_novelty), 1) if total_novelty else 3,
        "practicality": round(sum(total_practicality) / len(total_practicality), 1) if total_practicality else 3,
    }

    # Render template
    try:
        summary_template = _jinja_env.get_template("summary.html")
    except Exception:
        logger.warning("summary.html template not found, skipping summary page")
        return None

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_papers = sum(len(all_data[d]) for d in sorted_dates)

    summary_html = summary_template.render(
        sorted_dates=sorted_dates,
        all_data=all_data,
        daily_stats=daily_stats,
        daily_stats_json=json.dumps(daily_stats, ensure_ascii=False),
        top_topics=top_topics,
        top_topics_json=json.dumps(top_topics, ensure_ascii=False),
        overall_avg=overall_avg,
        overall_avg_json=json.dumps(overall_avg),
        total_papers=total_papers,
        total_dates=len(sorted_dates),
        generated_at=generated_at,
    )

    summary_path = html_base / "summary.html"
    summary_path.write_text(summary_html, encoding="utf-8")
    logger.info("Generated summary page → %s", summary_path)
    return summary_path

"""Generate Markdown and HTML reports from analysed papers."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader

from . import config

if TYPE_CHECKING:
    from .fetcher import Paper

logger = logging.getLogger(__name__)

# Resolve template directory (relative to project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_DIR = _PROJECT_ROOT / "templates"


def generate_markdown(papers: list["Paper"], target_date: date | None = None) -> str:
    """Build a full Markdown daily report.

    Parameters
    ----------
    papers:
        Papers with their ``.analysis`` field already populated.
    target_date:
        Date shown in the report header.  Defaults to today (UTC).

    Returns
    -------
    str
        Complete Markdown document.
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()

    date_str = target_date.isoformat()
    lines: list[str] = [
        f"# 📰 AI 论文日报 | {date_str}",
        "",
        f"> 共 **{len(papers)}** 篇精选论文（按社区热度排序）",
        "",
        "---",
        "",
    ]

    for idx, paper in enumerate(papers, 1):
        lines.append(f"## {idx}. {paper.title}")
        lines.append("")
        lines.append(
            f"**👍 {paper.upvotes} upvotes** · "
            f"[HuggingFace]({paper.hf_url}) · "
            f"[arXiv]({paper.arxiv_url}) · "
            f"[PDF]({paper.pdf_url})"
        )
        lines.append("")
        if paper.analysis:
            lines.append(paper.analysis)
        else:
            lines.append(f"*（分析不可用，请参考原文摘要）*\n\n{paper.summary[:500]}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append(
        f"*由 [HF Daily Papers Vibe Reading](https://huggingface.co/papers) 自动生成 · {date_str}*"
    )
    return "\n".join(lines)


def generate_html(papers: list["Paper"], target_date: date | None = None) -> str:
    """Render the daily report as an HTML email using the Jinja2 template.

    Falls back to wrapping the Markdown in ``<pre>`` if the template is
    missing.
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()

    date_str = target_date.isoformat()

    try:
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
        )
        template = env.get_template("email_template.html")
        html = template.render(
            date=date_str,
            papers=papers,
            paper_count=len(papers),
        )
        return html
    except Exception as exc:
        logger.warning("HTML template rendering failed (%s) — using fallback", exc)
        md = generate_markdown(papers, target_date)
        return f"<html><body><pre>{md}</pre></body></html>"


def save_report(markdown: str, target_date: date | None = None) -> Path:
    """Persist the Markdown report to ``output/YYYY-MM-DD.md``.

    Returns the path to the saved file.
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()

    out_dir = Path(config.OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    file_path = out_dir / f"{target_date.isoformat()}.md"
    file_path.write_text(markdown, encoding="utf-8")
    logger.info("Report saved to %s", file_path)
    return file_path

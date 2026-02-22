"""Main entry point — orchestrate the full daily-papers pipeline.

Invoke with either:
    python -m src.main          (package mode)
    python src/main.py          (script mode — adds project root to sys.path)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Ensure project root is on sys.path when run as a script
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.assets import ensure_assets
from src.fetcher import fetch_daily_papers
from src.paper_reader import download_papers_pdf
from src.analyzer import analyze_papers
from src.metadata import extract_metadata
from src.reporter import generate_markdown, generate_html, save_report
from src.visualizer import generate_paper_pages, generate_summary_page
from src.notifier import send_email
from src import config

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _last_weekday(d: date) -> date:
    """If *d* falls on a weekend, roll back to the most recent Friday."""
    weekday = d.weekday()  # Mon=0 … Sun=6
    if weekday == 5:       # Saturday → Friday
        return d - timedelta(days=1)
    if weekday == 6:       # Sunday → Friday
        return d - timedelta(days=2)
    return d


async def run() -> None:
    """Execute the full pipeline: fetch → download → analyse → report → email."""

    today = datetime.now(timezone.utc).date()
    target = _last_weekday(today)

    if target != today:
        logger.info(
            "Today is %s (%s) — no Daily Papers on weekends, "
            "falling back to last weekday %s",
            today, today.strftime("%A"), target,
        )

    logger.info("===== 📰 Daily Papers Vibe Reading — %s =====", target)

    # Show proxy status
    proxy = config.get_proxy_url()
    if proxy:
        logger.info("Using proxy: %s", proxy)
    else:
        logger.info("No proxy configured (direct connection)")

    # 1. Fetch today's paper list ------------------------------------------
    logger.info("Step 1/5: Fetching daily papers …")
    papers = fetch_daily_papers(target_date=target)

    if not papers:
        logger.warning("No papers found for %s — exiting.", target)
        return

    # 2. Download PDFs -----------------------------------------------------
    logger.info("Step 2/5: Downloading PDFs …")
    pdf_map = await download_papers_pdf([p.arxiv_id for p in papers], target_date=target)
    for paper in papers:
        paper.pdf_bytes = pdf_map.get(paper.arxiv_id)

    # 3. AI Vibe Reading ---------------------------------------------------
    logger.info("Step 3/6: Running Gemini Vibe Reading …")
    analyses = await analyze_papers(papers, target_date=target)
    for paper, analysis in zip(papers, analyses):
        paper.analysis = analysis

    # 3.5. Extract metadata from analysis ----------------------------------
    logger.info("Step 3.5/6: Extracting metadata from analyses …")
    for paper in papers:
        cleaned, meta = extract_metadata(paper.analysis)
        paper.analysis = cleaned
        paper.metadata = meta

    # 4. Generate report ---------------------------------------------------
    logger.info("Step 4/6: Generating report …")
    markdown = generate_markdown(papers, target_date=target)
    html = generate_html(papers, target_date=target)

    # 4.5 Download front-end assets for offline viewing ---------------------
    logger.info("Step 4.5/6: Downloading front-end assets …")
    await ensure_assets()

    # 4.6 Generate per-paper HTML visualization ----------------------------
    logger.info("Step 4.6/6: Generating per-paper HTML pages …")
    html_dir = generate_paper_pages(papers, target_date=target)
    logger.info("HTML visualization pages → %s", html_dir)

    # 4.7 Generate cross-day summary page ----------------------------------
    logger.info("Step 4.7/6: Generating cross-day summary page …")
    generate_summary_page(papers, target_date=target)

    # 5. Save archive ------------------------------------------------------
    report_path = save_report(markdown, target_date=target)
    logger.info("Markdown report archived at %s", report_path)
'''
    # 6. Send email --------------------------------------------------------
    logger.info("Step 5/5: Sending email …")
    subject = f"📰 AI 论文日报 | {target} | {len(papers)} 篇精选"
    try:
        send_email(html, subject=subject)
    except RuntimeError as exc:
        # Missing SMTP config — not fatal, just warn
        logger.warning("Skipping email: %s", exc)

    logger.info("===== Pipeline finished ✅ =====")
'''

def main() -> None:
    """Sync wrapper so the module can be invoked with ``python -m src.main``."""
    asyncio.run(run())


if __name__ == "__main__":
    main()

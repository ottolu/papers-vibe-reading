"""Fetch the HuggingFace Daily Papers list for a given date."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import httpx
import requests

from . import config

logger = logging.getLogger(__name__)

HF_DAILY_PAPERS_API = "https://huggingface.co/api/daily_papers"


def _fetch_with_fallback(url: str, params: dict | None = None) -> list:
    """GET JSON from *url*, trying httpx first then falling back to requests.

    The Clash proxy on this machine causes SSL EOF errors with httpx/httpcore
    for certain domains (huggingface.co).  ``requests`` uses urllib3 which
    handles the same proxy without issue, so we fall back to it automatically.
    """
    proxy_url = config.get_proxy_url()

    # --- attempt 1: httpx (preferred, async-friendly elsewhere) -----------
    try:
        resp = httpx.get(
            url, params=params, timeout=30, proxy=proxy_url,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("httpx request failed (%s), falling back to requests …", exc)

    # --- attempt 2: requests + urllib3 ------------------------------------
    proxies = {"https": proxy_url, "http": proxy_url} if proxy_url else None
    resp2 = requests.get(url, params=params, timeout=30, proxies=proxies)
    resp2.raise_for_status()
    return resp2.json()


@dataclass
class Paper:
    """Represents a single paper from the HF daily list."""

    arxiv_id: str
    title: str
    summary: str
    authors: list[str] = field(default_factory=list)
    upvotes: int = 0
    published_at: str = ""
    # Derived links
    hf_url: str = ""
    arxiv_url: str = ""
    pdf_url: str = ""
    # Populated later
    pdf_bytes: bytes | None = None
    analysis: str = ""

    def __post_init__(self) -> None:
        self.hf_url = self.hf_url or f"https://huggingface.co/papers/{self.arxiv_id}"
        self.arxiv_url = self.arxiv_url or f"https://arxiv.org/abs/{self.arxiv_id}"
        self.pdf_url = self.pdf_url or f"https://arxiv.org/pdf/{self.arxiv_id}"


def fetch_daily_papers(
    target_date: date | None = None,
    top_n: int | None = None,
) -> list[Paper]:
    """Fetch the top-N daily papers from HuggingFace for *target_date*.

    Parameters
    ----------
    target_date:
        The date to query.  Defaults to today (UTC).
    top_n:
        Number of papers to return (sorted by upvotes descending).
        Defaults to ``config.PAPERS_TOP_N``.

    Returns
    -------
    list[Paper]
        Sorted list of papers (most upvoted first).
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()
    if top_n is None:
        top_n = config.PAPERS_TOP_N

    date_str = target_date.isoformat()  # YYYY-MM-DD
    logger.info("Fetching HF daily papers for %s (top %d) …", date_str, top_n)

    data = _fetch_with_fallback(
        HF_DAILY_PAPERS_API,
        params={"date": date_str},
    )

    logger.info("API returned %d papers for %s", len(data), date_str)

    papers: list[Paper] = []
    for item in data:
        paper_info = item.get("paper", {})
        arxiv_id = paper_info.get("id", "")
        if not arxiv_id:
            continue

        authors = [
            a.get("name", "") or a.get("user", {}).get("fullname", "")
            for a in paper_info.get("authors", [])
        ]

        papers.append(
            Paper(
                arxiv_id=arxiv_id,
                title=paper_info.get("title", ""),
                summary=paper_info.get("summary", ""),
                authors=authors,
                upvotes=item.get("paper", {}).get("upvotes", 0),
                published_at=paper_info.get("publishedAt", ""),
            )
        )

    # Sort by upvotes (descending) and take top N
    papers.sort(key=lambda p: p.upvotes, reverse=True)
    papers = papers[:top_n]

    logger.info(
        "Selected %d papers: %s",
        len(papers),
        [p.arxiv_id for p in papers],
    )
    return papers

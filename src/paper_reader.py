"""Download paper PDFs from arXiv, with local date-based cache."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path

import httpx

from . import config

logger = logging.getLogger(__name__)

ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
DOWNLOAD_TIMEOUT = 120  # seconds – PDFs can be large
PDF_CACHE_DIR = Path(config.OUTPUT_DIR) / "papers"


def _pdf_cache_path(arxiv_id: str, target_date: date) -> Path:
    """Return ``output/papers/YYYY-MM-DD/<arxiv_id>.pdf``."""
    safe_name = arxiv_id.replace("/", "_")
    return PDF_CACHE_DIR / target_date.isoformat() / f"{safe_name}.pdf"


def load_cached_pdf(arxiv_id: str, target_date: date) -> bytes | None:
    """Return cached PDF bytes if already on disk, else ``None``."""
    path = _pdf_cache_path(arxiv_id, target_date)
    if path.exists() and path.stat().st_size > 0:
        logger.info("[%s] Cache HIT → %s", arxiv_id, path)
        return path.read_bytes()
    return None


def save_pdf_to_cache(arxiv_id: str, target_date: date, data: bytes) -> Path:
    """Write PDF bytes to the date-based cache directory.  Returns the path."""
    path = _pdf_cache_path(arxiv_id, target_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    logger.info("[%s] Saved PDF (%.1f KB) → %s", arxiv_id, len(data) / 1024, path)
    return path


async def download_pdf(arxiv_id: str, client: httpx.AsyncClient) -> bytes:
    """Download a single PDF from arXiv with retry logic.

    Parameters
    ----------
    arxiv_id:
        The arXiv paper identifier (e.g. ``"2401.12345"``).
    client:
        A reusable ``httpx.AsyncClient``.

    Returns
    -------
    bytes
        Raw PDF content.

    Raises
    ------
    httpx.HTTPStatusError
        If all retries are exhausted.
    """
    url = ARXIV_PDF_URL.format(arxiv_id=arxiv_id)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "[%s] Downloading PDF (attempt %d/%d) …",
                arxiv_id,
                attempt,
                MAX_RETRIES,
            )
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            pdf_bytes = resp.content
            logger.info(
                "[%s] Downloaded %.1f KB",
                arxiv_id,
                len(pdf_bytes) / 1024,
            )
            return pdf_bytes
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            logger.warning(
                "[%s] Attempt %d failed: %s", arxiv_id, attempt, exc
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)
            else:
                raise


async def download_papers_pdf(
    arxiv_ids: list[str],
    target_date: date,
) -> dict[str, bytes | None]:
    """Download PDFs for a list of arXiv IDs concurrently.

    Checks the local cache (``output/papers/YYYY-MM-DD/``) first;
    only downloads when a file is not already present.

    Returns a mapping ``{arxiv_id: pdf_bytes}``.
    """
    results: dict[str, bytes | None] = {}
    to_download: list[str] = []

    # --- check cache first ------------------------------------------------
    for aid in arxiv_ids:
        cached = load_cached_pdf(aid, target_date)
        if cached is not None:
            results[aid] = cached
        else:
            to_download.append(aid)

    if not to_download:
        logger.info("All %d PDFs found in cache — skipping downloads", len(arxiv_ids))
        return results

    logger.info(
        "%d/%d PDFs cached, downloading remaining %d …",
        len(arxiv_ids) - len(to_download),
        len(arxiv_ids),
        len(to_download),
    )

    # --- download missing -------------------------------------------------
    async with httpx.AsyncClient(
        timeout=DOWNLOAD_TIMEOUT,
        proxy=config.get_proxy_url(),
    ) as client:
        sem = asyncio.Semaphore(3)

        async def _download(aid: str) -> None:
            async with sem:
                try:
                    pdf_bytes = await download_pdf(aid, client)
                    save_pdf_to_cache(aid, target_date, pdf_bytes)
                    results[aid] = pdf_bytes
                except Exception as exc:
                    logger.error("[%s] Failed to download PDF: %s", aid, exc)
                    results[aid] = None

        await asyncio.gather(*[_download(aid) for aid in to_download])

    return results

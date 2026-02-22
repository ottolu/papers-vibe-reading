"""Download front-end assets (KaTeX, Mermaid, Chart.js, ECharts) to local disk.

Ensures that HTML visualization pages work when opened via ``file:///`` protocol
where browsers block CDN requests.  Assets are cached — files that already exist
and have size > 0 are skipped.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

from . import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Asset manifest — (relative_path, CDN URL)
# ---------------------------------------------------------------------------

_KATEX_VERSION = "0.16.21"
_KATEX_CDN = f"https://cdn.jsdelivr.net/npm/katex@{_KATEX_VERSION}/dist"

_MERMAID_VERSION = "11"
_CHARTJS_VERSION = "4"
_ECHARTS_VERSION = "5"

# KaTeX font files required for proper rendering
_KATEX_FONTS = [
    "KaTeX_AMS-Regular.woff2",
    "KaTeX_Caligraphic-Bold.woff2",
    "KaTeX_Caligraphic-Regular.woff2",
    "KaTeX_Fraktur-Bold.woff2",
    "KaTeX_Fraktur-Regular.woff2",
    "KaTeX_Main-Bold.woff2",
    "KaTeX_Main-BoldItalic.woff2",
    "KaTeX_Main-Italic.woff2",
    "KaTeX_Main-Regular.woff2",
    "KaTeX_Math-BoldItalic.woff2",
    "KaTeX_Math-Italic.woff2",
    "KaTeX_Math-Regular.woff2",
    "KaTeX_SansSerif-Bold.woff2",
    "KaTeX_SansSerif-Italic.woff2",
    "KaTeX_SansSerif-Regular.woff2",
    "KaTeX_Script-Regular.woff2",
    "KaTeX_Size1-Regular.woff2",
    "KaTeX_Size2-Regular.woff2",
    "KaTeX_Size3-Regular.woff2",
    "KaTeX_Size4-Regular.woff2",
    "KaTeX_Typewriter-Regular.woff2",
]

ASSET_MANIFEST: list[tuple[str, str]] = [
    # KaTeX core
    ("katex/katex.min.css", f"{_KATEX_CDN}/katex.min.css"),
    ("katex/katex.min.js", f"{_KATEX_CDN}/katex.min.js"),
    ("katex/contrib/auto-render.min.js", f"{_KATEX_CDN}/contrib/auto-render.min.js"),
    # KaTeX fonts
    *[
        (f"katex/fonts/{font}", f"{_KATEX_CDN}/fonts/{font}")
        for font in _KATEX_FONTS
    ],
    # Chart.js (UMD bundle)
    ("chart.umd.min.js", f"https://cdn.jsdelivr.net/npm/chart.js@{_CHARTJS_VERSION}/dist/chart.umd.min.js"),
    # ECharts
    ("echarts.min.js", f"https://cdn.jsdelivr.net/npm/echarts@{_ECHARTS_VERSION}/dist/echarts.min.js"),
    # Mermaid UMD (self-contained, works with file:/// unlike ESM)
    ("mermaid.min.js", f"https://cdn.jsdelivr.net/npm/mermaid@{_MERMAID_VERSION}/dist/mermaid.min.js"),
]


# ---------------------------------------------------------------------------
# Download logic
# ---------------------------------------------------------------------------

async def _download_one(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
) -> None:
    """Download a single file if not already cached."""
    if dest.exists() and dest.stat().st_size > 0:
        return  # cache hit

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        logger.debug("  ✓ %s (%d bytes)", dest.name, len(resp.content))
    except Exception as exc:
        logger.warning("Failed to download %s: %s", url, exc)


async def ensure_assets() -> Path:
    """Download all front-end assets to ``output/html/assets/``.

    Files that already exist (size > 0) are skipped.  Download failures are
    logged as warnings but do **not** interrupt the pipeline.

    Returns the assets directory path.
    """
    assets_dir = Path(config.OUTPUT_DIR) / "html" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    proxy_url = config.get_proxy_url()
    transport_kwargs: dict = {}
    if proxy_url:
        transport_kwargs["proxy"] = proxy_url

    async with httpx.AsyncClient(
        timeout=60.0,
        **transport_kwargs,
    ) as client:
        tasks = [
            _download_one(client, url, assets_dir / rel_path)
            for rel_path, url in ASSET_MANIFEST
        ]
        await asyncio.gather(*tasks)

    # Count how many files are present
    present = sum(
        1 for rel_path, _ in ASSET_MANIFEST
        if (assets_dir / rel_path).exists() and (assets_dir / rel_path).stat().st_size > 0
    )
    logger.info(
        "Assets ready: %d/%d files in %s",
        present, len(ASSET_MANIFEST), assets_dir,
    )
    return assets_dir

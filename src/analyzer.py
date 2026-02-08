"""Gemini 3.0 Pro Vibe Reading — analyse papers via the Google GenAI SDK."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from google import genai
from google.genai import types
import httpx

from . import config

if TYPE_CHECKING:
    from .fetcher import Paper

logger = logging.getLogger(__name__)

VIBE_READING_PROMPT = """\
你是一位顶级的 AI researcher，精通学术内容解读与数据可视化。你的任务是将一篇复杂的学术论文，转化为一份符合能让读者高效、快速掌握文章核心内容、原理和创新点的阅读材料。
请将上传的指定学术论文，按照要求生成一份能让读者高效、快速掌握文章核心内容、原理和创新点的阅读材料，其中需深度解析并重点展示论文的
- **研究动机**：发现了什么问题，为什么需要解决这个问题，本文研究的 significance 是什么
- **数学表示及建模**：从符号/表示到公式，以及公式推导和算法流程，注意支持 latex 的渲染
- **实验方法与实验设计**：系统性整理实验细节（比如模型、数据、超参数、prompt等），尽可能参考 appendix，达到可复现的程度；
- **实验结果及核心结论**：对比了那些baseline，达到了什么效果，揭示了什么结论和insights
- **你的评论**：作为一个犀利的reviewer，整体锐评下这篇工作，优势与不足，以及可能的改进方向
- **思考题**: 提出三个基于这篇文章的思考问题，难度层层递进，考察读者对这篇文章的理解。
- **One More Thing**: 你也可以自由发挥本文中其他你认为重要、希望分享给我的内容
注意：
1. 所有的符号及公式，都要能支持正确进行 latex 渲染（不只是公式块，还包括inline的公式，注意**行内公式不要换行**）；
2. 除公式以及一些核心术语和技术名词外，尽可能用中文。
3. figure/table 插入时，用论文中具体的 figure/table 来表示。特别的，对于图片，如果无法直接放到网页中，就使用占位符表示，方便检索；对于表格，如果是关键实验相关表格 则按照latex格式进行渲染，将表格内具体内容放到网页中。
4. 要尽可能地事无巨细，目标是读完这个材料，基本把握了论文90%的内容了，可以达到复现论文的程度。
"""

GEMINI_LOG_DIR = Path(config.OUTPUT_DIR) / "gemini_logs"


def _build_client() -> genai.Client:
    """Create a Google GenAI client, routing through the configured proxy.

    Forces HTTP/1.1 when a proxy is configured — Clash proxies often fail
    the TLS/ALPN negotiation for HTTP/2, causing ``SSL: UNEXPECTED_EOF``.
    """
    proxy_url = config.get_proxy_url()
    if proxy_url:
        transport = httpx.HTTPTransport(
            proxy=proxy_url,
            http1=True,
            http2=False,
        )
        http_client = httpx.Client(transport=transport, timeout=300)
        return genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(httpxClient=http_client),
        )
    return genai.Client(api_key=config.GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# Gemini call logging
# ---------------------------------------------------------------------------

def _log_dir(target_date: date) -> Path:
    """Return ``output/gemini_logs/YYYY-MM-DD/``."""
    d = GEMINI_LOG_DIR / target_date.isoformat()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_request_log(
    arxiv_id: str,
    target_date: date,
    user_prompt: str,
    has_pdf: bool,
) -> None:
    """Persist the request we are about to send (everything except the binary PDF)."""
    safe = arxiv_id.replace("/", "_")
    path = _log_dir(target_date) / f"{safe}_request.json"
    payload = {
        "arxiv_id": arxiv_id,
        "model": config.GEMINI_MODEL,
        "contents_structure": {
            "role": "user",
            "parts": (
                ["Part(inline_data=PDF)", "Part(text=user_prompt)"]
                if has_pdf
                else ["Part(text=user_prompt)"]
            ),
        },
        "has_pdf_attachment": has_pdf,
        "user_prompt": user_prompt,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[%s] Request log → %s", arxiv_id, path)


def _save_response_log(
    arxiv_id: str,
    target_date: date,
    response: types.GenerateContentResponse,
    analysis: str,
) -> None:
    """Persist the API response metadata + full analysis text."""
    safe = arxiv_id.replace("/", "_")
    path = _log_dir(target_date) / f"{safe}_response.json"

    # Extract usage metadata safely
    usage: dict = {}
    if response.usage_metadata:
        um = response.usage_metadata
        usage = {
            "prompt_tokens": getattr(um, "prompt_token_count", None),
            "candidates_tokens": getattr(um, "candidates_token_count", None),
            "total_tokens": getattr(um, "total_token_count", None),
        }

    # Extract finish reason
    finish_reason = None
    if response.candidates:
        fr = getattr(response.candidates[0], "finish_reason", None)
        finish_reason = str(fr) if fr else None

    payload = {
        "arxiv_id": arxiv_id,
        "model": config.GEMINI_MODEL,
        "finish_reason": finish_reason,
        "usage": usage,
        "analysis_length": len(analysis),
        "analysis": analysis,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[%s] Response log → %s", arxiv_id, path)


def _save_error_log(
    arxiv_id: str,
    target_date: date,
    error: Exception,
) -> None:
    """Persist error information when the API call fails."""
    safe = arxiv_id.replace("/", "_")
    path = _log_dir(target_date) / f"{safe}_error.json"
    payload = {
        "arxiv_id": arxiv_id,
        "error_type": type(error).__name__,
        "error_message": str(error),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[%s] Error log → %s", arxiv_id, path)


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

async def analyze_paper(
    paper: "Paper",
    client: genai.Client,
    target_date: date,
) -> str:
    """Analyse a single paper with Gemini.

    The PDF is uploaded as an inline_data Part, followed by the vibe-reading
    instructions as a user text Part.  No system_instruction is used — the
    full prompt lives in the user turn so the model treats the PDF + prompt
    as a single coherent request.

    Returns
    -------
    str
        The model's Markdown-formatted analysis.
    """
    parts: list[types.Part] = []

    has_pdf = bool(paper.pdf_bytes)

    if has_pdf:
        # 1) PDF as the first part — Gemini sees the full document natively
        parts.append(
            types.Part.from_bytes(data=paper.pdf_bytes, mime_type="application/pdf")
        )
        logger.info(
            "[%s] Attaching PDF (%d bytes, %.1f KB) as inline_data",
            paper.arxiv_id,
            len(paper.pdf_bytes),
            len(paper.pdf_bytes) / 1024,
        )
    else:
        logger.warning(
            "[%s] No PDF available — falling back to abstract", paper.arxiv_id
        )

    # 2) Build the user prompt — vibe reading instructions + paper title
    #    When no PDF is available, append the abstract text as context.
    user_text = f"论文标题：{paper.title}\n\n"
    if not has_pdf:
        user_text += f"论文摘要：\n{paper.summary}\n\n"
    user_text += VIBE_READING_PROMPT

    user_text = VIBE_READING_PROMPT

    parts.append(types.Part.from_text(text=user_text))

    # Log request
    _save_request_log(paper.arxiv_id, target_date, user_text, has_pdf)

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=config.GEMINI_MODEL,
            contents=[
                types.Content(role="user", parts=parts),
            ],
            config=types.GenerateContentConfig(
                max_output_tokens=16384,
            ),
        )
        analysis = response.text or ""
        logger.info("[%s] Analysis completed (%d chars)", paper.arxiv_id, len(analysis))

        # Log response
        _save_response_log(paper.arxiv_id, target_date, response, analysis)

        return analysis

    except Exception as exc:
        logger.error("[%s] Gemini API error: %s", paper.arxiv_id, exc)
        # Log error
        _save_error_log(paper.arxiv_id, target_date, exc)
        # Fallback: return a simple summary based on the abstract
        return _fallback_summary(paper)


def _fallback_summary(paper: "Paper") -> str:
    """Generate a minimal summary when the AI call fails."""
    return (
        f"## 📌 一句话总结\n{paper.title}\n\n"
        f"## 🔑 核心贡献\n（AI 分析暂时不可用，请参考原文摘要）\n\n"
        f"## 🛠️ 方法概述\n{paper.summary[:500]}\n\n"
        f"## 📊 关键结果\n（请参考原文）\n\n"
        f"## 💡 为什么值得关注\n该论文在 HuggingFace 社区获得了 {paper.upvotes} 个赞。\n\n"
        f"## 🏷️ 关键词标签\nAI, ML"
    )


async def analyze_papers(
    papers: list["Paper"],
    target_date: date,
) -> list[str]:
    """Analyse multiple papers concurrently.

    Returns a list of analysis strings aligned with the input list.
    """
    client = _build_client()
    sem = asyncio.Semaphore(3)  # limit concurrency to avoid rate-limits

    async def _run(paper: "Paper") -> str:
        async with sem:
            return await analyze_paper(paper, client, target_date)

    results = await asyncio.gather(*[_run(p) for p in papers])
    return list(results)

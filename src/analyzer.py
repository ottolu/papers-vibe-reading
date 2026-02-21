"""Gemini 3.0 Pro Vibe Reading — analyse papers via the Google GenAI SDK."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
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

---

**最后，请在分析文本结束后，追加一个 JSON 元数据块。** 请使用如下格式，用 ` ```json:metadata ``` ` 围栏包裹：

```json:metadata
{
  "one_line_summary": "一句话总结（中文，30字以内）",
  "tags": ["标签1", "标签2", "标签3"],
  "difficulty": 3,
  "novelty": 4,
  "practicality": 4,
  "topics": ["主题1", "主题2"],
  "key_metrics": [
    {"name": "指标名", "value": "数值", "context": "对比说明"}
  ],
  "mermaid_concept_map": "graph TD\\n    A[问题] --> B[方法]\\n    B --> C[结果]",
  "related_areas": ["相关领域1", "相关领域2"]
}
```

字段说明：
- `one_line_summary`：一句话概括论文核心贡献，中文，不超过30字
- `tags`：3-5个关键词标签（英文），如 "LLM", "RL", "Efficiency", "Vision"
- `difficulty`：阅读难度 1-5（1=入门，5=非常困难）
- `novelty`：创新性 1-5（1=增量改进，5=开创性）
- `practicality`：实用性 1-5（1=纯理论，5=即刻可用）
- `topics`：2-4个具体研究主题
- `key_metrics`：论文中的关键实验指标（1-3个），每个包含 name/value/context
- `mermaid_concept_map`：用 Mermaid.js 语法画一个简明的概念图/流程图，展示论文核心思路（问题→方法→结果），节点文字用中文，注意转义换行为 \\n
- `related_areas`：2-3个相关研究领域
"""

GEMINI_LOG_DIR = Path(config.OUTPUT_DIR) / "gemini_logs"

# PDFs larger than 20 MB must go through the File API (inline_data limit).
_INLINE_DATA_LIMIT = 20 * 1024 * 1024


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
# Large-PDF upload via File API
# ---------------------------------------------------------------------------

def _upload_pdf_file(
    client: genai.Client,
    pdf_bytes: bytes,
    arxiv_id: str,
) -> types.Part:
    """Upload a large PDF via the Gemini File API and return a Part.

    The File API supports files up to 2 GB, compared to ~20 MB for
    inline_data.  This function blocks (synchronous SDK call) and is
    meant to be called via ``asyncio.to_thread()``.
    """
    uploaded = client.files.upload(
        file=io.BytesIO(pdf_bytes),
        config={"mime_type": "application/pdf", "display_name": f"{arxiv_id}.pdf"},
    )

    # Poll until processing completes (usually immediate for PDFs)
    while getattr(uploaded.state, "name", str(uploaded.state)) == "PROCESSING":
        time.sleep(2)
        uploaded = client.files.get(name=uploaded.name)

    state_name = getattr(uploaded.state, "name", str(uploaded.state))
    if state_name not in ("ACTIVE", "State.ACTIVE"):
        raise RuntimeError(f"File upload failed: state={state_name}")

    logger.info("[%s] PDF uploaded via File API: %s", arxiv_id, uploaded.name)
    return types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type)


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

async def _generate(
    client: genai.Client,
    parts: list[types.Part],
    arxiv_id: str,
    target_date: date,
    user_text: str,
    has_pdf: bool,
) -> str:
    """Send parts to Gemini and return the analysis text.

    Raises on API errors so the caller can decide how to retry.
    """
    _save_request_log(arxiv_id, target_date, user_text, has_pdf)

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=config.GEMINI_MODEL,
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(max_output_tokens=16384),
    )
    analysis = response.text or ""
    logger.info("[%s] Analysis completed (%d chars)", arxiv_id, len(analysis))
    _save_response_log(arxiv_id, target_date, response, analysis)
    return analysis


async def analyze_paper(
    paper: "Paper",
    client: genai.Client,
    target_date: date,
) -> str:
    """Analyse a single paper with Gemini.

    Strategy:
      1. Try with PDF attached (inline_data for ≤20 MB, File API for larger).
      2. If the PDF fails (upload error or generation error), retry with
         just the title + abstract — still a full Gemini call, not a static
         template.
      3. Only fall back to ``_fallback_summary`` if even the abstract-only
         call fails.

    Returns
    -------
    str
        The model's Markdown-formatted analysis.
    """
    has_pdf = bool(paper.pdf_bytes)

    # -- Attempt 1: with PDF ------------------------------------------------
    if has_pdf:
        try:
            parts: list[types.Part] = []
            pdf_size = len(paper.pdf_bytes)

            if pdf_size > _INLINE_DATA_LIMIT:
                logger.info(
                    "[%s] PDF too large for inline_data (%d bytes, %.1f MB), "
                    "uploading via File API",
                    paper.arxiv_id, pdf_size, pdf_size / (1024 * 1024),
                )
                pdf_part = await asyncio.to_thread(
                    _upload_pdf_file, client, paper.pdf_bytes, paper.arxiv_id,
                )
                parts.append(pdf_part)
            else:
                parts.append(
                    types.Part.from_bytes(
                        data=paper.pdf_bytes, mime_type="application/pdf",
                    )
                )
                logger.info(
                    "[%s] Attaching PDF (%d bytes, %.1f KB) as inline_data",
                    paper.arxiv_id, pdf_size, pdf_size / 1024,
                )

            user_text = f"{VIBE_READING_PROMPT}"
            parts.append(types.Part.from_text(text=user_text))

            return await _generate(
                client, parts, paper.arxiv_id, target_date, user_text,
                has_pdf=True,
            )

        except Exception as exc:
            logger.warning(
                "[%s] PDF-based analysis failed (%s), retrying with abstract only",
                paper.arxiv_id, exc,
            )
            _save_error_log(paper.arxiv_id, target_date, exc)

    # -- Attempt 2: abstract only -------------------------------------------
    try:
        user_text = (
            f"论文标题：{paper.title}\n\n"
            f"论文摘要：\n{paper.summary}\n\n"
            f"{VIBE_READING_PROMPT}"
        )
        parts = [types.Part.from_text(text=user_text)]

        if has_pdf:
            logger.info("[%s] Retrying with abstract only", paper.arxiv_id)
        else:
            logger.warning(
                "[%s] No PDF available — using abstract", paper.arxiv_id,
            )

        return await _generate(
            client, parts, paper.arxiv_id, target_date, user_text,
            has_pdf=False,
        )

    except Exception as exc:
        logger.error("[%s] Abstract-only analysis also failed: %s", paper.arxiv_id, exc)
        _save_error_log(paper.arxiv_id, target_date, exc)
        return _fallback_summary(paper)


def _fallback_summary(paper: "Paper") -> str:
    """Generate a minimal summary when the AI call fails."""
    import json as _json

    metadata_block = _json.dumps(
        {
            "one_line_summary": paper.title[:30],
            "tags": ["AI", "ML"],
            "difficulty": 3,
            "novelty": 3,
            "practicality": 3,
            "topics": [],
            "key_metrics": [],
            "mermaid_concept_map": "",
            "related_areas": [],
        },
        ensure_ascii=False,
        indent=2,
    )
    return (
        f"## 📌 一句话总结\n{paper.title}\n\n"
        f"## 🔑 核心贡献\n（AI 分析暂时不可用，请参考原文摘要）\n\n"
        f"## 🛠️ 方法概述\n{paper.summary[:500]}\n\n"
        f"## 📊 关键结果\n（请参考原文）\n\n"
        f"## 💡 为什么值得关注\n该论文在 HuggingFace 社区获得了 {paper.upvotes} 个赞。\n\n"
        f"## 🏷️ 关键词标签\nAI, ML\n\n"
        f"```json:metadata\n{metadata_block}\n```"
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

# CLAUDE.md — Papers Vibe Reading 项目指南

## 项目概述

自动化 ML 论文分析 pipeline：从 HuggingFace 拉取每日热门论文 → 下载 PDF → Gemini Vibe Reading 深度分析 → 生成多格式输出（Markdown / HTML 邮件 / 独立可视化网页）。

## 项目结构

```
src/
├── main.py          # 异步 pipeline 入口：fetch → download → analyze → extract metadata → report → visualize → save
├── config.py        # 环境变量配置（Gemini / SMTP / 代理 / 输出）
├── fetcher.py       # HuggingFace Daily Papers API + Paper 数据类定义
├── paper_reader.py  # arXiv PDF 下载（带本地缓存 + 重试 + 并发控制）
├── analyzer.py      # Gemini Vibe Reading 分析（PDF 内嵌 + JSON 日志 + 元数据 prompt）
├── metadata.py      # PaperMetadata 数据类 + json:metadata 块解析
├── reporter.py      # Markdown 报告 + HTML 邮件生成
├── visualizer.py    # 单篇论文 HTML 页面 + 当日总览页 + 跨天汇总页生成
└── notifier.py      # SMTP 邮件发送（当前已注释掉）

templates/
├── email_template.html  # 邮件模板（700px 宽，内联 CSS）
├── paper.html           # 单篇论文页（双栏布局：TOC 侧边栏 + 内容区，Mermaid 概念图，KaTeX 公式）
├── index.html           # 当日总览页（Chart.js 统计面板 + 标签筛选 + 增强卡片）
└── summary.html         # 跨天汇总仪表盘（ECharts 趋势图/雷达图/主题频次 + 日期浏览器）

output/
├── YYYY-MM-DD.md                   # 每日 Markdown 报告
├── papers/YYYY-MM-DD/*.pdf         # PDF 缓存
├── gemini_logs/YYYY-MM-DD/*.json   # Gemini API 请求/响应/错误日志
└── html/
    ├── papers_index.json           # 跨天论文元数据索引（自动追加）
    ├── summary.html                # 跨天汇总仪表盘
    └── YYYY-MM-DD/                 # 可视化网页
        ├── index.html
        └── {arxiv_id}.html
```

## 核心数据类

`Paper`（定义在 `src/fetcher.py`）是贯穿整个 pipeline 的核心模型：

```python
@dataclass
class Paper:
    arxiv_id: str          # "2401.12345"
    title: str
    summary: str
    authors: list[str]
    upvotes: int
    published_at: str
    hf_url / arxiv_url / pdf_url: str  # __post_init__ 自动生成
    pdf_bytes: bytes | None            # download 阶段填充
    analysis: str                      # analyze 阶段填充
    metadata: PaperMetadata | None     # metadata 提取阶段填充
```

`PaperMetadata`（定义在 `src/metadata.py`）存储 Gemini 返回的结构化元数据：

```python
@dataclass
class PaperMetadata:
    one_line_summary: str        # 一句话总结
    tags: list[str]              # 关键词标签（英文）
    difficulty: int              # 阅读难度 1-5
    novelty: int                 # 创新性 1-5
    practicality: int            # 实用性 1-5
    topics: list[str]            # 具体研究主题
    key_metrics: list[dict]      # 关键实验指标 [{name, value, context}]
    mermaid_concept_map: str     # Mermaid.js 概念图/流程图语法
    related_areas: list[str]     # 相关研究领域
```

修改 Paper/PaperMetadata 字段时注意：模板（4 个 HTML）、reporter、visualizer 都依赖这些属性名。

## 开发约定

### 代码风格
- **命名**：模块 `snake_case.py`，函数 `snake_case()`，类 `PascalCase`，常量 `UPPER_CASE`
- **私有函数**：前缀 `_`（如 `_fetch_with_fallback()`、`_make_snippet()`）
- **类型标注**：所有文件开头 `from __future__ import annotations`，使用 `X | None` 联合类型
- **Python 版本**：要求 ≥3.13（pyproject.toml）

### 异步与并发
- 整体用 `asyncio.run()` 驱动
- PDF 下载和 Gemini 分析都用 `asyncio.Semaphore(3)` 限制并发数（硬编码）
- `asyncio.gather()` 聚合并行任务结果
- Gemini 调用通过 `asyncio.to_thread()` 桥接同步 SDK

### 错误处理模式
- **逐层降级**：httpx 失败 → requests 兜底；PDF 无法下载 → 用摘要替代；Gemini 失败 → 返回 fallback 摘要
- **不中断 pipeline**：单篇论文失败不影响其他论文处理
- **详尽日志**：每步操作都有 `logger.info/warning/error`，Gemini 交互完整写入 JSON

### 代理处理（重要）
- Clash 代理（默认 `127.0.0.1:7890`）与 httpx/httpcore 存在 SSL EOF 兼容性问题
- `fetcher.py` 实现了 httpx → requests 的自动降级
- `analyzer.py` 中 Gemini 客户端强制 HTTP/1.1（ALPN 协商问题）
- 代理 URL 通过 `config.get_proxy_url()` 统一获取

### 缓存策略
- PDF 按日期目录缓存：`output/papers/YYYY-MM-DD/{arxiv_id}.pdf`
- 存在且文件大小 > 0 即视为缓存命中，跳过下载
- 不同日期互不冲突

## 模板与样式

### 配色方案（三个模板统一）
- 背景 `#f4f5f7`、卡片 `#ffffff`、链接蓝 `#4a90d9`
- Upvote 徽章：`#fff3e0` 底色 + `#e65100` 文字
- 正文 `#1a1a1a`，副文字 `#666` / `#888`

### 字体栈
```css
-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif
```

### KaTeX 公式渲染（仅 paper.html）
- CDN 引入：`katex@0.16.21`（CSS + JS + auto-render）
- 支持分隔符：`$$...$$`（display）、`$...$`（inline）、`\\(...\\)` / `\\[...\\]`
- `throwOnError: false` 容错处理

### Mermaid.js 概念图（仅 paper.html）
- CDN 引入：`mermaid@11`（ESM 模式）
- 条件渲染：仅当 `paper.metadata.mermaid_concept_map` 存在时加载
- `securityLevel: 'loose'` + `theme: 'neutral'`
- 渲染失败时优雅降级

### Chart.js 统计图表（仅 index.html）
- CDN 引入：`chart.js@4`（~60KB gzip）
- 主题分布饼图 + 平均评分柱状图
- 条件渲染：仅当 `stats.topic_counts` 存在时加载

### ECharts 仪表盘（仅 summary.html）
- CDN 引入：`echarts@5`（~300KB gzip）
- 折线/柱状复合图：每日论文数 & 平均 upvotes 趋势
- 横向柱状图：主题出现频次
- 雷达图：综合 difficulty/novelty/practicality 评分
- 响应式 resize

### visualizer.py 中的 Markdown 转 HTML
- 使用 `markdown` 库，启用扩展：`tables`、`fenced_code`、`codehilite`、`toc`、`nl2br`
- Jinja2 `autoescape=False`（有意为之，因为 HTML 由 markdown 库生成而非用户输入）
- 每篇论文转换前调用 `_md.reset()` 防止 TOC 等状态泄漏

## 运行方式

```bash
# 安装依赖（自动创建 .venv 并同步锁文件）
uv sync

# 运行 pipeline（需要 .env 中配置 GEMINI_API_KEY）
uv run python src/main.py

# 查看可视化结果
# 浏览器打开 output/html/YYYY-MM-DD/index.html

# 添加新依赖
uv add <package-name>

# 更新锁文件
uv lock
```

## 当前进度（2025-02-08）

### 已完成
- 完整 pipeline：fetch → download PDF → Gemini 分析 → 元数据提取 → Markdown/HTML 报告 → 可视化网页
- **可视化系统全面改版**：
  - `src/metadata.py`：`PaperMetadata` 数据类 + `extract_metadata()` 从 Gemini 输出解析 `json:metadata` 块
  - `src/analyzer.py`：Gemini prompt 追加元数据输出指令（标签、评分、Mermaid 图、关键指标等）
  - `templates/paper.html`：双栏布局（TOC 侧边栏 + 内容区）、Mermaid 概念图、评分条、关键指标卡、prev/next 导航、移动端折叠 TOC
  - `templates/index.html`：Chart.js 统计面板（主题饼图 + 评分柱状图）、标签筛选/排序、增强卡片（one_line_summary + tags + mini 评分条 + key_metric）、日期导航
  - `templates/summary.html`：ECharts 跨天仪表盘（趋势图、主题频次、雷达图）、热门主题标签云、日期浏览器
  - `src/visualizer.py`：TOC 提取、prev/next 论文引用、统计计算、相邻日期检测、`papers_index.json` 持久化、`generate_summary_page()` 生成跨天汇总
- 可视化系统：`src/visualizer.py` + `templates/paper.html` + `templates/index.html`（KaTeX 公式渲染）
- 项目管理迁移到 uv（删除 requirements.txt，依赖统一在 pyproject.toml）
- GitHub Actions CI 使用 uv（`astral-sh/setup-uv@v5`）
- 仓库已推送：https://github.com/ottolu/papers-vibe-reading

### 待修复的 Bug
- ~~**`src/analyzer.py` 第 205 行 prompt 覆盖 bug**~~：已通过改版修复

### 待做 / 可优化
- 邮件发送功能待启用（`src/main.py` 中用三引号注释掉了）
- 并发上限 Semaphore(3) 硬编码，可考虑移到 config

## 已知问题 / 注意事项

1. **邮件发送已禁用**：`src/main.py` 中邮件步骤用三引号注释掉了（`'''...'''`）
2. **CI 使用 uv**：GitHub Actions 通过 `astral-sh/setup-uv@v5` 安装 uv，用 `uv sync` + `uv run` 执行
3. **并发上限硬编码**：Semaphore(3) 写死在代码中，需改代码才能调整
4. **周末自动回退**：周六/周日运行时自动查询上周五的论文（HF 周末无新论文）

## 新增功能的检查清单

添加新的 pipeline 步骤时：
1. 在 `src/main.py` 的 `run()` 中按顺序插入调用
2. 如果涉及网络请求，考虑代理兼容性（参考 fetcher 的降级模式）
3. 如果涉及并发，使用 `asyncio.Semaphore` 控制
4. 新增依赖用 `uv add <package>`，会自动更新 `pyproject.toml` 和 `uv.lock`
5. 模板文件放 `templates/`，通过 Jinja2 `FileSystemLoader` 加载
6. 输出文件放 `output/` 子目录，按日期组织
7. 改完代码后推送：`git push`（remote 已配置为 origin → github.com/ottolu/papers-vibe-reading）
8. 推送含 `.github/workflows/` 的修改需要 gh auth 有 `workflow` scope

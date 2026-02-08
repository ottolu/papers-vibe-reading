# Papers Vibe Reading

> 每日自动获取 HuggingFace 热门 AI 论文，通过 Gemini 进行深度 "Vibe Reading" 分析，生成可在浏览器中阅读的精美可视化页面。

## 功能特性

- **自动获取论文** — 每日从 [HuggingFace Daily Papers](https://huggingface.co/papers) 拉取 Top-N 热门论文（按 upvotes 排序）
- **PDF 智能缓存** — 从 arXiv 下载论文 PDF，本地按日期缓存，避免重复下载
- **Gemini 深度分析** — 将完整 PDF 发送给 Gemini，生成包含数学公式、实验细节、锐评的全方位解读
- **多格式输出** — 同时生成 Markdown 报告、HTML 邮件、独立可视化网页
- **LaTeX 公式渲染** — 可视化页面集成 KaTeX，正确渲染行内公式与公式块
- **GitHub Actions 定时运行** — 每日 UTC 08:00（北京时间 16:00）自动执行

## 快速开始

### 1. 环境要求

- Python >= 3.13
- [Google Gemini API Key](https://aistudio.google.com/apikey)

### 2. 安装

```bash
git clone https://github.com/your-username/papers-vibe-reading.git
cd papers-vibe-reading
pip install -r requirements.txt
```

### 3. 配置

复制环境变量模板并填入你的配置：

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
# 必填 — Gemini API
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-3-pro-preview

# 可选 — 论文数量（默认 5）
PAPERS_TOP_N=5

# 可选 — 邮件通知
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_TO=recipient@email.com

# 可选 — 网络代理（如 Clash）
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890

# 可选 — 输出配置
LANGUAGE=zh
OUTPUT_DIR=output
```

### 4. 运行

```bash
python src/main.py
```

运行完成后，用浏览器打开可视化页面：

```
output/html/YYYY-MM-DD/index.html
```

## 输出结构

```
output/
├── 2025-02-06.md                        # Markdown 日报
├── papers/2025-02-06/                   # PDF 缓存
│   ├── 2602.05386.pdf
│   └── ...
├── gemini_logs/2025-02-06/              # Gemini API 日志（调试用）
│   ├── 2602.05386_request.json
│   ├── 2602.05386_response.json
│   └── ...
└── html/2025-02-06/                     # 可视化网页 ← 主要阅读入口
    ├── index.html                       # 当日总览（论文卡片列表）
    ├── 2602.05386.html                  # 单篇论文详细分析
    └── ...
```

## 分析内容

每篇论文的 Vibe Reading 包含以下部分：

| 章节 | 内容 |
|------|------|
| **研究动机** | 发现了什么问题，为什么需要解决，研究的 significance |
| **数学表示及建模** | 符号定义、公式推导、算法流程（LaTeX 渲染） |
| **实验方法与设计** | 模型、数据集、超参数、prompt 等可复现级别的细节 |
| **实验结果及核心结论** | Baseline 对比、关键指标、insights |
| **锐评** | 作为 reviewer 的优势/不足分析与改进方向 |
| **思考题** | 三个难度递进的问题，考察对论文的理解 |
| **One More Thing** | 其他值得关注的亮点 |

## Pipeline 流程

```
HuggingFace API        arXiv PDF           Gemini 3.0 Pro
     │                    │                      │
     ▼                    ▼                      ▼
 ┌────────┐        ┌───────────┐          ┌───────────┐
 │ Fetch  │───────▶│ Download  │─────────▶│ Analyze   │
 │ Top-N  │        │ + Cache   │          │ Vibe Read │
 └────────┘        └───────────┘          └─────┬─────┘
                                                │
                         ┌──────────────────────┼──────────────────┐
                         ▼                      ▼                  ▼
                  ┌─────────────┐      ┌──────────────┐    ┌─────────────┐
                  │  Markdown   │      │  HTML Email   │    │ HTML Pages  │
                  │  Report     │      │  (optional)   │    │ + Index     │
                  └─────────────┘      └──────────────┘    └─────────────┘
```

## GitHub Actions 自动化

项目已配置 GitHub Actions 工作流，每日自动运行：

1. 在仓库 **Settings → Secrets** 中添加 `GEMINI_API_KEY`（必填），以及 SMTP 相关 secrets（可选）
2. 工作流每天 UTC 08:00 自动触发，也可在 **Actions** 页面手动触发
3. 生成的报告会作为 Artifact 上传，可在 Actions 运行记录中下载

## 项目结构

```
src/
├── main.py          # Pipeline 入口（异步编排）
├── config.py        # 环境变量配置管理
├── fetcher.py       # HuggingFace API 拉取 + Paper 数据类
├── paper_reader.py  # arXiv PDF 下载（缓存 / 重试 / 并发控制）
├── analyzer.py      # Gemini Vibe Reading 分析
├── reporter.py      # Markdown 报告 + HTML 邮件生成
├── visualizer.py    # 单篇论文 HTML 页面 + 当日总览页
└── notifier.py      # SMTP 邮件发送

templates/
├── email_template.html  # 邮件模板
├── paper.html           # 单篇论文页面模板（含 KaTeX）
└── index.html           # 当日总览页面模板
```

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.13+ | 运行时，async/await 异步编排 |
| [Gemini API](https://ai.google.dev/) | 论文深度分析（支持 PDF 原生理解） |
| [httpx](https://www.python-httpx.org/) | 异步 HTTP 客户端 |
| [Jinja2](https://jinja.palletsprojects.com/) | HTML 模板渲染 |
| [markdown](https://python-markdown.github.io/) | Markdown → HTML 转换 |
| [KaTeX](https://katex.org/) | 客户端 LaTeX 公式渲染（CDN） |
| GitHub Actions | 每日定时执行 + 产物归档 |

## License

MIT

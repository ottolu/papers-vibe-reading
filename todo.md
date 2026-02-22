# TODO

## 待验证

- [ ] 运行 `uv run python src/main.py` 做一次完整 pipeline 测试
- [ ] 检查 `output/gemini_logs/` 中 response 是否包含 `json:metadata` 块
- [ ] 浏览器打开 `output/html/YYYY-MM-DD/index.html`，验证统计面板、标签筛选、卡片增强
- [ ] 打开任意 `{arxiv_id}.html`，验证 TOC 侧边栏、Mermaid 概念图、评分条、prev/next 导航、KaTeX 公式
- [ ] 打开 `output/html/summary.html`，验证跨天图表
- [ ] 移动端视口下测试响应式布局
- [ ] `git push` 推送到远程

## 待修复 / 待观察

- [ ] `src/config.py` 有未提交的小改动，确认是否需要保留
- [ ] Gemini 实际返回的 Mermaid 语法可能不合法，需观察降级效果
- [ ] `json:metadata` 块解析容错：观察实际 Gemini 输出是否符合预期格式

## 待做 / 可优化

- [ ] 邮件发送功能待启用（`src/main.py` 中用三引号注释掉了）
- [ ] 并发上限 Semaphore(3) 硬编码，可考虑移到 config
- [ ] summary.html 可增加更多维度（按作者统计、按标签趋势等）
- [ ] 考虑为 papers_index.json 加数据清理/归档机制（数据量增长后）

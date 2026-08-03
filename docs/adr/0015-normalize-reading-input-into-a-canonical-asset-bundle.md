# 将阅读输入标准化为 Canonical Reading Asset 包

每个成功的规范化运行发布 `canonical/manifest.json`、`canonical/document.md`、`canonical/blocks.jsonl` 与 `canonical/images/`：manifest 固定来源、运行、工具、配置、逐文件哈希，并记录由 document、blocks 与全部 image 实际字节确定、但不含 run ID、时间或工具信息的 `canonical_content_sha256`。Markdown 提供人和模型阅读的规范正文，JSONL 为每个 Evidence Block 提供稳定 `block_id`、类型、正文、页码和坐标，图片保存正文引用的视觉资产；MinerU 原始产物只保存在 `vendor/mineru/` 用于审计，下游不得依赖其私有格式。Candidate Knowledge 使用 `canonical_content_sha256 + block_id` 构成内容寻址 Evidence Pointer，具体 `canonical_run_id` 只由 semantic 或 Handoff manifest 作为物理 locator 保存，使相同内容的强制重跑不会改变 Candidate 身份。

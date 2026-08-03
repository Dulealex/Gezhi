# 使用 Work、Source 与 Assets 建模 Literature 身份

Literature 的稳定身份层级为 `Work → Source → Assets`：Work 表示独立科研成果，Source 表示其具体来源、版本和内容快照，PDF、HTML、XML/JATS、规范正文及派生产物都是 Source 下的 Assets。新模型不保留独立 File 领域实体，也不继承 `file_id`、`active_file`、`paper_id` 或 `raw_paper_id`；`active_source_id` 选择一次阅读唯一使用的 Source，每个 Source Asset 仍保存完整 SHA-256 以实现内容去重与追溯。

# 由 Knowledge Intake 独占可重建的 Candidate 搜索投影

Candidate Registry 的四张逻辑治理表继续作为唯一治理事实源；T19 另以独立 schema identity 和 Registry generation binding 维护 `unicode61`、`trigram` 两路 FTS5 派生投影。Knowledge Intake 是该投影的唯一 writer，并在 applied accept/withdraw 的同一 transaction 内同步 membership；已知 T18 基线 Registry 可在 exact Intake replay 时补建投影而不改变治理 generation 或 `unchanged` disposition，未知 schema 不迁移。`knowledge search` 只读要求投影版本与 generation 完全匹配，`knowledge show` 只依赖治理基线；两个读取命令都不创建、修复或迁移投影。

# 版本化并快照 Codex 提示词与 Schema

`literature_reader_v1` 与 `knowledge_answerer_v1` 的提示词和 Pydantic 输出模型分别保存在所属上下文内，Pydantic 是 JSON Schema 的唯一来源，不建立中央提示词目录、手写重复 Schema 或散落在 Python、TOML、`AGENTS.md`、skills 和个人配置中的隐藏指令。每次实际进入模型语义运行的角色都保存实际有效的 `prompt.txt`、确定性生成的 `schema.json` 及其 SHA-256，并在 manifest 中记录角色版本、模型、reasoning、Codex CLI 版本和 Git revision；任何影响语义的提示词或 Schema 变化都创建新的角色版本，旧运行继续绑定原版本和完整快照。

ADR 0071 细化并取代本文对每个 Knowledge Answer 无条件保存 `prompt.txt` 的要求：Knowledge 只有在 P4、非零 Candidate 且完整 synthesis 调用包通过复验后，才把 `prompt.txt` 与 `schema.json` 作为 C 原子对共同保存；每个实际 launch attempt 必须绑定同一 C 对。Retrieval 终态、零 Candidate 分支和 `synthesis_input_invalid` 不保存其中任一文件。

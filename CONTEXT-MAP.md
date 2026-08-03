# 格致上下文地图

格致是一个可持续接入新业务 Bot 的本地研究与知识工作平台。每个 Bot 在格致内部表现为拥有独立业务语言和状态所有权的领域上下文，而不是独立复制一套产品基础设施。

## 上下文

- [Literature](./docs/contexts/literature/CONTEXT.md) — 处理论文及强相关科研资料，形成可审核的阅读资产、候选知识与交接包。
- [Knowledge](./docs/contexts/knowledge/CONTEXT.md) — 接收已审核交接，治理、检索和引用跨来源候选知识。

新 Bot 只有在业务职责、语言和状态所有权被明确后才加入本地图；不预建没有领域定义的空上下文。

## 关系

- **Literature → Knowledge**：Literature 只通过版本化 Reviewed Handoff 交付符合 [Candidate Knowledge v1](./docs/contracts/candidate-knowledge-v1.md) 的已审核候选、来源身份、Evidence Pointer、风险与审核状态。
- **Knowledge → Literature**：Knowledge 可以报告合同、证据或冲突问题，但不回写 Literature 的全文、阅读资产或 Active Source 决策。
- **未来上下文 ↔ 现有上下文**：通过显式、版本化的交接合同协作；一个上下文不得直接拥有或改写另一个上下文的内部状态。
- **共同边界**：任何上下文都不能静默把 Candidate Knowledge 变成 Promoted Knowledge。
- **共同 CLI JSON seam**：所有公开命令通过 [CLI JSON v1](./docs/contracts/cli-json-v1.md) 的封闭五字段 outer 输出机器结果，并复用 [CLI Diagnostics v1](./docs/contracts/cli-diagnostics-v1.md) 的两字段 item、角色、排序、容量与隐私 profile；每个 concrete command 仍拥有自己的 result、code/context union 与跨字段矩阵。[Operations v1](./docs/contracts/operations-v1.md) 已冻结 `doctor/status` 的只读健康与跨 Context 状态投影，[Knowledge Ask Diagnostics v1](./docs/contracts/knowledge-ask-diagnostics-v1.md) 冻结 `knowledge.ask` 的 committed/no-commit binding；各上下文不复制共享 diagnostic-set module 或 JSON writer。

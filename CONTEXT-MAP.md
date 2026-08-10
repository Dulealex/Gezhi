# 格致上下文地图

格致是一个可持续接入新业务 Bot 的本地研究与知识工作平台。每个 Bot 在格致内部表现为拥有独立业务语言和状态所有权的领域上下文，而不是独立复制一套产品基础设施。

## 上下文

- [Literature](./docs/contexts/literature/CONTEXT.md) — 处理论文及强相关科研资料，形成可审核的阅读资产、候选知识与交接包。
- [Knowledge](./docs/contexts/knowledge/CONTEXT.md) — 接收已审核交接，治理、检索和引用跨来源候选知识。

新 Bot 只有在业务职责、语言和状态所有权被明确后才加入本地图；不预建没有领域定义的空上下文。

## 关系

- **Literature → Knowledge**：Literature 只通过版本化 Reviewed Handoff 交付符合 [Candidate Knowledge v1](./docs/contracts/candidate-knowledge-v1.md) 的已审核候选、来源身份、Evidence Pointer、风险与审核状态。
- **Literature 阅读边界**：[Canonical Reading Asset v1](./docs/contracts/canonical-reading-asset-v1.md) 冻结 Active Source 经 OCR success 生成 `document.md`、Evidence Block、内容寻址图片、Canonical 内容身份与 Evidence Pointer 的确定性合同；Reader 和后续 Bot 只消费该边界，不读取 MinerU 私有输出。
- **Knowledge → Literature**：Knowledge 可以报告合同、证据或冲突问题，但不回写 Literature 的全文、阅读资产或 Active Source 决策。
- **未来上下文 ↔ 现有上下文**：通过显式、版本化的交接合同协作；一个上下文不得直接拥有或改写另一个上下文的内部状态。
- **共同边界**：任何上下文都不能静默把 Candidate Knowledge 变成 Promoted Knowledge。
- **共同 Codex runtime seam**：[Codex Role Invocation v1](./docs/contracts/codex-role-invocation-v1.md) 冻结 project-pinned resolver、exact argv、cwd 与 Unicode environment allowlist；[Codex Child Process v1](./docs/contracts/codex-child-process-v1.md) 独占 Windows pipe、Job、stop、capture 与资源归零。每个 Bot 仍须显式拥有自己的 prompt、Schema、provider event adapter、retry 与领域结果，不能因复用基础设施而继承其他上下文语义。
- **Knowledge 只读发现与审计**：[Knowledge Read v1](./docs/contracts/knowledge-read-v1.md) 冻结 Candidate Search Result、Candidate Detail、普通 search 与 Retrieval View 的边界；[Knowledge Read Diagnostics v1](./docs/contracts/knowledge-read-diagnostics-v1.md) 冻结其 machine/Human receipt。
- **Knowledge Ask 可观察性**：[Knowledge Ask Observable v1](./docs/contracts/knowledge-ask-observable-v1.md) 以 [ADR 0122](./docs/adr/0122-keep-knowledge-ask-observability-outside-the-domain-result.md) 为边界，冻结 [Retrieval Audit v1 Schema](./docs/contracts/schemas/retrieval-audit-v1.schema.json)、补充诊断、Human 表示与 presentation failure；这些投影不改变既有 Answer identity、primary、result、commit 或 recovery 决策。
- **共同 CLI JSON seam**：所有公开命令通过 [CLI JSON v1](./docs/contracts/cli-json-v1.md) 的封闭五字段 outer 输出机器结果，并复用 [CLI Diagnostics v1](./docs/contracts/cli-diagnostics-v1.md) 的两字段 item、角色、排序、容量与隐私 profile；每个 concrete command 仍拥有自己的 result、code/context union 与跨字段矩阵。[Operations v1](./docs/contracts/operations-v1.md) 已绑定 `doctor/status`，[Literature Commands v1](./docs/contracts/literature-commands-v1.md) 已绑定三个 Literature command，[Knowledge Read v1](./docs/contracts/knowledge-read-v1.md) 与 [Knowledge Read Diagnostics v1](./docs/contracts/knowledge-read-diagnostics-v1.md) 已绑定 `knowledge.search/show`，[Knowledge Ask Result v1](./docs/contracts/knowledge-ask-result-v1.md)、[Knowledge Ask Diagnostics v1](./docs/contracts/knowledge-ask-diagnostics-v1.md) 与 [Knowledge Ask Observable v1](./docs/contracts/knowledge-ask-observable-v1.md) 共同闭合 `knowledge.ask`。公开命令仍恰好八条，T05 的 `search/show` 不继承 Ask 的 Answer、cancellation 或 presentation 语义；合同闭合不等于宣称实现已 production complete。各上下文不复制共享 diagnostic-set module 或 JSON writer。

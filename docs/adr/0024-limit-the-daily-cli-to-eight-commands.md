# 将首版日常 CLI 限制为八个命令

首版公开日常接口只包含全局 `gezhi doctor`、`gezhi status [work_id]`，Literature 的 `add`、`resume`、`review`，以及 Knowledge 的 `search`、`show`、`ask`。所有命令支持人用 Rich 输出和稳定 `--json`；阶段级恢复与测试入口属于内部正式命名空间，不承诺为日常接口。旧 PaperBot/KnowledgeBot 命令、脚本和兼容别名不迁入格致，以保持单一产品入口并为未来上下文保留清晰命名空间。

这些命令的 JSON mode 共享 ADR 0089 的五字段 outer，但不共享一套虚构的领域 result：每个命令静态冻结自己的 `command` identity、result/diagnostic Schema 与 outcome matrix。`knowledge.ask` 是首个 binding；后续 [Operations v1](../contracts/operations-v1.md) 已显式绑定 `doctor/status`，其余命令和未来 Bot 仍不得仅因 outer 已冻结就提前发明 payload。

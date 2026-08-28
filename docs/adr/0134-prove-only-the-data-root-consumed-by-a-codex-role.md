# ADR 0134：只证明 Codex role 实际消费的数据根

状态：已接受

共享 Codex workspace 曾同时打开并冻结 Literature 与 Knowledge 两个 authoritative root，以便证明 attempt namespace 与两者隔离；但 Context command 合同要求只对当前操作实际消费的 Data Root 执行 physical gate。两者冲突会让 Literature Reader 因未消费的 Knowledge root 缺失而提前阻塞，也会让 Knowledge Answerer 对 Literature root 产生同类耦合。

每个 sealed attempt workspace 现在必须绑定唯一 role，并且只携带该 role 实际消费的 authoritative root proof：`literature_reader_v1`只打开 Literature root，`knowledge_answerer_v1`只打开 Knowledge root。Plan formation 与 child commitment 仍对 attempt root、项目根、`CODEX_HOME`及该 role-owned root执行完整物理隔离和 identity 复验；未消费 Context 的配置值只经过共享 lexical invariant，不被 workspace 或 child 打开、探测或记录 identity。若未来一个新 role 确实需要同时消费多个 Context，必须通过新的版本化决策显式声明 root capability 集，不能重新把所有已配置 root 作为通用前置条件。

# 将 Knowledge Ask 可观察性保持在领域结果之外

`knowledge ask` 的可观察表面由三个 command-owned projection 组成：从同一冻结 retrieval snapshot 和同一份 immutable measured Retrieval View bytes 构造的 `RetrievalAuditV1` 资产、从已锁存 recovery/attempt facts 构造的 supplemental diagnostics，以及从 sealed command state 构造的 Human presentation candidate。三者不得改变 Candidate/Answer identity、既有领域语义、检索候选选择、primary diagnostic、outcome、result、commit 或 recovery 决策；`KnowledgeAskResultV1` 与 Answer manifest 的既有字段和状态矩阵因而保持不变。

“投影不改变领域结果”不表示投影可以缺失。`retrieval_audit.json` 是 P3 的必需资产，仍服从 Knowledge Answer 既有 materialization、terminal asset 与 recovery gate：Audit 自身形成失败、`within_limit` View 的同一 measured buffer 安装或交叉绑定失败，都映射到既有 `failed: retrieval_materialization_failed`；`too_large` 只禁止安装 View，不豁免 Audit。Supplemental projection failure 只表示完整公开 error surface 无法表示：它不得伪装成 `orphan_scan_failed`，也不得改写已确定的 primary、outcome、result 或 commit，但会阻止 JSON/Human 完整 presentation，并进入封闭的 pre-I/O no-output terminal seam。

Audit builder、supplemental builder 与 Human renderer 各自提供窄的全值或 typed-verdict interface，command adapter 只负责按固定顺序组合，并让正常 mode candidate 或 no-output failure candidate 参加同一个 generation/seal 竞争。成功 seal 后必须先完成全部适用 command-owned resource settle、cancellation zero-in-flight 与 source release；只有到达 `RELEASED` 才可 presentation。JSON 的既有 ADR 0107–0109 serialization/binary-writer failure 保持不变；共同的 diagnostic projection failure 与 Human 的封闭 pre-I/O failure 则都以空 stdout、空 stderr 和恰好一次 `os._exit(1)` 结束，不生成 diagnostic、fallback、日志或持久事实。

任何已经产生 Human 前缀的 write/console failure 都不得回退 JSON、追加 diagnostic、重写 Answer 或伪造正常 exit；未被 typed union 接受的 `MemoryError`、`AssertionError`、`KeyboardInterrupt`、`SystemExit`、I/O/实现异常与未知异常保持既有矩阵之外。该限制以不为 exotic endpoint 提供统一错误 envelope 为代价，保证 partial output 不污染 sealed command state，也不会让调用方把 presentation receipt 误认成 Answer commit acknowledgment。

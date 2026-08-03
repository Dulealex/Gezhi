# 将 knowledge.ask 结果建模为两字段提交收据

`command="knowledge.ask"` 在 `gezhi.cli_result.v1` 下的 concrete `result` interface 固定为 `KnowledgeAskResultV1`。只有本次 invocation 在历史 staging 扫描结束后生成自己的新 `answer_id`，并成功完成该新 Answer 的 non-replacing 同卷目录 rename，outer `result` 才是非 `null` object；该 object 必须且只能包含两个 required key，root `additionalProperties=false`：

~~~json
{
  "answer_id": "ans_550e8400-e29b-41d4-a716-446655440000",
  "answer_output": null
}
~~~

`answer_id` 必须是既有 40-byte ASCII `ans_<lowercase UUIDv4>` 身份，逐 byte 等于本次 expected ID、新 committed Answer 的目录 basename 与 terminal manifest `answer_id`。`answer_output` 必须是完整 `AnswerOutputV1` JSON object 或 JSON `null`；两个 key 都不能缺失、为别名或增加第三个 key。

Presence matrix 唯一固定为：

| 本次 `knowledge.ask` 的新 Answer | terminal manifest `status` | outer `outcome` | outer `result` | `result.answer_output` |
|---|---|---|---|---|
| 目录 commit 成功 | `succeeded` | `succeeded` | `KnowledgeAskResultV1` object | 完整且已验证的 `gezhi.answer_output.v1` object |
| 目录 commit 成功 | `blocked` | `blocked` | `KnowledgeAskResultV1` object | `null` |
| 目录 commit 成功 | `failed` | `failed` | `KnowledgeAskResultV1` object | `null` |
| 目录 commit 成功 | `interrupted` | `interrupted` | `KnowledgeAskResultV1` object | `null` |
| 没有目录 commit 成功 | 不存在或只在 staging | 按 ADR 0093 为 `blocked`、`failed` 或 `interrupted`；禁止 `succeeded` | `null` | 不存在 |

`succeeded` 行同时包含 semantic `answer_status=answered` 与 `answer_status=insufficient_evidence`；不得把正常证据不足降为 `null`、`blocked` 或失败 diagnostic。非 `succeeded` committed Answer 按既有原子资产矩阵禁止拥有 `answer_output.json`，所以不能伪造空 object、失败版 AnswerOutput、历史输出或 staging 中看似完整的值。

非 `null` `answer_output` 是本次 commit 所绑定 `answer_output.json` 的完整规范 JSON value，不是原始 JSON string、部分字段投影、Markdown、文件路径或重新生成的摘要。下式中的 `canonical_json(value)` 精确等于 `json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")`；它必须满足：

~~~text
canonical_json(result.answer_output) + LF
==
committed target 中 answer_output.json 的实际 bytes
~~~

该正式文件还必须通过 `gezhi.answer_output.v1` 的完整验证，并与 terminal manifest 中对应 asset 的 `byte_length` 与 SHA-256 相等。不得从 `answer.md`、Codex final text、events、历史 Answer 或内存近似副本重新构造。既有 `answer_output.json` 32,768-byte cap 继续约束正式资产；后续 [ADR 0107](./0107-seal-one-bounded-immutable-knowledge-ask-json-buffer.md) 已独立冻结 CLI outer 含末尾 LF 的 65,536-byte cap，并以 `32,767 + 16,384 + 187 = 49,338` bytes 证明当前任一合法 `knowledge.ask` envelope 都可容纳，因此本 result 合同不再受 stdout 容量待决项阻塞。

Result object 的存在是一张本次新 Answer 已完成 process-level logical commit 的机器收据，不是断电 durability 或 exactly-once acknowledgment 承诺。只有完整验证通过且包含规范末尾 LF 的 envelope 中该 object 才构成 stdout acknowledgment，并证明目录 rename 已先返回成功；可解析但缺少 LF 的 JSON、空 stdout 或 partial stdout 都不是 acknowledgment，也不能反向证明 Answer 未提交。Commit 后发生 envelope/stdout failure 或进程崩溃不得回滚或改写 Answer；若 [ADR 0108](./0108-return-1-for-controlled-knowledge-ask-json-presentation-failure.md) 的 completed presentation failure 后调用方仍收齐并验证 exact full buffer（包括 LF），该 receipt 也不因随后 `os._exit(1)` 而撤销。当前没有 idempotency key，调用方在无 acknowledgment 后直接重试可能生成第二个新 Answer。

启动时补交的旧 orphan Answer 永远不是本次新 Answer：仅补交旧 orphan 时 `result=null`；随后本次新 Answer 也提交时，result 只使用新 ID，旧 orphan 只能进入后续 diagnostics。Busy、pre-answer failure、manifest/rename failure、target conflict、仅在 staging 中生成的 ID 或锁存的 terminal cause 都不能成为本次 result。用户取消只有在 `interrupted` Answer 已成功 commit 后才得到 object 加 `answer_output=null`；ADR 0098 的同一 cancellation latch 在 atomic pre-ID barrier 先赢时，只形成 no-commit interruption 候选并保持 `result=null`，最终 outcome 由 ADR 0097 的 `failed > interrupted > blocked` 选择。`answer_id` 一旦成功生成、验证并锁存，安全取消必须尝试提交 interrupted Answer；terminalization/commit 失败仍为 `result=null`，但 outcome 是 no-commit `failed` 或不进入正常矩阵，不能借取消改成 no-commit `interrupted`。

`result` 不复制 outer `outcome`、manifest `status/error`、`answer.md`、Question、Retrieval View、路径、asset 清单/哈希、时间、provenance、attempt、usage、orphan 列表或 `committed` flag。Human adapter 可以展示已提交 `answer.md`；JSON adapter 只返回稳定语义 object 与 Answer 身份。错误解释和附属现场使用 ADR 0091 的共享 `diagnostics[*]` item；ADR 0092 已冻结 committed Answer 的 15+1 primary，ADR 0093 已冻结 no-commit outcome/result 分类与正常 JSON exit，ADR 0094、ADR 0095 与 ADR 0096 已分别冻结 no-commit blocked、failed 与 interrupted primary/context，ADR 0097 已冻结跨 outcome 静态优先级，ADR 0098 已冻结 cancellation/identity cutover，ADR 0099 已冻结 `NoCommitSafeBoundaryV1`。Supplemental mappings 仍待冻结，任何诊断都不能塞入这两个 result 字段。

`KnowledgeAskResultV1` 的 wire identity 由 `(schema_version="gezhi.cli_result.v1", command="knowledge.ask")` binding 与本 ADR 的封闭两字段 Schema 共同确定；不增加第三个 result-level version key。`answer_output` 自己的 `gezhi.answer_output.v1` 独立版本身份必须保留。以后若改变 result 字段、类型、nullability、commit presence matrix 或接受的 AnswerOutput generation，必须建立具有新 wire discriminator 的 concrete binding，例如升级 outer major 或使用新的 command identifier；不能在同一 pair 下静默演进。

Knowledge command adapter 负责构造并验证该 result 与跨字段矩阵，共享 CLI JSON writer 仍只验证五字段 outer、JSON 可编码性和 channel/serialization 约束。本决策不改变 Answer commit point、manifest、持久资产、Human 文案、diagnostic item、exit code、依赖、配置或模型调用。

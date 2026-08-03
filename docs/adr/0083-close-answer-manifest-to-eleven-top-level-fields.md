# 封闭 Answer manifest 的十一字段顶层 envelope

每个已经形成的 Knowledge Answer terminal `manifest.json` 根值必须是 JSON object，并且必须且只能包含以下十一项顶层 key；十一项在 `succeeded`、`blocked`、`failed`、`interrupted` 以及零 Candidate 分支中全部 required，root `additionalProperties=false`，不得条件省略、提供默认值或接受别名：

```text
schema_version
answer_id
status
error
started_at
finished_at
elapsed_ms
provenance
attempts
usage_totals
assets
```

`schema_version` 必须精确为 `gezhi.answer_manifest.v1`；其余十项的类型、范围、封闭子结构、条件矩阵与跨资产不变量继续由既有 ADR 分别拥有。在这十一个顶层 value 中，只有 `error` 的 Schema 允许 JSON `null`，并且只能按既有矩阵在 `succeeded` 与 `interrupted` 时为 `null`；`blocked` 与 `failed` 时它是封闭两字段 object。这个限定不禁止既有嵌套 nullable value，例如 unborn Git revision、attempt 的条件式 exit/failure/token 字段以及 `usage_totals` 的独立 nullable 成员。

`attempts` 顶层自身始终是非 `null`、长度 0–3 的 array，`usage_totals` 顶层自身始终是非 `null` 的封闭 object，`assets` 顶层自身始终是非 `null` array 且至少包含 P0 `effective_config.json`；除 `error` 外的其余顶层 value 也全部非 `null`。全部字段只在已经形成 terminal manifest 时必填；`answer_id` 生成前的阻塞，或完整 terminal manifest 形成前的进程崩溃，可以没有合法半成品 manifest，不得为满足闭包伪造终态；若字面 manifest 已存在，其有效性只由共享 reader 与恢复合同裁决。

顶层字段集合没有语义顺序。ADR 0082 的 `sort_keys=True` 单独决定规范文件中的实际 key 顺序为 `answer_id`、`assets`、`attempts`、`elapsed_ms`、`error`、`finished_at`、`provenance`、`schema_version`、`started_at`、`status`、`usage_totals`；它不排序任何 array，`assets` 与 `attempts` 继续服从各自领域顺序。

V1 不得增加 `answer_status`、`semantic_status`、`terminal_status`、顶层 `stage`、`attempt_count`、顶层 `usage_unavailable`、cost/currency、配置副本或哈希、额外身份/时间、provider/session/request ID、overflow latch 或外部诊断。以后确需新增顶层字段时必须升级 Answer manifest Schema；本次 invocation 的诊断载体已由 ADR 0089 放在外部 CLI outer，共享 item/profile 已由 ADR 0091 冻结，committed primary subset 已由 ADR 0092 冻结，剩余 Knowledge variants 仍待冻结且任何 CLI diagnostic 都不能成为第十二个 key。若以后需要持久诊断，必须另行批准版本化资产或新 Schema。

本决定只关闭现有字段集合，不新增依赖、资产或字段，也不改变任何字段既有语义。Manifest raw-byte cap 已由 ADR 0084 冻结，asset `byte_length` 范围已由 ADR 0085 冻结，有界 parser profile 已由 ADR 0086 冻结，direct exclusive-create leaf formation 已由 ADR 0087 冻结，V1 不承诺断电 durability 的边界已由 ADR 0088 冻结；ADR 0089 已冻结 invocation-local diagnostic outer，ADR 0091 已冻结共享 item/profile，ADR 0092 已冻结 committed primary subset，剩余 Knowledge variants、Human 映射与持久诊断仍待后续批准。

# Knowledge Ask Result v1 合同

状态：已冻结。该合同只定义 `command="knowledge.ask"` 在 `gezhi.cli_result.v1` 下的 `result`；共享 outer 见 [CLI JSON v1](./cli-json-v1.md)，决策依据见 [ADR 0090](../adr/0090-use-a-two-field-commit-receipt-for-knowledge-ask-results.md)，committed primary 与两种 commit presence 下的 outcome/normal-exit 见 [Knowledge Ask Diagnostics v1](./knowledge-ask-diagnostics-v1.md)，no-commit 分类与 blocked/failed/interrupted primary 分别见 [ADR 0093](../adr/0093-classify-uncommitted-knowledge-ask-outcomes-by-terminal-cause.md)、[ADR 0094](../adr/0094-freeze-uncommitted-blocked-knowledge-ask-primary-diagnostics.md)、[ADR 0095](../adr/0095-freeze-uncommitted-knowledge-ask-failed-primary-diagnostics.md) 和 [ADR 0096](../adr/0096-freeze-uncommitted-knowledge-ask-interrupted-primary-diagnostic.md)，跨 outcome 静态优先级见 [ADR 0097](../adr/0097-prioritize-uncommitted-knowledge-ask-outcomes-as-failed-interrupted-blocked.md)，cancellation 与 Answer identity cutover 见 [ADR 0098](../adr/0098-use-one-cancellation-latch-and-an-atomic-pre-id-barrier.md)，no-commit drain/cleanup 与安全后置条件见 [ADR 0099](../adr/0099-prove-no-commit-safety-with-a-zero-live-resource-ledger.md)，pre-seal JSON buffer/cap 见 [ADR 0107](../adr/0107-seal-one-bounded-immutable-knowledge-ask-json-buffer.md)，controlled presentation hard fail-stop 见 [ADR 0108](../adr/0108-return-1-for-controlled-knowledge-ask-json-presentation-failure.md)，exact Windows stdout primitive 见 [ADR 0109](../adr/0109-use-binary-fd1-and-blocking-os-write-for-knowledge-ask-json.md)，Answer 身份见 [ADR 0061](../adr/0061-bind-answer-id-in-the-manifest-to-the-directory.md)，嵌套语义对象见 [Knowledge Answerer v1](./knowledge-answerer-v1.md)。

Final result 与 outcome/diagnostics 的共同 seal、handled cancellation window 封闭及 presentation cutover 见 [ADR 0100](../adr/0100-seal-the-handled-cancellation-window-before-presentation.md)。

No-source lifecycle 与 never-registered release proof 见 [ADR 0104](../adr/0104-continue-with-a-no-source-cancellation-profile-when-capability-is-absent.md)；debugger-present selection 见 [ADR 0105](../adr/0105-use-the-no-source-profile-when-the-current-process-is-being-debugged.md)。

## 封闭 Schema

`KnowledgeAskResultV1` 必须是恰好包含以下两个 required key 的 JSON object，`additionalProperties=false`：

| field | required rule |
|---|---|
| `answer_id` | 非 `null` 40-byte ASCII string；满足既有 `ans_<lowercase UUIDv4>` 规则，并逐 byte 等于本次 expected ID、新 committed Answer 的目录 basename 与 terminal manifest `answer_id` |
| `answer_output` | 完整 `AnswerOutputV1` object 或 `null` |

两个 key 不得缺失、改名或增加第三项。成功且证据不足的合法示例为：

~~~json
{
  "answer_id": "ans_550e8400-e29b-41d4-a716-446655440000",
  "answer_output": {
    "answer_status": "insufficient_evidence",
    "answer_units": [],
    "insufficiency_reason": "no_matching_candidates",
    "qualification_units": [],
    "schema_version": "gezhi.answer_output.v1"
  }
}
~~~

## Commit 与 presence matrix

| current invocation state | outer `outcome` | outer `result` | `answer_output` |
|---|---|---|---|
| 本次新 Answer 的目录 rename 成功，manifest `status=succeeded` | `succeeded` | 两字段 object | 完整 `gezhi.answer_output.v1` object |
| 本次新 Answer 的目录 rename 成功，manifest `status=blocked` | `blocked` | 两字段 object | `null` |
| 本次新 Answer 的目录 rename 成功，manifest `status=failed` | `failed` | 两字段 object | `null` |
| 本次新 Answer 的目录 rename 成功，manifest `status=interrupted` | `interrupted` | 两字段 object | `null` |
| 本次没有新 Answer 目录 commit | 按 ADR 0093 为 `blocked`、`failed` 或 `interrupted`；禁止 `succeeded` | `null` | 不存在 |

完整 result object 的 presence 当且仅当本次 invocation 在历史 staging 扫描结束后自己生成的新 `answer_id` 已完成 non-replacing 同卷目录 rename。旧 orphan 在启动扫描中被补交、历史对象被读取、`answer_id` 只在 staging 中生成或 terminal cause 已锁存但目录 rename 未成功，都不能满足该条件。Busy、pre-answer failure、manifest/rename failure 和 target conflict 一律没有 result object；共享 diagnostic item/profile 已由 ADR 0091 冻结，committed Answer 的 15+1 primary 已由 ADR 0092 冻结，无 committed Answer 的 outcome、`result=null`、`succeeded` 禁令与正常 JSON exit 已由 ADR 0093 冻结，no-commit blocked 的 11 项 primary/context 与 blocked 内部仲裁已由 ADR 0094 冻结，no-commit failed 的 7 项 primary/context 已由 ADR 0095 冻结，no-commit interrupted 的唯一 primary 已由 ADR 0096 冻结，跨 outcome 静态优先级已由 ADR 0097 冻结，cancellation/identity cutover 已由 ADR 0098 冻结，no-commit `NoCommitSafeBoundaryV1` 已由 ADR 0099 冻结；supplemental variants 后续冻结。

`result.answer_output` 非 `null` 当且仅当该 committed manifest 为 `status=succeeded`。该行同时允许 `answer_status=answered` 与 `answer_status=insufficient_evidence`；后者仍是正常成功。

## AnswerOutput 同一性

`result` 非 `null` 且 `outcome=succeeded` 时，`answer_output` 必须是本次 committed `answer_output.json` 的完整、严格验证、规范 JSON value。下式中的 `canonical_json(value)` 精确等于 `json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")`；它必须满足：

~~~text
canonical_json(result.answer_output) + LF
==
committed answer_output.json bytes
~~~

正式 bytes 同时必须匹配 terminal manifest 记录的 `byte_length` 与 SHA-256，且 `schema_version="gezhi.answer_output.v1"`。不得：

- 返回 raw JSON string、`answer.md`、路径或只含 `answer_status` 的摘要；
- 删除、增加、重排语义 array item，或重新生成/改写字符串；
- 从 Codex raw capture、历史 Answer、Retrieval View、staging 临时文件或内存近似副本回退构造；
- 把 `insufficient_evidence` 映射为 `null` 或运行失败。

`blocked`、`failed` 与 `interrupted` 时，正式结果对按 Answer 合同禁止存在，`answer_output` 必须精确为 `null`。即使 `final_message.txt` 或 staging 中有看似合法 JSON，也不得建立带 `error` 的 AnswerOutput 变体或暴露该内容。

## Orphan、acknowledgment 与非所有权

Recovery rename 不算本次新 Answer commit。若先补交旧 orphan、随后本次新 Answer 提交，result 只引用新 ID；旧 orphan 只能由 diagnostics 报告且不能改变 result/outcome。只有 interactive profile 在 `ACCEPTING` 已 accepted 的 Ctrl+C 才能设置 ADR 0098 的同一 cancellation latch；no-source profile 没有 latch 写入者。取消后的 result 由本次新 Answer 最终是否 commit 决定，不能由 callback 或 observation 单独决定。

ADR 0100 seal 先赢后，`result` 已不可变；后到 Ctrl+C 无权把 committed receipt 改成 `null`、把 `null` 改成 receipt、回滚 commit 或建立新的 interrupted result。Presentation 前必须完成所选 profile 的 zero-in-flight 与 source-specific release proof 并进入 `RELEASED`：interactive profile 排空 accepted callback 并移除 matching registration，no-source profile 则证明 `source=none`、accepted-in-flight 为零且 registration 从未建立，不调用 removal。

包含规范末尾 LF、完整可验证 envelope 内的非 `null` result 是 rename 已成功的 process-level acknowledgment，但不承诺 ADR 0088 明确排除的 power-loss durability，也不承诺 stdout 与 commit 原子或 exactly once。仅“可解析”却缺少 LF、空或 partial stdout 都不是本合同的 acknowledgment，也不能证明未提交。Commit 后 envelope 构造、序列化、stdout 写出失败或进程崩溃不得回滚 Answer；若操作系统最终仍交付并由调用方验证 exact full envelope，则该 receipt 不因随后 `os._exit(1)` 或异常终止而撤销。当前无 idempotency key，无 acknowledgment 后重试可能创建第二个 Answer。

Result 不拥有或复制 outer `outcome`、manifest `status/error`、diagnostics、Question、Retrieval、`answer.md`、路径、asset 元数据、时间、provenance、attempt 或 usage。`answer_id` 是定位与审计身份；`answer_output` 是本次已提交正式资产的临时机器语义投影，不是第二持久事实源。Human renderer 继续使用已提交的 `answer.md`。

## 版本与实现 seam

该 Schema 绑定于 `(gezhi.cli_result.v1, knowledge.ask)`；`answer_output` 保留独立的 `gezhi.answer_output.v1`。改变两字段闭包、类型、nullability、presence matrix 或接受的 AnswerOutput generation 必须建立具有新 wire discriminator 的 concrete binding，不能复用当前 pair。

Knowledge command adapter 在越过 presentation seam 前验证 result、规范 AnswerOutput bytes/manifest binding 与全部矩阵；共享 JSON preparation/writer 不解释 Answer、manifest 或 commit，只负责 outer、JSON 可编码性、确定性 serialization、cap 与 stdout。ADR 0107 已用 `A + D + 187 <= 49,338` bytes 的保守上界证明当前最大合法 AnswerOutput、diagnostics 与 outer 可同时被 65,536-byte inclusive cap 容纳，因此本合同已不再受 stdout 容量待决项阻塞。

每个 coherent generation 的完整 envelope 在 ADR 0100 conditional seal 前恰好整体序列化一次，并与 candidate token、exact result/triple、presentation disposition、byte length 一起绑定；callback 先赢时整个 candidate 作废重建，seal 成功后不得重新读取 AnswerOutput 或重新序列化。Writer 只在 `RELEASED` 后消费 `READY_BYTES` 的 exact buffer，并按 ADR 0109 使用一次 direct binary `setmode` 与 direct blocking `os.write` whole-suffix loop；`NO_OUTPUT_PRESENTATION_FAILURE` 恰好写零 bytes 并按 ADR 0108 无 cleanup/flush 地 `os._exit(1)`，完成状态确定的 setup/write failure 也相同。Presentation 期间的外部/default Ctrl+C 可以造成零字节或 exact prefix，但不能触发重算、fallback 或由 Gezhi 选择应用级 normal-return `130`；external termination、pending I/O 与 seal/release proof failure 不被 ADR 0108 改写，外部/default termination 的数值仍可能偶合 `1` 或 `130`。

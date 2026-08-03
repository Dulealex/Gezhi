# CLI Diagnostics v1 合同

No-commit `failed` 的完整 primary union 已由 ADR 0095 闭合为 `knowledge.ask.pre_answer_formation_failed.v1`、`knowledge.ask.data_root_integrity_lost.v1`、`knowledge.ask.orphan_scan_failed.v1`、`knowledge.ask.answer_staging_failed.v1`、`knowledge.ask.answer_manifest_failed.v1`、`knowledge.ask.answer_target_conflict.v1` 与 `knowledge.ask.answer_commit_failed.v1` 七项，`context` 都必须为 `{}`；七项只能作为 `outcome=failed`、`result=null` 的 primary，不能作为 blocked、committed 或 supplemental item。No-commit `interrupted` 的唯一 primary 已由 ADR 0096 冻结为 `knowledge.ask.user_interrupted_before_answer.v1`，`context={}`，且只允许配 `outcome=interrupted` 与 `result=null`。

状态：共享 item、数组角色、排序、容量、omission 与隐私 profile 已冻结；`knowledge.ask` committed Answer 的 15+1 primary subset、no-commit 的 outcome/result/正常 JSON exit，以及 no-commit `blocked` 的 11 项、`failed` 的 7 项与 `interrupted` 的 1 项 primary/context 已由 [Knowledge Ask Diagnostics v1](./knowledge-ask-diagnostics-v1.md) 冻结，blocked 内部 fail-fast 仲裁、跨 outcome 静态优先级、cancellation latch/checkpoints、atomic pre-ID barrier 与 `NoCommitSafeBoundaryV1` 也已冻结。ADR 0108 另行冻结 controlled `knowledge.ask --json` presentation failure 为不生成 diagnostic 的静默 `os._exit(1)`；[ADR 0116](../adr/0116-return-2-with-one-fixed-stderr-line-for-raw-argv-resource-violation.md) 另行冻结同样不生成 diagnostic 的 raw argv resource violation 为 fixed stderr/empty stdout/exit `2`。全部 supplemental variants、其他 command union、Human 文案/exit、其余 bootstrap/internal/argument exit 与 ADR 0108 排除的 presentation failure 仍分别待冻结。决策依据见 [ADR 0091](../adr/0091-use-two-field-code-discriminated-cli-diagnostics.md)、[ADR 0092](../adr/0092-map-committed-knowledge-ask-outcomes-to-primary-diagnostics-and-exit-codes.md)、[ADR 0093](../adr/0093-classify-uncommitted-knowledge-ask-outcomes-by-terminal-cause.md)、[ADR 0094](../adr/0094-freeze-uncommitted-blocked-knowledge-ask-primary-diagnostics.md)、[ADR 0095](../adr/0095-freeze-uncommitted-knowledge-ask-failed-primary-diagnostics.md)、[ADR 0096](../adr/0096-freeze-uncommitted-knowledge-ask-interrupted-primary-diagnostic.md)、[ADR 0097](../adr/0097-prioritize-uncommitted-knowledge-ask-outcomes-as-failed-interrupted-blocked.md)、[ADR 0098](../adr/0098-use-one-cancellation-latch-and-an-atomic-pre-id-barrier.md)、[ADR 0099](../adr/0099-prove-no-commit-safety-with-a-zero-live-resource-ledger.md)、[ADR 0108](../adr/0108-return-1-for-controlled-knowledge-ask-json-presentation-failure.md) 与 [ADR 0116](../adr/0116-return-2-with-one-fixed-stderr-line-for-raw-argv-resource-violation.md)，outer 见 [CLI JSON v1](./cli-json-v1.md)。

Diagnostic set 只有在 [ADR 0100](../adr/0100-seal-the-handled-cancellation-window-before-presentation.md) 的 final command-state seal 中与 `outcome`、`result` 一起锁存后才是可呈现终态；seal 后 callback 不得增加、删除、重排或重分类 item。Presentation 只能在所选 cancellation profile 的 zero-in-flight 与 source-specific release proof 完成并进入 `RELEASED` 后开始。

[ADR 0101](../adr/0101-use-a-project-owned-native-win32-ctrl-c-bridge.md) 已冻结 interactive profile 的项目自有 native Win32 DLL、C-only handler、generation-checked conditional seal 与主线程 Python adapter；[ADR 0104](../adr/0104-continue-with-a-no-source-cancellation-profile-when-capability-is-absent.md) 已冻结 no-source profile 的零 drain 与 never-registered release proof，[ADR 0105](../adr/0105-use-the-no-source-profile-when-the-current-process-is-being-debugged.md) 已冻结 debugger-present selection fact 本身不得新增、删除或改写 diagnostic。[ADR 0106](../adr/0106-run-command-owned-children-without-a-console.md) 冻结的 Codex attempt-root launch profile、stdio/handle allowlist、Job assignment 与 root exit 同样只是内部 lifecycle 事实，本身不新增、删除或改写 diagnostic。[ADR 0107](../adr/0107-seal-one-bounded-immutable-knowledge-ask-json-buffer.md) 把本合同最多 16,384-byte 的完整 diagnostics array 原样计入 `knowledge.ask` 的 65,536-byte stdout cap；它不改变 item/array cap、omission 或 diagnostic 语义。[ADR 0108](../adr/0108-return-1-for-controlled-knowledge-ask-json-presentation-failure.md) 明确 serialization/cap/setup/completed-write presentation failure 不新增 diagnostic、不改写原集合，只在严格 terminal seam 选择 `os._exit(1)`。共享 diagnostic item 不读取 cancellation profile state、selection reason、Codex attempt-root isolation 或 presentation failure state；后续独立成立的领域 outcome 仍必须按既有 presence matrix 形成自己的 primary/supplemental 集合。

## CliDiagnosticItemV1

每个 item 必须且只能包含两个 required key：

~~~json
{
  "code": "knowledge.ask.example.v1",
  "context": {}
}
~~~

| field | shared rule |
|---|---|
| `code` | 1–96 bytes lowercase ASCII dotted、显式版本化 identifier；具体 segment grammar 与 enum 由 command-owned 合同冻结 |
| `context` | 非 `null`、code-owned、封闭 JSON object；无参数时为 `{}` |

Item root 与每个 concrete context 均 `additionalProperties=false`。Concrete command 必须用有限 discriminated union 枚举所接受的完整 code versions，并为每个 code 固定角色、context keys、required/optional matrix、类型、范围、array 规则与跨字段约束。Code 必须来自该静态 enum，不能从路径、异常或其他运行时字符串动态生成；未知 code、旧 code 的新解释、同 code 的另一 context shape 或额外字段一律无效。

`context` 最多 8 个 member。字段值只允许该 code 明确批准的 JSON boolean、非负 JSON integer、受控 ASCII enum、严格验证的稳定 ID，或最多 8 项且每项均属于这些安全 scalar 的 array；boolean 不能充当 integer。V1 禁止 `null`、float、负数、nested object、nested array、任意键值袋与自然语言自由文本。每个 concrete code 必须进一步冻结字段类型与上界，以及 array 的元素类型、空值、unique 与排序规则。公共 V1 不额外冻结统一的整数上界、字符串长度或 segment grammar。

`role`、`severity`、`stage`、`message`、`remediation`、`details` 和 item-level `schema_version` 都不是 V1 字段。`code` 的 `.vN` 版本化该 variant 的语义、角色和 context Schema。

## Array 与 outcome 矩阵

| outer outcome | required array role |
|---|---|
| `succeeded` | `diagnostics` 可为 `[]`；若非空，全部为 supplemental |
| `blocked` | 非空；index 0 是唯一 primary，其余 supplemental |
| `failed` | 非空；index 0 是唯一 primary，其余 supplemental |
| `interrupted` | 非空；index 0 是唯一 primary，其余 supplemental |

Primary 不由 item 字段重复表示。Concrete command 必须静态冻结每个 code 允许的 outcome/position 与 supplemental code 集合；若同一 code 可处在不止一种派生角色，必须逐项显式列出，不能由实现临时决定。Supplemental 不改变 outcome、result、commit、manifest 或 recovery。

同一 code 每次 invocation 最多一个 item。重复领域事实由 command adapter 在越过 presentation seam 前聚合进该 code 的 context；若需要出现次数，必须使用该 code 明确批准的 `count` 字段。非 omission supplemental items 按 code ASCII bytes 严格升序；primary 固定在前，不参加该排序。

## 规范容量

Item 与 array 使用 CLI outer 相同的 Python 3.11 canonical JSON 参数计算，但不添加 LF：

~~~python
json.dumps(
    value,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
~~~

每个 item 必须不超过 1,024 bytes。完整 `diagnostics` array 包含 brackets 与 commas，必须不超过 16,384 bytes；array 最多 16 items。三个上界均为 inclusive。

Command-owned constructors 必须先完成 code/context Schema、单项 cap 与同 code 聚合。共享 `DiagnosticSetV1` module 随后：

1. 验证 outer outcome 所需的 primary presence；
2. 保留 primary 并按 code 排序 supplemental；
3. 若完整数组同时符合 count/byte caps，直接返回；
4. 否则从已排序 supplemental 的尾部省略 items，保留可与 primary 和 omission item 一起满足 caps 的最长 prefix，并把 omission item 放在最后；`succeeded` 没有 primary，prefix 直接从 supplemental 开始。

Omission item 精确为：

~~~json
{
  "code": "cli.diagnostics_omitted.v1",
  "context": {
    "count": 1
  }
}
~~~

Omission `context` 必须且只能有 required `count`，`additionalProperties=false`。`count` 必须是 `1..9223372036854775807` 的 JSON integer 且不能是 boolean，表示聚合后省略的 supplemental item 数量。为 omission item 腾出位置而额外放弃的 item 也计入；primary 与 omission item 自身不计入。Primary 永不省略。Command adapter 不得自行发出该保留 code；它永远是 supplemental、永不改变 outcome，并且是 supplemental ASCII 排序的唯一末尾例外：不参加排序，存在时无条件最后，即使在 `succeeded` 中位于 index 0 也不成为 primary。选择最长前缀时必须按已经排序的完整 supplemental 序列计算，不能按大小、观察时间或实现容器顺序择优。

单个 concrete item 不合法或超过 1,024 bytes 不能通过 omission 抢救；禁止截断/删除 context、替换 code、重序列化成另一形状或追加 fallback JSON。每个 concrete code 合同必须把字段组合收窄到可证明所有合法 item 均不超过单项 cap。

## 隐私与 Human adapter

V1 不允许 JSON item 携带自然语言、路径、未验证名称、用户/文档内容、URL、命令行、环境/配置、秘密信息、异常/堆栈、进程/机器/用户身份、raw channel excerpt 或 provider/session/request identity。不得通过裁剪、哈希、base64 或转义把禁止内容伪装成安全 string。

每个 context 字段必须由 code-specific allowlist 证明为稳定 enum、常量/limit、受界 count、ordinal、channel 或先通过正式格式验证的 Gezhi opaque ID；非法 basename 不能借 opaque-ID 例外回显。具体 command 合同可以进一步收窄，不能放宽公共 profile。

Human renderer 直接消费同一个已验证 diagnostic set，并按 code/context 映射中文说明和处理建议；machine JSON 不保存 message 或 remediation。JSON writer 不拥有 code 选择、领域聚合、Human 文案或隐私清洗。

## 演进

公共 item/array/profile/cap/omission 变化需要新的 CLI outer generation。单个 variant 的 machine 语义、允许的 outcome/position 或 context Schema/上限变化需要新的 `.vN` code；新语义从新的 `.v1` code 开始。Code 本身是 concrete diagnostics 的嵌套 wire discriminator：每个 command 静态枚举自身 union，新增 code 显式扩展该 union，旧 concrete validator 对未知 code 安全拒绝；逐 code Human 中文措辞变化不要求升级 code。新增 Context 不改变公共 V1，只建立自己的 concrete union。

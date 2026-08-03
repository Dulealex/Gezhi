# 使用两字段 code-discriminated CLI diagnostics

所有进入 `CliResultEnvelopeV1` handled `--json` path 的公开命令共享一个 `CliDiagnosticItemV1` interface。每个 `diagnostics[*]` 必须是恰好包含 `code` 与 `context` 两个 required key 的 JSON object，item `additionalProperties=false`：

~~~json
{
  "code": "knowledge.ask.example.v1",
  "context": {}
}
~~~

该 JSON 只示意两字段形状，不冻结示例 code。`code` 必须是 1–96 bytes 的 lowercase ASCII dotted、显式版本化 identifier，例如以 `.v1` 结束。公共 profile 不能代替 concrete command 的静态封闭 code enum；只有该 command 合同列出的完整 code 才合法，不能从路径、错误文本或其他运行时字符串动态生成。每个 code version 唯一判别自身语义、允许角色与 `context` Schema。新语义使用新的 versioned code；改变既有语义或 context Schema 必须使用新的 code version，旧 code 不得重解释。Segment 数量、segment 级 grammar 与各 version 的具体 enum 不在本决策中额外冻结。

`context` 始终是非 `null` JSON object；无参数 code 精确使用 `{}`。每个 code-owned variant 必须关闭字段集合与 presence matrix，`additionalProperties=false`，最多 8 个 member。字段值只允许该 code 明确批准的 JSON boolean、非负 JSON integer、受控 ASCII enum、严格验证的稳定 ID，或最多 8 项且每项均属于这些安全 scalar 的 array；boolean 不能充当 integer。禁止 `null`、float、负数、嵌套 object、嵌套 array、任意键值袋与自然语言自由文本。每个 concrete code 必须进一步冻结字段类型与上界，以及 array 的元素类型、空值、唯一性与排序规则；公共 interface 不在本决策中追加统一的整数上界、字符串长度或 segment grammar。

Item 不保存 `role`、`severity`、`stage`、`message`、`remediation`、`details` 或 item-level `schema_version`。角色由 outer `outcome` 与数组位置唯一确定：

| outer `outcome` | primary diagnostic | supplemental diagnostics |
|---|---|---|
| `succeeded` | 不存在 | 全部 items |
| `blocked`、`failed` 或 `interrupted` | 恰好一个，固定为 `diagnostics[0]` | `diagnostics[1:]` |

因此 `diagnostics=[]` 只允许干净的 `succeeded` invocation；任一非 `succeeded` handled envelope 必须至少有一个 item。每个 code 允许出现的 outcome/position 与每个 command 的 supplemental code 集合由 concrete command 合同冻结；若同一 code 可处在不止一种派生角色，合同必须逐项显式列出，item 本身仍不增加 role。Supplemental item 不能改变 outer outcome、result、manifest、commit 或恢复裁决。一个 code 在同一 invocation 中最多出现一次；重复事实必须由 command-owned adapter 按该 code 的封闭 context 聚合，不能复制 items。

非 omission supplemental items 按 `code` 的 ASCII bytes 严格升序排列。`diagnostics` 最多 16 项；使用 ADR 0089 的 Python 3.11 规范 JSON profile 计算时，每个 item 的 canonical JSON bytes 不含 LF 且不得超过 1,024 bytes，完整 array 的 canonical bytes 包含 `[`、`]` 与逗号、不含 LF 且不得超过 16,384 bytes。边界值合法，超过任一上限均不能直接进入 envelope。

共享 `DiagnosticSetV1` module 只接受已经通过 concrete code/context Schema 的零或一个 primary 与已经按 code 聚合的 supplemental items。它禁止 command adapter 直接提供保留 code `cli.diagnostics_omitted.v1`，并按以下唯一算法形成有界数组：

1. 按 outer outcome 固定 primary presence，把 primary 保留在 index 0；supplemental 按 code ASCII bytes 升序。
2. 若完整候选同时满足 16-item 与 16,384-byte cap，原样输出且不生成 omission item。
3. 若任一 cap 超出，primary 永不省略；`succeeded` 没有 primary，直接从 supplemental 开始。从已排序 supplemental 的尾部省略 items，保留能够与 omission item 共同满足两个 cap 的最长前缀。
4. 最后一项固定为 `{"code":"cli.diagnostics_omitted.v1","context":{"count":N}}`，其 `context` 必须且只能有 required `count`；`N` 是 `1..9223372036854775807` 的 JSON integer、不能是 boolean，表示聚合后未进入 wire 的 supplemental item 数量。它不是原始异常、目录项或观察事件数量。该保留 item 是 supplemental、永不改变 outcome，并且是 ASCII 排序规则的唯一末尾例外；它不参加排序，存在时无条件位于最后，即使在 `succeeded` 中成为 index 0 也不成为 primary。

若为 omission item 预留一个槽位导致额外 supplemental item 被省略，这些项也计入 `N`；omission item 自身与 primary 不计入。Primary 或任一 concrete item 自身未通过 Schema/1,024-byte cap 属于构造失败，不能截断字段、改 code、把 context 清空、降级为 omission 或打印 fallback。每个 concrete code 合同必须把自身字段组合界定到可证明所有合法 item 均不超过 1,024 bytes，command-owned constructor 再在 presentation seam 前保证单项有效。共享 module 只负责集合级顺序、唯一性、容量与 omission，不解释领域事实。

JSON diagnostics 禁止携带自然语言 message/remediation、原始 Question 或文档内容、题名/作者/URL、绝对或相对路径、未验证 basename、argv、环境变量或配置值、秘密名称/值/存在性、exception type/text、stack、stdout/stderr/event excerpt、PID、用户名/主机身份、provider/session/request/thread ID 及其他未被 code Schema 明确允许的内容。允许值必须来自稳定枚举、合同常量/上限、受界计数、attempt ordinal、capture channel 或先通过正式格式验证的 Gezhi opaque ID；非法 basename 不能借 opaque-ID 例外回显。不得把不可信字符串裁剪、散列或编码后绕过禁令。

Human renderer 与 JSON writer 继续是同一 command outcome seam 上的两个 adapter。Human renderer 根据已验证 `code + context` 生成中文说明与处理建议，不从 JSON stdout 反解析，也不把自然语言写回 machine result；逐 code 文案映射后续单独冻结。共享 writer 仍只拥有 outer、JSON 可编码性、确定性 serialization 与 stdout，不能选择 code、聚合领域事实或修复 diagnostics。

改变两字段 item、公共 context profile、角色/位置语义、排序、唯一性、容量或 omission 算法必须升级 CLI outer generation。改变某一 code 的 machine 语义、允许的 outcome/position 或 context Schema 必须使用新的 code version；新语义使用新的 `.v1` code。Code 本身是 concrete diagnostics 的嵌套 wire discriminator，新增 code 会显式扩展该 command 的静态 union，旧 concrete validator 对未知 code 安全拒绝；逐 code Human 中文措辞变化不要求升级 code。Literature、Knowledge 与未来 Bot 复用公共 interface 与 shared omission code，但各自静态拥有 concrete code/context union。本决策本身不冻结任何 `knowledge.ask` code/outcome/exit-code 映射；后续 ADR 0092 冻结其 committed primary subset 与正常 committed JSON exit，ADR 0093 冻结 no-commit outcome/result 分类与正常 JSON exit，ADR 0094、ADR 0095 与 ADR 0096 分别冻结 no-commit blocked、failed 与 interrupted primary/context，ADR 0097 冻结跨 outcome 静态优先级，ADR 0098 冻结 cancellation/identity cutover，ADR 0099 冻结 no-commit drain/cleanup 安全证明，ADR 0107 在不改变本 `16,384`-byte diagnostics array cap 的前提下冻结 `knowledge.ask` 完整 stdout cap 与 buffer，ADR 0108 则明确可控 JSON presentation failure 静默 exit `1` 且绝不新增 diagnostic。Human 文案/exit、supplemental variants、bootstrap/argument 与其余 presentation failure exit、持久诊断资产、依赖、配置或模型调用仍不在本决策范围。

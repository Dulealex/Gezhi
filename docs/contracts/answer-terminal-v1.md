# Answer Terminal v1 合同

状态：冻结 Knowledge Answer v1 的根级资产 identity、逐路径与整目录读取预算、terminal authority、无 current pointer 约束、正式 target / 同身份 staging 双件矩阵、orphan 补交、原地逻辑隔离与 rename 不确定结果边界。本合同不改变 Answer manifest Schema、`KnowledgeAskResultV1`、CLI outcome/diagnostics，也不新增公开命令、依赖、配置、持久文件或模型调用。

## 适用范围与权威来源

本合同只适用于 Knowledge 数据根下的：

```text
answers/<answer_id>/
answers/.staging/<answer_id>/
```

`answer_id`、目录安全、同卷原子提交、writer mutex、terminal manifest、P0–P4 / C / O、attempt 双文件、capture 语义、CLI receipt 与 no-commit 边界继续分别由 [Knowledge Answerer v1](./knowledge-answerer-v1.md)、[ADR 0051](../adr/0051-atomically-commit-every-terminal-answer-record.md)、[ADR 0052](../adr/0052-serialize-knowledge-answer-writes-with-a-windows-mutex.md)、[ADR 0053](../adr/0053-complete-only-fully-valid-orphaned-answer-commits.md)、[ADR 0054](../adr/0054-use-a-closed-answer-manifest-asset-inventory.md)、[ADR 0071](../adr/0071-use-closed-stage-prefixes-and-atomic-pairs-for-answer-root-assets.md)、[ADR 0072](../adr/0072-use-a-fixed-two-file-capture-for-every-knowledge-attempt.md)、[ADR 0073](../adr/0073-use-octet-stream-for-knowledge-attempt-captures.md)、[ADR 0077](../adr/0077-cap-knowledge-attempt-captures-per-file.md)、[ADR 0081](../adr/0081-project-knowledge-usage-only-from-sub-cap-events.md)、[ADR 0082](../adr/0082-serialize-answer-manifest-as-canonical-json.md)、[ADR 0083](../adr/0083-close-answer-manifest-to-eleven-top-level-fields.md)、[ADR 0084](../adr/0084-cap-answer-manifest-at-64-kib.md)、[ADR 0085](../adr/0085-bound-answer-asset-byte-length-to-signed-int64.md)、[ADR 0086](../adr/0086-bound-answer-manifest-parser-resources.md)、[ADR 0087](../adr/0087-directly-exclusive-create-answer-terminal-manifest.md)、[ADR 0088](../adr/0088-do-not-promise-power-loss-durability-for-knowledge-answers.md)、[Knowledge Ask Result v1](./knowledge-ask-result-v1.md) 与 [Knowledge Ask Diagnostics v1](./knowledge-ask-diagnostics-v1.md) 拥有。本合同只填补这些来源明确留下的 terminal / recovery seam，不重述其内部 Schema。

V1 威胁边界仍是服从同一 writer mutex 的协作进程与 crash / power-loss 后重新观察到的实际本地文件系统状态；不增加抵御高权限恶意本机进程的承诺。

## Module、Interface 与状态词

`AnswerTerminalV1` 是 Knowledge Context 内的 deep module。它隐藏 safe-open、路径闭合、预算、hash、Schema/media identity、跨资产验证与 recovery checkpoint；调用方只能通过以下三个行为 seam 使用它：

1. `read_committed(answer_id)`：只读并整体接受或拒绝字面 `answers/<answer_id>/`。
2. `inspect_orphan(staging_entry)`：只允许在当前线程持有该 Knowledge 数据根 writer ownership 时检查 `.staging/` 的一个直接子项。
3. `complete_orphan(inspected_orphan)`：只消费同一次完整检查得到的不可变证据，最多执行一次 non-replacing same-volume directory rename。

这三个名称描述行为合同，不冻结 Python module path、class、exception 或返回对象。CLI adapter、Human renderer、diagnostic constructor 与未来 Context 不得绕过该 module 直接解释 Answer 文件。

以下四个词是 invocation-local 的检查分类，不写入 manifest、CLI result、diagnostics、sidecar、marker 或 current pointer：

| classification | 精确定义 |
|---|---|
| `committed` | 字面 `answers/<answer_id>/` 存在，并由 `read_committed` 对当前实际 bytes 完整验证通过。路径存在、manifest 存在或旧 CLI 成功都不够。 |
| `staged` | `.staging/` 项仍由当前活跃 writer 拥有，或检查方尚未通过同一 mutex 证明 prior owner 已不存在；正式 consumer 必须忽略。 |
| `orphaned` | 检查方已取得 writer ownership，候选是安全直接子目录，完整 terminal validation 通过，expected target 当前缺失，因此只差原定目录 rename。 |
| `quarantined` | target 或 ownerless staging 无法成为可接受的 committed Answer：无效、不完整、不安全、超限、target conflict，或本轮发生确定的 candidate-local recovery failure。隔离是原路径上的逻辑拒绝；V1 不移动、修补、标记或删除它。 |

同一 `answer_id` 可以同时有一个 `committed` target 和一个因 target conflict 而 `quarantined` staging；分类对象是具体目录项，不是只允许一个值的 Answer 字段。

## 根级 asset identity 与逐路径 cap

`manifest.assets[*]` 对下列路径必须逐字使用表中恰好一个 identity key/value。未选 identity key 必须缺失而不是 `null`；大小写变体、别名、额外参数、缺少参数或表外值均使整个 terminal Answer 无效。

所有 cap 都是未命名主数据流从第一个 byte 到 EOF 的 raw logical bytes，端点包含；`cap` 合法，确认存在第 `cap + 1` 个 byte 才超限。语义合同给出的更小上限继续优先，不能用本表扩大 payload。

| exact `path` / pattern | exact manifest identity | path cap bytes | role-owned constant |
|---|---|---:|---|
| `effective_config.json` | `schema_id=gezhi.knowledge_answerer_effective_config.v1` | 4,096 | `ANSWER_EFFECTIVE_CONFIG_MAX_BYTES` |
| `question.json` | `schema_id=gezhi.question.v1` | 16,384 | `ANSWER_QUESTION_MAX_BYTES` |
| `retrieval_query.json` | `schema_id=gezhi.retrieval_query.v1` | 262,144 | `ANSWER_RETRIEVAL_QUERY_MAX_BYTES` |
| `retrieval_audit.json` | `schema_id=gezhi.retrieval_audit.v1` | 2,097,152 | `ANSWER_RETRIEVAL_AUDIT_MAX_BYTES` |
| `retrieval_view.json` | `schema_id=gezhi.retrieval_view.v1` | 262,144 | `ANSWER_RETRIEVAL_VIEW_MAX_BYTES` |
| `prompt.txt` | `media_type=text/plain; charset=utf-8` | 262,144 | `ANSWER_PROMPT_MAX_BYTES` |
| `schema.json` | `media_type=application/schema+json` | 262,144 | `ANSWER_SCHEMA_SNAPSHOT_MAX_BYTES` |
| `answer_output.json` | `schema_id=gezhi.answer_output.v1` | 32,768 | `ANSWER_OUTPUT_MAX_BYTES` |
| `answer.md` | `media_type=text/markdown; charset=utf-8` | 524,288 | `ANSWER_MARKDOWN_MAX_BYTES` |
| `attempts/NN/events.jsonl` | `media_type=application/octet-stream` | 16,777,216 | `ANSWER_ATTEMPT_EVENTS_MAX_BYTES` |
| `attempts/NN/final_message.txt` | `media_type=application/octet-stream` | 1,048,576 | `ANSWER_ATTEMPT_FINAL_MESSAGE_MAX_BYTES` |

`NN` 仍只能是 manifest attempt ordinal 对应的 `01`、`02`、`03`；两个 capture 路径继续成对出现。Capture 的无参数 `application/octet-stream` 不因内容或扩展名改变，也不被本表的 UTF-8 文本 identity 取代。

`prompt.txt` 与 `answer.md` 的 `charset` 参数是 exact media string 的组成部分；分号后恰好一个 ASCII space，`utf-8` 为 lowercase。`schema.json` 精确使用无参数 `application/schema+json`，不得误写为 `schema_id=gezhi.answer_output.v1`：它是 JSON Schema 文档快照，而不是 `AnswerOutputV1` instance。Media identity 只选择内容 adapter，不替代 C/O 条件、严格 UTF-8、确定性 snapshot / rendering 或跨资产复验。

`manifest.json` 不自列于 `assets`；它继续使用 `schema_version=gezhi.answer_manifest.v1`，并独立服从既有 `ANSWER_MANIFEST_MAX_BYTES = 65_536`。

## 整目录 aggregate cap

单个 target 或 staging candidate 的共享 reader 固定：

```text
ANSWER_TERMINAL_MAX_BYTES = 56_623_104  # 54 MiB
```

计量值精确等于当前实际 `manifest.json` raw byte length，加上 manifest 列出的全部 asset 未命名主数据流实际 raw byte length。它不包含目录项、NTFS allocation、ADS、writer-private spool、相邻 Answer、相邻 orphan 或整个数据根；ADS 本身仍直接非法。

Aggregate cap 是独立的 reader envelope，不是各文件可互借的 quota。即使每项分别不超限，合计第 `56_623_105` byte 仍使整个 candidate 无效；某项未用额度不能扩大另一项。Writer 必须在 terminal manifest formation 前用相同路径表与 checked integer addition 证明合计可容纳；不能先发布再截断或清理。

## 有界 reader 的固定顺序与 EOF 证据

`read_committed`、writer readback 与 `inspect_orphan` 必须复用同一个 terminal validator，并按以下顺序 fail closed：

1. 从 frozen canonical Knowledge root 派生 exact candidate，safe-open 根目录；拒绝 reparse、ADS、unsafe alias 与 expected `answer_id` / basename 不一致。
2. Safe-open 字面 lowercase `manifest.json`，先以 `65_536 + 1` witness 读 raw bytes；只有明确读到 EOF 且实际长度不超过 cap 才进入 framing、strict UTF-8、structural preflight、strict parse、当前 Schema 与 canonical byte round-trip。
3. 在使用任何 asset path 前，完整验证 `assets` 顺序、唯一性、path grammar、`byte_length` exact integer/range、上表 identity、P0–P4 / C / O、attempt 双文件与全部 manifest 跨字段矩阵。
4. 以 checked non-negative integer addition 计算“实际 manifest length + 全部 declared asset lengths”。若大于 `ANSWER_TERMINAL_MAX_BYTES`，不打开任何 asset 内容并整体拒绝。
5. 枚举 candidate namespace，证明普通文件集合恰好为字面 manifest 加清单、目录集合恰好为清单需要的根与 attempt 目录。发现第一个 extra/missing/wrong-kind/reparse/ADS/ordinal-ignore-case alias 即停止；不读取 extra 文件内容，也不通过遍历整个额外子树证明它无效。
6. 对存在的 asset 固定按以下 dependency order 各读一次；跳过合法缺席项：

```text
effective_config.json
question.json
retrieval_query.json
retrieval_audit.json
retrieval_view.json
prompt.txt
schema.json
attempts/01/events.jsonl
attempts/01/final_message.txt
attempts/02/events.jsonl
attempts/02/final_message.txt
attempts/03/events.jsonl
attempts/03/final_message.txt
answer_output.json
answer.md
```

7. 每个 expected leaf 都从 offset `0` 以拒绝 write/delete sharing 的 binary handle 流式读取。短 read 不是 EOF；reader 继续到明确 EOF，或观察到 declared length、path cap、aggregate remaining 三者中最早边界之外的第一个 byte。该额外 byte 只是拒绝 witness，不解析、不保留为资产，也不继续 drain 恶意大文件。
8. 只有 EOF 已证明、实际 length 恰等于 manifest `byte_length`、增量 SHA-256 恰等于 manifest `sha256`、路径 cap 与 aggregate cap 均通过，才把该资产交给表中选择的内容 adapter。内容 adapter 再执行已有 Schema、canonical bytes、strict UTF-8、usage、C/O 与 deterministic rendering 规则。
9. 全部资产通过后，复核目录/root handle identity 与 target/staging mode 的跨资产后置条件；任何 failure 都整体拒绝，不返回 partial Answer、partial `answer_output`、fallback Markdown 或推测状态。

Manifest metadata、`GetFileSizeEx`、目录项 size、一次短 read 或已知 producer buffer 都不能代替 EOF witness。Reader 不按 manifest 长度预分配，不为 hash 读到 path cap 之后，也不因 JSON 看似已结束而跳过尾随 bytes。

## Terminal authority、CLI receipt 与 current pointer

持久 authority 只有完整有效的 `answers/<answer_id>/manifest.json` 及其闭合资产目录。`KnowledgeAskResultV1` 是产生本次新 Answer 的 process-level、非持久 commit receipt；它不是 manifest 副本，也不成为第二个 authority。两者的一致性固定为：

| 情形 | 持久状态 | 本次 `knowledge.ask result` | current pointer |
|---|---|---|---|
| 本次新 Answer 的 non-replacing rename 明确成功，且 receipt 候选从该 committed target 重读形成 | `committed` | 按既有矩阵为非 `null`；若随后 crash / presentation failure，stdout 仍可能没有完整 receipt | 必须缺席 |
| 启动时补交旧 `orphaned` Answer 明确成功 | 历史 Answer 变为 `committed` | 不能成为本次 result；新 Ask 是否另有 result 只看自己的新 commit | 必须缺席 |
| 只读历史 target | 验证通过才是 `committed` | 不构造 `knowledge.ask` receipt | 必须缺席 |
| 历史 staged/orphaned/quarantined 项自身，且本次新 Answer 最终确定 no-commit | 没有本次 committed target | `result=null`，并服从既有 no-commit outcome/diagnostic 合同 | 必须缺席 |
| rename completion 无法确定 | 同一 invocation 不猜测 committed/no-commit | 不得发布正常 receipt；走后文 uncertain boundary | 必须缺席 |

Answer V1 明确不存在 `answers/current.json`、`runs/current.json`、latest/success pointer、manifest sidecar 或等价 marker。通用 [ADR 0013](../adr/0013-preserve-immutable-stage-runs-and-atomic-current-pointers.md) 的 current pointer 适用于其列出的 Source / OCR / Reader / Candidate / Review / Handoff 成功运行；Answer 由更具体的 [ADR 0031](../adr/0031-use-a-flat-auditable-knowledge-asset-tree.md) 与 ADR 0051 固定为每次提问一个不可变 `answer_id`，不继承该 pointer。

任何现存的 `answers/current.json`、大小写 alias、reparse pointer 或 current-like sidecar 都是不受信任的未批准 namespace entry：normal reader、`knowledge ask`、`status` 与 recovery 不读取、不更新、不据此选 Answer，也不据此合成 receipt。它不能让另一个按 explicit `answer_id` 完整有效的 target 失效；报告或处理该 entry 只能是 Answer-local 的独立维护事项。

## 普通命令、recovery 与 maintenance 边界

V1 已批准的持久 mutation 只有两类：当前 writer 自己的 staging 生命周期，以及满足本合同全部前置条件的 `complete_orphan` 单次目录 rename。

| consumer / operation | 可读 target | 可检查 staging | 可提交 orphan | 可移动、删除、修补或标记 quarantined entry |
|---|---:|---:|---:|---:|
| explicit-ID Answer reader / 历史展示 | 是，只整体读取 target | 否 | 否 | 否 |
| `status` / 普通只读检查 | 是，只读 | 若其自身合同以后批准报告，最多使用未分类 presence；不能声称 ownerless | 否 | 否 |
| `knowledge ask` 持锁 pre-ID recovery | 是 | 是 | 是，每候选最多一次 non-replacing rename | 否 |
| writer 处理自己的 active staging | 否，不以 target 代替 staging | 是，只限自己拥有的目录 | 只提交自己的 terminal Answer | 否 |
| explicit maintenance seam | 不适用；seam 未开放 | 必须以后单独冻结 | V1 无额外 action | V1 mutating action set 为空 |

“V1 mutating action set 为空”是封闭决定，不是允许实现自行补命令：当前不提供 archive、purge、repair、force-promote、terminalize、quarantine marker 或 `resume Answer`。若以后需要显式维护，必须另行冻结入口、授权/确认、exact target、并发 ownership、保留路径、幂等键、失败与不确定结果；在此之前，`ask`、`status`、`doctor`、历史 reader 或后台任务都不能代行。

逻辑 `quarantined` 不等于物理 `.quarantine/`；V1 不创建该目录。普通 reader 的 Interface 因此保持很小：explicit ID in，完整 Answer 或整体拒绝 out；recovery 的 mutation seam 也只有一条可证明的 rename。

## Formal target / same-ID staging 双件矩阵

无 writer ownership 时，任何 staging 都只能是 `staged`；reader 不能借观察 mutex 名称、时间戳、PID、manifest 或文件静止来宣称 orphan。取得 ownership 并完成 candidate inspection 后，按当前实际状态执行下表：

| formal target | same-ID staging 缺席 | staging 尚未证明 ownerless | ownerless 且完整有效 | ownerless 但无效、不完整、不安全或超限 |
|---|---|---|---|---|
| 缺席 | 当前无该 Answer | `staged`；忽略且不动 | `orphaned`；满足 final checkpoint 后可补交 | staging `quarantined`；原地不动 |
| 完整有效 | target `committed` | target 可读；staging 仍 `staged` | target `committed`；staging 因 target conflict `quarantined` | target `committed`；staging `quarantined` |
| 存在但无效、不完整、不安全或无法完整证明 | target `quarantined`，正式读取拒绝 | target `quarantined`；staging 仍 `staged` | target 存在阻止补交；两者分别 `quarantined` | 两者分别 `quarantined` |

Target 的存在性判断使用字面 expected path 与安全 namespace 规则；target 一旦存在，recovery 不以“staging 看起来更好”为理由覆盖、replace、merge、copy-delete、删除后重试或择优。一个坏 target 只拒绝该 `answer_id`，不能污染其他 target、Candidate Registry、search、Literature 或未来 Context。

## `complete_orphan` 的唯一允许动作

对安全枚举得到的直接子项先执行 basename 门禁；非法或 unsafe basename 在不派生 target path 的前提下归为 `quarantined`。通过门禁的 recovery candidates 必须按 `answer_id` ASCII bytes 升序串行处理。调用 `complete_orphan` 前必须同时成立：

- 当前线程 depth-one 持有与 frozen Knowledge root physical identity 绑定的 writer ownership；
- candidate 是 `.staging/` 的安全、非 reparse 直接子目录，basename 是合法 `answer_id`，并与 manifest 完全相等；
- 共享 terminal reader 已对当前实际 bytes、全部 cap、hash、identity、Schema、usage 与跨资产矩阵完整通过；
- expected target 在检查时缺失；
- recovery 打开的 leaf / candidate handles 已关闭；
- 紧邻操作前的 root identity、canonical path、两条父链 no-reparse、同卷与 target-absent checkpoint 全部通过。

随后只允许一次 non-replacing same-volume directory rename，且只接受以下 closed outcome：

| rename observation | 当前 invocation 的行为 |
|---|---|
| 明确成功 | 该历史 Answer 成为 `committed`；不重跑阶段、不改 manifest、不生成本次 Ask receipt。随后可从 formal target 全量重读，但成功 rename 已是 process-level commit point。 |
| 明确 target-exists | 不覆盖；按双件矩阵完整检查 target，staging 作为 target-conflict `quarantined`。 |
| 明确为其他 candidate-local failure，且 root trust 与“target 未由本操作提交”均可证明 | 本轮把 staging 归为 `quarantined`，原地保留，只形成待冻结的 supplemental fact，并继续下一个候选。不得在同一 invocation 重试。 |
| completion / commit outcome 无法确定 | 立即 stop-new-work；不得重试、回滚、删除、补 pointer、生成 receipt、选择 normal no-commit outcome或继续扫描。只有后续独立 invocation 重新取得 ownership、重新 safe-open 当前 namespace 并从零应用双件矩阵。 |

后续独立 invocation 不是根据旧异常猜测：target valid 则接受 committed；target 缺失且 staging valid 才重新成为 orphaned；target 存在但无效则阻止补交；两侧都缺失则当前没有该 Answer。它永远不为旧 invocation 追造 CLI receipt。

## Crash checkpoints 与幂等性

| crash / abrupt-stop checkpoint 后重新观察 | 允许分类与动作 |
|---|---|
| 新 ID 或 staging direct child 尚未建立 | 没有该 Answer；不复用旧预生成 UUID bytes。 |
| staging 已建，但只有私有/partial/non-terminal 资产 | 取得 ownership 后 `quarantined`；不补 manifest、不伪造成 interrupted。 |
| terminal assets 已形成，但 `manifest.json` 缺失、空、partial、超限或无效 | `quarantined`；不寻找 temp/backup/sidecar，不 canonicalize。 |
| `manifest.json` 与全部资产完整有效，rename 尚未发生 | `orphaned`；只允许 `complete_orphan`。 |
| rename 已发生，CLI receipt 尚未完整写出 | target 经全量复验后为 `committed`；receipt 缺失不回滚，也不补 current pointer。 |
| power loss 后 target/staging 并存、任一 partial 或两侧缺失 | 只按当前 bytes 应用双件矩阵；不从旧 success、日志、时间戳或 rename 猜测。 |

重复 `read_committed` 与 `inspect_orphan` 不写磁盘。`complete_orphan` 成功后重复运行会先看到 target，因而不再 rename；target conflict 永不覆盖。确定失败在同一 invocation 不重试；下一 invocation 若重新获得完整证据，可以再次按 closed matrix 作一次新尝试。不确定 outcome 在当前 invocation 没有幂等重试资格。

## Answer-local failure 与诊断边界

- 一个 candidate 的 identity、cap、hash、Schema、target conflict 或确定 recovery failure 只隔离该 candidate；持锁 scan 继续处理下一 candidate，并允许当前 Ask 使用新 `answer_id`。
- `.staging/` 无法安全枚举、invocation-wide scan protocol 不能完成、root trust 丢失或本次 Answer terminalization/commit 失败，继续使用 Knowledge Ask Diagnostics v1 已冻结的 primary/outcome 边界；本合同不新增或重排 code。
- 一个 formal target 无效只使 explicit-ID reader 整体拒绝该 Answer；不得回退到同身份 staging、另一个 Answer、current pointer、raw `answer.md` 或 manifest 片段。
- `retrieval_audit.json` 的 closed semantic fields、orphan/capture/maintenance supplemental variants、Human 文案与其他命令 result 仍由各自来源合同拥有。缺失时只阻塞相应 Answer semantic adapter 或外部报告，不阻塞 Registry/search、Literature、未来 Context 或不消费该信息的开发任务。

## 验收矩阵

实现票必须优先从真实 public CLI subprocess seam 覆盖可见结果；public seam 无法精确制造 raw boundary 或 uncertain rename 时，才允许对 `AnswerTerminalV1` 增加窄内部测试。

### Identity 与闭合

- 表中每个 exact identity 各有接受用例；`schema_id`/`media_type` 互换、大小写变化、参数变化、两 key 同时存在、两 key 都缺失均拒绝。
- `prompt.txt`、`schema.json` 与 `answer.md` 分别验证 exact media string；attempt captures 始终保持无参数 octet-stream。
- P0–P4、C/O、attempt pair、unknown/extra/missing/reparse/ADS/alias 继续按既有有限矩阵整体拒绝。

### Capacity 与 EOF

- 对 manifest、表中每个 path cap 以及 aggregate cap，覆盖 `cap - 1`、`cap`、`cap + 1`；前两者只表示容量门禁通过，仍需其他语义有效，`cap + 1` 必须在解析/返回内容前拒绝。
- 覆盖 manifest declared length 超限、declared aggregate 超限、实际文件短于声明、实际文件长于声明、实际第 `path cap + 1` byte、实际第 `aggregate cap + 1` byte、short-read 后继续到 EOF，以及 size metadata 与实际 stream 不一致。
- 任一路径或 aggregate boundary 若无法用完整领域 payload 独立达到，使用窄 raw-reader fixture；不得放宽正式 Schema 只为造测试。

### 状态、恢复与冲突

- 双件矩阵每个 cell 至少一个测试；无 ownership 时 staging 只能 staged，持锁后才可 orphan/quarantine。
- 有效 orphan 的 rename 明确成功、target-exists、其他确定失败与 uncertain completion 四分支全部覆盖。
- 验证 failure、cap overflow、坏 target 与 target conflict 不得被解释为 succeeded，不得返回 partial Answer 或 non-null Ask receipt。
- Crash checkpoints 表逐行覆盖；尤其是“rename 成功、receipt 前 crash”必须接受 target 但不能追造 receipt/current pointer。
- 任意 normal/recovery 路径都断言不创建或修改 `current.json`、quarantine marker、backup、sidecar，不 overwrite/delete/merge target。

### Locality 与 maintenance absence

- 单个 quarantined Answer 不阻塞其他 explicit-ID target、Registry/search 或 Literature。
- `status` / reader 不触发 rename；`knowledge ask` 只在持锁 pre-ID recovery 调用 `complete_orphan`。
- 八条日常 CLI 中不存在 Answer archive/purge/repair/force-promote/resume；测试不得通过隐藏 alias 暗中提供。

## 非目标与残余风险

- 不提供 power-loss durability、flush 顺序、恶意本机并发防护或历史 Answer 总存储 quota；ADR 0088 的边界不变。
- 不冻结 `retrieval_audit.json` 尚未由其来源合同闭合的字段，也不借 terminal cap 发明字段。
- 不冻结 orphan/capture/maintenance supplemental diagnostic code/context、Human 文案或 `status` payload；实现不得使用通用 fallback、异常文本或任意 dict 填补。
- 不提供 physical quarantine、archive、purge、repair 或 current/latest selection。未来增加任一持久路径、marker、pointer 或 mutation action，都必须显式演进相应合同；不能静默扩展 Answer V1。

该设计把复杂 filesystem 与恢复规则压入一个深 module，以一个整体 reader 和一个单次 rename seam 服务 writer readback、历史读取与 crash recovery；代价是异常现场会原地积累，但正常命令接口保持小、局部、可验证，且不会把损坏现场升级为正式 Answer。

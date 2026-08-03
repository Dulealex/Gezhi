# 为 CLI JSON 结果使用一个封闭外层

所有公开 Gezhi 命令在显式 `--json` 模式下共享一个 `CliResultEnvelopeV1` interface；Literature、Knowledge 与未来 Context 的命令 adapter 只提供已经验证的 command-owned report，共享 CLI JSON writer module 独占五字段组装、外层验证、确定性序列化与 stdout 写出。不得让每个 Context 复制 JSON 外层、直接打印 dict，或为复用该接口建立 Command Bus、动态插件系统与跨 Context 领域基类；未来命令继续通过 ADR 0032 的静态 composition 接入。

Root 必须是禁止额外字段且五项全部必填、非重复的 JSON object：

| field | V1 outer type / value |
|---|---|
| `schema_version` | string constant `gezhi.cli_result.v1` |
| `command` | concrete command contract 拥有的稳定 ASCII dotted identifier；首个冻结 binding 是 `knowledge.ask` |
| `outcome` | string enum `succeeded`、`blocked`、`failed` 或 `interrupted` |
| `result` | JSON object 或 `null`；具体 object 由 command-owned 版本化合同闭合 |
| `diagnostics` | 始终存在且非 `null` 的 0–16 项 JSON array；每项为 ADR 0091 的 `CliDiagnosticItemV1`，完整 array canonical bytes 不超过 16,384，无诊断时为 `[]` |

`additionalProperties=false` 冻结 outer；`knowledge.ask result` 已由 ADR 0090 闭合，共享 `CliDiagnosticItemV1` profile 已由 ADR 0091 闭合，`knowledge.ask` committed primary subset 与完整 committed JSON 正常返回 exit table 已由 ADR 0092 闭合，无 committed Answer 的 outcome/result 分类与正常 JSON exit 已由 ADR 0093 闭合，no-commit blocked、failed 与 interrupted primary/context 已分别由 ADR 0094、ADR 0095、ADR 0096 闭合，跨 outcome 静态优先级已由 ADR 0097 闭合，cancellation/identity cutover 已由 ADR 0098 闭合，no-commit drain/cleanup 与安全后置条件已由 ADR 0099 闭合。其他命令的 result、各 command 的剩余 concrete code/context union，以及 `knowledge.ask` 的 supplemental 矩阵仍不是任意 map 授权；在这些部分完成前，`knowledge.ask` 仍没有可宣称稳定的完整 concrete Schema。不得自行加入顶层 `status`、`ok`、`error`、`warnings`、`data`、`message`、`committed`、`commit_state`、时间、路径、PID、provider/Codex identity 或第六个字段。

`outcome` 是当前 CLI invocation 的运行终态，不是 Knowledge `answer_status`、历史对象状态、HTTP status 或 process exit code。对于本次 `knowledge.ask` 已经成功执行目录级 commit 的新 Answer，outer `outcome` 必须逐值等于该 Answer terminal manifest 的 `status`；只有目录 rename 返回成功后才可发出这种 envelope。没有本次新 committed Answer 时 `result=null` 且禁止 `succeeded`：Question 领域输入或可恢复前置条件形成 provisional `blocked`，本地 Answer 形成、验证或目录提交失败形成 `failed`，ADR 0098 的同一 cancellation latch 在 atomic pre-ID barrier 先赢并完成安全收尾时形成 provisional interruption；ADR 0097 固定按 `failed > interrupted > blocked` 选择最终 no-commit outcome。`answer_id` 一旦成功生成、验证并锁存，安全取消必须尝试提交 interrupted Answer；提交失败属于 no-commit `failed` 或不安全矩阵外路径。Blocked、failed 与 interrupted primary code/context 分别由 ADR 0094、ADR 0095、ADR 0096 冻结；跨 outcome 静态优先级由 ADR 0097 冻结，cancellation latch/checkpoints、work commitment、stop-new-work、final no-commit lock 与 identity cutover 由 ADR 0098 冻结，`NoCommitSafeBoundaryV1` 由 ADR 0099 冻结。不得伪造 manifest 或 result object，也不得把未提交 staging 中已经锁存或看似完整的 `status` 当作 outcome 权威。只读命令以后即使成功读取一个历史 `status=failed` 的对象，其 invocation outcome 仍可为 `succeeded`；启动时补交的旧 orphan Answer 也不是本次新 Answer，其 `status` 不支配本次 outcome。Answer parity 绝不能泛化到 `show`、`search` 或其他命令，orphan warning 等附属 diagnostics 也不自行改变主 outcome。正常发布的 `answer_status=insufficient_evidence` 仍对应 outer `outcome=succeeded` 与 manifest `status=succeeded`。

Writer 必须先在内存中形成并验证完整 envelope value，再使用 Python 3.11 标准库的等价调用形成唯一 immutable byte buffer：

```python
json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
```

V1 使用 binary stdout；没有 UTF-8 BOM、ANSI、raw `0x0D`、pretty-print、Windows newline translation、`default` coercion、Unicode normalization 或第二个 JSON value，唯一 raw LF 是最后一个 byte。`--json` 输出是恰好一个 JSON object，不是 JSONL；不能与 `codex exec --json` 的 provider event JSONL 混用。Writer 必须在同一 stdout 上循环处理正长度 short write；zero/越界 write、I/O failure 或 broken pipe 后不得追加第二份 fallback JSON、人用说明或 partial repair。后续 [ADR 0107](./0107-seal-one-bounded-immutable-knowledge-ask-json-buffer.md) 已为 concrete `knowledge.ask` binding 独立冻结包含末尾 LF 的 65,536-byte inclusive cap、pre-seal immutable buffer 与 same-buffer write；[ADR 0109](./0109-use-binary-fd1-and-blocking-os-write-for-knowledge-ask-json.md) 又把该 binding 的 Windows primitive 冻结为首次 I/O 前一次 `msvcrt.setmode(1, os.O_BINARY)`，随后以 direct synchronous `os.write(1, remaining_view)` 循环请求整个未写 suffix。该 cap 和 primitive 都不被 Literature、其他命令或未来 Bot 静默继承。

只要命令已经进入受支持的 `--json` handled path，stdout 就只能包含上述 bytes，Rich progress、spinner、prompt、日志、人用表格与 traceback 均不得写入 stdout；handled path 也不向 stderr 复制人用结果或进度。Human mode 使用独立 adapter 渲染同一 command outcome，不解析 JSON stdout。目录 commit 后、JSON acknowledgment 完成前仍可能崩溃，因此空或 partial stdout 绝不能证明本次 Answer 未提交。ADR 0092 冻结完整 committed `knowledge.ask --json` envelope 的正常 `0/2/1/130` exit，ADR 0093 冻结完整 no-commit handled envelope 的 `2/1/130` exit；后续 [ADR 0108](./0108-return-1-for-controlled-knowledge-ask-json-presentation-failure.md) 又把已 seal/release 且无 pending write 的 `NO_OUTPUT_PRESENTATION_FAILURE`、stdout setup、invalid synchronous count、I/O/broken-pipe failure 独立映射为静默 exit `1`。[ADR 0116](./0116-return-2-with-one-fixed-stderr-line-for-raw-argv-resource-violation.md) 另行冻结 command recognition 前 raw argv resource violation 的 empty stdout、fixed stderr 与 exit `2`；它不进入本 JSON envelope。Python/CLI 入口建立前的其他解释器/内部启动失败、未知命令/参数解析失败、envelope/result/diagnostic 构造或 validation 失败、外部实际终止、Human failure 与不确定 presentation 仍不进入上述受控集合。

`diagnostics` 是本次 invocation 的 manifest-external 报告载体，不是持久 Answer、asset、recovery 事实源或跨命令状态；它可以与 ADR 0090 的 committed result 并存，但不能回写 manifest、改变已经锁存的 Answer terminal cause 或授权修复现场。ADR 0091 已冻结两字段 item/profile；ADR 0092 至 ADR 0099 已冻结 `knowledge.ask` 的 committed/no-commit primary、outcome、exit、cancellation 与安全边界，后续 [Operations v1](../contracts/operations-v1.md) 已冻结 `doctor/status` 的完整 V1 union 与 Human 中文。`knowledge.ask` supplemental variants以及 Literature 三命令与 Knowledge `search/show` 的 concrete union/Human 仍由各自后续决策冻结。

添加新 command identifier 或新 Context 不改变五字段 outer v1；每个 concrete command 必须静态注册自己的固定 `command`、封闭 result/diagnostic Schema 与跨字段矩阵。改变 outer 字段集合、字段类型、四值 outcome 语义、序列化字节或 channel guarantee 必须升级 `gezhi.cli_result.v1`。本决策不增加持久资产、配置、marker、sidecar、依赖或运行时模型调用。

# Codex Child Process v1 合同

状态：已冻结。本文补齐 [ADR 0106](../adr/0106-run-command-owned-children-without-a-console.md) 明确保留给后续决策的 Windows pipe buffer/chunk、同步 I/O、completion/polling、内部 Job termination DWORD 与确定性验收细节。实现不得用较高层 subprocess 默认值、shell wrapper 或经验性 cleanup 替代本文的精确边界。

本文中的“必须”“只能”“禁止”均为规范性要求。本文只深化 Windows command-owned Codex child module；角色输入、resolver、prompt/Schema、provider event 分类、重试策略、Answer/Run 持久化与 CLI presentation 继续由既有合同拥有。发生冲突时，角色合同和已接受 ADR 的语义所有权不变；实现不得借本文重分类既有业务结果。

## 1. 适用范围与非目标

`CodexChildProcessV1` 是一个深模块：外部只提交已经冻结的 launch plan 与只读 cancellation observation，模块内部独占 pipe、worker、Job、process、polling、stop、capture finalization 与 handle ledger，且只在全部资源归零后返回一个不可变 terminal evidence。调用方看不到 pipe handle、worker、轮询 tick、Job handle 或可继续写入的 capture sink，也不能从外部竞争调用终止 API。

V1 的 production target 只能是项目 resolver 已经证明并为本 invocation 粘性冻结的 x64 native `codex.exe`。它服务以下两个已存在的 runtime role：

| role | 共享本合同的部分 | role-owned overlay |
|---|---|---|
| `literature_reader_v1` | 进程创建、stdio、handle allowlist、同步 pipe、Job、polling、stop、资源归零 | 条件式 `final_message.txt`、独立逐文件 cap、exact prefix、overflow、`attempt.json`、usage、终态与持久化规则 |
| `knowledge_answerer_v1` | 同上 | 固定双 capture、逐文件 cap、exact prefix、overflow、usage gate、attempt item 与 Answer 提交规则 |

未来 Bot 只有在自己的版本化 role contract 明确采用 `CodexChildProcessV1` 并冻结 capture overlay 后才能接入；本合同预留组合点，但不会让未知 Bot 自动继承 Knowledge 或 Literature 的持久语义。

以下内容明确不在本模块中：

- 不解析 PATH、App Paths、npm shim、PowerShell wrapper 或 Codex 版本；resolver 与 role invocation 在模块外完成。
- 不建立 `Provider`、`LLM`、Ollama、OpenAI API 或可替换模型抽象。production plan 的 provider identity 恒为项目锁定 Codex CLI。
- 不拥有 prompt、Schema、Question、Retrieval View 或 Reader Input 的形成；只接收最终 immutable prompt bytes。
- 不从 stderr、exit code 或 stdout 自由文本发明 provider failure；provider event adapter 仍由角色合同拥有。
- 不产生 CLI JSON/Human output，不继承 [ADR 0107](../adr/0107-seal-one-bounded-immutable-knowledge-ask-json-buffer.md) 至 [ADR 0109](../adr/0109-use-binary-fd1-and-blocking-os-write-for-knowledge-ask-json.md) 的 fd1 presentation writer。
- 不安装依赖、不修改 runtime/lock、不调用 WSL，也不启动隐藏的 `codex --version`。

### OCR 明确不继承

OCR **不继承** `CodexChildProcessV1`。OCR executable、GPU/runtime、stdio、并发、超时、重试、console、Job、termination DWORD、capture、usage 与 failure mapping 都必须由 OCR 自己的合同冻结。OCR adapter 不得构造本模块的 production launch plan；本文任何常量或测试结论也不能被视为 OCR 默认值。

## 2. 既有决策与所有权

本合同依赖并保持以下既有决策：

- 环境与唯一项目 Codex runtime：[Environment Contract](../environment-contract.md)、[ADR 0033](../adr/0033-use-two-isolated-codex-runtime-roles.md)、[ADR 0034](../adr/0034-version-and-snapshot-codex-prompts-and-schemas.md) 与 [ADR 0106](../adr/0106-run-command-owned-children-without-a-console.md)。
- retry 与 attempt 序列：[ADR 0028](../adr/0028-retry-only-classified-transient-failures.md)、[ADR 0065](../adr/0065-model-codex-attempts-as-an-ordered-launch-sequence.md)、[ADR 0066](../adr/0066-use-a-closed-ten-field-knowledge-attempt-record.md)、[ADR 0067](../adr/0067-scope-the-95-minute-window-to-codex-synthesis.md) 与 [ADR 0068](../adr/0068-arbitrate-attempt-terminal-signals-in-two-stages.md)。
- Knowledge usage：[ADR 0069](../adr/0069-read-attempt-usage-only-from-turn-completed.md)、[ADR 0070](../adr/0070-use-independent-checked-answer-usage-totals.md) 与 [ADR 0081](../adr/0081-project-knowledge-usage-only-from-sub-cap-events.md)。
- Knowledge capture：[ADR 0071](../adr/0071-use-closed-stage-prefixes-and-atomic-pairs-for-answer-root-assets.md)、[ADR 0072](../adr/0072-use-a-fixed-two-file-capture-for-every-knowledge-attempt.md)、[ADR 0073](../adr/0073-use-octet-stream-for-knowledge-attempt-captures.md)、[ADR 0074](../adr/0074-decode-knowledge-attempt-semantics-as-strict-utf-8.md)、[ADR 0075](../adr/0075-frame-knowledge-events-on-raw-lf-with-an-optional-eof-tail.md)、[ADR 0076](../adr/0076-scope-knowledge-capture-retention-to-committed-assets.md)、[ADR 0077](../adr/0077-cap-knowledge-attempt-captures-per-file.md)、[ADR 0078](../adr/0078-retain-exact-cap-prefixes-on-knowledge-capture-overflow.md)、[ADR 0079](../adr/0079-stop-the-knowledge-job-after-confirmed-capture-overflow.md) 与 [ADR 0080](../adr/0080-classify-knowledge-capture-overflow-as-an-unretryable-process-failure.md)。
- Literature capture：[ADR 0132](../adr/0132-bound-literature-reader-attempt-captures.md)。
- cancellation 与 no-commit safe finalization：[ADR 0097](../adr/0097-prioritize-uncommitted-knowledge-ask-outcomes-as-failed-interrupted-blocked.md)、[ADR 0098](../adr/0098-use-one-cancellation-latch-and-an-atomic-pre-id-barrier.md)、[ADR 0099](../adr/0099-prove-no-commit-safety-with-a-zero-live-resource-ledger.md)、[ADR 0100](../adr/0100-seal-the-handled-cancellation-window-before-presentation.md)、[ADR 0101](../adr/0101-use-a-project-owned-native-win32-ctrl-c-bridge.md)、[ADR 0102](../adr/0102-normalize-inherited-ctrl-c-ignore-before-activation.md)、[ADR 0103](../adr/0103-require-a-read-only-conin-processed-input-capability-gate.md)、[ADR 0104](../adr/0104-continue-with-a-no-source-cancellation-profile-when-capability-is-absent.md) 与 [ADR 0105](../adr/0105-use-the-no-source-profile-when-the-current-process-is-being-debugged.md)。
- 完整角色语义：[Literature Reader v1](./literature-reader-v1.md) 与 [Knowledge Answerer v1](./knowledge-answerer-v1.md)。

本合同关闭 mechanics，不改变这些 ADR 中的字段集合、路径集合、media type、diagnostic、正常 exit code 或 retry eligibility。

## 3. 外部 interface 与内部 seam

production 只有一个公开操作，其语义可写成：

```text
run_codex_child(
    frozen_launch_plan,
    read_only_cancellation_observation,
) -> PreAttemptRejected | AttemptTerminalEvidence
```

`frozen_launch_plan` 是不可变 value，不是可执行 callback 集合，至少已经由调用方冻结：

- role identity；
- resolver proof 绑定的 absolute `codex.exe` path、FileIdentity、size 与 SHA-256；
- exact argv、不可变的 Windows quoted command-line value、Unicode environment block 与 working directory；
- exact immutable prompt bytes；
- attempt ordinal、私有 capture namespace 与 fresh final spool pathname；
- role-owned capture profile；
- role-owned 单 attempt timeout duration/policy、同一 monotonic clock domain，以及仅在前一次成功启动已建立时才存在的 shared absolute deadline；
- attempt root、working/TEMP/SQLite/capture parent、Literature/Knowledge authoritative root 与 `CODEX_HOME` 的 frozen directory identity；attempt root 另冻结恰含 `captures`、`sqlite`、`temporary`、`working` 四个 immediate directory 的 exact entry set，四个 child 另冻结 exact empty entry set；
- Schema 的 canonical path、FileIdentity、size 与 SHA-256；
- commitment 前已经通过的 prompt/Schema/config/provenance/audit prerequisites。

该 plan 不含秘密的持久副本，不允许把 prompt/Question 放进 argv，也不允许在模块内改选 executable、model、reasoning 或 role。plan 与其 attempt workspace 都是 non-cloneable sealed value：公开构造器拒绝实例化，只有 role module 的 private exact-field builder 能物化；`dataclasses.replace`、字段复制、伪造 seal 或只伪造 `proof_kind` 不能通过本模块的完整 seal/proof validation。

模块在 commitment 前以 no-follow handle 重新打开并持有 executable、Schema 与上述目录 capability，逐项复验 frozen identity；executable/Schema 同时复验 size 与 SHA-256，attempt root 复验 exact four-name directory entry set，四个 attempt child 复验 exact empty entry set，Literature/Knowledge authoritative root 与 `CODEX_HOME` 只复验 directory identity。任一同路径替换、generation 变化、内容变化或 private namespace 漂移都必须在 `CreateProcessW` 前得到 `PreAttemptRejected`；最后一次复验后不得再释放这些 path guard 再按 pathname 重开。若一个已打开但不匹配的 capability 在拒绝路径上无法确定关闭，结果必须升级为 `UNSAFE_HOLD`，不能以 `PreAttemptRejected` 与伪造 ledger=0 降级。

plan 绝不预存「从未来成功启动时刻计算」的 absolute attempt deadline。30-minute 规则仍由两个角色各自拥有，plan 只携带该角色已冻结的 duration/policy；模块仅在 `ResumeThread` 精确返回 `1` 后采集 `provider_started_at`，再在同一 monotonic domain 内派生本 attempt 的 absolute deadline。Knowledge 第一次成功启动还在同一转换中建立 95-minute shared absolute deadline；后续 retry 的新 plan 只能携带这个已经存在且不可变的 shared deadline。第一次启动前不存在可推测的 shared deadline。所有 duration、deadline 与可用 observation 都是非负 integer nanoseconds，禁止 bool、float 或 wall-clock duration 进入裁决。

`read_only_cancellation_observation` 只能读取 ADR 0098–0105 已选择并拥有的 latch/profile。模块不能 install/release console handler、不能写 cancellation latch、不能把 child exit 转成 cancellation，也不能把一个 no-source profile 伪装成可取消 profile。

返回 union 只有两种：

1. `PreAttemptRejected`：launch commitment 从未发生；没有 attempt item；所有临时文件、线程与 handle 已归零。
2. `AttemptTerminalEvidence`：launch commitment 已发生；包含角色分类所需的冻结事实与已经完成的 role capture，但不包含仍可变化的 worker、source 或 handle。它只能在本合同的 terminal boundary 后形成。

没有“process handle 返回给调用方”“后台 collector 仍在跑”“稍后 await cleanup”或“先返回 timeout 再清理”的第三种正常结果。无法到达 terminal boundary 时不得构造上述 union 的任一看似完整结果。

### 3.1 深模块边界

pipe I/O、Job、polling、final spool generation 与 resource ledger 是一个 cohesive module，不拆成由业务层编排的浅 wrapper 链。内部可保留以下 seam，但不得暴露为产品 provider abstraction：

- production Win32 syscall adapter；
- production native Codex executable target；
- test-only deterministic executable double 与 fault adapter；
- role capture policy 的静态组合数据。

测试 executable 是同一 OS process seam 的第二个真实 adapter，不是第二个语义 provider。test-only executable path 不得进入 production config、resolver fallback 或运行时自动探测。

## 4. 固定常量

| constant | 精确值 | 所有权与含义 |
|---|---:|---|
| `CODEX_PIPE_BUFFER_HINT_BYTES_V1` | `65,536` | 两个 anonymous pipe 的 `CreatePipe.nSize` suggestion；不得依赖实际 kernel buffer 等于该值 |
| `CODEX_PIPE_IO_CHUNK_BYTES_V1` | `65,536` | 每次同步 `ReadFile` / `WriteFile` 的最大请求字节数 |
| `CODEX_CHILD_POLL_QUANTUM_MS_V1` | `50` | 没有更早 deadline 时 orchestrator 的最大空闲 wait quantum |
| `CODEX_JOB_STOP_EXIT_DWORD_V1` | `0x475A0001`（`1,197,080,577`） | `TerminateJobObject` 和 assignment-failure `TerminateProcess` 的内部 DWORD |
| `KNOWLEDGE_EVENTS_CAPTURE_CAP_V1` | `16,777,216` | 只属于 `knowledge_answerer_v1` |
| `KNOWLEDGE_FINAL_CAPTURE_CAP_V1` | `1,048,576` | 只属于 `knowledge_answerer_v1` |
| `LITERATURE_EVENTS_CAPTURE_CAP_V1` | `16,777,216` | 只属于 `literature_reader_v1` |
| `LITERATURE_FINAL_CAPTURE_CAP_V1` | `1,048,576` | 只属于 `literature_reader_v1` |

以上常量都不是用户配置，不进入 TOML、environment、manifest、provenance 或 CLI output。前四项 mechanics 常量的任何修改都需要新的 child-process 合同版本；任一角色 cap 的修改需要该角色的新合同版本。两组 cap 数值相同不表示共享所有权，也不允许一个角色通过修改另一个角色的常量改变行为。Job stop DWORD 不得使用 `130` 或 `259`；数值偶合、进程自然返回同值或读取到该值，都不能反推 stop 原因。

## 5. 进程与 handle 建立

### 5.1 固定 creation profile

唯一 root launch 必须直接调用一次 `CreateProcessW`：

- `lpApplicationName` 是 resolver 冻结的非空 absolute native `codex.exe` path；
- audit 所用 quoted command-line value 只由冻结 argv 通过项目 Windows quoting 形成，且保持不可变；
- 在进入 `READY_TO_COMMIT` 前，模块必须为该 value 分配 attempt-private、可写、NUL-terminated 的 `wchar_t[]` 副本，并只把该副本作为 `lpCommandLine`；其容量与生命周期覆盖 `CreateProcessW` 调用到返回，允许 Windows 原地改写该副本，但任何改写都不得回写 frozen argv、quoted value、hash 或 audit identity；调用返回后释放该副本；
- `bInheritHandles=TRUE`；
- flags 恰包含 `CREATE_SUSPENDED | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT`；
- flags 不含 `CREATE_NEW_CONSOLE`、`DETACHED_PROCESS`、`CREATE_NEW_PROCESS_GROUP` 或 `CREATE_BREAKAWAY_FROM_JOB`；
- `STARTUPINFOEXW.cb` 正确，`STARTF_USESTDHANDLES` 已置位；
- 不使用 `shell=True`、`cmd.exe`、PowerShell、`.cmd`、`ShellExecute`、文件关联、临时 wrapper、`PROC_THREAD_ATTRIBUTE_JOB_LIST` 或先行版本 probe。

### 5.2 两个同步 anonymous pipe

模块在 commitment 前各调用一次 `CreatePipe`，两次都传 `nSize=65,536`，不使用 named-pipe pathname、`FILE_FLAG_OVERLAPPED`、overlapped structure、IO completion port、`PeekNamedPipe` 或 `CancelSynchronousIo`：

```text
stdin:  parent stdin-write  -> child stdin-read
stdout: child stdout-write -> parent stdout-read
stderr: child stderr-NUL    -> NUL
```

`nSize` 只是 Windows buffering suggestion。正确性、吞吐与无死锁证明均不得假设实际 buffer size，且必须在实际 buffer 小于一个 chunk 时仍成立。

创建 pipe 时可让两个 endpoint 暂时 inheritable，但必须在 `CreateProcessW` 前清除父侧 `stdin-write` 与 `stdout-read` 的 inheritance flag。`NUL` 以 child-write 方向打开并可继承；三个 child-side handle 必须有效、方向正确、可继承。

### 5.3 唯一 inheritance allowlist

`PROC_THREAD_ATTRIBUTE_HANDLE_LIST` 的 handle 顺序固定为：

1. `stdin-read`
2. `stdout-write`
3. `stderr-NUL`

列表恰含这三项。Job、process、primary thread、parent pipe endpoints、capture files、final spool、Data Root、staging directory、mutex、cancellation bridge、wake/start/abort event、日志和其他任何 handle 都必须不可继承且不在列表内。父进程 console 的 stdin/stdout/stderr 不能出现。

attribute list 的 backing memory 与三项 handle storage 必须保持有效直到 `CreateProcessW` 返回。只要 `InitializeProcThreadAttributeList` 已成功初始化，该 list 随后必须恰好调用一次 `DeleteProcThreadAttributeList`；此 API 返回 `VOID`，不存在可检查的“返回失败”。调用后才释放 backing memory。未能调用该 `VOID` teardown、ownership 不确定，或 backing-memory release 的可观察失败属于 lifecycle integrity failure；不得为一个已经 delete 的 list 虚构 retry。

### 5.4 attempt-exclusive Job

commitment 前创建 unnamed、不可继承、attempt-exclusive Job，只设置 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`；不得设置 `BREAKAWAY_OK` 或 `SILENT_BREAKAWAY_OK`。外层 Job/nested-job capability 必须按 ADR 0106 已证明，不允许失败后无 Job resume。

Job handle 自建立起由 orchestrator 独占，并保留到 terminal boundary 的最后一个 handle close。`KILL_ON_JOB_CLOSE` 仅是 owner crash fail-safe，不是正常 stop 或完成证明。

## 6. worker 模型与 I/O loops

V1 使用同步 handle 加两个专用 worker：一个 stdin writer、一个 stdout collector。orchestrator 线程从不执行可能被 child backpressure 无限阻塞的 pipe read/write。

两个 worker 在 launch commitment 前已经启动并进入可证明状态：

- stdin writer 等待内部 start gate；只有 `ResumeThread` 精确返回 previous suspend count `1` 后才获得 `GO`。
- stdout collector 已拥有 `stdout-read`，可在 child 启动前阻塞等待读取。
- 任一 pre-commit reject、create failure、assignment failure或 resume anomaly 都向 writer 发 `ABORT`，绝不把 prompt 写给未被承认为 started 的 provider。

worker 只能向一个受锁保护的 internal fact queue 追加事实，然后设置一个不可继承的 manual-reset `wake_event`。只有 orchestrator 消费事实、锁存 stop、调用 termination API 与转换 attempt 状态。

### 6.1 stdin writer

writer 是 `stdin-write` 的唯一 owner。收到 `GO` 后，从 offset `0` 开始写 exact immutable prompt bytes：

1. 每次请求 `min(65,536, remaining)` bytes，`lpOverlapped=NULL`；禁止 zero-byte `WriteFile`。
2. `WriteFile` 成功且 `1 <= written <= requested` 时只推进 `written`，对 partial write 继续剩余 suffix。
3. 成功但 `written=0`、`written>requested` 或 offset 算术异常，锁存 `stdin_delivery_failure`。
4. 非 stop 情况下的 `ERROR_BROKEN_PIPE`、`ERROR_NO_DATA` 或其他 error 锁存 `stdin_delivery_failure`；orchestrator 请求 Job stop。
5. 每次 write 前先读取受锁保护的 in-memory abort/stop fact，再对 Win32 abort event 做 zero-time observation；任一来源已锁存时都不开始下一次 write，event wait 的 `WAIT_FAILED` 或任何非 `WAIT_OBJECT_0`/`WAIT_TIMEOUT` 结果锁存 structural failure。若一个同步 write 已阻塞，orchestrator 先终止 Job，使 child/descendant read handles 关闭；该次 write 返回后还要再次检查 in-memory abort fact，才能决定是否推进 suffix。主线程禁止并发关闭一个正被 worker 使用的 handle。
6. 全部 bytes 已被 Windows write 调用接受后，writer 立即且恰好一次关闭 `stdin-write`，向 child 表示 EOF。
7. `ABORT` 或 stop 后也由 writer 本身关闭该 handle；不得由 orchestrator 与 writer 双重关闭。

prompt 不做 CRLF 转换、不补 LF、不加 BOM、不重编码，也不因 chunk boundary 改变 bytes。若 prompt 为空，writer 不调用 zero-byte write，只关闭 handle 表示 EOF；是否允许空 prompt 由 role preflight 决定。

### 6.2 stdout collector

collector 是 `stdout-read` 与 events private sink 的唯一 owner。每次调用同步 `ReadFile` 请求恰好 `65,536` bytes，`lpOverlapped=NULL`：

- `TRUE` 且 `1 <= read <= requested`：按实际到达顺序消费这段原始 bytes；short read 只消费实际 prefix，下一次仍请求最多 `65,536` bytes。
- `TRUE` 且 `read = 0`：这是对端 zero-byte write 的合法 no-data observation，不是 EOF；立即进入下一次阻塞 read，不产生空 record。
- `TRUE` 但 `read > requested`、负数或 count/offset 算术异常：锁存 `stdout_collector_failure` 并请求 stop，不把越界 count 当作 bytes。
- `FALSE` 且 `GetLastError() = ERROR_BROKEN_PIPE`：这是 anonymous stdout pipe 的唯一正常 EOF。
- 其他 failure：锁存 `stdout_collector_failure`，请求 stop；该一次 failure 不是 EOF。只要 endpoint ownership 仍确定，collector 就继续 mechanical drain，直到后续真实 `ERROR_BROKEN_PIPE`，或在 Job 已空且全部 child-side writer 已证明消失后由其唯一 owner安全结清 endpoint。只有 role capture 仍可形成时才可按既有 lifecycle `process_error` 收尾；无法证明 drain/EOF/ownership 的完整边界时不形成正常 terminal evidence。

collector 不在读取时解码 UTF-8、解析 JSONL、投影 usage、判断 provider error 或寻找 `turn.completed`。这些都是 capture 完成后的 role adapter 工作。

若 private sink write/flush 失败，collector锁存 capture I/O failure，停止向该 sink 写语义 bytes，但继续读取并丢弃 stdout 直到 EOF，以免 child 因 backpressure 死锁。只有 role contract 允许保留实际 prefix、双资产/manifest 能安全形成时才产生 `process_error`；否则只留 staging。

### 6.3 无循环等待证明

V1 的 liveness 依赖以下拓扑，而不依赖 pipe buffer 大小：

- child 在读完 stdin 前大量写 stdout时，独立 collector 持续释放 stdout buffer；
- child 在写 stdout 前缓慢读 stdin 时，独立 writer 可阻塞但不会阻塞 collector或 orchestrator；
- child 不再读 stdin时，timeout/cancel/lifecycle stop 由 orchestrator 终止整个 Job，使所有继承的 read handles 最终关闭，pending writer 返回；
- root 退出但 descendant 仍持有 stdout-write 时，collector 继续读，orchestrator 继续看 Job `ActiveProcesses`，不会把 root signal误当 EOF；
- stderr 永远写 `NUL`，没有需要 drain 的第三个 pipe。

因此 main/orchestrator 不得先 join writer 再开始读 stdout，不得先等 root 再启动 collector，也不得以“关闭 stdout-read 让 child 退出”替代 Job stop。

## 7. launch commitment 与唯一启动顺序

`READY_TO_COMMIT` 表示 pipes、NUL、Job、attribute list、writable command-line buffer、capture namespace、workers、ledger、monotonic clock domain 与最后一次 cancellation/既存 shared-deadline check 均已完成。root-process 与 primary-thread 的 ledger ownership slots 也必须在此状态前预留；`CreateProcessW` 成功只把 raw handles 事务性激活进既有 slots，commitment 后不能再为它们分配 ledger entry。此状态以前的任何失败都按 pre-attempt 收尾。

commitment 是 attempt ordinal 被不可逆加入 invocation attempt 序列的线性化点。成功记录 commitment 后，不允许执行新的验证、路径解析、allocation、hash 或字符串构造；下一项且唯一一项操作必须是本 attempt 的单次 `CreateProcessW`。可写 command-line buffer 已在 commitment 前分配，不是此后的新 allocation。

完整顺序固定为：

1. 完成 `READY_TO_COMMIT`，读取 cancellation observation 与同一 monotonic domain 的 `now`；只在 plan 已携带既存 shared absolute deadline 时检查该 deadline。
2. 采集 role 已规定的 attempt start facts并原子记录 launch commitment。
3. 调用一次 `CreateProcessW`。
4. API 明确返回失败且 `PROCESS_INFORMATION` 没有可接管的成功句柄：记录 Win32 failure，结清两个 reserved slots，关闭三项 child-side parent duplicates，向 writer 发 `ABORT`，让 collector取得 EOF，形成 role 规定的空/条件式 capture，再安全收尾；这是 attempted `process_error`，不是 pre-attempt。
5. API 返回成功时，把 root process 与 primary thread raw handles 激活进两个 reserved slots。若 fault adapter/异步异常发生在真实 `CreateProcessW` 已成功且两个 raw handles 已填充之后，仍必须识别为 committed created root并完成同一接管；该 root 保持 suspended，禁止 Assign/Resume，直接 `TerminateProcess` 后按 root signal、stdout drain、worker join与ledger规则收尾。任一 slot activation/adoption 异常同样 force-adopt仍有效的raw handle并进入该 containment分支，不能把它退回create failure。
6. 只有成功接管且 create observation 确定时才调用 `AssignProcessToJobObject`；返回失败或 adapter 抛异常时，root 始终不 resume，直接 `TerminateProcess` 并排空。
7. assignment 成功后，关闭父进程持有的 `stdin-read`、`stdout-write`、`stderr-NUL` 三项 child-side duplicates。
8. 在任何 `ResumeThread` 前执行确定性 post-create/pre-resume gate：再次读取 cancellation observation 与同一 monotonic domain 的 `now`，并且只检查 plan 中可能已经存在的 shared absolute deadline。若已经观察 cancel，或 `now` 已到/越过既存 shared deadline，root 必须保持 suspended，writer 获得 `ABORT` 而不是 `GO`，绝不调用 `ResumeThread`；orchestrator 只通过唯一 stop latch 恰好一次调用 `TerminateJobObject(attempt_job, 0x475A0001)`，随后按普通 Job-empty、root signal、stdout drain、worker join 与 ledger 规则机械收尾。两项同时满足时都保留真实 observation，最终仍由既有时间仲裁决定，时间相等时 cancel 赢。
9. gate 通过后才调用一次 `ResumeThread`。只有返回 previous suspend count 恰为 `1` 才在同一转换中记录 `provider_started_at`、从 role-owned duration/policy 派生本 attempt absolute deadline、按需建立 Knowledge 首个 95-minute shared deadline、打开 writer `GO` gate并进入 `RUNNING`。
10. primary thread handle 在 gate/resume 决策已经读取、且不存在待对该 handle 执行的操作后关闭；root process handle保留到 signaled 并读取最终 DWORD。

特殊分支：

- create observation/adoption/assignment failure：只要真实创建留下可接管的 root handle，root 必须保持 suspended；用 `TerminateProcess(root, CODEX_JOB_STOP_EXIT_DWORD_V1)` 直接请求终止，随后关闭三项 child-side duplicates、向 writer发 `ABORT`，等待 root signaled并排空 stdout。空 Job 不能证明 root 已死。
- post-create/pre-resume gate 赢得：commitment 已存在，所以这是没有 `provider_started_at`、没有 attempt deadline 的真实 attempted item；既存 shared deadline与cancel仍按第12节裁决，不能撤回为pre-attempt。
- `ResumeThread` 返回 `0`、大于 `1`、`0xFFFFFFFF` 或调用结果不确定：按“可能已运行”处理，writer 不获 `GO`，用 attempt Job stop 整棵树并机械排空。
- assignment/resume failure 不得用普通 launch、第二个 process、breakaway 或 wrapper 重试。同一 semantic retry只能在本 attempt 已经安全冻结、且 role retry policy明确允许后创建下一个 ordinal。

30-minute process deadline 只能从成功的 `provider_started_at` 派生；Knowledge 95-minute shared semantic deadline只按ADR 0067在第一次成功started child时建立。第一次 CreateProcess/assignment 的耗时不计入尚不存在的30-minute attempt deadline或95-minute shared window；retry的CreateProcess/assignment虽也不计入新的30-minute duration，却始终受plan中既存shared deadline约束。上述第二道gate明确覆盖CreateProcessW或assignment跨过既存deadline/收到cancel的窗口，不会让过期的suspended root被resume。CreateProcess、assignment、gate-stop或resume failure都不会虚构成功启动anchor。

## 8. completion 与 polling

### 8.1 单一 orchestrator loop

orchestrator 是 attempt state、stop latch、deadline observation、Job query、root signal、exit DWORD、final-spool monitor 与 terminal arbitration 的唯一 writer。每轮固定执行：

1. 在同一 mutex 下取走 internal fact queue；若 queue 已空，在仍持锁时 `ResetEvent(wake_event)`，随后复查 queue，再释放锁，防止 lost wakeup。
2. 读取 cancellation observation 与同一 clock domain 的 `now`。
3. 用 zero-time wait观察 root process；root signal后恰好一次取得最终 DWORD，之后不再用 `STILL_ACTIVE` 判活。
4. assignment 成功后调用 `QueryInformationJobObject(JobObjectBasicAccountingInformation)` 读取 `ActiveProcesses`。
5. 对当前角色的 final spool执行一次 best-effort active overflow probe。
6. 串行计算 stop transition、readiness 与分类 facts。
7. 若尚未 ready，调用 `WaitForMultipleObjects(..., bWaitAll=FALSE)` 等待 `[root-process-if-not-yet-signaled, wake_event]`；timeout 为 `min(50 ms, ceil(nearest_active_absolute_deadline - now))`；尚无 active deadline 时为 `50 ms`，已经到期则为 `0`。每次 wait后都重新读取 absolute monotonic time；不得以 tick 计数累计 timeout。

`WaitForMultipleObjects` 同时看到多个 signaled handle时仍必须处理该轮全部事实，不能因 handle index较小而丢弃另一个事实。root 已 signaled后从 wait set移除，以免永久 signal造成 busy loop；process handle在最终 DWORD读取成功后可结清。`WAIT_FAILED`、Job query failure或 exit-code query failure锁存 lifecycle integrity failure；模块继续请求/验证安全 stop，只有后续完整收敛才能冻结 `process_error`。

50 ms 是最大空闲检测粒度，不是 deadline 的语义来源。系统调度、sleep/resume 或 API延迟可以令实际观察更晚；裁决始终比较 frozen absolute facts，而不是 callback到达顺序或“第几次 poll”。

### 8.2 完成不是单一 signal

以下任一项单独都不是 attempt completion：

- root process signaled；
- exit code为 `0`、`130` 或内部 stop DWORD；
- `TerminateJobObject` 返回 TRUE；
- `turn.completed` 已出现；
- stdout EOF；
- final pathname存在；
- Job handle被关闭。

`classification_ready_at` 只在 orchestrator首次同时证明下列条件时采集并锁存：

1. 未创建进程，或已创建 root 已 signaled且最终 DWORD已取得/无法取得事实已冻结；
2. attempt Job为空，`ActiveProcesses=0`；assignment failure分支则另行证明 suspended root已 signaled且空 Job始终为空；
3. stdout collector观察到正常 EOF，或角色合同允许的 collector failure已经完成安全 drain/endpoint结清；
4. stdin writer完成/停止并 join，`stdin-write` 已由其唯一 owner结清；
5. stdout collector join，private events sink已关闭并可复验；
6. final source在 Job空后完成 post-close权威复验；
7. role capture已按自身规则形成并安装，所有 spool、tail与private temp已撤销；
8. 全部 worker/monitor已 join，不会再产生 overflow、I/O或provider facts；
9. 除 Job handle外，attempt resource ledger全部 `settled`。

随后 orchestrator在同一串行转换中锁存 terminal facts，关闭最后一个 Job handle并把 ledger归零。Job close成功且 ownership确定后才可形成 `AttemptTerminalEvidence`。若最后 close失败或 ownership不确定，不得重试可能已经关闭的 raw handle，也不得返回正常结果。

monotonic clock/cancellation observation 自身也属于受审计的 syscall seam。commitment 前读取失败、返回非 `None | nonnegative exact int` 的 cancellation 值，或 monotonic clock失败时，模块必须撤销全部预备资源并返回 `PreAttemptRejected`。commitment 后同类 fault 必须只锁存一次结构性 lifecycle fact、请求至多一次 stop并继续机械收敛；不得让 orchestrator 以未处理异常跳过 Job/worker/ledger teardown。若成功 resume 或 capture-ready transition 恰逢 clock fault，evidence 中对应 `provider_started_monotonic_ns` / `capture_ready_monotonic_ns` 为 `null`，并分别保留 `provider_started_timestamp_unavailable` / `capture_ready_timestamp_unavailable`；内部用于 fail-safe 排序的值不得伪装成真实观测时间对外暴露。

## 9. stop、termination 与 teardown

### 9.1 唯一 stop latch

cancel、attempt/shared deadline、role capture overflow、stdin/stdout lifecycle failure、Job/wait failure或外层显式 abort都只提交事实。orchestrator在第一次需要停止且 Job尚未证明为空时执行唯一 `stop_requested: false -> true` transition；worker、monitor和role classifier不得直接终止进程。

后续 stop facts可追加审计事实，但不能再次转换状态、重写 first stop observation或竞争第二种 termination primitive。自然完成与 stop request竞态最终都用 root signal、Job empty、pipe EOF和capture finalization收敛。

### 9.2 正常 stop primitive

assignment已成功或 resume结果不确定时，正常 stop恰好调用一次：

```text
TerminateJobObject(attempt_job, 0x475A0001)
```

- 调用前若已经证明 root signaled且 `ActiveProcesses=0`，记录 `not_called_job_already_empty`，不发无意义终止。
- TRUE只表示终止请求被接受，不表示进程已静止；继续 poll到完整 terminal boundary。
- FALSE锁存 lifecycle failure；若 Job随后自然变空且其余边界成立，可按既有优先级形成 `process_error`。Job仍不空则不得关闭最后 handle来伪造正常 stop，只能继续安全收尾/留在正常矩阵外。
- 不调用 `GenerateConsoleCtrlEvent`、`TerminateProcess`逐 PID、WM_CLOSE、shell signal、taskkill或关闭最后 Job handle作为正常 stop。

assignment failure是唯一允许直接 `TerminateProcess(root, 0x475A0001)` 的分支，因为 root尚未属于 attempt Job且仍应 suspended。调用返回不替代 root signaled证明；若无法终止并证明 suspended root静止，不得返回或遗弃该进程。

### 9.3 teardown 与 close order

每个 resource在 ledger中有唯一 owner。raw handle ownership一经移动，旧 owner立即清空本地 slot；禁止复制裸整数后由多个 finally block竞争关闭。正常路径的依赖顺序为：

1. `CreateProcessW` 返回后，对已初始化的 attribute list 恰好调用一次返回 `VOID` 的 `DeleteProcThreadAttributeList`，再释放其 backing storage 与 writable command-line buffer；不存在可注入的 Delete 返回失败。
2. assignment完成（成功或进入其失败收尾）后关闭三项 parent-held child-side duplicates。
3. resume结果确定后关闭 primary thread handle；异常分支最迟在 root signaled后关闭。
4. stdin writer关闭 `stdin-write`并 join。
5. stdout collector读到 EOF、关闭 events sink与`stdout-read`并 join。
6. root signaled后读取最终 DWORD，再关闭 process handle。
7. Job empty后完成 final source exclusive open/read/generation verification与删除。
8. role capture pair/conditional asset形成、复验和private temp撤销。
9. 关闭 wake/start/abort等内部 event与其他非-Job资源。
10. 最后关闭 Job handle，证明 ledger为零。

发生 stop时步骤 4–8可并行推进，但 owner与终态依赖不变。不得在另一个线程仍对 handle执行同步 I/O或 wait时并发 `CloseHandle`；Windows对 pending wait中的 handle被关闭不提供安全语义。

`CloseHandle` failure使该 ledger entry进入 `uncertain`，不得盲目第二次 close，因为数值可能已被回收复用。任何 `uncertain` entry都阻止正常 terminal evidence。commitment 后的 close uncertainty 不得直接 unwind：若发生在 pre-resume gate 以前，它必须阻止 `ResumeThread`；若发生在 `GO` 以后，它必须经唯一 Job stop transition 终止整棵树。两者都要先完成 root/Job/pipe/worker 的机械收敛，再以 `UNSAFE_HOLD` 暴露 ownership 不确定性，不能伪造 ledger=0 或普通 `process_error`。

## 10. capture 与 final spool

### 10.1 共同 raw-byte规则

stdout与 final source均按 binary bytes处理。transport不添加 BOM、LF、marker、header，不做文本模式转换、Unicode修复、JSON修复或重新排序。所有 hash、长度与role验证都以最终捕获的原始 bytes为准。

`--output-last-message` 的路径属于当前 attempt 的 fresh、唯一、writer-private staging namespace；launch前 pathname不得已有任何 entry，且不得跨 attempt复用。该文件不作为 inherited handle传给 child，Codex只通过冻结 argv得到 path。stdout绝不能补造 final，final也不能补造 events。

### 10.2 角色自有 events cap

collector 先从 frozen capture profile 选择角色自有的 `role_events_cap`；Knowledge 与 Literature 当前分别为 `KNOWLEDGE_EVENTS_CAPTURE_CAP_V1` 和 `LITERATURE_EVENTS_CAPTURE_CAP_V1`。它对每个非空 chunk依次执行：

```text
keep = min(len(chunk), role_events_cap - retained_length)
sink.write_all(chunk[0:keep])
if len(chunk) > keep:
    events_overflow_latch = true
```

sink恰到角色 cap后仍继续 read；只有下一次实际非空 byte才锁存 overflow。锁存后继续 mechanical drain到 EOF，但 tail不解析、不hash、不进入正式资产。正式 `events.jsonl` 只能是完整实际 bytes（长度低于或等于角色 cap）或已证明 overflow时长度恰为该 cap的 exact prefix。

### 10.3 角色自有 final active probe 与权威复验

orchestrator 从 frozen capture profile 选择角色自有的 `role_final_cap`；Knowledge 与 Literature 当前分别为 `KNOWLEDGE_FINAL_CAPTURE_CAP_V1` 和 `LITERATURE_FINAL_CAPTURE_CAP_V1`。每个 50 ms loop至多执行一次 active probe：

- pathname不存在、sharing violation或暂时打不开只表示“本次无可靠 observation”，不是 failure，也不证明未 overflow；
- 成功打开时，用 `GetFileInformationByHandleEx(FileIdInfo)` 记录 generation identity，并实际读取 offset `role_final_cap` 的一个 byte；只有读到该 byte才锁存 final overflow；
- metadata length只能帮助决定是否尝试，不能代替 cap+1 witness；
- probe不读取/保留 tail，也不从 pathname拼接不同 generation。

Job `ActiveProcesses=0` 后，对 final pathname执行一次权威 finalization：

1. 不存在且没有early overflow witness：Knowledge正式 final为0 bytes；Literature按其合同表示为“不存在条件式资产”。
2. 存在时，以普通文件、non-reparse、exclusive read/delete handle打开；成功exclusive open是writer source已关闭的证明。取得 FileId与实际size，从offset 0以65,536-byte chunks读取。
3. size小于等于角色 cap时读完全部 bytes并验证 EOF；大于角色 cap时读取exact cap prefix与offset cap witness，锁存overflow。
4. early witness的generation与最终generation不同，旧latch不能被清除；最终generation必须独立证明overflow，否则不能形成terminal capture。early witness后source缺失、不可读或最终generation缩至不大于cap也只能留staging。
5. authoritative handle绑定当前generation完成删除（例如以delete-on-close语义），关闭后验证private pathname不再存在；不能close后按pathname误删replacement。

任一角色的 formal final在overflow时恰为该角色 cap的 exact prefix；witness与tail不进入资产。非overflow时为完整source bytes。任何overflow final prefix都不能进入角色成功结果验证。

### 10.4 Knowledge pair、overflow与role-owned usage seam

每个 launch-committed Knowledge attempt最终必须且只能成对安装：

- `attempts/NN/events.jsonl`
- `attempts/NN/final_message.txt`

即使 `CreateProcessW`失败，两者也都是可关闭、读取、hash的0-byte资产。pair installation、stage prefix与manifest inventory继续由ADR 0071–0072拥有；本模块在pair尚未安全完成时不返回terminal evidence。

两个 overflow latch都是单调 `false -> true`，在capture-finalization时做OR。任一为true都按ADR 0080固定最高优先级、不可重试的`process_error`，覆盖cancel、deadline、provider、exit与其他lifecycle facts；safe boundary失败则不是一个可提交`process_error`，而是只留staging。

本共享 child module 到正式 events 安装并形成 mechanical terminal evidence 为止，不解析 JSONL、不计算 usage，也不在 T13 evidence 中创建 usage 字段。T22 Knowledge role adapter 必须在 capture 已安装后按自己的版本化合同计算 usage receipt：

- `byte_length == 16,777,216`：四项token全部`null`且`usage_unavailable=true`，不解码、不parse；这不反推overflow。
- `byte_length < 16,777,216`：按ADR 0069/0081对完整正式bytes运行strict whole-file adapter，只从唯一`turn.completed.usage`逐字段投影。
- `byte_length > 16,777,216`：合同无效，不能形成terminal manifest。

usage缺失本身不产生process failure；event编码/framing/结构或collector lifecycle failure继续按Knowledge Answerer完整矩阵处理。T14 Literature role adapter同样在共享 child 返回 raw capture 后形成自己的 `attempt.json` 与 usage/metadata receipt；两种 receipt 都不能反向污染共享 child 的 provider-neutral evidence。

### 10.5 Literature capture差异

Literature Reader v1依据 ADR 0132采用自己独立版本化的 16 MiB events cap与1 MiB final cap。它们虽然与Knowledge现值相同，却不继承Knowledge常量、固定双文件或exact-cap usage gate。因此：

- 共享collector按10.2使用 `LITERATURE_EVENTS_CAPTURE_CAP_V1`；恰到 cap不是overflow，第cap+1个实际byte才锁存overflow并只保留exact prefix。
- final存在时按10.3使用 `LITERATURE_FINAL_CAPTURE_CAP_V1`；不存在时不得补0-byte `final_message.txt`。
- 任一Reader overflow都具有最高机械优先级；Job仍非空时只请求一次stop，安全收敛后形成不可重试`process_error`，公开Reader映射为`failed: codex_process_failed`。
- Reader `attempt.json`、usage与failure/retry由Literature Reader v1拥有。
- 若磁盘/capture I/O失败，仍须stop并drain；能否形成terminal Reader Run只按Reader现有持久化合同判断。

独立常量和独立验收防止跨bounded-context语义泄漏；以后改变任一 Reader cap、overflow mapping或缺失final语义，都必须升级Reader角色/合同版本，不能通过Knowledge决策旁路改变。

## 11. attempt 状态机

### 11.1 主状态

| state | commitment | process可能运行 | 允许的下一状态 |
|---|---:|---:|---|
| `PREPARING` | 否 | 否 | `READY_TO_COMMIT`、`PRE_ATTEMPT_REJECTED` |
| `READY_TO_COMMIT` | 否 | 否 | `CREATE_PENDING`、`PRE_ATTEMPT_REJECTED` |
| `CREATE_PENDING` | 是 | 否/未知于调用返回前 | `CREATED_SUSPENDED`、`DRAINING` |
| `CREATED_SUSPENDED` | 是 | 否 | `JOB_ASSIGNED`、`DRAINING` |
| `JOB_ASSIGNED` | 是 | post-create gate前仍否；只有resume异常时按可能是 | `RUNNING`、`DRAINING` |
| `RUNNING` | 是 | 是 | `DRAINING` |
| `DRAINING` | 是 | 可能，直到Job空 | `READY_TO_FREEZE`、`UNSAFE_HOLD` |
| `READY_TO_FREEZE` | 是 | 否 | `TERMINAL`、`UNSAFE_HOLD` |
| `TERMINAL` | 是 | 否 | 无；item/evidence不可回写 |
| `PRE_ATTEMPT_REJECTED` | 否 | 否 | 无；ledger必须为零 |
| `UNSAFE_HOLD` | 可能 | 未证明为否 | 只能继续安全收尾；不是正常返回值 |

`stop_requested`、`root_signaled`、`job_empty`、`stdout_eof`、`events_overflow`、`final_overflow` 与各I/O/lifecycle failure是state旁的monotonic facts，不另建可来回跳转的并行状态机。

### 11.2 关键transition

| event | 当前state | 唯一action | terminal含义 |
|---|---|---|---|
| preflight/setup/cancel/deadline在commit前赢得 | `PREPARING/READY_TO_COMMIT` | abort workers、关闭handles、撤销temp | no attempt |
| commitment成功 | `READY_TO_COMMIT` | 立即调用一次`CreateProcessW` | ordinal已存在 |
| CreateProcess失败 | `CREATE_PENDING` | child-side close、空capture、drain | attempted `process_error` |
| assignment失败 | `CREATED_SUSPENDED` | direct root terminate+wait | safe后`process_error` |
| post-create gate观察到cancel/既存shared deadline | `JOB_ASSIGNED` | 不resume，writer ABORT，唯一Job stop+drain | safe后按时间仲裁的真实attempt |
| resume恰为1 | `JOB_ASSIGNED` | writer GO，记录started anchor | `RUNNING` |
| resume其他/不确定 | `JOB_ASSIGNED` | Job stop，writer ABORT | safe后`process_error` |
| cancel/deadline/overflow/lifecycle stop | `RUNNING/DRAINING` | 第一次才锁存stop并终止非空Job | 由两阶段仲裁，不由API返回决定 |
| root signal | `RUNNING/DRAINING` | 取exit DWORD，继续等Job/EOF | 不单独完成 |
| 全部ready条件成立 | `DRAINING` | 锁存`classification_ready_at` | 进入`READY_TO_FREEZE` |
| Job最后close且ledger=0 | `READY_TO_FREEZE` | 冻结evidence与role next action | `TERMINAL` |

## 12. cancellation、deadline 与 completion竞态

### 12.1 唯一串行裁决

所有成功取得的时间事实都属于同一 monotonic clock domain并冻结为非负 integer nanoseconds，且只有orchestrator可以冻结`classification_ready_at`。clock observation fault 按第8.2节锁存结构性 failure；缺失时间戳不得由 wall clock 或内部 fallback 冒充。每个attempt恰好执行一次以下算法：

1. 若capture-finalization/lifecycle完整性门禁不成立：不分类、不返回，继续安全收尾或进入`UNSAFE_HOLD`。
2. 任一适用角色的 overflow latch为true：`process_error`。
3. 任一结构性进程/Job/wait/exit/capture/event failure为true：`process_error`。
4. 若`cancel_observed_at <= classification_ready_at`，且`active_deadline`不存在或`cancel_observed_at <= active_deadline`：`interrupted`；相等时cancel赢。
5. 否则若`active_deadline`存在且`active_deadline <= classification_ready_at`：`timeout`。
6. 否则只允许 role adapter 消费其版本化合同明确批准的结构化 provider discriminator；Codex CLI `0.146.0` 的 V1 role 没有这类字段，因此本步不产生分类。
7. 否则已安全收尾的 provider terminal或unknown nonzero exit：`process_error`；exit 0且无failure：`null`。

`active_deadline`是可选值：成功 resume 后取派生 attempt deadline 与既存/新建 shared absolute deadline 中较早者；成功 resume 前只能是 plan 已携带的既存 shared deadline；两者都不存在时 deadline 条件视为不成立，而 cancel 与 `classification_ready_at` 仍可独立裁决。poll晚到不会移动deadline，也不会令晚观察的自然exit倒赢。

### 12.2 cancel-completion唯一transition

当completion与cancel在同一poll中可见时，orchestrator先收集该轮全部facts，再在一个临界区内：

- 若cancel时间早于或等于ready时间，锁存cancel事实并按上表请求/完成stop；
- 若ready时间严格早于cancel，attempt终因已经冻结，晚到cancel不得回写item；外层command是否在下一commit/barrier处理该cancel仍由ADR 0098–0100决定；
- 若stop已因deadline/overflow发出，后来root自然退出或`TerminateJobObject`返回不能创建第二个终因；
- child exit、descendant exit、internal stop DWORD、数值130都不能写parent latch。

每个 successfully-started attempt 只有一条 `RUNNING -> DRAINING -> READY_TO_FREEZE -> TERMINAL` 轨迹。commitment 后但尚未 successfully started 的分支不虚构 `RUNNING`：CreateProcess failure 从 `CREATE_PENDING`、assignment failure 从 `CREATED_SUSPENDED`、post-create gate 赢得或 resume anomaly 从 `JOB_ASSIGNED` 直接进入 `DRAINING`，再共用 `DRAINING -> READY_TO_FREEZE -> TERMINAL` 收敛段。每条分支都只有一个串行轨迹；没有 cancel callback 与 completion callback 互相覆盖的双写窗口。

## 13. pre-attempt 与 attempted矩阵

| failure/cancel point | launch commitment | attempt item/capture | role-visible分类 |
|---|---:|---|---|
| resolver、argv quoting、prompt/schema/config、path trust失败 | 否 | 禁止attempt | 既有pre-attempt blocked/failed |
| pipes/NUL/Job/attribute/worker/sink准备失败 | 否 | 禁止attempt；先证明ledger=0 | 既有pre-attempt cause |
| final cancel/既存shared-deadline gate在commit前赢 | 否 | 禁止attempt | 既有interrupted/timeout outer规则 |
| CreateProcess与assignment成功后第二道gate赢 | 是 | safe capture boundary后形成；无started anchor | 既有时间仲裁，cancel同刻赢；禁止resume |
| commitment记录本身失败 | 否 | 禁止attempt | 既有formation/staging failure |
| `CreateProcessW`返回FALSE | 是 | Knowledge固定0-byte pair；Literature按其attempt资产规则 | `process_error`，exit_code=`null` |
| process创建后assignment/resume/Job/wait/exit query失败 | 是 | safe capture boundary后形成 | `process_error`；exit DWORD按实际可得/null |
| started后cancel | 是 | 先stop/drain/finalize | 按时间仲裁为`interrupted`，结构failure优先 |
| started后deadline | 是 | 先stop/drain/finalize | 按时间仲裁为`timeout`，结构failure优先 |

commitment后即使没有任何provider byte，也不能把attempt“撤回”为pre-attempt。反之，commitment前已经启动worker不等于attempt；这些worker必须先归零才可返回no-attempt。

## 14. resource ledger

正常返回前必须对每项建立、owner移动与settlement做进程内证明。最小ledger如下：

| resource | 初始owner | 最终settlement owner |
|---|---|---|
| attempt Job handle | orchestrator | orchestrator，且最后关闭 |
| stdin child-read duplicate | orchestrator | orchestrator |
| stdin parent-write | stdin writer | stdin writer |
| stdout child-write duplicate | orchestrator | orchestrator |
| stdout parent-read | stdout collector | stdout collector |
| stderr `NUL` | orchestrator | orchestrator |
| process handle | orchestrator | orchestrator after signal/exit query |
| primary thread handle | orchestrator | orchestrator after resume decision |
| initialized attribute list/backing storage | orchestrator | CreateProcess返回后恰好一次`DeleteProcThreadAttributeList`，再释放backing；Delete无返回值 |
| writable `lpCommandLine` buffer | orchestrator | orchestrator after CreateProcess returns；frozen quoted value不变 |
| wake/start/abort primitives | orchestrator | orchestrator after workers join |
| stdin worker | orchestrator owns join duty | orchestrator |
| stdout worker | orchestrator owns join duty | orchestrator |
| events private sink | stdout collector | collector close，随后role finalizer验证 |
| final spool generation | Codex path writer，后由finalizer接管 | finalizer exclusive read/delete |
| capture private temp/pair | role finalizer | role finalizer |

ledger entry只能为`not_acquired -> owned -> settled`，或在不可证明的close/ownership异常后进入`uncertain`。`uncertain`不可变回`settled`，不能通过清空Python变量伪造关闭。Job close以前必须只剩Job一项`owned`；Job close以后必须恰好零项live/uncertain。

## 15. 确定性 executable double 验收

实现必须提供Windows test-only `CodexChildExecutableDoubleV1`。它是普通child executable，必须经过与production相同的`CreateProcessW` flags、stdio allowlist、suspended→Job→resume、pipe workers与polling路径；禁止在测试中用in-process fake跳过kernel semantics。

double通过固定scenario参数控制行为，但其stdout/final仍是普通bytes，stdin仍从标准输入读取。test harness可另外传递test-only barrier/event身份以制造确定竞态；这些test参数不得进入production plan。double至少支持：

- 分块/延迟读取stdin并回报SHA-256与byte length；
- 按固定chunk与barrier写stdout，包括zero-byte write、恰cap、cap+1与大于pipe buffer；
- 写、关闭、替换或不创建final spool；
- 在root退出前spawn一个继续持有stdout的descendant；
- 长时间hang直到Job termination；
- 向stderr写大于pipe buffer量级的数据；
- 检查`GetConsoleWindow()==NULL`及standard handle类型；
- 尝试访问一组由parent创建、标记inheritable但未列入allowlist的sentinel raw handle values，并回报每次 probe；parent 以自己仍持有的 authoritative event objects 证明child没有 signal这些对象；Windows可在child中复用相同数值指向无关对象，因此不得把“同一裸整数上的调用成功/失败”当成继承身份的唯一证明；
- 返回固定exit DWORD。

Win32 API本身的失败（CreateProcess、Assign、Resume、Wait、Query、Terminate、Close）以及同步 `ReadFile` / `WriteFile` 的 result、error 与 transferred-count 组合，由test-only syscall fault adapter在原调用边界注入；它只控制该次kernel-call observation，真实状态机、ledger、两个worker与executable double仍照常运行。adapter不得把worker换成mock、直接写内部fact、伪造EOF/Job-empty或跳过drain。`DeleteProcThreadAttributeList` 返回 `VOID`，不属于可注入“返回失败”的调用。

D01 另行冻结 test-only `CodexPipeCapacityObserverV1`。它的实现只位于 `tests/support`；production invocation 不提供 observer callback，production execution 因而不调用 `GetNamedPipeInfo`。共享源码只保留一个窄的 test-hook 注入点。测试中，该 observer 在两次 `CreatePipe` 成功后、任何 endpoint ownership 移动、worker 启动或 commitment 之前，以 borrowed handle 对本 attempt 的 `stdin-read` 与 `stdout-read` 各恰好调用一次 `GetNamedPipeInfo(handle, &flags, NULL, &in_buffer_size, NULL)`；两次调用都必须证明 byte-pipe mode且 `in_buffer_size > 0`，并分别锁存为 `measured_stdin_pipe_capacity_bytes` 与 `measured_stdout_pipe_capacity_bytes`。observer 不 duplicate/close handle、不改变 inheritance、不执行 pipe I/O，也不把测量值写入 production plan、evidence、状态或 correctness decision。任一 probe 失败或返回零只令 D01 test setup 失败，且发生在 commitment 前，不触发产品 fallback。两个值来自本次将实际交给 writer/collector 的两个不同 pipe instance，禁止假定二者相等，也禁止以 `CODEX_PIPE_BUFFER_HINT_BYTES_V1` 代替任一测量值。double 的 pending stdout boundary 必须以一个预分配 buffer 的单次 oversized native Win32 `WriteFile` 实现；started/returned events 紧贴该调用前后，不能以 Python buffered stream 或多次小 write 伪造“同一个调用仍 pending”。

### 15.1 必过矩阵

| ID | setup / double行为 | 必须观察到的结果 |
|---|---|---|
| D01 | `CodexPipeCapacityObserverV1` 分别取得本次两个实际 pipe 的 `measured_stdin_pipe_capacity_bytes` 与 `measured_stdout_pipe_capacity_bytes`；prompt length 恰为 `4 * measured_stdin_pipe_capacity_bytes + 17`，double 在读取任何 stdin 前同步写出的 stdout payload length 恰为 `4 * measured_stdout_pipe_capacity_bytes + 17`。test-only barriers 先保持 collector 的首个 read call 尚未进入 kernel，并用 call-boundary begin/return events 在同一确定性检查点证明 parent stdin `WriteFile` 与 child stdout `WriteFile` 各至少有一次已经开始但尚未返回；检查只用 zero-time event observation。随后释放 collector read gate，stdout 完成后 double 才打开 stdin read gate；join observer 在任何 writer join 前要求 collector-read event 已置位 | 两个 payload 分别严格大于各自独立测得的 pipe capacity，且不得假定两值相等；两个 pending-call observation 分别证明 stdin 与 stdout backpressure；最终 stdin SHA/length 完全相等、stdout 完全捕获、无 deadlock、ledger=0。错误的“先 join writer 再启动 collector”在 barrier/join observer 处立即确定失败，不用 sleep 或概率 timeout |
| D02 | stdout以1、65,535、65,536、65,537-byte边界分块 | events byte-for-byte相等，chunk boundary不改变内容 |
| D03 | double执行zero-byte stdout write再写数据 | zero write不是EOF，后续数据完整捕获 |
| D04 | root退出，descendant继续持有/写stdout后退出 | root signal后不完成；直到Job active=0与stdout EOF才ready |
| D05 | descendant无限持有stdout，deadline到期 | 一次Job stop杀整棵树，collector EOF、writer join、ledger=0，分类timeout |
| D06 | double从不读stdin且持续运行，cancel到达 | pending writer不被main并发close；Job stop后writer返回并关闭，分类interrupted |
| D07 | stderr写至少1 MiB，stdout正常 | stderr不capture且不造成backpressure；stdout/final正常 |
| D08 | no-console与forbidden inheritable sentinel probe | 无console；stdio为pipe/pipe/NUL；child对每个raw value执行probe；parent持有的authoritative sentinel event objects全部保持unsignaled，证明没有对象身份越过allowlist。child中数值slot复用不算继承 |
| D09 | `CreateProcessW` fault | commitment已存在；Knowledge两项0-byte；exit null；process_error；ledger=0 |
| D10 | `AssignProcessToJobObject` fault | root始终未resume，direct terminate后signal；process_error；无orphan |
| D11 | `ResumeThread`分别返回0、2、`0xFFFFFFFF` | writer从未GO；各自只用Job stop；process_error；无第二launch |
| D12 | events为Knowledge cap恰好值后EOF | 无overflow；正式长度cap；T13不解析usage，terminal evidence不因长度改变；T22另以该正式capture证明全null/`usage_unavailable` receipt |
| D13 | events为Knowledge cap+1 | latch只在真实第cap+1 byte；exact-cap prefix；一次Job stop；不可重试process_error |
| D14 | final为Knowledge cap恰好值 | 无overflow；完整cap资产；T13不产生usage，T22 role adapter只从events形成usage receipt |
| D15 | final为Knowledge cap+1且active probe读到witness | latch绑定generation；exact prefix；一次Job stop；process_error |
| D16 | active final witness后pathname替换成小文件 | 不清latch、不拼generation、不提交terminal Answer；保留staging |
| D17 | active probe一直sharing violation，Job空后发现cap+1 | post-close锁存overflow并形成exact prefix；不对空Job调用terminate |
| D18 | events sink在已写prefix后fault，double继续大量stdout | collector转drain-only并取得EOF；若role资产可安全形成则process_error，否则不terminal；无child block |
| D19 | `TerminateJobObject`返回FALSE但double/descendant随后自然退出 | API失败事实保留；完整收敛后process_error；不以Job-close杀树 |
| D20 | `TerminateJobObject`返回TRUE但descendant延迟退出 | TRUE不完成；继续poll到active=0/EOF |
| D21 | root exit DWORD恰为130或`0x475A0001`且无parent cancel | 不生成interrupted；按provider/unknown-exit规则分类 |
| D22 | cancel barrier与completion barrier同tick，cancel时间相等 | 只冻结一次，cancel赢；item不回写 |
| D23 | ready时间严格早于late cancel | attempt保持原终因；late cancel只交外层barrier处理 |
| D24 | deadline早于cancel且都早于ready | timeout；不因stop API exit改成interrupted |
| D25 | lifecycle failure与cancel/deadline并存且安全收尾 | process_error优先且只冻结一次 |
| D26 | pre-commit pipe/worker/final gate fault | 无CreateProcess调用、无attempt、所有temp撤销、ledger=0 |
| D27 | Literature无final pathname | 不补0-byte final；其余attempt资产按Reader合同形成 |
| D28 | Literature events/final分别恰到Reader cap及达到Reader cap+1 | 恰到cap完整保留且无overflow；cap+1只保留Reader exact-cap prefix并锁存overflow，活跃Job只stop一次，`process_error`且不重试 |
| D29 | 内部worker完成与wake reset以fresh Win32 wake event及fresh ledger交错一万次barrier迭代；另至少一次公开 executable attempt覆盖同一reset观察点 | 无lost wakeup、无hang、每次barrier ledger=0；公开attempt完整收敛且terminal ledger=0。这里的一万次是wake-state barrier迭代，不是一万次child launch |
| D30 | parent有多个额外inheritable sentinel objects并并发launch两个attempt | 每个child只得到自己的三项stdio；cross-attempt无继承、prompt/capture不串线；parent authoritative sentinels全程unsignaled，且不以child裸handle数值是否复用作身份判断 |
| D31 | real CreateProcess/Assign调用边界分别由barrier跨过cancel或既存shared deadline；另含cancel时间恰等于deadline | root始终suspended、writer只ABORT、Resume调用数为0、唯一Job stop后完整收敛；attempt保留且无started anchor，cancel同刻赢 |
| D32 | command-line adapter在CreateProcess内原地改写最后一个参数及NUL前字符 | 传入buffer可写且NUL-terminated、生命周期覆盖调用；frozen argv/quoted value/hash/audit identity逐byte不变，返回后buffer settled |
| D33 | fresh-attempt 参数化组，每个子例创建新 attempt，且每个 terminal/invalid 子例只注入一个目标 observation：`W-progress` 在同一正常 attempt 依次注入 success+full、success+short，再以合法 success 完成交付；`W-zero` 注入 success+0；`W-over` 注入 success+`requested+1`；`W-broken` 注入 pre-stop `FALSE/ERROR_BROKEN_PIPE`；`W-no-data` 注入 pre-stop `FALSE/ERROR_NO_DATA`；`W-other` 注入 pre-stop `FALSE/ERROR_GEN_FAILURE` | `W-progress` 只按实际 count 推进 remaining suffix、最终逐 byte 完整交付且不 stop。其余每个 fresh attempt 都独立证明该唯一目标 observation 锁存 `stdin_delivery_failure` 并请求至多一次 stop；stop 后 writer 不开始下一次 write，不在同一 attempt 继续注入其他 terminal observation；stdout 按真实 lifecycle 排空，worker 全部 join，terminal boundary 完整且 ledger=0，任何 failure 都不伪装成 EOF |
| D34 | fresh-attempt 参数化组：`R-progress` 在同一正常 attempt 依次覆盖 success+0、success+short、合法正数 progress，最后取得真实 `FALSE/ERROR_BROKEN_PIPE`；`R-over` 在新 attempt 注入唯一 terminal observation success+`requested+1`；`R-other` 在另一新 attempt 注入唯一 terminal observation `FALSE/ERROR_GEN_FAILURE`。`R-over` 与 `R-other` 首次锁存后，后续 read 可使用真实 observation 或只注入合法的非 EOF progress 来 mechanical drain，最终必须取得真实 `ERROR_BROKEN_PIPE`，或在 Job 已空且所有 child-side writer 已证明消失后由唯一 owner 安全结清 endpoint | `R-progress` 证明 zero 不是 EOF、short bytes 按序完整保留且正常 EOF 不产生 failure。`R-over` 与 `R-other` 各自独立锁存 `stdout_collector_failure` 并请求至多一次 stop；目标 invalid/failure 本身不当作 EOF，collector 不跳过 drain，并在各自 fresh attempt 达到完整 terminal boundary、worker join 与 ledger=0；同一 attempt 不串联第二个 terminal/invalid observation |
| D35 | fault adapter 先调用真实 `CreateProcessW` 并确认成功、PI 已填入两个 raw handles，随后在返回 observation 前抛异常；test-only watchdog 只作 orphan safeguard且不得实际触发 | committed root 保持 suspended；两个 reserved slots 接管 PI handles；Assign/Resume 调用数均为0；direct `TerminateProcess` 恰好一次；root signal、stdout EOF、workers join 后两个 raw handles 都由 production close；watchdog未兜底，terminal为`process_error`且ledger=0 |
| D36 | fault adapter 先调用真实 `ResumeThread` 并确认 previous suspend count为1，随后在返回 observation 前抛异常；double保持运行直到Job stop，test-only watchdog只作orphan safeguard且不得实际触发 | 结果按“可能已运行”处理但不形成started anchor，writer从未GO；锁存structural fact并经唯一stop transition调用一次`TerminateJobObject`；root/Job/EOF/workers完整收敛，watchdog未兜底，terminal为`process_error`且ledger=0 |
| D37 | 分别在 pre-reserved `root-process` 与 `primary-thread` slot activation 边界抛异常，每个子例使用 fresh real CreateProcess | 两种子例都force-adopt PI中的两个有效raw handles，Assign/Resume均为0，direct `TerminateProcess`恰好一次，两个raw handles均由production close，terminal为`process_error`且ledger=0 |

矩阵编号可随已冻结mechanics继续增加，不存在“最多30项”的上限。并发与竞态case必须用barrier/event控制先后，不用概率性sleep断言。每个case除业务断言外都必须断言：单次CreateProcess、单次commit、stop transition至多一次、root/Job/capture terminal边界、worker全部join、private source按合同撤销、ledger恰为零。

## 16. 支持边界与残余风险

以下内容是明确边界，不允许实现静默填空：

- Literature Reader v1的独立capture retention cap与overflow策略已由 [ADR 0132](../adr/0132-bound-literature-reader-attempt-captures.md) 冻结；相同数值不构成与Knowledge共享所有权，未来Bot也不自动继承。
- Knowledge capture-overflow 的外部 supplemental diagnostic 已由 [Knowledge Ask Observable v1](./knowledge-ask-observable-v1.md) 冻结为 `knowledge.ask.capture_overflow.v1`；本文仍只冻结内部 latch、stop 与既有 primary mapping，不拥有或扩展 diagnostic/Human 字段与 code。
- `CreatePipe.nSize`不保证实际buffer大小；验收必须覆盖更小实际capacity。
- final active probe是best-effort，sharing policy可使物理spool在Job退出前暂时超过当前角色的1 MiB cap；ADR 0076/0079与ADR 0132都只冻结正式资产上限、witness、stop和收敛语义，不承诺writer-private spool的瞬时物理硬上限。
- plan formation到commitment之间的runtime executable、Schema与关键directory replacement/原地修改由held capability、FileIdentity、size/hash与entry-set复验拒绝。最后一次复验后，attempt-private namespace仍依赖composition提供的exclusive trusted owner；同权限外部进程的主动注入不在supported baseline，generation checks不构成对抗性sandbox。
- Windows kernel API持续失败、assignment-failure suspended root无法终止、Job永不为空、pipe无法证明EOF、final source无法exclusive open或任一handle ownership进入`uncertain`时，模块不能伪造正常结果；它保持`UNSAFE_HOLD`/fail-safe路径，最终进程异常退出时才由`KILL_ON_JOB_CLOSE`兜底。
- 本合同没有用Job阻止不受信任descendant主动`AllocConsole`或创建breakaway process；锁定Codex runtime不做这些行为是ADR 0106的supported baseline。

## 17. Win32 语义依据

实现与测试应以Microsoft文档的以下语义为基线：

- [CreatePipe](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-createpipe)：`nSize`仅为suggestion；满buffer可阻塞writer；last write handle关闭后reader取得broken-pipe EOF。[GetNamedPipeInfo](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-getnamedpipeinfo) 可接受anonymous-pipe handle，并分别报告incoming/outgoing buffer size。
- [ReadFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-readfile) 与 [WriteFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-writefile)：同步I/O、pipe阻塞、zero-byte与`ERROR_BROKEN_PIPE`规则。
- [CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)：`lpCommandLine` 必须指向可写buffer且该函数可以修改其内容；[InitializeProcThreadAttributeList](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-initializeprocthreadattributelist) 与 [DeleteProcThreadAttributeList](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-deleteprocthreadattributelist)：初始化后生命周期与返回 `VOID` 的一次销毁。
- [Handle inheritance](https://learn.microsoft.com/en-us/windows/win32/procthread/inheritance) 与 [UpdateProcThreadAttribute](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)：`bInheritHandles`、`STARTF_USESTDHANDLES`与`PROC_THREAD_ATTRIBUTE_HANDLE_LIST`。
- [AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject)、[TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject) 与 [QueryInformationJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject)：assignment、全Job终止与active-process查询。
- [JOBOBJECT_BASIC_ACCOUNTING_INFORMATION](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)：`ActiveProcesses`含义。
- [WaitForMultipleObjects](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitformultipleobjects)：process/event wait与pending wait期间禁止关闭handle的要求。
- [GetExitCodeProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getexitcodeprocess)：只在process已终止后读取最终DWORD，且不能把`STILL_ACTIVE (259)`当作终态判据。

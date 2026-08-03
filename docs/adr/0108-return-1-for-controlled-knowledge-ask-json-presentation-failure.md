# 让可控的 knowledge.ask JSON presentation failure 静默硬终止为 1

`(gezhi.cli_result.v1, knowledge.ask)` 的 handled `--json` path 建立一个独立于业务 outcome table 的 `ControlledKnowledgeAskJsonPresentationFailureV1` terminal seam。它只有在 [ADR 0107](./0107-seal-one-bounded-immutable-knowledge-ask-json-buffer.md) 的 candidate 已以 matching token 成功 seal、exact triple 与 presentation disposition/payload 已 authoritative、所选 cancellation profile 的 accepted-in-flight 已归零、source-specific release/ownership proof 已完成并进入 `RELEASED`，且唯一同步 writer 没有 outstanding/pending I/O 或其他仍可能触碰 stdout 的执行单元时才适用。其 concrete Windows setup/write primitive、support profile 与调用边界由 [ADR 0109](./0109-use-binary-fd1-and-blocking-os-write-for-knowledge-ask-json.md) 冻结。它不是第五种 outcome、不是第八项 no-commit `failed`、不是 diagnostic，也不改变 Answer terminal state 或业务正常返回表。

受控集合恰好闭合为下表；除 `NO_OUTPUT_PRESENTATION_FAILURE` 外，其余行只适用于 sealed `READY_BYTES`：

| presentation fact | 必须成立的完成证明 | stdout 允许形态 |
|---|---|---|
| `NO_OUTPUT_PRESENTATION_FAILURE`，internal failure kind 为 `canonical_serialization_failed` 或 `stdout_cap_exceeded` | buffer/byte length absent，`RELEASED` 已证明，writer 从未启动 | 恰好零 bytes |
| binary stdout setup failure | 首次 write 前唯一 direct `msvcrt.setmode(1, os.O_BINARY)` 调用抛出 `OSError`；没有取得或遗留 setup-owned 第二 buffer、会继续写出的资源/执行单元或 pending operation，sealed authoritative buffer/read-only view 仍保持强引用 | 恰好零 bytes |
| synchronous write 返回 invalid count | 本次调用已结束；只有 `type(count) is int` 且 `1 <= count <= requested` 才有效，故 `bool`、其他非 `int`、`count <= 0` 或 `count > requested` 均无效；没有 outstanding/pending write 或会继续触碰 stdout 的执行单元 | 已交付部分只能是 authoritative buffer 从 offset zero 开始的 exact prefix |
| synchronous write 报告获准的 I/O failure，包括 broken pipe | 唯一 direct `os.write(1, current_view)` 调用抛出 `OSError` 及其子类；catch 只包住该调用，返回后没有 Gezhi-owned/background/overlapped pending write，任何已接受 bytes 只能来自本次传入的 exact remaining suffix | authoritative buffer 从零长度到完整长度的 exact prefix |

`READY_BYTES` 的每次同步调用必须令 `remaining = byte_length - offset`、`requested == len(current_request_view)` 且 `1 <= requested <= remaining`；只有 `type(count) is int` 且 `1 <= count <= requested` 才不是 failure。Writer 只按实际 count 推进 offset，并从同一 authoritative buffer/read-only view 建立下一段未写 suffix；`count < requested` 是合法 short write，`count > requested` 即使不大于 `remaining` 也无效。只有后续命中上表，才停止且使用本 ADR；若 `offset == byte_length`、末尾 LF 已被同步 primitive 接受且没有用户态 pending/flush bytes，presentation 已完整，必须改用 sealed business outcome 的既有正常 `0/2/1/130` table，不能再按本 ADR 重分类。能解析但缺少该规范末尾 LF 的 JSON 仍是不完整 presentation，不能构成本合同的 machine acknowledgment。

命中受控集合的检测是 presentation failure linearization point。唯一 adapter 必须不可逆锁存该 terminal fact、停止并禁止一切新 JSON write，并保持 sealed presentation payload 的身份到进程终止：`READY_BYTES` 继续强引用同一个 authoritative buffer/read-only view，`NO_OUTPUT_PRESENTATION_FAILURE` 则继续保持 buffer/byte length absent 与既有 sealed token/disposition；不得重写已确认 prefix、重开/切换/关闭 stdout 后重试、补 LF，或追加 fallback JSON、Human 文本或 stderr。此后恰好一次调用 `os._exit(1)`：不得普通 `return`、`sys.exit(1)`、raise 后由顶层转换，也不得运行 `finally`/context-manager cleanup、`atexit`、对象终结器或任何显式/隐式 stdout/stderr flush。[Python 3.11 对 `os._exit` 的定义](https://docs.python.org/3.11/library/os.html#os._exit)正是立即退出且不调用 cleanup handler、不刷新 stdio；这里在业务资源、cancellation source 与 presentation pending 状态都已先行证明结清后，刻意使用这条终端窄缝来保证静默 decimal `1`。

该 hard fail-stop 不得修改 sealed `outcome/result/diagnostics`、presentation disposition、Answer/manifest/commit、cleanup 或 cancellation state，不生成 primary/supplemental diagnostic，不保存 internal failure kind，不写日志、trace、telemetry 或持久资产，也不触发模型、领域操作、commit 或 presentation retry。它不是 handled normal return；`os._exit(1)` 之前不得再做可能失败或产生输出的工作。

这个 `1` 与完整合法 envelope 中 `outcome=failed` 的 normal exit `1` 只是数值偶合。调用方只有取得并验证包含规范末尾 LF 的完整 `CliResultEnvelopeV1`，才能按 envelope 内容解释业务 acknowledgment；零字节或 partial JSON 加 exit `1` 只证明本次 invocation 没有完整交付 machine acknowledgment，不能推断 sealed triple、Answer 是否 committed 或失败发生在哪一层。若底层异常/invalid count 与操作系统实际交付竞态导致调用方仍收齐并验证 exact full buffer（包括 LF），完整 receipt 本身仍是 acknowledgment，即使进程随后执行 `os._exit(1)`；exit `1` 不能覆盖已收到的 envelope 语义。Commit 后 presentation failure 不回滚 Answer；没有 acknowledgment 后直接重试仍可能创建第二个 Answer。反之，完整 receipt 已到达后发生的外部终止或 terminal-adapter 故障也不撤销该 process-level acknowledgment。

以下路径明确不进入本 exit seam：

- candidate identity/token、seal、phase、profile activation、zero-in-flight、matching removal、no-source never-registered、release 或 ownership proof 失败；这些仍在既有正常矩阵外；
- write/setup 尚未返回、completion/count 或 outstanding/pending I/O 不确定、仍可能追加 stdout bytes，或无法证明所有 writer 执行单元已静止；不得猜测成 broken pipe/invalid count 后执行 `os._exit(1)`；
- external/default Ctrl+C 实际终止、Task Manager、父进程/`TerminateProcess`、runtime termination、process crash，以及实际逃逸的 `BaseException`、`KeyboardInterrupt`、`SystemExit`、`MemoryError`、`AssertionError` 或 ADR 0109 direct-call `OSError` 之外的异常；Gezhi 不用广泛的 `except Exception`/`except BaseException` 捕获并改写为 `1`，保留真实 OS/runtime termination 或异常语义；
- exact buffer 已完整写完后的 crash、normal-exit adapter failure，或其他发生在 presentation completion 之后的异常；
- interpreter/import/CLI bootstrap、parser resource profile、unknown command/option、missing/repeated/conflicting argument、进入 handled adapter 前的 failure、bridge activation，以及 envelope/result/diagnostic construction 或 validation failure；其中 [ADR 0116](./0116-return-2-with-one-fixed-stderr-line-for-raw-argv-resource-violation.md) raw argv resource failure 仍不进入本 exit seam，而由自己的 fd2 presenter 正常返回 `2`；
- Human presentation、Literature、其他命令与未来 Bot，除非各自后续明确采用；supplemental diagnostics 与任何持久诊断也不在本 ADR 范围。

不得根据推测因果扩大这些排除项：若 prior/default handler 消费 Ctrl+C、进程继续，随后同步 stdout primitive 独立返回符合上表的 completed I/O failure，则只按该权威 write fact 执行 `os._exit(1)`；不能因为“可能与 Ctrl+C 有关”而改判。反过来，只有进程实际被外部/default/runtime 语义终止时才不存在应用级受控 hard fail-stop。

[ADR 0109](./0109-use-binary-fd1-and-blocking-os-write-for-knowledge-ask-json.md) 已冻结 concrete Windows primitive：只支持同步 console/普通文件/anonymous blocking byte pipe profile，首次 I/O 前一次 direct `msvcrt.setmode(1, os.O_BINARY)`，再由唯一 writer 以 direct blocking `os.write(1, whole_remaining_view)` 处理任意合法 short write；每个 `OSError` catch 只包住单个直接调用，不设置 timeout/nonblocking，不恢复 mode，也不建立 overlapped/background/thread-owned completion、第二用户态 buffer 或后续 flush。下游消费与普通文件 durability 不属于 completion proof。ADR 0116 已独立冻结 raw argv resource failure 的 fd2/return-`2` contract；其余 parser/bootstrap/internal/argument exit、Human 文案/bytes/exit、supplemental variants、持久 diagnostics 及本 ADR 其余明确排除项继续待决。本决策不增加 CLI 字段、stderr 输出、依赖、配置、Answer 资产、日志或 runtime model call。

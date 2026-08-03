# 为 knowledge.ask JSON 封存一个有界不可变输出缓冲区

`(gezhi.cli_result.v1, knowledge.ask)` 的 handled `--json` path 必须把 presentation preparation 纳入 [ADR 0100](./0100-seal-the-handled-cancellation-window-before-presentation.md) 与 [ADR 0101](./0101-use-a-project-owned-native-win32-ctrl-c-bridge.md) 的同一 candidate/seal 协议：领域执行与适用的 committed/no-commit safe-finalization 完成后，唯一主编排器在 `ACCEPTING` 中取得 coherent cancellation snapshot，构造并验证 exact candidate `outcome/result/diagnostics`，组装并验证完整五字段 envelope，随后才为该 snapshot 准备一次 JSON presentation candidate。Human mode 不构造该 JSON candidate、不受本 ADR 的 65,536-byte cap；Literature、其他命令与未来 Bot 也不能静默继承本 concrete binding，必须先用自己的 result/diagnostic 合同证明边界并显式采用。

正常候选固定为 `READY_BYTES`。每个 candidate generation 最多执行一次以下完整、非 streaming serialization；不得拼接 JSON 字符串、直接嵌入 `answer_output.json` raw bytes、增量输出或在多个 serializer 结果之间选择：

~~~python
json.dumps(
    envelope,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8") + b"\n"
~~~

`PreparedKnowledgeAskJsonCandidateV1` 的 `READY_BYTES` 分支必须一次性不可变绑定 expected generation、fresh nonzero/non-reused/non-wrapping candidate token、exact validated triple、完整 envelope value、该唯一 canonical `bytes` object 与其 exact byte length。Token 不进入 CLI、diagnostic 或持久资产。成功 seal 后该 buffer 由 pending slot 强引用，至少保持到完整写出与 normal-return exit 决定完成，或进程被外部/default 语义终止；不得重新组装 outer、重新验证/读取 Answer 资产、重新序列化、替换 buffer，或仅凭值相同接受另一个 bytes object。

Cap 独立固定为完整 buffer 最多 65,536 raw UTF-8 bytes，边界包含：从首个 `{` 到唯一末尾 LF 的全部 bytes 都参加计数，65,536 合法，65,537 拒绝。它与 Answer `manifest.json` 的 65,536-byte cap 数值相同但合同所有者、对象与证明相互独立，不是继承关系。不得为适配 cap 截断、压缩、删减 result/diagnostics、再次运行 omission、改变 outcome、把 AnswerOutput 改成摘要、重试 serializer 或启动模型重答。

现有闭合合同给出保守可证明上界，而不是可达最大值证明。令 `A` 为嵌入的 `canonical_json(answer_output)` 长度，不含其正式文件 LF，则 `A <= 32,767`；令 `D` 为完整 canonical diagnostics array 长度，则 `D <= 16,384`。唯一允许非空 AnswerOutput 的 committed `succeeded` 分支，在排除 `A` 与 `D` 后的固定 outer/result/40-byte Answer ID/末尾 LF 共 187 bytes，因此：

~~~text
len(stdout_buffer) <= A + D + 187
                   <= 32,767 + 16,384 + 187
                   = 49,338 bytes
~~~

65,536-byte cap 因而保留至少 16,198 bytes 余量；当前 generation 的任一合法 `knowledge.ask` envelope 必然可容纳。运行期 cap 超限只能表示 contract、serializer 或 implementation invariant 破坏，不是 Question/Answer 太大、blocked/failed 业务 cause 或可通过缩减输出恢复的分支。未来改变 AnswerOutput、result、diagnostics 或 outer 的边界时必须重新证明完整上界；不能只保留本数值而放宽子合同。

Interactive profile 先以 coherent snapshot 的 generation 构造完整 candidate，再调用 generation-checked conditional seal。Callback 在 serialization 期间、cap 通过后或 seal 前先赢 admission，或 admission publication 尚未形成 coherent proof 时，seal 必须返回 retry；编排器必须废弃整个 pending candidate、buffer 与 token，重新消费 latch、服从既有 ID/commit/terminal-cause 和 `failed > interrupted > blocked` 仲裁，并从新的 coherent snapshot 构造全新 candidate。旧 buffer 即使 bytes 恰好相同也不得复用。只有 native seal 在同一 atomic gate 先赢且 `sealed_candidate_token` 精确匹配仍不可变存活的 pending slot 时，exact triple、presentation disposition、envelope、buffer 与 byte length 才共同成为 authoritative。持续 callback 竞争可以持续阻止 seal，不得以 retry 次数上限绕过 generation proof。

No-source profile 使用同一 pending-candidate union 与一次性 token binding，只是 expected generation 固定为零且唯一主线程执行逻辑 seal；它仍必须先形成完整 `READY_BYTES` candidate，再锁存 exact triple、disposition、envelope、buffer 与长度，并完成 `source=none`、zero-in-flight、latch unset、observation absent 与 never-registered release proof。两种 profile 都禁止在 `RELEASED` 前写出任何 stdout byte；buffer formation 是无 I/O 的 presentation preparation，不是 presentation write。

若 exact triple 与完整 envelope 已验证，但本 generation 的 canonical serialization 失败或 buffer 超过 cap，编排器不得伪造新 outcome/diagnostic 或让 cancellation source 留在 `ACCEPTING`。只要能够证明没有 stdout byte、OS handle、pending I/O 或其他 presentation resource 被取得或遗留，它必须为同一 generation 建立 `NO_OUTPUT_PRESENTATION_FAILURE` candidate：该分支不可变绑定 expected generation、fresh token、exact triple、完整 envelope、闭合的 invocation-local failure kind `canonical_serialization_failed` 或 `stdout_cap_exceeded`，并明确令 buffer 与 byte length absent；不得用 `b""` 冒充 absent。Cap 超限时必须先从 pending state 丢弃 oversized temporary buffer，才能安装 absent-buffer candidate；serialization failure 不得通过捕获 `BaseException` 或 `KeyboardInterrupt` 把外部/default/runtime termination 翻译成该分支。它与 `READY_BYTES` 是唯一两个 presentation dispositions。Callback 先赢时整项 failure candidate 同样废弃并重新仲裁；seal 先赢后照常 drain/release，进入 `RELEASED` 后恰好写零 stdout bytes，并按 [ADR 0108](./0108-return-1-for-controlled-knowledge-ask-json-presentation-failure.md) 恰好一次执行无 cleanup/flush 的 `os._exit(1)`，绝不使用 triple 的正常 `0/2/1/130` exit table。Failure kind 不进入 JSON、Human、diagnostic、Answer、manifest、日志、trace、telemetry 或持久资产，也不保存异常文本。无法安装/证明该最小 failure candidate 或无法证明临时准备状态已结清时保持正常矩阵外。

`READY_BYTES` 只有在 `RELEASED` 后才交给共享 JSON writer。Writer 必须使用无用户态待 flush bytes 的 binary unbuffered stdout primitive，从 offset `0` 开始，以 exact buffer 的 read-only view 每次只请求尚未提交的 suffix，不得用 `buffer[offset:]` 复制出第二份 bytes。每次调用必须满足 `remaining = byte_length - offset`、`requested == len(current_request_view)` 与 `1 <= requested <= remaining`；只有 `type(count) is int` 且 `1 <= count <= requested` 时才推进实际 count，`bool` 无效，`count < requested` 是合法 short write。Zero/negative/其他非整数、returned count 大于 request、获准 I/O failure、broken pipe 或 stdout binary/unbuffered setup failure 都立即终止本次 presentation；不得重写已确认 prefix、重开 stdout、改用第二份 buffer、追加 fallback JSON/Human/stderr 文本或修补末尾 LF。只有 `offset == byte_length`、同步 primitive 已接受 exact buffer 包括最后 LF 的全部 bytes，且没有用户态 pending/flush bytes 时，才算完整 JSON presentation 并允许既有 outcome-to-exit table；能解析但缺少末尾 LF 仍不是完整 acknowledgment，这也不承诺下游已读取或持久化。[ADR 0108](./0108-return-1-for-controlled-knowledge-ask-json-presentation-failure.md) 已要求 setup/write failure 只有在 operation completed、无 outstanding/pending write 且没有其他 writer 时，停止所有新 write 并恰好一次 `os._exit(1)`；[ADR 0109](./0109-use-binary-fd1-and-blocking-os-write-for-knowledge-ask-json.md) 已进一步冻结实际 primitive 为一次 direct `msvcrt.setmode(1, os.O_BINARY)` 后、对同一 `bytes` read-only view 的 direct blocking `os.write(1, whole_remaining_suffix)`，只捕获各直接调用边界的 `OSError`，不设置 timeout/nonblocking、不建立 overlapped/background completion 或第二层需另行 flush 的缓冲。

Seal 后的 external/default Ctrl+C、Task Manager、父进程终止或 runtime termination 可以在 release 或写出期间留下零字节、exact buffer prefix 或完整 buffer；它们不得反向改变 sealed triple/disposition、重新 cleanup/commit、生成 interrupted、追加 fallback 或让 Gezhi 选择应用级 `130`。Serialization/cap/no-output、stdout setup/write/broken-pipe 都属于 presentation plane，不回写领域状态、Answer 或 diagnostics。完整 receipt 到达前的零/partial stdout 仍不能证明 Answer 未提交；完整 receipt 到达后也不改变既有 process-level acknowledgment。ADR 0108 已冻结其中成功 seal/release 且完成状态确定的可控 JSON presentation failure 为静默 exit `1`；外部实际终止、pending/completion 不确定路径仍不得改写。Bootstrap/argument/parser resource profile、envelope/result/diagnostic 构造失败、Human bytes/文案/exit、supplemental diagnostics 与持久诊断继续由后续决策冻结。

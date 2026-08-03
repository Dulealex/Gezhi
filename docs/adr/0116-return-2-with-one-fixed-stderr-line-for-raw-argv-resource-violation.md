# 用一行固定 stderr 与 exit 2 呈现 raw argv 资源超限

对结构合法的 [ADR 0113](./0113-feed-one-immutable-argv-snapshot-to-preflight-and-typer.md) immutable snapshot，`RawArgvPreflightV1` 的封闭返回类型固定为无 payload 的 `RawArgvPreflightVerdictV1 = PASS | RESOURCE_LIMIT_EXCEEDED`。[ADR 0115](./0115-cap-raw-argv-at-128-arguments-8192-elements-each-and-16384-total.md) 三个超限谓词任一为真时返回 `RESOURCE_LIMIT_EXCEEDED`，三者都为假时返回 `PASS`；预期的资源超限通过返回 variant 表达，不抛异常。该 variant 不携带 count/per-token/aggregate dimension、token index、observed value、limit、argv0、command 或任何原始 token 内容。Malformed/empty/non-`str` snapshot、snapshot allocation/`MemoryError`、preflight implementation/invariant failure 与其他异常不得被 catch 后映射成这个 variant。

`RawArgvPreflightV1` 本身继续保持 [ADR 0110](./0110-run-a-decoded-argv-resource-preflight-before-typer.md) 的纯机械判定与无 I/O 职责。只有最小 `gezhi.bootstrap:main` 收到 `RESOURCE_LIMIT_EXCEEDED` 后，才调用 bootstrap-owned resource-failure presenter；该 presenter 仍位于 [ADR 0111](./0111-lazy-import-the-cli-framework-and-command-graph-after-argv-preflight.md) 的 pre-Typer/Rich/command-graph import closure 内，但不是 preflight 的一部分。私有 module/function 名称仍由实现隐藏，不能让 Literature、Knowledge 或未来 Bot 分别拥有 writer。

Presenter 的唯一 authoritative payload 是源码中的 56-byte ASCII `bytes` constant：

~~~python
b"gezhi: error: command-line input exceeds safety limits\r\n"
~~~

正常完整 presentation 必须令 Gezhi-owned stdout 恰好为零 bytes，stderr 恰好为上述 bytes：固定 lowercase 产品名 `gezhi`、无 BOM、ANSI、JSON、usage、help、traceback、dimension/limit 说明、额外空格或第二个换行。产品名不得从 argv0、launcher path 或 token 派生；payload 不得在运行时 `.encode()`、格式化、拼接、翻译或加入动态数据。字面 `--json`、help/version spelling、known/unknown command 与任意其他 token 都没有特殊语义，因为 command grammar 尚未开始。

Windows V1 presenter 对 CRT fd `2` 使用一条独立于 [ADR 0109](./0109-use-binary-fd1-and-blocking-os-write-for-knowledge-ask-json.md) 的同步 binary writer 路径。它先恰好一次直接调用 `msvcrt.setmode(2, os.O_BINARY)`；成功后只由当前 bootstrap thread 以 direct blocking `os.write(2, whole_remaining_view)` 写同一个 fixed payload，并按每次实际返回 count 推进 offset，直到全部 56 bytes 被接受或 presentation 已确定失败。每次 request 必须恰好覆盖当前 remaining suffix；只有 `type(count) is int` 且 `1 <= count <= requested` 合法，`count < requested` 是合法 short write，boolean、其他类型、`count <= 0` 或 `count > requested` 都是 invalid count。不得使用 `sys.stderr`、`print`、text encoding/newline translation、flush、close、dup/rebind、`WriteFile`、`WriteConsoleW`、第二 writer、timeout、nonblocking setup、thread/task、overlapped I/O 或 background completion，也不恢复 fd `2` 的 text mode。

受支持 endpoint profile 是启动时继承且未被项目重绑的同步 Windows console、普通文件或 anonymous blocking byte pipe。一次成功 `os.write` 只证明返回 count 对应的 bytes 已被同步调用接受，不承诺下游已经消费或普通文件已经 durable；下游不消费时 writer 可以阻塞到下游恢复或进程被外部终止。项目不探测或修复范围外的 inherited nonblocking/exotic endpoint；实际返回的 `BlockingIOError` 仍按 `OSError` failure 处理。

Presentation 与 exit 的闭合矩阵如下：

| completed fact | Gezhi-owned stderr | Gezhi-owned stdout | `gezhi.bootstrap:main` |
|---|---:|---:|---:|
| `setmode` 与全部 writes 成功 | exact 56 bytes | 0 bytes | return `2` |
| direct `setmode` 抛 `OSError` | 0 bytes | 0 bytes | return `2` |
| direct `os.write` 在 offset `k` 抛 `OSError` | exact payload prefix `[0:k]` | 0 bytes | return `2` |
| direct `os.write` 返回 invalid count | 已确认的 exact payload prefix | 0 bytes | return `2` |

每个 `OSError` catch 只包住相应的一次 direct call；`BrokenPipeError` 与 `BlockingIOError` 因为是其子类而包含在内。Setup/write/invalid-count failure 后不得 retry setup、恢复 mode、切换 endpoint、写 stdout、追加第二条 stderr、生成 JSON/traceback、记录日志或调用 `os._exit`；已经交付的 prefix 不可回滚。Presenter 无论完整、零或部分写出都让 `main()` 普通返回整数 `2`，两个 [ADR 0112](./0112-package-gezhi-with-two-launch-adapters-and-one-bootstrap-seam.md) launcher 必须原样把该结果变成 process exit。非 `OSError` 的意外异常、`MemoryError`、`KeyboardInterrupt`、`SystemExit`、其他 `BaseException`、尚未返回的 blocking I/O 或外部实际终止不被捕获或伪装成正常 resource presentation/exit `2`。

这个 decimal `2` 是独立的 pre-command bootstrap resource-failure exit，不是 Typer parser classification、Knowledge `blocked`、`CliDiagnosticItemV1`、Human handled result、`CliResultEnvelopeV1` outcome 或 [ADR 0108](./0108-return-1-for-controlled-knowledge-ask-json-presentation-failure.md) presentation state。调用方不得只凭 exit `2` 推断具体 failure；Knowledge handled `--json` 的 `blocked=2` 必须伴随完整合法 stdout envelope，而本路径 stdout 恒空。它不建立 cancellation profile/latch、Answer identity、cleanup、persistent diagnostic 或 machine-readable bootstrap envelope。

Count、per-token 与 aggregate 单独或同时超限都产生同一个无 payload variant、同一 fixed line 与同一 exit，因此公开合同不存在 dimension selection、observed/limit disclosure 或多维优先级。实现可以按 ADR 0115 安全短路，但不得让短路顺序改变可观察输出。未来若要增加 machine-readable bootstrap failure、公开具体 limit、中文/本地化消息或 dimension-specific remediation，必须另行版本化，不得根据 literal `--json` 静默扩张本合同。

Contract tests 必须覆盖：三个维度各自和同时超限都返回 exact no-payload variant；PASS 不调用 presenter；malformed/internal/`MemoryError` 不被误映射；两个真实 launcher 对普通、literal `--json`、help/version 与 known/unknown spelling 的超限 invocation 都产生 empty stdout、exact ASCII CRLF stderr 与 exit `2`，且不 import/call Typer、Rich、command graph、parser 或领域 adapter。Writer tests 必须覆盖一次 setup、单次完整写、多次 short write 的 remaining-suffix identity、setup `OSError`、首写 `OSError`、partial 后 `OSError`、`bool`/`None`/`0`/负数/`>requested` invalid count、closed fd2/broken pipe、非 `OSError` 与 blocking/external termination 的不同语义，以及任何失败都没有 stdout/fallback/flush/restore/`os._exit`。Binary fd mode 是进程级状态，真实 fd 测试必须在独立 subprocess 中运行，不能污染可复用 test runner。

本 ADR 闭合且授权 ADR 0115 resource violation 的 production classification、dimension non-disclosure、固定文案/bytes、stderr channel、writer completion/failure 与 exit；它不增加依赖、配置、CLI option、diagnostic code、持久资产、日志、telemetry 或模型调用。Malformed snapshot 与其他 bootstrap/import/internal failure、Typer parser/argument failure、handled Human presentation、ADR 0108 其余排除项、future machine-readable bootstrap protocol，以及 exotic/nonblocking stderr endpoint 的支持仍待独立决定，不能复用 `RESOURCE_LIMIT_EXCEEDED` 或本 presenter 作为 catch-all。

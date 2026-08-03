# 将 argv[0] 完全排除在 RawArgvPreflight 资源计量之外

[ADR 0113](./0113-feed-one-immutable-argv-snapshot-to-preflight-and-typer.md) 冻结的完整 immutable `argv_snapshot: tuple[str, ...]` 继续是 `RawArgvPreflightV1` 的输入；本 ADR 只冻结它向资源计量投影哪些 index，不把 preflight 的 interface 改成 suffix-only。对每个结构合法的受支持 invocation，全部当前与未来 RawArgvPreflight resource measurement 的唯一 domain 是 snapshot indices `1..n`，也就是概念上的 argument suffix；index `0` 保留在完整 snapshot 中，但对资源计量恒无贡献。

Argument-count measurement 精确计算 suffix token 数；空字符串、`--`、option、value、known/unknown token 都各算一个 token，不执行语义合并。[ADR 0115](./0115-cap-raw-argv-at-128-arguments-8192-elements-each-and-16384-total.md) 的 per-argument ceiling 只逐项应用于 indices `1..n`，aggregate ceiling 也只聚合这些 index。`argv[0]` 不计入 argument count、不接受 per-argument ceiling、不贡献 aggregate measurement，也不设置独立 argv0 resource ceiling；固定 `prog_name="gezhi"`、launcher 名称、executable path 或其他 metadata 都不得作为 argv0 的替代 pseudo-token 重新加入计量。

因此，对任意两个结构合法的 snapshots，只要 index `1..n` 的 token 值、Unicode 内容、数量与顺序逐项完全相同，全部资源 measurement 与 resource verdict 就必须完全相同，不受 `argv[0]` 的值、长度、Unicode 内容、路径形状或来自 console script/`python -m gezhi` 哪个 launcher 的影响。即使 index `0` 单独超过 ADR 0115 的 `8192` 或 `16384` 数值，也不得据此形成 resource violation；同一内容一旦位于 suffix，则按 ADR 0115 的正常边界处理。Typer 仍只接收 ADR 0113 的 exact `argv_snapshot[1:]`，不得重新插入 argv0 或由 argv0 派生 program name。

排除 argv0 只是项目 preflight 的政策计量，不承诺保护 Windows raw command line、`CreateProcessW`、CPython argv allocation/decoding、`site`、entry stub 或 snapshot tuple 形成前已经发生的成本与失败，也不表示操作系统允许无限长 launcher token。缺失或非 `str` 的 argv0、空或其他异常 `sys.argv` shape/type、snapshot allocation/`MemoryError`、measurement implementation failure 继续属于 ADR 0110/0113 尚未冻结 presentation/exit 的 bootstrap/internal boundary：不得因为 argv0 不计量而自动 PASS，也不得冒充 resource violation、parser argument failure 或 Knowledge outcome。

本 ADR 不冻结异常 snapshot 的具体处置；argument-count/per-argument/aggregate 的数值、`len(str)` 单位、不含 separator/quote/fixed overhead 的精确 aggregate 与 inclusive 判定已由 ADR 0115 冻结，[ADR 0116](./0116-return-2-with-one-fixed-stderr-line-for-raw-argv-resource-violation.md) 又冻结单项或多维同时超限都使用同一个无 payload verdict、无公开维度/observed/limit/优先级、固定 stderr 与 exit `2`，并授权 production rejection。内部检查顺序仍是不可观察的 implementation detail。Shell completion 已由 ADR 0113 独立关闭，不构成本计量 domain 的例外或第二套 arguments。

Contract tests 必须证明：短、长、Unicode 与两个真实 launcher 自然形成的不同 argv0，在 exact suffix 相同时产生完全相同的 measurement；`("launcher",)` 的 argument count 为 `0`，而 `("launcher", "")` 为 `1`；ADR 0115 每个 count/per-argument/aggregate 边界的 `limit - 1`、`limit`、`limit + 1` witness 都加入只改变 argv0 的对照且 verdict 不变；超长内容只位于 argv0 时不能触发任何超限 predicate，移入 suffix 后才服从对应 ceiling。Malformed/missing/non-string argv0 测试只能证明进入独立 internal boundary，不能断言 resource PASS 或构造 resource violation；两个真实 launcher 的验收不得把 Windows/CPython 启动前失败误报为 preflight rejection。

该选择以不为 launcher token 提供项目级资源拒绝为代价，换取 console script 与 `python -m gezhi` 对同一用户 argument suffix 的完全一致计量，并避免用一个在 preflight 前已经分配、不会交给 Typer parser、且形状受 launcher/install path 影响的 token 制造无效安全感或环境相关拒绝。

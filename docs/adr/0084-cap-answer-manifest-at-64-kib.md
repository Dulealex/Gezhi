# 将 Answer manifest 原始文件限制为 64 KiB

`gezhi.answer_manifest.v1` 为完整 `manifest.json` 固定 raw-byte cap `ANSWER_MANIFEST_MAX_BYTES = 65_536`。计数对象是文件从第一个 byte 到 EOF 的原始序列，包含 ADR 0082 要求的唯一末尾 LF，也包含随后会因 BOM、CR、编码、framing 或 JSON 规则被拒绝的任何 byte。实际长度 `0..65_536` 只表示通过容量门禁，仍须通过全部其他验证；只有确认存在第 `65_537` 个 byte 才是超限，长度恰好 `65_536` 合法，因此一个规范文件中末尾 LF 之前的 JSON payload 最多 `65_535` bytes。不得截断、只解析 prefix、丢弃 BOM/空白后计数或把超限文件规范化成较短版本。

该数值是 v1 新增的 aggregate validity condition，不宣称由各字段现有上限推导出 manifest 的精确数学最大值。Writer 必须按 ADR 0082 恰好序列化一次形成包含末尾 LF 的 immutable canonical byte buffer，在 ADR 0087 direct exclusive-create 字面 `manifest.json` 前对该 buffer 执行 `len(bytes)` 门禁，并把通过检查的同一 byte sequence 写入唯一 handle；不得检查一份后再次序列化另一份。超限时不得创建最终 manifest、不得提交 Answer 目录，也不得改变已经锁存的 Answer terminal cause。若本次新 Answer 因此无法 commit、root trust 仍成立且能够安全停止，ADR 0095 固定以 no-commit `knowledge.ask.answer_manifest_failed.v1` 对外报告；否则遵守其正常矩阵外边界。

共享 reader 在通过既有安全路径边界打开字面 `manifest.json` 后，必须循环读取同一 binary handle，直到观察到 EOF 或累计取得 `65_537` bytes；short read 本身不等于 EOF。取得第 `65_537` byte 时立即把 manifest 判为超限，不再读取、解码或解析；只在累计不超过 `65_536` 且明确观察到 EOF 时，才保留这份完整 raw bytes 依次进入 ADR 0082 的 BOM/framing 与 strict UTF-8、ADR 0086 的 structural preflight 与 strict hooks parse、当前 Schema、canonical round-trip 与后续 asset 验证。不得只相信路径元数据中的预报长度，也不得在 cap 门禁前无界读取整个文件。

Writer 的 write handle 成功关闭后必须用同一 reader 重读，因此写前与写后都执行相同边界。Crash recovery 与正式 committed-Answer reader 也复用该 reader；超限 staging 原字节原位置隔离且不得补交或修短，已提交目录中的超限 manifest 整体拒绝。Cap failure 不生成第十二个顶层字段、不变造 `status` / `error`、不新增 manifest 内部 error code，也不授权删除、重写或移动现场。

该 cap 是版本化 manifest 文件合同常量，不进入 `effective_config.json`、manifest 顶层、`assets`、asset item、marker 或 sidecar。它与 eligible `final_message.txt` 恰好相同的 `65_536` validation budget 是两个独立常量，不共享错误分类、overflow 语义或实现配置。以后改变数值或包含边界必须演进 Answer manifest Schema；由于版本只能在 JSON parse 后得知，支持更大未来版本的新 reader 还必须显式提高自己的外层 pre-parse 上限，并在解析后继续对 v1 强制 `65_536`，旧 v1 reader 仍安全拒绝更大文件。有界 parser profile 已由 ADR 0086 独立冻结，direct exclusive-create leaf formation 已由 ADR 0087 冻结，V1 不承诺断电 durability 的边界已由 ADR 0088 冻结；本 ADR 不冻结根级资产 identity 或外部诊断，也不新增第三方依赖。

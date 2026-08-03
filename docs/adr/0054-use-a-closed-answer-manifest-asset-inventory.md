# 使用封闭的 Answer manifest 资产清单

每个终态 Answer 根目录固定以 `manifest.json` 作为 terminal manifest，顶层 `schema_version` 严格等于 `gezhi.answer_manifest.v1`，并在必填 `assets` 数组中按 `path` 的 UTF-8 bytes 升序列出除 manifest 自身外的全部普通文件；每项只包含安全且唯一的 `/` 分隔相对 `path`、严格落在 `0..9223372036854775807` 的实际 JSON integer `byte_length`、实际 64-character lowercase hexadecimal `sha256`，以及恰好一个 `schema_id` 或 `media_type`。验证时，目录中除根级 `manifest.json` 外的普通文件集合必须与 `assets` 完全相等，不能缺失、额外、重复或通过符号链接、junction、reparse point、绝对路径、反斜杠、`.`/`..` 逃逸；路径还必须解码为 Unicode scalar value 序列，并以首个点之前的 basename 拒绝 Windows 保留设备名，同时拒绝冒号、尾随点/空格和 ordinal-ignore-case 别名，发现任何 reparse entry 直接失败。支持 named streams 的 Windows volume 必须进一步证明 Answer 根、所有目录与文件没有任何 alternate data stream。manifest 不列出自身，也不保存自哈希。新增持久审计文件属于 Answer manifest Schema 演进，旧读取器必须拒绝未知 `schema_version`，以扩展必须显式版本化为代价，使原子提交与 crash recovery 能证明目录资产闭合且每个文件可按原始字节复验。

ADR 0085 进一步要求 `byte_length` 必填且非 `null`：JSON boolean、float、string、`null`、负数或大于 `9223372036854775807` 的值都无效，不能转换、clamp、wrap 或补值。该类型与范围必须在使用任何 asset path 之前通过；随后记录值仍须精确等于对应普通文件未命名主数据流的实际逻辑 byte 数。该通用范围不是读取预算，任何路径专属较小 cap 都优先；改变字段类型、上下界或包含边界必须演进 Answer manifest Schema。

Manifest 自身虽然不进入资产清单，仍必须独立满足 ADR 0082 的规范 JSON 原始 bytes 与 ADR 0086 的有界 parser profile：共享 reader 完成 raw cap、framing/strict UTF-8、structural preflight、strict hooks parse 与当前 Schema 后，按相同 Python 3.11 serialization profile 重序列化并要求 byte-for-byte 相等。该门禁不引入 manifest 自长度、自哈希或 sidecar，也不允许 validator/recovery 自动 canonicalize 一个 profile-invalid 或非规范文件。

ADR 0087 进一步要求 manifest 只在全部列入 `assets` 的文件与全部私有临时 entry 已经闭合后，对字面 `manifest.json` direct exclusive-create；它不产生 manifest temp、backup、marker 或 sidecar。写后 reader 仍须重新证明完整目录恰好等于“字面 manifest 加 `assets` 清单”，然后关闭全部 handle，目录改名才可发布。

ADR 0088 下，正式 target 即使在断电前已经完成进程级目录提交，后续 reader 仍须对当前实际 bytes 重新执行本 ADR 的完整闭合验证；无效、partial 或非法 target 整体拒绝并保持不可变，不读取部分资产、不修复，也不回退到同身份 staging。该规则保留完整性，但不把目录分类为断电持久。

ADR 0083 进一步把 manifest root 封闭为十一项全部必填的顶层 key，并设置 root `additionalProperties=false`；本 ADR 继续只拥有 `schema_version` 常量、`assets` 顶层 array 及 asset item/目录闭合规则。`assets` 顶层自身不得为 `null`，任何新增顶层 key 或持久资产类型都必须经过相应 Schema 版本演进。

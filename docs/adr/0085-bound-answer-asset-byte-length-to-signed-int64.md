# 将 Answer asset byte_length 限定为非负 signed 64-bit integer

`gezhi.answer_manifest.v1` 的每个 `assets[*].byte_length` 都是必填且非 `null` 的 JSON integer，合法闭区间固定为 `0..9223372036854775807`。`0` 与 `9223372036854775807` 都合法；JSON boolean、float、string、`null`、负数以及大于 `9223372036854775807` 的值都无效。Python 实现必须检查 exact integer type，不能因 `bool` 是 `int` 的子类而接受 `true` / `false`，也不得用字符串转数、浮点转换、clamp、wrap、saturate、取模或 unsigned reinterpretation 修复越界值。类型与范围属于 Schema 验证，必须在使用任何 asset path 之前通过。

该字段必须精确等于对应普通文件从起点到逻辑 EOF 的未命名主数据流 byte 数，`0` 表示合法空文件；它不是 NTFS allocation size、压缩后大小、稀疏文件实际占盘、目录项大小或 alternate data stream 总量。目录、链接、reparse entry 与 alternate data stream 继续不是合法 asset。无法取得可证明的实际逻辑长度，或声明值与实际值不一致时，整个 manifest 无效；声明值只用于精确比较，不能作为预分配、无界读取或跳过实际长度与 SHA-256 复验的授权。

`0..9223372036854775807` 只是所有 asset item 的通用表示域，不是单文件读取预算、`assets` 合计 quota 或整个 Answer 的容量承诺。任何已冻结或以后随版本冻结的路径专属较小 byte cap 都与该范围取交集，并由较小上限优先；尤其 `attempts/NN/events.jsonl` 的 `0..16777216` 与 `attempts/NN/final_message.txt` 的 `0..1048576` 不被本决策扩宽，既有包含端点、`cap + 1` witness、exact-prefix retention、usage 与终态分类语义全部不变。

`manifest.json` 不列入 `assets`，因此没有自身的 `byte_length` item；ADR 0084 对 manifest 完整 raw bytes 的 `65_536` cap 与本字段范围彼此独立。以后改变 `byte_length` 的类型、上下界或包含边界必须演进 Answer manifest Schema。有界 parser profile 已由 ADR 0086 冻结，direct exclusive-create leaf formation 已由 ADR 0087 冻结，V1 不承诺断电 durability 的边界已由 ADR 0088 冻结；Answer 资产逐路径与整目录读取额度已由 [Answer Terminal v1](../contracts/answer-terminal-v1.md) 冻结，外部诊断仍由其所属命令合同决定。本决策不增加 manifest 字段、asset、sidecar、配置项、错误码或第三方依赖。

# 为 Answer manifest 冻结有界 parser profile

`gezhi.answer_manifest.v1` 的共享 terminal-manifest reader 固定使用下列 parser resource ceilings；全部上限都包含端点，只有出现 `limit + 1` witness 才因对应门禁拒绝：

| 计数项 | inclusive maximum |
|---|---:|
| container depth | `8` |
| 单个 object 的 pairs | `16` |
| 全文 object pairs | `128` |
| 单个 array 的 items | `16` |
| 全文 array items | `32` |
| object 与 array containers 合计 | `32` |
| JSON value nodes 合计 | `256` |
| integer token 的 ASCII decimal digits | `19` |

Container depth 只由 object/array 嵌套决定：root object 或 root array 的 depth 是 `1`，scalar 不增加 depth。每个 object 或 array value 各算一个 container；root value 也算一个 value node。Object pair 按原文中每次 decoded key/value occurrence 计数，unknown 与 duplicate pair 在被拒绝前也分别计数；object key 自身不是 value node。Array item 按每次元素 occurrence 计数。Value node 是 root，以及每个 object member value 和 array element 各一次，所以对单一合法 JSON tree 恒有 `nodes = 1 + total_pairs + total_array_items`。所有计数器都是每次 reader 调用私有、从零开始且不会在 `limit + 1` 前回绕的整数。

在 ADR 0084 的完整 raw-byte cap、ADR 0082 的 BOM/framing 与 strict UTF-8 decode 通过后，reader 必须先对去掉唯一末尾 LF 的完整 decoded payload 做 quote/escape-aware structural preflight，再建立 Python JSON object/list。Preflight 只把 JSON string 外的结构标记当作结构，维护 container stack，并对上述 depth、pairs、array items、containers 与 nodes 执行精确计数；每个 stack frame 还必须记录 object/array kind 与当前 grammar expectation，只有语法位置上的 value start 才增加相应 node、pair 或 item，不能仅在 string 外机械统计冒号或逗号。String 内的 `{`、`[`、`]`、`}`、`:`、`,` 以及 escaped quote 都不得改变计数。禁止用正则、朴素字符频次或不理解 string/escape 的括号计数替代。Preflight 只能提前拒绝，不能接受、修复或规范化 JSON；完整语法仍由随后唯一的 strict JSON parse 判定。

Strict parse 显式使用 `json.loads(..., strict=True, ...)` 与每次调用私有的 Python 3.11 hooks。`parse_int` 在调用 `int()` 前取得完整 integer token，按 ASCII `0-9` 计算 digits，optional leading `-` 不计入 `19`；第 `20` 个 digit 立即拒绝。通过 digit 门禁不代表字段合法：负数以及 `9999999999999999999` 等 19-digit 越界值仍须由当前 Schema 的字段专属范围拒绝。`parse_float` 对任何含 fraction 或 exponent 的 JSON number token 直接拒绝，所以 `0.0`、`1e0` 与 `-0.0` 都不能转换成 integer；`parse_constant` 拒绝 `NaN`、`Infinity` 与 `-Infinity`。不得依赖或修改进程全局 `sys.set_int_max_str_digits`、`sys.setrecursionlimit` 或其他全局解释器开关来实现合同。

`object_pairs_hook` 必须基于 parser 提供的完整 ordered pair list，在生成普通 mapping 前再次验证单 object 与全文 pair 计数，并拒绝任意允许深度上的 decoded-key duplicate。Duplicate 比较大小写敏感且不做 Unicode normalization；例如 `"a"` 与 `"\u0061"` 解码后是同一个 key，必须拒绝。结构 preflight 之后的迭代式 tree walk 可以防御性复核 array、container、node 与 depth 计数，但不能替代解析前门禁，也不能在检查前投影 Schema、丢弃 unknown 字段或合并 duplicate pair。

完整顺序固定为：从同一安全 binary handle 执行 ADR 0084 的 `65_536`-byte raw cap并确认 EOF；验证 ADR 0082 的 BOM/CR/LF framing；去掉唯一末尾 LF并 strict UTF-8 decode；执行本 ADR 的 structural preflight 与 strict hooks parse；确认唯一顶层 JSON object；完成本 ADR 的全部计数复核；验证当前 Schema 与 path 字段自身安全性；执行 canonical reserialization 并要求 raw bytes byte-for-byte 相等；最后才允许用 manifest 值构造或打开 asset path。Canonical round-trip 发生太晚，不能充当 parser resource gate。

这些 ceiling 不排除任何合法 v1 manifest。即使不利用终态与结果资产互斥关系、而把互斥分支的局部最大保守相加，当前封闭 Schema 也只需要 depth `3`、单 object `11` pairs、全文 `114` pairs、单 array `15` items、全文 `18` array items、`25` containers、`133` value nodes 与 `19` integer digits；考虑跨字段互斥后，真正跨终态可同时达到的全文最大值是 `112` pairs、`24` containers 与 `131` value nodes。本决策用较高的保守上界证明兼容性，不依赖较低的可达值。Schema 仍拥有精确形状与字段范围；parser profile 只是先行的有界外壳。String、object key 与 whitespace 不另设独立 parser ceiling，其完整原始表示已经受 ADR 0084 的 raw-byte cap 约束；这不取消 Schema、路径或 canonical 字节规则。

任一 profile、strict parse、Schema 或 canonical 门禁失败都使整个 manifest 无效：writer 不得提交，crash recovery 保留 staging 原字节原位置，正式 reader 整体拒绝；不得 fallback 到宽松 parser、截断、删除字段、补默认值、重排、重写或新增 manifest 内诊断。Raw cap 约束输入 bytes，不承诺 Python object graph 或峰值内存恰为 `65_536` bytes；本 ADR 也不把预期 hostile-input rejection 与尚未冻结的外部实现故障诊断混为一类。

这些数值是当前 v1-only reader 在读取 `schema_version` 前就必须执行的外层合同常量，不进入 `effective_config.json`、manifest、asset item、marker 或 sidecar。未来 multi-version reader 若要支持更宽结构，必须先冻结足以覆盖其全部受支持版本的 outer pre-version profile，解析后仍对声明为 `gezhi.answer_manifest.v1` 的文档重新强制本组上限；旧 v1 reader 继续安全拒绝超出本 profile 的未来文档。改变 v1 上限或包含边界需要 Answer manifest Schema/profile 演进。本决策不增加字段、资产、配置、错误码或第三方依赖，也不适用于 `events.jsonl` 或其他 JSON 资产；direct exclusive-create leaf formation 已由 ADR 0087 冻结，V1 不承诺断电 durability 的边界已由 ADR 0088 冻结，阻止本次新 Answer terminal manifest 形成或复验的 no-commit primary 已由 ADR 0095 冻结。其他 reader command 诊断与未设路径专属 cap 的 Answer 资产读取额度仍待后续批准。

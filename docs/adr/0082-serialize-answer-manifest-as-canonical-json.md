# 以规范 JSON 字节序列化 Answer terminal manifest

Answer writer 只对已经冻结且通过当前 `gezhi.answer_manifest.v1` 封闭 Schema、类型、范围、顺序与跨字段不变量验证的 manifest value 执行以下 Python 3.11 标准库序列化；不得使用自定义 encoder、`default`、Unicode normalization、换行转换或其他等价替代：

```python
json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
```

最终 `manifest.json` 必须以 binary I/O 保存上述原始 bytes：没有 UTF-8 BOM，没有任何 raw `0x0D`，唯一 raw `0x0A` 是文件最后一个 byte。JSON string 中的 CR/LF 由该 serializer 写成 escape sequence，不是物理换行。`sort_keys=True` 递归排序每个 object 的 key，但不改变 array 顺序；`assets` 的 UTF-8 path 顺序、`attempts` 的 launch ordinal 与其他领域数组顺序仍由各自不变量验证，validator 不得借 canonicalization 排序或修复它们。

共享 terminal-manifest reader 必须保留原始 bytes，先按 ADR 0084 对完整文件执行包含末尾 LF 的 65,536-byte inclusive pre-parse 门禁，再拒绝 BOM、raw CR、缺失或多余末尾 LF，以及末尾 LF 之前的任何 raw LF；随后只把去掉唯一末尾 LF 的 payload 以 strict UTF-8 解码。建立 JSON tree 前必须通过 ADR 0086 的 quote/escape-aware structural preflight，再用其每次调用私有的 numeric/constant/object-pairs hooks 严格解析为唯一顶层 JSON object并完成全部资源计数；允许结构深度内的 duplicate object key、任何 float/exponent number、`NaN`、`Infinity`、`-Infinity`、trailing second value、comment 或其他非标准扩展一律拒绝。不能 trim、替换、猜测编码、fallback 或修复。解码、profile、Schema validation 或按同一规则重新 UTF-8 编码失败也都使 manifest 无效。

在用 manifest 中的值构造或打开任何 asset path 前，reader 必须先通过上述 framing、strict parse、当前 Schema 与路径字段自身的安全约束，再以同一 Python 3.11 调用重序列化 parsed value，并要求结果与保留的完整原始 bytes byte-for-byte 相等；之后才可执行目录闭合、reparse/ADS、长度、哈希、identity、usage、终态与其余跨资产验证。语义等价但 key 顺序、空白、escape、数字拼写或末尾换行不同的文件仍然无效。

Writer 必须按 ADR 0087 把已检查的同一 immutable canonical buffer direct exclusive-create 到字面 `manifest.json`，不得使用 manifest temp leaf、leaf rename/replace 或第二次 serialization；关闭后让最终 leaf 通过同一个 reader，并与原 buffer 逐 byte 相等，关闭全部句柄后才允许执行 Answer 目录原子提交。Crash recovery 与正式 reader 也必须复用同一 raw cap、parser profile、Schema、canonical round-trip 与跨资产 validator；profile 超限、非规范、partial 或不一致的 manifest 只保留原 staging，禁止重写成规范形式。Manifest 继续不列出自身、不保存自身长度或哈希。

本决定只冻结 serialization 与 byte-level verification，不新增第三方依赖、字段、资产、Schema version 或外部诊断码。最终顶层 envelope 已由 ADR 0083 闭合，manifest raw-byte cap 已由 ADR 0084 冻结，asset `byte_length` 范围已由 ADR 0085 冻结，有界 parser profile 已由 ADR 0086 冻结，direct exclusive-create leaf formation 已由 ADR 0087 冻结；ADR 0088 已冻结 V1 不调用强制持久化 API且不承诺断电 durability。

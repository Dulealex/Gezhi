# Candidate Knowledge v1 合同

状态：已冻结。该合同是 Literature、Reviewed Handoff 与 Knowledge 共同使用的 Candidate 内容身份边界；任何改变哈希前像、字段语义或规范化规则的修改都必须使用新的 Schema 版本。

## 职责边界

`CandidateDraftV1` 是 Codex 的临时输出；`CandidateKnowledgeV1` 是 Python 在完成 Schema、证据、Descriptor、预算和碰撞校验后生成的正式持久记录。Candidate 的内容身份与运行定位严格分离：内容身份不包含 Canonical 或 semantic run ID，物理运行位置由所在 semantic manifest 或 Reviewed Handoff manifest 保存。

短证据摘录、页码、bbox、文件路径、审核收据和 Descriptor 正文快照是交接或展示信息，不进入 Candidate 内容身份；它们必须能由正式引用验证，不能反向改变 `candidate_id`。

相关决策：[ADR 0015](../adr/0015-normalize-reading-input-into-a-canonical-asset-bundle.md)、[ADR 0018](../adr/0018-content-address-candidate-knowledge.md)、[ADR 0039](../adr/0039-resolve-temporary-descriptor-locators-to-content-addressed-references.md)。

## CanonicalJsonV1

所有身份哈希前像都先构造成只含 JSON object、array、string、integer、boolean 或 null 的值；禁止 float、NaN、Infinity、重复 object key 和未知字段。ASCII ID、枚举和哈希只接受合同规定的严格格式，不做大小写或文本修复。

人类文本字段 `text`、`label` 与 `source_terms` 按以下顺序规范化：

1. CRLF 和 CR 转换为 LF；
2. Unicode 规范化为 NFC；
3. 使用冻结的 Python 3.11 Unicode `str.strip()` 去除首尾空白；
4. 保留内部空白，不做 NFKC、lowercase、断词修复或空白折叠。

字符串长度按规范化后的 Unicode code point 数计算。规范化后为空的必填字符串无效；NUL 与非配对 surrogate 无效。

哈希前像使用 Python 3.11 标准库下列等价编码：

```python
json.dumps(
    value,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

哈希前像无 UTF-8 BOM、无尾随换行。SHA-256 写成 64 位小写十六进制。持久 `.json` 文件在 CanonicalJsonV1 bytes 后追加一个 LF；`.jsonl` 每条记录使用 CanonicalJsonV1 bytes，记录间和文件末尾各使用一个 LF。文件哈希对包含末尾 LF 的实际文件字节计算，因此文件哈希与 payload 身份哈希是不同概念。

set-like 数组先规范化、再判重和排序：

- `source_terms` 按 UTF-8 bytes 升序；
- Evidence Pointer 按 `(canonical_content_sha256, block_id UTF-8 bytes)`；
- `risk_flags` 按 ASCII 升序；
- Descriptor Reference 按固定 kind 顺序 `method、object、dataset、experiment、metric`，再按 `payload_sha256`；
- `candidates.jsonl` 按 `(candidate_id, payload_sha256)`。

## CanonicalContentIdentityV1

`canonical_content_sha256` 不等于包含 run ID、时间或工具版本的 manifest 文件哈希。它是以下身份 payload 的 CanonicalJsonV1 bytes 的 SHA-256：

```json
{
  "blocks_sha256": "<blocks.jsonl 实际文件字节的 SHA-256>",
  "document_sha256": "<document.md 实际文件字节的 SHA-256>",
  "images": [
    {
      "path": "images/<POSIX-style relative path>",
      "sha256": "<图片实际文件字节的 SHA-256>"
    }
  ],
  "schema_version": "gezhi.canonical_content.v1"
}
```

`images` 包含 `canonical/images/` 下全部普通文件，路径使用正斜杠、Unicode NFC 且按 UTF-8 bytes 排序；绝对路径、`.`、`..`、反斜杠、reparse point，以及在 Windows 不区分大小写后发生冲突的路径均无效。Manifest 保存 `canonical_content_sha256`；相同 Canonical 内容即使来自不同强制重跑也得到相同内容身份。

## EvidencePointerV1

正式证据引用只包含：

```json
{
  "block_id": "<大小写敏感的 Canonical Evidence Block ID>",
  "canonical_content_sha256": "<64 位小写十六进制>",
  "schema_version": "gezhi.evidence_pointer.v1"
}
```

`block_id` 必须属于该内容哈希固定的 `blocks.jsonl`。Evidence Pointer 不包含 `canonical_run_id`、页码、bbox、摘录或路径；semantic manifest 负责把 `canonical_content_sha256` 映射回具体 Canonical run。所有属于同一 Candidate 的 Evidence Pointer 必须指向 Candidate payload 顶层相同的 `canonical_content_sha256`。

## DescriptorPayloadV1 与 DescriptorReferenceV1

Codex 的 `DescriptorLocatorV1` 经验证后解析为完整 Method 或 Study Descriptor，再生成以下 Descriptor 身份 payload：

```json
{
  "kind": "method|object|dataset|experiment|metric",
  "schema_version": "gezhi.descriptor_payload.v1",
  "value": {}
}
```

`kind=method` 时，`value` 是规范化 `EvidenceStatementV1`，其中 Evidence Block ID 已替换为 `EvidencePointerV1`；其他 kind 的 `value` 只含规范化的 `label`、`source_terms` 与 `evidence_pointers`。`payload_sha256` 是该 Descriptor payload 的 CanonicalJsonV1 SHA-256，`descriptor_id` 为 `desc_<payload_sha256 前24位>`。

Candidate 只保存正式引用：

```json
{
  "descriptor_id": "desc_<24 位小写十六进制>",
  "kind": "method|object|dataset|experiment|metric",
  "payload_sha256": "<64 位小写十六进制>",
  "schema_version": "gezhi.descriptor_reference.v1"
}
```

Reference 不复制 Descriptor 正文或数组位置。相同完整 payload 确定性归并；同一短 ID 对应不同完整 hash、或同一完整 hash 对应不同 CanonicalJsonV1 bytes，均为碰撞并使整个 semantic run 失败。

## CandidateKnowledgeV1

正式记录由不参与自身哈希的 envelope 和参与哈希的 payload 组成：

```json
{
  "candidate_id": "cand_<24 位小写十六进制>",
  "payload": {
    "candidate_type": "method|claim|limitation|relevance|open_question",
    "canonical_content_sha256": "<64 位小写十六进制>",
    "descriptor_refs": [],
    "schema_version": "gezhi.candidate_payload.v1",
    "source_id": "src_<24 位小写十六进制>",
    "source_sha256": "<64 位小写十六进制>",
    "statement": {
      "evidence_pointers": [],
      "risk_flags": [],
      "source_terms": [],
      "support_kind": "direct|synthesized|interpretive",
      "text": "<简体中文规范陈述>"
    },
    "work_id": "wrk_<lowercase UUIDv4>"
  },
  "payload_sha256": "<64 位小写十六进制>",
  "schema_version": "gezhi.candidate_knowledge.v1"
}
```

每层 object 均禁止额外字段。`source_id` 必须等于 `src_<source_sha256 前24位>`。`work_id`、`source_id`、`source_sha256` 和 `canonical_content_sha256` 都参与身份；标题、作者、年份等可修订 Identity Alias 不参与身份。

非 Relevance Candidate 禁止出现 `research_interest_id`，包括 null；Relevance Candidate 必须在 payload 顶层包含非空 `research_interest_id`。首个可执行切片在构造正式 payload 前禁止 Relevance Candidate，因此不会出现该字段。

`payload_sha256` 是 `payload` 的 CanonicalJsonV1 bytes 的完整 SHA-256，`candidate_id` 为 `cand_<payload_sha256 前24位>`。`candidate_id`、`payload_sha256`、envelope `schema_version`、Canonical/semantic run ID、时间戳、Codex 会话、模型用量与模型自报置信度不进入 payload。

同一 `candidate_id`、完整 hash 与 CanonicalJsonV1 payload bytes 可以幂等重放；同一短 ID 对应不同完整 hash、或同一完整 hash 对应不同 bytes，均使整个 semantic run 失败且不得覆盖既有 Candidate。Candidate Review 必须同时绑定 `candidate_id` 与 `payload_sha256`。

## Draft 转换与重复项顺序

正式转换顺序固定为：

1. 对原始 `candidate_drafts` 做 Schema 校验，原始总数最多 12；
2. 规范化文本，校验 Evidence Block 成员资格、支持关系和风险标记；
3. 解析 Descriptor Locator，并构造 Evidence Pointer 与 Descriptor Reference；
4. 构造正式 Candidate payload，计算完整 hash 和短 ID并检查碰撞；
5. 只按相同完整 hash 加相同 CanonicalJsonV1 bytes 合并完全相同 Candidate；
6. 对合并后的唯一 Candidate 集合执行逐类型预算；
7. 按 `(candidate_id, payload_sha256)` 写入 `candidate_knowledge.jsonl`。

顶层 `candidate_drafts` 数组是“列表内部禁止完全重复”的唯一例外；Candidate 内部的 `source_terms`、证据、风险标记和 Descriptor Locator 仍禁止重复。相似但 payload 不同的 Candidate 不得自动合并；任何碰撞、预算超限或无效引用都使整个 semantic run 失败且不部分发布。

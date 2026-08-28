# Canonical Reading Asset v1 合同

状态：已冻结。该合同定义 Literature `canonicalize` 阶段发布给 Reader 和 Candidate Knowledge 的唯一规范阅读边界。任何改变 Evidence Block 字段、规范化、哈希前像、页面/标题语义、图片选择或恢复规则的修改都必须使用新的 Schema 版本。

相关决策：[ADR 0015](../adr/0015-normalize-reading-input-into-a-canonical-asset-bundle.md)、[ADR 0126](../adr/0126-publish-content-addressed-canonical-reading-assets.md)、[Candidate Knowledge v1](./candidate-knowledge-v1.md)。

## 职责与 authority

Canonicalize 是 Literature-owned 的确定性深模块。它只消费由 `ocr/current.json` 唯一选中并完成验证的 OCR success，不调用 Codex，不读取非 Active Source，不把 MinerU 私有路径或格式暴露给下游，也不复制完整 vendor 输出。

Native text 只使用 `output/native_text.json`。MinerU 3.4.4 只使用 `output/mineru/source/ocr/source_content_list_v2.json` 作为结构化正文 authority；`source.md`、v1 content list 和 middle document 不参与正文拼接。Canonicalize 对实际消费的 Native JSON、MinerU v2 JSON 和引用图片逐项复验 OCR manifest 中的 path、byte length 与 SHA-256；验证后的资产漂移属于 `asset_integrity_lost`。

## 持久布局

每个 Source 的物理布局固定为：

```text
canonical/
  current.json
  runs/
    .staging/
    canrun_<lowercase UUIDv4>/
      blocks.jsonl
      document.md
      images/
      manifest.json
      provenance.json
      schema.json
```

成功 run 根目录恰好包含上述六个 entry；`images/` 恰好包含被 Evidence Block 引用的内容寻址图片，不允许额外文件、空目录、嵌套目录或未知 entry。`manifest.json` 最后写入且不把自身列入 `assets`。

`canrun_` ID、时间、物理路径、工具输出目录和 Codex 会话都属于运行定位，不进入 Canonical 内容身份。

## CanonicalJsonV1 与文本规范化

JSON、JSONL、SHA-256 和 Unicode 使用 [Candidate Knowledge v1 的 CanonicalJsonV1](./candidate-knowledge-v1.md#canonicaljsonv1)。文本按以下顺序处理：

1. CRLF 和 CR 转换为 LF；
2. Unicode 规范化为 NFC；
3. 使用冻结的 Python 3.11 `str.strip()` 去除首尾空白；
4. 保留内部空白，不做 NFKC、lowercase、翻译、断词修复或解码替换。

NUL、非配对 surrogate、规范化后为空的 Evidence Block 均无效。Native text 先按页处理，再以一个或多个空白行分段；每个完成的段落单独执行同一规范化。

## 页面与 `document.md`

页面使用从 0 开始的连续 `page_index`。每页在 `document.md` 中先写：

```text
<!-- gezhi-page:<page_index> -->
```

随后按 Evidence Block order 写该页规范文本，块之间和页面之间使用两个 LF，整个文件恰好以一个 LF 结束。空页保留 page marker，但不制造空 block；所有页面均没有可用文本时 Canonicalize 失败。

`document.md` 是由 `blocks.jsonl` 和 page count 确定性投影出的可读视图，不是独立语义 authority。验证 run 时必须从 blocks 重建并逐字节相等。

## EvidenceBlockV1

`blocks.jsonl` 每行恰好一个 closed object，并以 LF 结束：

```json
{
  "bbox": null,
  "block_id": "blk_<24 位小写十六进制>",
  "heading_path": [],
  "image_path": null,
  "kind": "paragraph",
  "order": 0,
  "page_index": 0,
  "schema_version": "gezhi.evidence_block.v1",
  "text": "规范文本"
}
```

字段规则：

- `order` 从 0 连续递增，并定义 JSONL 与文档顺序。
- `kind` 只能是 `heading、paragraph、list_item、table、figure_caption、figure_text、equation、other_text`。
- `heading_path` 从最外层到最内层排列，heading block 不包含自身。同级或更外层新标题会替换此前同级/内层标题；首个标题可以不是 level 1，层级跳跃不会制造虚构祖先。
- `page_index` 必须落在 provenance 的 page count 内。
- Native block 固定为 `paragraph`、`bbox=null`、`image_path=null`、空 `heading_path`。
- MinerU `bbox` 恰好四个 decimal string，禁止指数、尾随零和负零，并满足 `x2 > x1`、`y2 > y1`。
- `image_path` 为 null 或 `images/<64 位小写 SHA-256>.jpg|png`。
- `text` 必须已经规范化、非空，且 UTF-8 bytes 不超过 1,048,576。

run 内的 `schema.json` 是上述 Evidence Block 的 Draft 2020-12 closed Schema 快照；manifest 用 `schema_sha256` 绑定其实际文件 bytes。几何关系、连续 order、内容身份和跨字段语义由确定性验证器补充，不能仅依赖 JSON Schema。

## Block 身份

`block_id` 是下列 object 的 CanonicalJsonV1 bytes SHA-256 前 24 位，并加 `blk_` 前缀：

```json
{
  "bbox": null,
  "heading_path": [],
  "image_path": null,
  "kind": "paragraph",
  "order": 0,
  "page_index": 0,
  "schema_version": "gezhi.evidence_block_identity.v1",
  "text": "规范文本"
}
```

同一短 ID 对应不同完整 hash，或同一 run 内出现重复完整身份，均使整个 Canonicalize 失败。相同输入必须得到相同 block bytes 和 block ID；物理 run ID 与时间不得改变它们。

## MinerU 映射

| MinerU v2 type | Canonical kind |
|---|---|
| `title` | `heading` |
| `paragraph` | `paragraph` |
| `list`、`index` 的每个 item | `list_item` |
| `table_caption` | `figure_caption` |
| table HTML | `table` |
| table footnote | `figure_text` |
| image/chart caption | `figure_caption` |
| image/chart footnote | `figure_text` |
| `equation_interline` | `equation` |
| code/algorithm caption、content、footnote | `other_text` |
| page header/footer/number/aside/footnote | `other_text` |

空的可选 caption、footnote 或 content 不产生 block。item 顺序、类型内顺序和外层页数组顺序必须保留。

## 图片

Canonicalize 只复制被结构化 block 引用且由 OCR manifest 绑定的普通 JPEG/PNG。图片使用 validated/no-follow handle 流式读取、复制和哈希；扩展名由 magic bytes 决定，JPEG 统一为 `.jpg`。Canonical path 使用完整图片 SHA-256，因此不同 provider path 的相同 bytes 确定性去重，未引用图片不发布。

`images` 在内容身份中按 NFC POSIX path 的 UTF-8 bytes 排序。绝对路径、反斜杠、`.`、`..`、reparse point、嵌套目录及 Windows casefold 冲突均无效。

## CanonicalContentIdentityV1 与 EvidencePointerV1

`canonical_content_sha256` 严格使用 [CanonicalContentIdentityV1](./candidate-knowledge-v1.md#canonicalcontentidentityv1)：只绑定 `document.md`、`blocks.jsonl`、全部 Canonical 图片实际 bytes 与 `gezhi.canonical_content.v1`，不包含 Work、Source、OCR/Canonical run、时间、工具、provenance、manifest 或 Schema snapshot。

正式证据引用恰好为：

```json
{
  "block_id": "blk_<24 位小写十六进制>",
  "canonical_content_sha256": "<64 位小写十六进制>",
  "schema_version": "gezhi.evidence_pointer.v1"
}
```

`block_id` 大小写敏感，且必须是该 `canonical_content_sha256` 所绑定 `blocks.jsonl` 的真实成员。Pointer 不携带 run ID、页码、bbox、摘录或物理路径；这些信息通过内容身份解析回正式 block。

## Provenance、manifest 与 current

`provenance.json` 绑定 Work、Source SHA-256、Canonical run、OCR method/run/manifest/input fingerprint、Canonicalizer profile，以及 page/block/image count。`manifest.json` 绑定相同 authority、Canonical input fingerprint、Schema snapshot、Canonical 内容身份和除自身外每个正式资产的 path、byte length、media type、SHA-256 与已知 Schema version。

`current.json` 是唯一可替换 pointer，恰好绑定：

- `work_id、source_id、source_sha256`；
- `run_id、manifest_sha256、input_fingerprint_sha256`；
- `canonical_content_sha256`；
- `schema_version=gezhi.literature_canonical_current.v1`。

Canonical input fingerprint 绑定 Work、Source、OCR run ID、OCR manifest SHA-256、OCR input fingerprint 和 Canonicalizer profile。相同 fingerprint 的唯一有效 success 必须复用；内容身份与 input fingerprint 是两个不同概念。

## 资源边界

以下均为 inclusive 上限，`+1` 在首个可决定位置停止且不得截断或部分发布：

- 4,096 页；
- 4,096 个 Evidence Block；
- 单 block 文本 1,048,576 UTF-8 bytes；
- `document.md`、`blocks.jsonl` 或任一 Canonical JSON 文件 67,108,864 bytes；
- 4,000 张 Canonical 图片；
- 单图 67,108,864 bytes；
- Canonical 图片合计 2,147,483,648 bytes；
- 单个恢复 namespace 4,096 entries。

段落扫描、JSONL 编码、文档编码、图片复制和图片哈希必须在达到首个决定性上限时停止，不得先物化超过上限的全文、JSONL 或图片集合。

## 发布、恢复与失败

新 run 只在 `.staging/<run_id>/` 构建并完成自验证；随后在 authority checkpoint 后复验 Active Source、OCR current/manifest 和实际消费的 OCR 资产，以 non-replacing rename 提交到正式 `runs/`，最后通过保留 replacement evidence 的原子 replace 发布 `current.json`。

恢复规则：

- 唯一、完整、与当前 input fingerprint 相同的 staging success 可以提交并补 current，不重跑 Canonicalize。
- 正式 success 已提交但 current 缺失时只补 current。
- 完整 success 与 current 均有效时幂等复用，不创建新 run。
- partial、invalid、unsafe、foreign、属于其他 input 的 staging，以及正式/staging target 冲突均保留证据并 fail-stop。
- 多个 success、多个 current temp、多个 replacement evidence、孤立或 bytes 不一致的 replacement evidence，以及无法证明结果的 rename/replace 均 fail-stop；不得覆盖、合并、删除证据或换 ID 重试。
- 正式 run 的任一内容、几何、目录、OCR provenance、manifest 或 current 绑定损坏均为 `canonicalize/asset_integrity_lost`。

确定性正文或资源语义无效为 `canonicalization_failed`；已知写入失败且结果仍可证明为 `commit_failed`；namespace/rename/replace 结果无法证明时抛 recovery uncertainty，不伪装成 handled receipt。

Canonicalize 成功后，若当前构建尚缺 `read` obligation 的下一项必要能力，则按 [ADR 0127](../adr/0127-expose-an-explicit-reader-prerequisite-frontier.md) 停在 `read/reader_prerequisite_unavailable`。T14 Reader 接入后，Canonicalize 不再因缺少 Reader-owned prompt、Schema、input projection 或执行 adapter 走该正常分支；但有效 T14 bundle 后缺少 T15 Candidate materializer 时，仍按 [ADR 0133](../adr/0133-keep-t14-reader-bundles-inside-the-read-stage.md) 使用同一 blocked reason。

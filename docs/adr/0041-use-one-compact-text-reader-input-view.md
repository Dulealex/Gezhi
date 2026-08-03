# 使用单一紧凑文本 Reader Input View

`literature_reader_v1` 不同时向 Codex 暴露会重复正文的 `document.md` 与 `blocks.jsonl`，而由 Python 从 Canonical Reading Asset 的文本 Evidence Block 一对一投影并快照唯一 `input.jsonl`。ReaderInputV1 冻结一条 exact metadata record、受控 block kind、0-based 连续投影 order、标题路径和页索引语义，以及无 BOM、Canonical JSON UTF-8、LF-only 和末尾 LF 的字节编码；表格、图题与已提取图中文字必须已是 Canonical 文本，Reader 不再解析、拆分或合并。首个切片不提供原始 PDF、MinerU vendor 产物或二进制图片，纯视觉结论不得生成；实际输入字节随 semantic run 保存并哈希，使 Windows 换行策略、JSON 空格或键顺序不能改变输入身份。

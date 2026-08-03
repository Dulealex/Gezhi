# 只允许经过验证的 URL 作为书目链接目标

统一 label escaping 现已由 [ADR 0049](./0049-escape-untrusted-visible-text-with-one-pass-commonmark-tokens.md) 冻结，因此本 ADR 所述“escaping 冻结前零链接”的前置条件已经满足；实际链接仍必须同时通过 identifier、target、destination 与 label 的全部合同后置条件。

`answer.md` 可以在参考文献中提供可点击链接，但 URL 只能来自已验证的 Citation 字段、通过明确 allowlist，并由 Python 按冻结的确定性模板构造；在模板和 allowlist 冻结前不得生成链接。URL 不得作为裸露可见文本、Source 身份字段或模型提供内容出现，从而保留 DOI、arXiv 等入口而不扩大模型输出和 provenance 展示边界。只有完整的 DOI 与 arXiv 可见片段能够成为链接，分别使用固定 HTTPS 基址 `https://doi.org/` 与 `https://arxiv.org/abs/`；作者、题名、年份和 Source fragment 保持纯文本，两种标识符并存时各自生成链接。链接由 Python 本地构造，不接受任意 URL，也不联网探测、解析重定向或验证可达性；合同现已冻结 bare DOI 与 modern/legacy bare arXiv 的完整验证、DOI 官方 UTF-8 byte percent-encoding、arXiv 路径构造、尖括号 CommonMark destination、逐 `&` 写成 `&amp;` 的字符引用防护与解析后 target byte round-trip，以及 `failed: citation_link_construction_failed`；非法 Citation 在 View 物化时按 `failed: retrieval_materialization_failed` 提前终止。完整参考文献模板与统一 escaping 均已冻结；实际链接仅在 identifier、target、destination 与 label 的全部合同及后置条件成立时生成。

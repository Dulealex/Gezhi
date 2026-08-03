# 使用稳定内部身份和可更新外部别名

Work 创建时获得永久不变的 `wrk_<UUIDv4>`，标题、作者、年份、DOI 和 arXiv ID 作为可补充或修正的 Identity Alias 保存，不参与目录命名。Source 使用 `src_<SHA-256 前24位>`，同时保存并校验完整 SHA-256；相同内容幂等命中同一 Source，明确相同的 DOI/arXiv 新版本归入已有 Work，只有弱书目信息相似时进入 Identity Review 而不自动合并。格致不继承旧项目按 DOI/arXiv/标题分支生成 `D_`、`A_`、`T_` 标识或使用 SHA-1 的规则。

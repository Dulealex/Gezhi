# 首个切片暂缓 Research Interest 与 Relevance

首个可执行纵向切片没有 Research Interest 的权威存储、管理命令或非技术用户界面，因此 `literature_reader_v1` 不接收 Research Interest，Reading Result 的 `relevance` 必须为空，也禁止生成 Relevance Candidate 或 `research_interest_id`；Codex 不允许自行猜测用户研究方向。Research Interest、Relevance Reading 与 Relevance Candidate 的领域和 Schema 位置继续保留，待后续以独立切片明确所有权、管理入口和交互后再升级 Codex 角色版本启用，从而避免为了形式上的五类齐全而引入隐藏配置与虚构相关性。本决策完善 ADR 0009 的首个闭环范围。

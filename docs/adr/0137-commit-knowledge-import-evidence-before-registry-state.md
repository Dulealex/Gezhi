# 先固定 Knowledge 导入证据，再提交 Registry 状态

Knowledge Intake 先以 non-replacing publication 原样提交或复用已验证的 Reviewed Handoff 两文件证据，再在一个 SQLite `BEGIN IMMEDIATE` transaction 中追加 Handoff revision 并重建该 Candidate 的 current projection。这样 Registry 仍是唯一治理事实源，数据库不会指向缺失证据；Registry transaction 之前失败只会留下无治理权威、可在同一 Handoff 重放时复用的 orphan evidence，而 commit completion 不确定不形成 handled acknowledgement。

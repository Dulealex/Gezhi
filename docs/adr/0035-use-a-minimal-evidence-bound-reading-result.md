# 使用最小且证据绑定的 Reading Result

`Reading Result v1` 只保留一段 synopsis，以及 research problems、methods、findings、limitations、relevance、open questions 和由 objects、datasets、experiments、metrics 构成的 study descriptors；每条语义陈述都必须绑定有效 Evidence Block，没有资料支持的集合保持为空，relevance 只有在输入明确 Research Interest 时才允许生成。同一次 Codex 输出另含五类 Candidate Draft，但只有值得跨 Work 检索和审核的独立候选才能进入该集合，不能把 Reading Result 全量复制为候选；任一证据引用无效时整个 semantic run 不发布，旧式逐章节摘要、阅读日记、重复 Markdown 报告和散落 sidecar 不进入格致。

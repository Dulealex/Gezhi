# 合并语义阅读与候选草拟调用

格致首版对每个 Canonical Reading Asset 执行一次逻辑 semantic read，以严格 Schema 同时返回 Reading Result 和 `candidate_drafts`；相同输入、提示词和 Schema 因网络中断、429、5xx 或超时而进行的有限全新进程 attempt 只是该逻辑调用的传输重试，不是第二次阅读、分块阅读或后续语义阶段。确定性 Python 随后校验证据和字段、解析 Descriptor、生成内容寻址 Candidate Knowledge、合并完全相同 payload 并检查预算，再把 Reading Result、Candidate Draft、Candidate Knowledge 与 Review Queue 作为一个不可分割的 semantic result 发布。任何无效草稿不得部分发布，失败 attempt 的部分输出不得复用；只有质量评测证明需要时才另行决策拆分业务职责或重复发送全文。

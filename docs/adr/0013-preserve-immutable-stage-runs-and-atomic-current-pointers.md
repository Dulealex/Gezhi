# 保留不可变阶段运行并原子切换当前结果

Source 原始内容和 OCR、Codex 阅读、Candidate Knowledge、审核及 Handoff 的成功运行结果均不可原位覆盖，每次运行使用独立 `run_id` 并记录输入指纹、工具版本和配置。终态运行先在目标目录同一卷的 staging 中写完文件，最后写列出其他资产哈希的 manifest，再以目录原子改名提交；只有完整有效的成功 manifest 才能原子替换小型 `current.json` 指针。目录已提交但指针尚未切换时，`resume` 只补指针而不重跑；blocked、failed、interrupted 与崩溃恢复记录保留审计但不能包含成功 result 或取代当前成功结果。相同指纹复用已有成功结果，只有显式强制重跑才创建新结果；历史清理属于独立维护操作，日常流水线无权自动删除。

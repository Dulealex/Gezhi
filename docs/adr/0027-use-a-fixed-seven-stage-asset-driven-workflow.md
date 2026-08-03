# 使用固定七阶段资产驱动流水线

首版只实现 `ingest → ocr → canonicalize → read → review → handoff → knowledge_import` 七个线性阶段，不建设通用 DAG、任务队列或后台调度器。阶段状态限定为 pending、running、succeeded、blocked、failed 和 interrupted；成功以已发布资产的 manifest 与哈希校验为准，SQLite 仅作投影，`resume` 从第一个未通过资产校验的阶段继续，遗留 running 在恢复时转为 interrupted。同一 Work 同时只允许一个写流程，自动搜索与未来批处理只能提交 Work，不改变阶段内部合同。

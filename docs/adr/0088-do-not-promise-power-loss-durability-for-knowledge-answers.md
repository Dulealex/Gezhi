# Knowledge Answer v1 不承诺断电持久性

Knowledge Answer v1 严格区分 process-level logical commit 与 power-loss durability。进程级提交点继续是：全部应保留资产与 terminal manifest 已完成、验证并关闭，随后唯一一次 non-replacing 同卷 staging-directory rename 返回成功。只有该返回成功后，当前 `knowledge ask` 才可向调用方报告 Answer 已提交；manifest 内已经锁存的 `status=succeeded` 只描述 Answer 工作流终态，也不能单独证明目录已提交。这个线性化点保证活跃 Windows 会话中的原子可见性和进程崩溃隔离，不表示 bytes、目录项或 rename 已被强制写到持久介质。

V1 writer 与 recovery 不调用也不依赖 `FlushFileBuffers`、Python `os.fsync`/CRT `_commit` 等价路径、file/directory/volume flush、`FILE_FLAG_WRITE_THROUGH`、`MOVEFILE_WRITE_THROUGH` 或其他 write-through/FUA 机制。ADR 0087 要求的 synchronous I/O completion、语言运行时用户态 buffer flush、close、写后 readback 与完整验证仍然必须成功；它们证明本进程观察到的 bytes 和逻辑提交前置条件，不是 power-safe 证据。操作系统或设备自行后台落盘不形成 Gezhi 可验证的持久性承诺。

突然断电、系统崩溃、强制重启或存储设备/控制器丢失后，v1 不承诺此前已经报告提交的 Answer 仍存在、仍位于 target、仍包含全部 bytes 或仍有效，也不承诺“非 manifest 资产先关闭、manifest 后关闭、目录最后 rename”的进程内顺序会以相同顺序持久化。下一进程不得依据断电前 CLI 输出、日志、时间戳、目录存在、manifest 存在、预报长度或 mutex 状态推断成功；它只对重新观察到的实际 namespace 和实际 bytes 执行既有安全路径门禁、共享 reader 与完整 validator。

重新观察到的状态按下表 fail closed；`target` 指 `answers/<answer_id>/`，`staging` 指同身份的 `answers/.staging/<answer_id>/`：

| target | staging | v1 动作 |
|---|---|---|
| 缺失 | 缺失 | 该 Answer 当前不存在；不得补造终态、复用同一 `answer_id` 或把先前成功当作持久证据。 |
| 缺失 | 完整有效 | 下一 writer 取得同一数据根 mutex 后，按 ADR 0053 再次全量验证、关闭全部 handle、复验 target 仍不存在，再只做一次 non-replacing rename；这次成功仍只是新的进程级提交。 |
| 缺失 | staging 存在但 manifest 缺失/partial/无效，或其他无效现场 | staging 原字节原位置隔离，正式消费者忽略；不得补写、修复、删除、移动或推断终态。 |
| 完整有效 | 缺失或任意 staging | 正式 reader 可接受 target；若 staging 同时存在，它仍作为 target-conflict orphan 原样保留并报告，不能合并或删除。 |
| 无效、partial 或非法类型/路径 | 缺失或任意 staging | 正式 reader 整体拒绝 target，任何同身份 staging 都因 target 已存在而不能自动补交；两侧都不得修复、覆盖、replace、merge、删除或按时间戳/哈希择优。 |

“完整有效”始终要求对当前实际路径重新执行 no-reparse、ordinary-file/directory、ordinal-ignore-case、raw cap、parser、Schema、canonical bytes、资产清单闭合、长度、哈希、identity 与全部跨字段不变量；不能从 API 历史或部分成功推导。无效正式 target 保持不可变并对所有正式读取整体不可用；reader 不回退到同身份 staging。若 target 与 staging 都存在，target 是否可读只由 target 自身验证决定，而 target 的存在无条件阻止 recovery rename staging。这里的“隔离”始终表示原路径上的逻辑忽略、拒绝与报告，不是物理移动或自动 quarantine。

V1 的验收测试覆盖正常提交顺序、禁止的强制持久化 API 不被调用、short/zero write、close/readback/rename failure、staging recovery、target conflict 以及正式 reader 对损坏 target 的整体拒绝。进程崩溃注入使用有限协议检查点矩阵：manifest create 前、create 后、partial write 后、full write 后但 close 前、close 后但 readback 前、readback/验证期间、验证 handle 全部关闭后但 rename 前，以及 rename 返回后但 CLI acknowledgment 前；不得把“所有机器指令点”当成不可穷举的验收要求。拔电或系统崩溃后仍保存最近 Answer 不是 v1 验收条件。面向用户的输出与文档不得把“已提交”“原子发布”表述为 `fsynced`、power-safe、durably persisted 或保证断电不丢。

以后若要提供更强保证，必须用新 ADR 冻结受支持的 filesystem、volume、local/remote storage 与设备缓存范围，逐资产、manifest、目录项与 rename 前后的 flush/write-through 顺序，失败语义、性能预算、故障注入测试和 success acknowledgment 点；不能追溯宣称既有 v1 Answer 在原提交时已 durable。若不同 Answer 需要携带可验证的 durability level 或 receipt，必须演进 manifest Schema 或冻结独立版本化外部收据，不能给 v1 偷加字段。

本决策只限定 Knowledge Answer v1，不改变 ADR 0014 把正式业务数据归类为长期保留且必须备份的“持久业务数据”，也不替 Literature、Knowledge Registry/Imports、SQLite 或未来 Bot 决定其断电策略。它不增加 manifest 字段、asset、marker、sidecar、journal、redo log、配置、错误码、第三方依赖或启动时全树 scrub；`knowledge ask` 继续只按 ADR 0053 扫描 staging，正式 reader 只在消费 target 时完整验证。它也不改变已经锁存的 Answer terminal cause；能够确定 no-commit 且安全停止的 manifest/commit failure 已由 ADR 0095 绑定封闭外部 primary，rename 结果不确定或无法安全收尾的路径仍位于正常矩阵外。

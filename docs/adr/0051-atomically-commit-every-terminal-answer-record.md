# 原子提交每个 Answer 终态记录

Final checkpoint 已通过、Root trust 仍成立且 target 不存在时，non-replacing same-volume staging-directory rename 返回非 target-conflict 失败；只有随后能够证明 staging 未提交、target 不是本次 commit 且全部操作安全停止，才使用 `{"code":"knowledge.ask.answer_commit_failed.v1","context":{}}` 返回 no-commit `failed`、`result=null`、正常 JSON exit `1`。禁止自动重试，完整 terminal staging 原地保留供后续 recovery 独立复验。Rename outcome 无法确定时不属于正常矩阵。

本次 expected target 在 final checkpoint 已存在，或 non-replacing staging-directory rename 明确返回 target-exists，且 Root trust 仍成立时，固定使用 `{"code":"knowledge.ask.answer_target_conflict.v1","context":{}}` 返回 no-commit `failed`、`result=null`、正常 JSON exit `1`。目标不得覆盖、删除、合并、比较后复用，且不得换新 `answer_id` 自动重试；本次 staging 原地隔离。其他 rename failure 不使用此码。

本次新 Answer 的 terminal manifest formation 已开始且 Root trust 仍成立时，canonical buffer/cap、direct exclusive-create、write/completion/close、readback、Schema/canonical bytes、目录闭合或跨资产复验失败，固定使用 `{"code":"knowledge.ask.answer_manifest_failed.v1","context":{}}` 返回 no-commit `failed`、`result=null` 与正常 JSON exit `1`。Partial、既存或无效 `manifest.json` 原样留在 staging，禁止删除、修补或重建。Manifest formation 前的资产失败、target conflict 与 final rename failure 分别使用其他 cause。

`answer_id` 已生成且 Root trust 仍成立时，staging direct child 无法安全创建、任一 terminal manifest 之前的资产无法形成/安装，或 writer-private entry 无法撤销而不能达到封闭 terminal asset set，使用 `{"code":"knowledge.ask.answer_staging_failed.v1","context":{}}` 返回 no-commit `failed`、`result=null`、正常 JSON exit `1`；已有 staging 留在原路径。Terminal manifest、expected target conflict 与最终 rename failure 不使用此码。

初始 Data Root gate 已成功后，最终 rename checkpoint 无法继续证明 root identity/canonical path/父链/reparse 状态仍安全且相同，是 no-commit `failed`，不得重新归类为 Data Root `blocked`。唯一 primary 固定为 `{"code":"knowledge.ask.data_root_integrity_lost.v1","context":{}}`，outer `result=null`、正常 JSON exit `1`。此时禁止为了记录失败而继续写入或提交 terminal Answer；本次 staging 保持原路径并继续对正式 reader 隔离。

在最终 staging-directory rename 之前，writer 必须按 ADR 0014 复核冻结 Data Root identity、handle-derived canonical root、staging/target 父链与 reparse 状态；失败时不得尝试 rename。该 checkpoint 用于检测协作环境中的目录漂移，不把 V1 提升为能够抵御恶意或高权限本机进程在最后检查与 rename 之间替换 namespace 的 race-free 合同。

每个已经分配 `answer_id` 的 Knowledge 请求只在同卷 `answers/.staging/<answer_id>/` 中写入，终态时完成并关闭其他资产，最后写入、验证并关闭 terminal manifest，再把整个目录原子改名为不可变的 `answers/<answer_id>/`；目标已存在时禁止覆盖、合并、删除后重试或以复制模拟提交。`succeeded`、`blocked`、`failed` 与 `interrupted` 都提交可审计的终态目录；`succeeded` 必须且只能成对包含完整有效的 `answer_output.json` 与 `answer.md`，其他终态不得包含任一正式结果文件。正常发布的 `insufficient_evidence` 仍属于 `succeeded`。Answer 不增加嵌套 `runs/`、`current.json` 或原位覆盖；崩溃遗留 staging 不能被读取为正式 Answer，后续持锁恢复只补交完整有效的既有 terminal commit，其余现场继续隔离。该边界以持续保留失败与孤立记录、并把清理留给独立维护操作为代价，换取活跃 Windows 会话及进程崩溃范围内明确、可审计且不向正式 reader 暴露半提交 Answer 的事务边界；ADR 0088 单独限定系统崩溃与断电后的实际残留状态必须重新全量验证。

最后形成的 terminal manifest 必须先满足 ADR 0084 包含末尾 LF 的 65,536-byte inclusive cap 与 ADR 0082 的 Python 3.11 规范 JSON bytes，再按 ADR 0087 对字面 `manifest.json` 执行一次 direct `CREATE_NEW` 等价操作，把已检查的同一 immutable buffer 写入唯一 handle；不得使用 manifest temp leaf、leaf rename/replace、重新序列化、覆盖或修补。关闭后由共享 reader 重读、重新执行 cap、framing/strict UTF-8、ADR 0086 structural preflight 与 strict hooks parse、当前 Schema、canonical round-trip、原 buffer byte identity、目录闭合与跨资产复验；全部句柄关闭且任何门禁均未失败后才可执行 staging-directory rename。该 manifest 仍不列出或哈希自身，目录改名仍是唯一进程级提交点；ADR 0088 已冻结 V1 不调用强制持久化 API且不承诺断电 durability，断电后只按实际残留 namespace 与完整验证结果 fail closed。

# 只补交完整有效的孤立 Answer 终态

当 Data Root trust 仍成立但 `answers/.staging/` 整体无法安全枚举，或 invocation-wide scan protocol 无法建立/完成时，当前 Ask 使用 `{"code":"knowledge.ask.orphan_scan_failed.v1","context":{}}` 选择 no-commit `failed`、`result=null` 与正常 JSON exit `1`，不生成新 `answer_id`。单个 candidate 的非法 basename、无效 manifest、target conflict 或 recovery rename failure 不使用此码，仍只作 supplemental 并继续扫描；如果检查转而证明 root trust 丢失，则使用优先级更高的 `knowledge.ask.data_root_integrity_lost.v1`。

持锁 recovery 的 checkpoint 若无法继续证明 invocation-wide Data Root identity/canonical path/父链/reparse 状态仍安全且相同，初始 Data Root gate 已成功，因此当前命令以 `{"code":"knowledge.ask.data_root_integrity_lost.v1","context":{}}` 选择 no-commit `failed`、`result=null` 与正常 JSON exit `1`，不能倒退为 `blocked`。这与单个历史 orphan 自身验证失败、target conflict 或 candidate-local rename failure 不同；后者仍保持原现场并只作为 supplemental，不阻止本次新 Ask。

Crash recovery 的最终目录改名前也必须执行 ADR 0014 的 Data Root identity、handle-derived canonical root、staging/target 父链与 reparse checkpoint；失败时原 staging 保持孤立且不得 rename。该检查只检测协作环境中的目录漂移，不承诺抵御 hostile concurrent namespace mutation。

`knowledge ask` 取得该数据根的 Answer writer mutex 后、生成新 `answer_id` 前，先扫描无活跃 owner 的 `answers/.staging/`：只有当某个 staging 已含完整有效的 terminal manifest、manifest 引用的全部资产都通过 byte length、SHA-256、Schema identity 与终态不变量复验、目标 `answers/<answer_id>/` 不存在时，才关闭恢复过程打开的句柄并只补做原定同卷原子改名，保留 manifest 记录的原终态且不重新运行任何阶段。该动作只是完成 manifest 已经证明存在的原运行 terminal commit，不创建新的 crash-recovery result，也不从部分资产推断成功；ADR 0013 中“崩溃恢复记录不得包含成功 result”的限制继续适用于没有完整有效 terminal manifest 的现场。manifest 缺失、损坏、资产不一致、路径不安全、内容不完整或目标冲突的 staging 都保持原字节与位置，不修补、删除、移动、复用部分输出或伪造成 `interrupted`；它们继续被正式消费者忽略并向当前调用报告，但不阻止新 `ask` 使用新 `answer_id`。Knowledge v1 不新增公开 `resume`，需要答案时重新提问；孤立 staging 的归档或终态化留给以后显式维护功能，以可能积累异常目录为代价，避免恢复过程破坏现场证据或把未提交结果误升格为正式 Answer。

ADR 0087 的 direct-create 可以留下缺失、空、partial 或完整-looking 的字面 `manifest.json`。恢复器只验证这个最终名称，不寻找或接受 manifest temp、backup、marker 或 sidecar，也不得补写、删除、截断、重命名、replace 或从其他 entry 安装 manifest；缺失或无效 leaf 原样隔离。若原 writer 在自身 readback 前崩溃，但遗留 manifest 的实际完整 bytes、目录闭合、全部资产与跨字段不变量后来都由共享 reader/validator 独立证明，则它仍属于首段允许只补做目录改名的完整有效 terminal commit。

ADR 0088 不承诺断电后的 namespace 或 bytes 仍保持 rename 前后状态。重启后 target 与 staging 都缺失就是当前没有该 Answer；target 缺失且 staging 完整有效时仍按首段补交，无效 staging 继续隔离。Target 一旦存在，正式 reader 只按 target 自身实际 bytes 决定接受或整体拒绝；任何同身份 staging 都成为 target-conflict orphan，即使 target 无效而 staging 有效也不得 rename、覆盖、replace、merge、删除或择优。断电前成功返回、日志、时间戳与 mutex 状态都不改变这组规则。

ADR 0081 的 usage 重算属于上述 terminal-manifest 不变量复验，而不是重新运行工作流：恢复器对实际长度恰为 events cap 的正式资产强制验证四项 `null` 与 `usage_unavailable=true`，只对低于 cap 的正式 events 运行同一严格 usage adapter，并要求 item 完全相等。它不得补写 token、修复 events、重新选择运行时分类，也不得重新运行 Codex、Answer validator 或 renderer。

ADR 0082 的规范 JSON byte identity 也是“完整有效”的必要条件：恢复器必须拒绝 BOM、物理 CR/LF framing 错误、strict UTF-8/JSON 失败、ADR 0086 允许结构深度内的任意 duplicate key、非标准常量及 canonical round-trip 不相等。语义等价但 bytes 不规范的 manifest 仍原样隔离，不得 trim、重排、重写或用规范副本替换。

ADR 0084 的 pre-parse cap 先于上述判断：恢复器从同一安全打开的 binary handle 循环读取，只有在完整 raw bytes 不超过 `65_536` 且明确观察到 EOF 时才继续；第 `65_537` byte 是整体拒绝 witness。超限 staging 仍原样隔离，不能截断 prefix、解码、重写或补交。

ADR 0086 的 structural preflight 与 strict hooks parse 紧随 framing/strict UTF-8，并先于 Schema、canonical round-trip 与任何 asset path 使用；depth、pair、item、container、node、integer-digit、float、constant 或 duplicate 任一门禁失败都使 staging 原样隔离。恢复器必须使用每次调用私有的 stack、counter 与 hooks，不得 fallback 到宽松 parser、修改进程全局限制、投影 unknown 字段后再计数或重写现场。

ADR 0085 的 asset `byte_length` exact type 与 `0..9223372036854775807` 闭区间属于解析后的 Schema 验证，并且必须在恢复器使用任何 asset path 之前通过；boolean、float、string、`null`、负数与超限值都会使 staging 原样隔离。声明长度只用于同实际未命名主数据流逻辑长度作精确比较，不能用来预分配、跳过实际长度/SHA-256 复验、修补 manifest 或补交现场；任一路径已有的较小 cap 仍优先。

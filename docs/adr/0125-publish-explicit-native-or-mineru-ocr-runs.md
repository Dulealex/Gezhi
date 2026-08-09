# 发布显式原生文本或 MinerU OCR 运行

`literature resume` 的 OCR 阶段把“是否调用 MinerU”本身作为可审计决定，而不是把原生文本 PDF 当成未经过 OCR 阶段。每个 Active Source 都先由 Core 环境中冻结的 `pypdf==6.14.2` 执行 `native_text_every_page_32_v1` 选择器：PDF 必须至少一页，且每页提取文本去掉 Unicode whitespace 后至少 32 个字符，才选择 `native_text`；零页、任一页不足或 pypdf 不能完成解析/提取，都明确选择 `mineru_ocr` 并保存原因。该规则偏保守，不做质量评分、自动修复或静默 fallback。

两条路径都发布同一种 OCR stage success authority：`sources/<source_id>/ocr/runs/<run_id>/` 是不可变 terminal run，`ocr/current.json` 原子指向完整成功 run。Run 先写入同卷 `ocr/runs/.staging/<run_id>/`，依次保存 `selection.json`、`input.json`、`receipt.json`、输出与除 manifest 自身外全部 regular file 的排序 hash/length/media/schema 清单，readback 后 non-replacing rename；只有完整 success manifest 才能替换 current。随机 `run_id` 只标识一次审计运行；由 Active Source identity、选择器版本与结果、所选 provider profile 形成的 `input_fingerprint_sha256` 才是稳定输入身份。相同 fingerprint 的有效 success 必须复用；完整 run 已 rename 而 current 缺失时只补 pointer。

`native_text` 输出为逐页、保序、未截断的 Canonical JSON，并在 receipt 中明确记录零个 MinerU attempt。`mineru_ocr` 固定使用本机 OCR venv 的绝对 `mineru.exe`、`pipeline` backend、`ocr` method、中文语言和 ADR 0123 的 local/CUDA/offline profile；同时固定 `NO_PROXY=127.0.0.1,localhost`，只让 MinerU client 绕过系统代理访问其同一受控进程树内的本机 API，不移除或放宽外部代理。输入先复制到该 run 的私有目录，MinerU 原始输出、每次 attempt 的 stdout/stderr 与 receipt 全部保留。Provider 输出必须位于固定 `output/mineru/source/ocr` 叶子并通过 no-reparse inventory、必需文件、hash 与 manifest 校验，不按“最大 Markdown”、mtime 或旧缓存猜测结果。

MinerU 启动前必须重新验证 ADR 0123 的 Python、直接包、配置、模型 manifest、CUDA build 与批准 GPU。运行环境缺失或漂移选择 `ocr_runtime_unavailable`；每次运行最长 900 秒，超时或非零退出最多再以完全相同输入/profile 启动一次全新 attempt，中间固定退避 10 秒，耗尽后选择 `ocr_transient_exhausted`。输出超限、成功退出但输出缺失/越界/无效或其他已确定 provider failure 选择 `ocr_failed`。禁止 GPU 到 CPU、其他 OCR、Ollama、下载、provider/backend/method 切换或复用失败 partial。

Blocked、failed 与 attempt 资产可以作为不可变 terminal audit run 提交，但绝不更新 success current。正常成功后 `.staging` 不留本次目录；崩溃遗留的 partial/unsafe/invalid staging 在原位置 quarantine，不删除、不补成 success。只有能从完整 bytes、manifest 与 namespace 唯一证明的 terminal success orphan 可以完成 rename/current；冲突、多个同 fingerprint success、无法确定提交结果或无法证明 Windows child/Job/pipe 已 settle 时停止正常 handled receipt，保留恢复证据。

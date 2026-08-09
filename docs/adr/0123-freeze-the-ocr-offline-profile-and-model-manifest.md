# 冻结 OCR 离线运行 profile 与模型内容 manifest

格致把已经通过真实 PDF 验收的 MinerU pipeline 模型快照固定为版本化的 [model-manifest.v1.json](../../runtimes/ocr/model-manifest.v1.json)。Manifest 的 files 按相对 POSIX path 排序，每项只含 path、十进制 size 与小写 SHA-256；root 另固定 schema_version=gezhi.ocr_model_manifest.v1、ModelScope 来源、模型身份、snapshot、精确文件数与总 bytes。Doctor 必须逐项证明文件集合、大小和哈希完全相同，不能用目录存在、总大小、mtime、缓存命中或历史成功替代内容身份。该 manifest 只是记录 2026-07-31 已验收的本地模型事实，不下载、复制或改写模型。

OCR child 与只读 doctor capability probe 使用同一个封闭环境 profile：MINERU_TOOLS_CONFIG_JSON=E:\Gezhi\.local\mineru\mineru.json、MINERU_MODEL_SOURCE=local、MINERU_DEVICE_MODE=cuda、HF_HUB_OFFLINE=1 与 TRANSFORMERS_OFFLINE=1。MinerU 3.4.4 的 MINERU_MODEL_SOURCE=local 是 ModelScope 下载路径的禁止门；冻结的 ModelScope 1.39.0 没有可采用的通用 offline 环境开关，因此不得发明 MODELSCOPE_OFFLINE。Hugging Face 两项开关防止间接组件发起远端解析。运行 profile 不设置下载期 MODELSCOPE_CACHE，也不允许 auto、modelscope 或 huggingface remote source。

Doctor 还必须验证 OCR CPython、四个直接包身份、MinerU 配置版本与本地 pipeline 目录、LLM-aided 禁用、CUDA PyTorch build、CUDA availability 和 NVIDIA GeForce RTX 4090，但不得加载 PDF、构造模型、运行 inference 或发起网络请求。任一文件、配置、包、GPU 或离线 profile 事实缺失或漂移都只令 ocr_runtime blocked；检查算法自身无法完成才是 failed。修改 manifest、模型内容、profile、包或设备基线必须重新开启明确的 OCR 依赖/模型变更窗口并复验真实 PDF。

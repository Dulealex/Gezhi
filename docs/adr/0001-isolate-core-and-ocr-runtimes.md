# 隔离核心运行时与 OCR 运行时

格致采用两个相互独立的 uv 项目：仓库根目录承载核心运行时，`runtimes/ocr/` 承载 MinerU 与 CUDA PyTorch；两者分别拥有自己的 `pyproject.toml`、`uv.lock`、`.python-version` 和 `.venv`，不使用共享 uv workspace 或共享锁文件。这样可以避免机器学习依赖污染核心环境，并确保 OCR 环境缺失或损坏时只阻塞 OCR 阶段；代价是需要分别锁定、同步和验证两个环境。

# 格致环境契约

格致的依赖在业务实现开始前一次性解析、安装和验收。最终锁定后，实施阶段不得执行会改变依赖图的操作。缺少或失效的依赖只阻塞依赖它的阶段，其余任务继续执行。

本基线于 2026-07-31 在 Windows 与 RTX 4090 上完成验收。

## 冻结规则

- 核心环境和 OCR 环境只允许执行 `uv sync --frozen`；不得执行 `uv add`、`uv remove`、`uv lock --upgrade` 或隐式更新锁文件的命令。
- Codex CLI 只允许执行 `npm ci --prefix runtimes\codex`，由 `package-lock.json` 还原；不得在实施期间执行 `npm update` 或改变 `package.json`。
- 需要新增、删除或升级任何依赖时，先把受影响阶段标为阻塞，再开启一次明确的依赖变更窗口；重新通过全部相关验收后才能形成新的冻结基线。
- 不允许静默安装缺失依赖、自动升级或切换备用模型。

## 包管理器与工具链

- Python 依赖统一使用 uv，不使用 Conda。用户级 `uv 0.11.32` 只是可执行工具；`tools/uv.ps1` 会校验版本，并把 Python、缓存和工具状态隔离到 `E:\Gezhi\.local\uv`。
- uv-managed CPython 固定为 `3.11.15`，两个 Python 项目均要求 `==3.11.*`。
- Codex CLI 是独立的项目级 npm 运行时。Node.js/npm 只用于依据锁文件安装它，不参与格致的 Python 依赖解析。
- Windows 已启用 Win32 长路径支持，并安装 Git、VC++ Runtime 与 NVIDIA 驱动。
- Conda、Ollama、Docker 和 WSL 不参与格致运行时；WSL PaperBot 仅作为行为、边界和数据夹具的只读参考。

## 核心环境

仓库根目录是独立 uv 项目，使用根目录的 `.venv`、`.python-version`、`pyproject.toml` 和 `uv.lock`。锁文件解析 41 个包，环境安装 39 个包。

直接运行时依赖的冻结版本：

- `feedparser==6.0.14`
- `httpx==0.28.1`
- `pydantic==2.13.4`
- `pydantic-settings==2.14.2`
- `pypdf==6.14.2`
- `rapidfuzz==3.14.5`
- `rich==15.0.0`
- `tenacity==9.1.4`
- `typer==0.27.0`

直接开发依赖的冻结版本：

- `mypy==2.3.0`
- `pytest==9.1.1`
- `pytest-cov==7.1.0`
- `pytest-timeout==2.4.0`
- `ruff==0.16.1`

SQLite、JSON、TOML、日志、哈希、路径、子进程和原子文件操作使用 Python 标准库。

## OCR 环境

`runtimes/ocr/` 是第二个独立 uv 项目，拥有自己的 `.venv` 和 `uv.lock`，不与核心环境共享 workspace 或锁文件。锁文件解析 86 个包，环境安装 85 个包。

直接依赖固定为：

- `mineru[pipeline]==3.4.4`
- `six==1.17.0`
- `torch==2.9.1`，安装产物为 `2.9.1+cu130`
- `torchvision==0.24.1`，安装产物为 `0.24.1+cu130`
- PyTorch wheel index：`https://download.pytorch.org/whl/cu130`

`six` 是真实 PDF 验收发现的必要兼容依赖：MinerU 3.4.4 运行时代码会导入它，但上游包元数据没有声明。它已在最终冻结前显式加入。不得安装 `torchaudio`。MinerU 强制带入的 OpenAI SDK 只允许作为 OCR 环境的间接依赖；格致代码不得导入或调用它。

## MinerU 模型与配置

- 安装期从 ModelScope 下载 pipeline 模型，共约 2.60 GB。
- `MODELSCOPE_CACHE` 仅在下载子进程中指向 `E:\Gezhi\.local\mineru`。
- 固定模板为 `runtimes/ocr/mineru.template.json`，来源是 MinerU `3.4.4` 发布标签。
- 实际配置生成到 `E:\Gezhi\.local\mineru\mineru.json`，不纳入 Git。
- 运行 OCR 时向子进程注入 `MINERU_TOOLS_CONFIG_JSON`、`MINERU_MODEL_SOURCE=local` 和 `MINERU_DEVICE_MODE=cuda`。
- 同时设置 ModelScope/Hugging Face 离线开关；运行期不得下载模型。
- 不设置用户级或系统级 MinerU/ModelScope 环境变量。

## 语义模型与 Codex CLI

确定性操作由 Python 规则完成。论文理解、候选知识提取与语义质量检查通过原生 Windows Codex CLI 的非交互模式完成；不使用 Ollama、本地小模型、模型路由器或 OpenAI Python SDK。Codex 不可用时只阻塞语义阶段。

- `runtimes/codex/package.json` 和 `package-lock.json` 精确锁定 `@openai/codex==0.146.0`。
- 所有项目调用统一经过 `tools/codex.ps1`；入口同时校验 npm 主包、Windows x64 原生包和实际 CLI 版本。
- Windows 上的 Codex CLI 最终运行一个原生 `codex.exe`，这是 CLI 的实现形式，不代表使用桌面应用内置版本。
- 不使用 Codex 桌面应用 WindowsApps 目录中的随附 CLI，也不使用用户级 npm Codex；这两者均不属于项目锁定范围。
- 桌面应用更新不会改变项目级 `0.146.0`。但在线服务的最低兼容版本不能由本地仓库冻结；如果服务端拒绝旧 CLI，只按冻结规则开启受控升级窗口。

## 已通过的验收门槛

1. 核心环境：`uv lock --check`、`uv sync --frozen`、`uv pip check`、全部直接依赖导入和工具版本均通过，且同步无安装、卸载或升级。
2. OCR 环境：同样通过锁、冻结同步和包兼容检查；Python 为 `3.11.15`，MinerU 为 `3.4.4`。
3. CUDA：PyTorch CUDA 构建为 `13.0`，`torch.cuda.is_available()` 为真，并识别 `NVIDIA GeForce RTX 4090`。
4. MinerU：在完全离线模型模式下，使用 GPU pipeline 解析真实的 6 页论文 PDF；生成 22 个文件、Markdown、4 个可解析 JSON、标注 PDF 和 14 张图片。
5. Codex：项目入口报告 `codex-cli 0.146.0`，登录状态为 ChatGPT；以只读、无工具、非交互方式调用 `gpt-5.6-sol`，返回精确标记 `GEZHI_CODEX_OK`。

至此环境进入冻结状态。后续业务实现不得改变上述依赖图。

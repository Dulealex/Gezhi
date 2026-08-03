# 格致环境契约

格致的依赖在业务实现开始前一次性解析、安装和验收。最终锁定后，实施阶段不得执行会改变依赖图的操作。缺少或失效的依赖只阻塞依赖它的阶段，其余任务继续执行。

本基线于 2026-07-31 在 Windows 与 RTX 4090 上完成依赖验收；2026-08-03 又完成一次受控 packaging baseline 更新，把根项目安装为 editable pure-Python distribution，但没有改变第三方 runtime/dev 依赖集合。

## 冻结规则

- 核心环境和 OCR 环境只允许执行 `uv sync --frozen`；不得执行 `uv add`、`uv remove`、`uv lock --upgrade` 或隐式更新锁文件的命令。根项目 build 只允许由项目锁定的 uv 0.11.32 使用其兼容 bundled `uv_build` 完成，不支持以其他 build frontend 重新解析 backend requirement。
- Codex CLI 只允许执行 `npm ci --prefix runtimes\codex`，由 `package-lock.json` 还原；不得在实施期间执行 `npm update` 或改变 `package.json`。
- 需要新增、删除或升级任何依赖时，先把受影响阶段标为阻塞，再开启一次明确的依赖变更窗口；重新通过全部相关验收后才能形成新的冻结基线。
- 不允许静默安装缺失依赖、自动升级或切换备用模型。

## 包管理器与工具链

- Python 依赖统一使用 uv，不使用 Conda。用户级 `uv 0.11.32` 只是可执行工具；`tools/uv.ps1` 会校验版本，并把 Python、缓存和工具状态隔离到 `E:\Gezhi\.local\uv`。
- uv-managed CPython 固定为 `3.11.15`，两个 Python 项目均要求 `==3.11.*`。
- 根项目的 Python distribution 使用 `src/gezhi/` packaged layout：`[tool.uv] package=true`，build requirement 固定在兼容范围 `uv_build>=0.11.26,<0.12`，实际受支持 backend 是 uv 0.11.32 executable 内的 bundled copy。`uv_build` 不进入核心 runtime dependency list，也不单独常驻核心环境；它不负责编译 ADR 0101 的项目自有 x64 cancellation bridge，该 DLL 继续由独立冻结的 MSVC 流程形成并通过标准库加载。
- 根项目只安装一个 `gezhi` console entry point，metadata target 精确为 `gezhi.bootstrap:main`；它与未来 `python -m gezhi` adapter 共用 [ADR 0112](./adr/0112-package-gezhi-with-two-launch-adapters-and-one-bootstrap-seam.md) 的同一 bootstrap seam。当前 packaging baseline 只验收 distribution、entry-point metadata 与 executable formation；bootstrap/preflight 源码形成前不声称 CLI runtime smoke 已通过。
- Codex CLI 是独立的项目级 npm 运行时。Node.js/npm 只用于依据锁文件安装它，不参与格致的 Python 依赖解析。
- Windows 已启用 Win32 长路径支持，并安装 Git、VC++ Runtime 与 NVIDIA 驱动。
- Ctrl+C bridge 的 build-only 系统工具固定为 Visual Studio Build Tools 2022 `17.14.13`、x64 MSVC toolset directory `14.44.35207`（`cl 19.44.35215.0`、`link 14.44.35215.0`）和 Windows SDK `10.0.26100.0`。构建入口必须通过 `vswhere.exe` 与已安装 metadata 发现路径，不能依赖 PATH 或硬编码当前安装盘。
- Native bridge 使用项目自有 x64 C DLL、release `/MT` 与 Windows SDK；Python 只通过标准库 `ctypes.WinDLL` 调用，不增加 Python headers、CMake、Ninja、CFFI、pybind11、uv 或 npm 依赖。上述工具缺失或漂移只阻塞 bridge build/test，实施阶段不得自动安装或升级。
- Conda、Ollama、Docker 和 WSL 不参与格致运行时；WSL PaperBot 仅作为行为、边界和数据夹具的只读参考。

## 核心环境

仓库根目录是独立 uv packaged project，使用根目录的 `.venv`、`.python-version`、`pyproject.toml` 和 `uv.lock`。锁文件仍解析 41 个包；环境安装 40 个 distribution，其中新增的一项只是来自 `file:///E:/Gezhi` 的 editable `gezhi==0.1.0`，第三方包数量仍为 39。锁文件中的根 source 已从 `virtual = "."` 改为 `editable = "."`。

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

Build-system requirement 是 `uv_build>=0.11.26,<0.12`。在受支持路径中它由固定 uv 0.11.32 executable 的兼容 bundled backend 满足，不作为第 41 个常驻 distribution，也不授权使用其他 frontend 选择一个不同 backend 版本。

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
- `tools/codex.ps1` 保留为安装验收与人工项目入口，负责校验 npm 主包、Windows x64 原生包和实际 CLI 版本；它不作为 Literature/Knowledge runtime attempt 的 PowerShell wrapper。
- Runtime adapter 在首次 launch commitment 前通过项目自有 resolver 读取同一 npm lock/package identity，证明主包 `0.146.0`、native package `0.146.0-win32-x64` 与唯一绝对 native CLI 路径，然后按 [ADR 0106](./adr/0106-run-command-owned-children-without-a-console.md) 直接启动该文件。不得在每个 attempt 内先运行 `codex.exe --version`，也不得引入可更新的 PowerShell host 作为运行时依赖。
- Windows 上的项目级 Codex CLI 最终就是上述原生 `codex.exe`；直接启动它是在调用 npm 锁定 CLI 的实现，不代表使用桌面应用内置版本。
- 不使用 Codex 桌面应用 WindowsApps 目录中的随附 CLI，也不使用用户级 npm Codex；这两者均不属于项目锁定范围。
- 桌面应用更新不会改变项目级 `0.146.0`。但在线服务的最低兼容版本不能由本地仓库冻结；如果服务端拒绝旧 CLI，只按冻结规则开启受控升级窗口。

## 已通过的验收门槛

1. 核心环境：`uv lock --check`、`uv sync --frozen`、`uv pip check`、全部直接依赖导入和工具版本均通过，且同步无安装、卸载或升级。Editable `gezhi==0.1.0` 已安装，环境中恰有一个名为 `gezhi` 的 console entry point，其 target 精确为 `gezhi.bootstrap:main`，并已生成 `.venv\Scripts\gezhi.exe`；按 [ADR 0112](./adr/0112-package-gezhi-with-two-launch-adapters-and-one-bootstrap-seam.md)，真正执行该入口的 runtime contract smoke 仍等待 bootstrap/preflight implementation。
2. OCR 环境：同样通过锁、冻结同步和包兼容检查；Python 为 `3.11.15`，MinerU 为 `3.4.4`。
3. CUDA：PyTorch CUDA 构建为 `13.0`，`torch.cuda.is_available()` 为真，并识别 `NVIDIA GeForce RTX 4090`。
4. MinerU：在完全离线模型模式下，使用 GPU pipeline 解析真实的 6 页论文 PDF；生成 22 个文件、Markdown、4 个可解析 JSON、标注 PDF 和 14 张图片。
5. Codex：项目入口报告 `codex-cli 0.146.0`，登录状态为 ChatGPT；以只读、无工具、非交互方式调用 `gpt-5.6-sol`，返回精确标记 `GEZHI_CODEX_OK`。
6. Native build-only 工具：`vswhere.exe` 能定位完整且可启动的 VS Build Tools 2022 `17.14.13`；x64 `cl/link` 实际报告 `19.44.35215.0/14.44.35215.0`，Windows SDK `10.0.26100.0` 的 console header 与 x64 `kernel32.lib` 已验证存在。Bridge source/ABI 尚未实现，因此这里不声称 DLL runtime smoke test 已通过。

至此 Python/npm 依赖图、root packaging metadata、uv build-system requirement 与 native build-only 系统工具基线进入冻结状态。后续业务实现不得改变上述依赖图、package mode、entry-point target 或工具链；确需改变时必须重新开启明确的环境变更窗口。

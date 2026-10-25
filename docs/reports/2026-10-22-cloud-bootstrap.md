# 云端启动实证（2026-10-22）

采集于 `2026-10-22T06:26:37Z` 附近；全部命令在已发布云端执行，不使用用户本机历史测试作通过证明。

| 检查 | 本次结果 |
| --- | --- |
| 环境启动 | 等待工具返回 `ready`，随后真实执行 shell/Python/Git |
| 仓库路径 | `/workspace/YGO-Kito`；`/workspace` 仅为父目录，不是 Git 仓库 |
| origin | `https://github.com/K1tKaLL0s/YGO-Kito.git` |
| 起点 HEAD | `8914e8055d45f3825fc56f67141750bd5067c2aa` |
| 初始工作区 | `git status --short --branch` 返回 `## work`，无修改 |
| 工作分支 | 已从该提交创建 `codex/phase-1-cpu-foundation` |
| AGENTS.md | 父目录和仓库均未发现 |
| 系统 | Linux 6.18.55 x86_64 |
| Python / uv | CPython 3.12.14 / uv 0.12.23 |
| Git / GCC / make | Git 2.52.0 / GCC 14.2.0 / make 可执行文件存在 |
| CMake / Ninja | 未发现；本次纯 Python M1 不需要，真实核心构建前补齐 |
| SQLite | 3.53.1；临时库 CREATE/INSERT/SELECT 返回 1，文件确实写入 |
| 项目 `.venv` | Python 3.12.14；torch 2.14.1+cpu、NumPy 2.3.5、setuptools 84.2.1 元数据存在 |
| 系统与项目 Python 差异 | 系统 Python 无 torch；执行项目命令须用 `.venv/bin/python` |
| pip / pytest | 系统 pip 26.2.1；项目环境无 pip；两处均无 pytest |
| 自动测试路线 | M1 使用标准库 unittest；不依赖历史 15 项参考答案测试 |
| 原件完整性 | 清单 11/11 字节数和 SHA-256 匹配；未解包/执行学生文件 |

验证命令包括 `git rev-parse --show-toplevel`、`git rev-parse HEAD`、`git remote -v`、`python --version`、`uv --version`、`gcc --version`，以及 Python `sqlite3` 临时库往返。`.venv` 版本通过 `importlib.metadata` 独立读取，未运行模型前后向、训练或 CUDA 检查。

已能开始 M1。当前生产代码、规则核心、卡脚本和 cards.cdb 均未提供，真实规则链路为待接入；CMake 缺失是后续原生构建准备项，不是已验证引擎能力。未产生凭据或权限阻碍，未启动付费资源。原定稿及学习分工已核对，最新统一说明的明确变更优先。

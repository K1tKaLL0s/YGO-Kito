# YGO-Kito

现行设计从 [docs/current/README.md](docs/current/README.md) 进入，覆盖总体、构筑流程、评分扣分、模型接口与训练验收。执行书和历史结果在 [docs/reports](docs/reports/)，不作为现行规则。

统一开发仓库为 N:\YGO-Kito\_publish_20261030；当前检出承担统筹与整合职责。决斗、构筑、统筹从同一基线分工，具体路径和提交见 [整合报告](docs/reports/2026-11-11-baseline-consolidation.md)。旧功能分支、旧CPU源码和监督WIP均以 archive 引用保留恢复，不再作为运行入口。

## 开发与运行

Python源码位于src/ygo_kito，命令入口为 python -m ygo_kito；项目安装/依赖以pyproject.toml和requirements目录为准。构筑CLI为scripts/run_construction.py，JSON Lines服务见 [Agent接入](docs/development/generic-agent-integration.md)，构筑操作见 [构筑运行说明](docs/development/construction-admission.md)。

正式本地课程使用 [独立 Python 3.12 CUDA 环境](docs/development/cuda-runtime.md)与 `configs/local-cuda-runtime-v1.json`。`local-training.ps1 -Action ValidateRestore` 完整检查课程恢复而不启动训练；旧 CPU 状态需通过显式迁移命令生成新 GPU 边界。认知训练环境独立维护。

安全CPU白名单为 scripts/check_merge_candidate.py，要求项目已有CPU-only Torch环境，输出本地回执；不运行未筛选discovery或原生故障测试。CI、真实引擎、GPU运行和正式能力成绩分别记录。

## 共享本地资产

资产根保持 N:\YGO-Kito\_local_cpu_20261027：assets、课程权重和reports不随分树复制。course-continuation.json是实际续接课程根的唯一入口；原reports/optimization-20261031/2207-course-006保留为CPU迁移来源。正式CUDA解释器由运行配置定位，旧venv仅供CPU回归。source目录退役为仅保留原.cache资产定位，不能加入PYTHONPATH。

规则资源实体为assets/native/engine-src；中文卡库database/locales/zh-CN/cards.cdb，禁表client/lflist.conf；效果字典assets/effect-blocks/effect-blocks-v1.sqlite3。source/.cache/local-base-training-20261027/2207-base-005/active-environment.local.json仍作既有环境定位。各工作树使用自己的源码和独立输出目录，不能并发写同一课程存档。

指定参考为configs/user-deck-references/main-01-source-v1.json（2207）及main-02-source-v2.json（2210）；只用于独立评价和允许的功能提示。原run-007、训练hold、checkpoint/latest不因仓库整理恢复或改写。

## 学习与来源

[学习资料](docs/learning/)和[技术参考](docs/reference/)保留。原件来源清单 [archive-manifest.json](archive-manifest.json) 标明哪些旧设计已由现行正文替代，旧正文从Git历史恢复。外层目录保留资源、艺术素材、回放与其他独立工具，不作为第二个开发基线。

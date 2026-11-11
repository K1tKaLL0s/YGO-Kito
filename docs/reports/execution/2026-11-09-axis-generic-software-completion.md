# 整个轴与泛用模块软件交付：机械执行补充

> 执行与历史记录。现行行为以 [现行设计](../../current/README.md) 为准；本文的日期状态和当时授权不自动适用于新任务。

2026-11-09，香港时间。主进程独立实施，无子代理，无待答问题。本书承接主计划全部 T1–T5 的源码工作；真实准备、正式训练、CB、原生引擎、CI 和实际能力发布继续暂停。工程样本更新、临时 checkpoint 与对应测试已获授权。本书交付后直接实施。

## 目标、事实与边界

完成数据入口、训练控制、四格消融配方、分组隔离校准、独立评估/逐能力发布接口、环境三路适配及使用文档。验收退出标准是这些路径有可调用源码、明确 CLI/API、人工夹具端到端证据、失败隔离与保存恢复；真实能力指标保持未验证。

现有证据：prepare_v3.prepare_records/prepare 已实现版本化分片、来源分组和旧标签迁移；train_v3._fit 每批直接 train_supervised，缺有效批量与早停；RoleTrainer 使用 Adam；GraphRoleNetwork 无 dropout；CandidateScorer 有校准回调但没有拟合实现；RoleAnalyzer 固定禁用 environment_value；v3 enable_lora 明确拒绝。此前 192 个方法/231 次执行按交接复用。

允许修改专属 multifactor 网络/训练/评分/分析模块、training/axis_generic 入口与新版本配置、专属测试和本文/报告/当前开发索引。新增 calibration.py、environment.py、workflow_v3.py。共享构筑源码只读核对，CB 用现有纯 callable 夹具验契约。禁止改构筑定价、真实资料、历史权重、活动/课程指针、暂停状态、原生与 CI；不执行提交、推送、切换或清理。所有既有 dirty/untracked/deleted 保留。

## 实施与逐项验收

| 步骤 | 文件、符号及前置 | 具体动作和不变量 | 检查方法与通过标准 | 失败处理 |
|---|---|---|---|---|
| S1 训练控制 | network.NetworkConfig、graph_network.GraphRoleNetwork、training.RoleTrainer、graph_training.train_supervised/save/load；先复用 M5 契约 | 可选 AdamW/weight_decay、dropout、梯度上限；有效批量跨微批累积按全批来源分母计算；仅一次更新；默认旧行为保留。优化器配置、随机状态、早停状态绑定恢复 | 新 tests.test_multifactor_training_controls_v3：整批/微批梯度与更新相符、无监督不更新、AdamW/dropout 下一步恢复一致、异常不更新；直接回归 M5 受影响类 | 有非有限值或配置/绑定不匹配立即拒绝；修复当前增量，不回滚用户文件 |
| S2 运行配方 | train_v3._fit/batches/binding_for、config.train.software.v3.json；S1 完成 | 节点/边预算微批、有效批量、早停、固定学习率和停止恢复；新增正式暂停的建议配方，不改旧配置。工程模式仅 CPU、有限批次/轮数与工程来源，检查全部输入后才能更新 | 同一新测试模块：微型 gzip 夹具走实际 runner，早停/恢复与锁释放；paused 入口在读资料/导入模型前拒绝 | 来源混入或游标损坏拒绝；临时目录保留错误日志，不触碰活动目录 |
| S3 消融与校准 | calibration.py、workflow_v3.py、train_v3.predict_saved；S1 完成 | 四格路线×流配方，同数据预算；只对指定有效两格补三种子。保留概率及 raw；来源组均衡温度拟合、决策阈值和类别覆盖；选模/校准/最终组互斥；工件绑定底座 | tests.test_multifactor_workflow_v3：四格独立、隔离拒绝、温度/阈值拟合与序列化、错误绑定/未覆盖拒绝，概率三层保持 | 不能覆盖的头标 unavailable，禁止用最终集修正校准；仅修复具体错误 |
| S4 独立评估与宿主发布接口 | workflow_v3、calibration、scoring、analysis；S3 完成 | 明确独立 test 与历史诊断，逐头 raw/calibrated/applied、覆盖/候选召回/迁移误放/未见接收/退化门槛；候选发布清单不切指针；宿主显式加载匹配工件。工程证据不能生成真实 available | 同上：缺类/缺切片/旧资料/工程来源不发布；合格人工模拟报告可验决定逻辑，真实状态仍 false；评分器接入回归 | 失效仅停对应能力；禁止伪造实际通过 |
| S5 环境支路 | environment.py、training.create_environment_adapter、training/axis_generic/environment_v3.py 及 analysis 环境接口；固定底座 | 独立 head_only、lora_head、full_copy 三种环境分支；仅显式公共环境特征与有来源投入价值反馈；底座不被训练/切换；适配器独立保存，校准与验证后宿主才能应用。v3 的旧 enable_lora 继续拒绝角色头 hook，新的显式环境工厂是确定路由 | tests.test_multifactor_environment_v3：三模式有限更新、基础输出逐值不变、冻结参数、保存恢复下一步、错底座/来源拒绝、默认禁用及显式能力接线；暂停入口在读文件前拒绝 | 任何基础参数变化或环境来源混用视为失败；不发布适配器 |
| S6 契约与交付 | tests.test_construction_recognition 已有 hints 方法；报告/开发说明/MASTER | 核对 _candidate_basic_cb 只调用提供的 fixture callable；guard 拦真实搜索/native/provider；文档列完整入口和剩余真实阶段 | 明确选取 hints 方法及新模块；git diff --check 限修改 tracked 文件，新文件 AST/空白检查；0 failures/errors/skips/禁止调用 | 禁止入口触发即停相应检查；记录真实结果后修复，保留原日志 |

## 工程运行约定

在 N:\YGO-Kito\_publish_20261030，用 E:\Ana\envs\pcacgate\python.exe -B -m unittest 上表明确模块/方法 -v；不 discovery。PYTHONPATH=仓库/src;仓库，PYTHONDONTWRITEBYTECODE=1，OMP/MKL 各 2，TEMP/TMP/TORCH_HOME 和日志在 .cache/axis-generic-software-20261109-01。必要 E 环境 DLL 路径仅在子命令 PATH 增加。无安装/下载/真实 catalog/deck_cache 访问，人工 gzip/SQLite/JSON 放任务临时目录。训练源码修改前只保存受改文件的小型回退副本，不做全仓哈希或新基线。每步通过后只随新改动重验直接影响面。

固定学习率是本轮确定路线，调度状态明确记录 constant；不新增未要求的学习率搜索。既有 checkpoint 的源码指纹约束保留；历史权重使用原代码，不能为兼容新代码移除校验。新工件不可覆盖，恢复失败保持文件不动。GPU、真实标注覆盖、统计强度、实际宿主和模型能力为后续真实阶段假设，本轮不宣称验证。

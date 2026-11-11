# 整个轴与泛用模块：源码与工程交付完成

后续核查更新（2026-11-09）：本报告保存首轮交付时的证据。随后全面源码核查发现并修复旧入口残留、比较链、恢复边界及评估绑定缺口；当前状态以[设计核查与清理报告](2026-11-09-axis-generic-review-cleanup.md)为准，不把本报告的“完成”表述作为免检依据。

2026-11-09，香港时间。实际仓库 N:\YGO-Kito\_publish_20261030，主进程独立实施，无子代理。完成范围是整个模块源码和允许的工程验收，包含 T1–T5 的软件路径，没有停留在 M7 或逐批等待指令。

## 交付范围

| 范围 | 源码与工程结果 |
|---|---|
| T1 数据准备 | 复用 prepare_v3 来源分组、四类留出、迁移、缓存与分片；补评估分片显式读取、语义身份、分区/来源检查。没有消费真实资料。 |
| T2 训练 | AdamW/weight_decay、dropout、梯度上限；有效批跨分片累积、图预算拆微批、全批来源分母归一化；早停、完成态恢复、完整配方及分区组记录；旧默认与原配置保留。 |
| T3 消融/校准 | 四格单种子与指定两格三种子配方、同预算比较；完整概率、分组等权温度/阈值拟合、训练/选模/校准组互斥；工件绑定实际底座权重。 |
| T4 评估/能力接线 | 独立 test 与历史诊断、三层输出、固定分母、来源等权指标、多类 Brier/ECE；类别/输出坐标/关键切片/召回/退化检查；逐能力候选及宿主显式加载，不写活动版本。 |
| T5 环境 | 固定底座外 head_only/lora_head/full_copy 三路，反馈隔离、来源等权损失、独立保存与恢复、校准/评估入口、默认 disabled 及显式环境 provider。 |
| CB 提示接口 | 核对 _candidate_basic_cb 只调用传入 callable；人工 callable 支持握手通过。真实搜索、provider 和原生入口被 guard 拦截，禁止调用计数 0。 |

主要新增为 multifactor/calibration.py、multifactor/environment.py、training/axis_generic/workflow_v3.py、environment_v3.py 和两份仍暂停的配置。完整 API/CLI、输入字段、恢复和真实阶段顺序见[使用说明](../development/axis-generic-software-v3.md)；修改前已交付[机械执行补充](execution/2026-11-09-axis-generic-software-completion.md)。

## 实际工程证据

使用既有 Python 3.10.20 / Torch 2.2.2，CPU、OMP/MKL 各 2，-B 和禁止 pyc。人工记录、gzip 和临时 checkpoint 位于任务缓存及测试临时目录，无安装或下载。

| 批次 | 实际结果 |
|---|---|
| training-first.log | 训练控制 6/6 首次通过。 |
| workflow-environment-first.log | 最初校准/环境 13/13 首次通过。 |
| acceptance-first.json | 88 项，85 通过、3 error；无 failure、skip、禁止调用。 |
| acceptance-fixes.json | 12/12 通过，闭合上述三项错误并复验直接影响面。 |
| acceptance-workflow-final.json | 20/20 通过，包括输出坐标覆盖、CLI 往返、环境边界增量。 |
| acceptance-cli.json | 3/3 通过：CLI 保存链、分片身份、65 条分批预测且无更新。 |
| acceptance-isolation.json | 16/16 通过，校准工件绑定训练组，调用者省略训练组不能绕过隔离；实际运行器保存分区和恢复通过。 |

完整方法和逐方法最新状态存于 .cache/axis-generic-software-20261109-01/acceptance-summary.json。首次错误和所有复验原日志保留。此前 M7 的 192 个不同方法/231 次执行复用，本轮有直接回归重叠，不能简单相加。

首次错误与修复：

- 新来源等权混淆矩阵混用整数与 unknown 字符串键，排序 JSON 失败；统一字符串键，增加 CLI JSON 往返验证。
- CB 提示方法选中的第一个牌表不含已注入已知效果的测试卡，因此无可用提示；仅专属方法换成含该卡的牌表，保持记录与调用对象一致。未修改共享夹具、解析器或生产 CB。
- 初次 git diff --check 将三个受改 tracked Python 文件的 CRLF 计为空白；仅这些文件规范化为 LF，复查通过，没有全仓格式清理。

## 文件与运行边界

全部既有 dirty/untracked/deleted 和并行构筑成果保留。graph_training.save 的 Windows 不覆盖 rename、其他平台 link、并发目标保护保留并经回归。无 prior 中性回退及原消费者修复保持。没有提交、推送、合并、发布、checkout/reset/clean/stash 或新 worktree。

旧训练配置、真实资料、历史/活动权重、课程/暂停指针、构筑定价和 CI 源码未切换。新配置的 formal_training、automatic_lora、core_course_resumed 均为 false。工程更新及临时 checkpoint I/O 有实际执行；正式训练、真实资料准备、CB 搜索、原生引擎、CI、真实能力发布执行数为 0。

## 完成与后续

M1–M7 和 T1–T5 的源码、配置、接口和允许的工程交付形成完整调用链。本轮共 94 个不同方法最终通过，158 次物理执行；0 failure、3 次历史 error（均已闭合）、0 skip、0 禁止入口调用，没有未闭合工程失败。工程与源码静态检查、CLI 帮助和文档链接回执保存在同一任务缓存目录。

真实标注质量/覆盖、正式训练、四格实际模型对照、真实校准与独立能力成绩、GPU 和真实宿主发布仍未验证。这些属于下一阶段实际运行，保留用户原运行限制；不能用本次随机工程工件冒充已训练角色能力。历史权重继续使用对应相容源码。

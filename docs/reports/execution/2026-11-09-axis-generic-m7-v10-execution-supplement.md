# M7 V10 回收时序与资源复用机械执行补充

> 执行与历史记录。现行行为以 [现行设计](../../current/README.md) 为准；本文的日期状态和当时授权不自动适用于新任务。

日期：2026-11-09，香港时间。依据[主执行书](2026-11-08-axis-generic-execution-plan.md)第 7 节 V10、第 9 节剩余项和用户本次“允许对应测试及必要导入、后续自行安排”的授权，先交付本补充后直接实施。全部由本聊天主进程完成，不启用子代理，没有待答问题；保留全部既有 dirty/untracked/deleted 和并行成果。

## 目标与实际基线

完整仓库 `N:\YGO-Kito\_publish_20261030`，复用 `codex/optimization-20261031`，定位 HEAD `3f57198e5e366152bbb672be8910e6800f8adbb4`，不按 HEAD 重建文件。Q1–Q5 先前累计 187 个不同方法通过、226 次物理执行，详见[Q5 报告](../2026-11-09-axis-generic-m7-q5.md)。这些已通过集合没有新影响时不重复。

已读取当前 `src/ygo_kito/multifactor/conditions.py` 的 `Resource/Condition/_Search.matches/compatible/atomic/solve_requirements` 和 Q2 现有资源方法。资源有 stage/available_until、source/known、pool_id/resource_id、state_zone；原 consume 预约持续到观察末尾，occupy/retain 有明确释放边界，别名共用物理槽。solve_requirements 文档明确要求回收/变换结果作为另一个带来源的库存事实提供。现有 `AllocationTests.test_occupancy_retention_and_distinctness` 已通过，本批补齐实际回收输入和反对照证据。

显式回收输出使用新的可用库存批次 pool_id，保留同一卡实体 resource_id 和回收来源；当前求解器检查所给库存/预约，不负责推导卡效或产生回收事实。名称使用限制作为单独的有限额度资源，同一名称的不同观察保持同一 pool_id。所有名称与资料均为本地人工工程夹具。

## 文件与技术范围

正常路径只新增 `tests/test_multifactor_v10_resources.py` 的五个方法、本补充及 `docs/reports/2026-11-09-axis-generic-m7-v10.md`，增量同步主计划当前/第 9 节、M7 A/V 相关末列与当前剩余、MASTER 末尾。既有用例和生产源码不预定修改。临时选择器、运行器、JSON/日志及三份共享文档原字节保存在新目录 `.cache/axis-generic-m7-v10-20261109-01`。

不改真实资料、runs、权重、配置、活动/暂停/课程指针、LoRA、构筑政策和数据库；不运行正式训练、真实准备、CB/provider/搜索、原生引擎或 CI，不提交、推送、合并或发布。沿用已有 `E:\Ana\envs\pcacgate\python.exe`，不安装依赖。本批只需标准库和轻量契约/资源求解导入，不需要模型、工程更新或 checkpoint I/O；之前 Q5 授权不撤销，但本批不重复这些检查。

## 五个明确验收方法

| 方法（`V10ResourceRecoveryTests`） | 输入/反对照 | 必须观察到的结果 |
|---|---|---|
| `test_recovery_is_available_only_at_its_declared_stage` | 初始手牌在 activation 消耗；同一实体回收到手牌的显式新库存批次仅 post_resolution 可用；对照缺回收、过早 resolution、错误区域/作用方 | 完整后续用法成功且两个消耗证据携带各自来源/批次；缺失或过早/错域在完整观察下失败，原输入不变 |
| `test_recovered_stock_and_aliases_do_not_duplicate_a_copy` | 两个 selector 观察同一回收库存；一次或两次请求；显式第二份独立回收库存 | 单份不能同时支付两个请求，别名不增量；实际两份可支付且 witness 槽不同 |
| `test_unknown_or_unobserved_recovery_keeps_the_result_unknown` | 相同后续用法，分别不完整观察、known=False 回收、完整缺失、明确 known 回收 | 开放/未知观察保持 None，完整缺失为 False，明确回收为 True，未知回收不能出现在已知消耗证据 |
| `test_occupancy_release_and_retention_have_explicit_boundaries` | 明确跨 activation..post_resolution 的库存，occupy/retain 到 resolution；在 resolution 或 post_resolution 请求消耗，及未声明延长的库存 | 结束阶段仍受预约，之后才可用；没有可用期依据不能延长。occupy/retain 证据保持各自 mode/start/end |
| `test_recovery_does_not_reset_a_named_use_limit` | 初始＋显式回收两份可用事实，各次调用都消耗同名额度；额度两个观察共用 pool，对照独立第二名称额度 | 同名一次额度不能因回收而再支付；只有显式独立额度支持两次，卡与额度 witness 各自有限 |

全组通过标准：5 个明确方法=5 个实际成功，0 failure/error/skip/loader error，禁止调用尝试为空。只调用公开 solve_requirements，不以复刻内部算法构造预期。模型/正式训练/真实来源/CB/原生/子进程入口不进入运行路径。

## 分步实施与停止条件

| 步骤 | 文件/符号与前置条件 | 具体动作与预期结果 | 不变量、验证方法/命令、通过标准 | 失败/停止或回退 |
|---|---|---|---|---|
| S1 交付并保存 | 本补充；四个新路径已确认不存在，三份共享文档当前可读 | 先交付本补充，保存三文档原字节并登记 manifest；写上述新模块及精确选择器/受限 runner | 保存逐字节相等；不覆盖旧缓存、测试或并行成果 | 路径被占用或共享锚点变化则读最新增量合并 |
| S2 实际 V10 验收 | 五个新方法，当前解释器存在，必要导入就绪 | 顺序运行一个明确类，不 discovery；保留原始 JSON/stdout/stderr | 原断言全过；sys.modules 无模型/正式训练/CB/原生运行模块，子进程尝试 0 | 保存首轮失败，进入 S3，不改弱断言或引入真实卡效/CB补救 |
| S3 具体失败修复 | 仅实际失败涉及的测试或 conditions.py 符号；原结果已保存 | 先核对是否夹具与已定契约冲突，交付精确修复增量、局部保存后再改；复验失败方法及直接受影响方法 | 若求解核心改变，明确选择 AllocationTests、RequirementTreeTests 和构筑共用分配器方法作直接回归；只改测试则不重跑无影响集合 | 需要被禁止行为时保留待验；仅逆向本批自有增量，不整文件恢复 |
| S4 结果和当前索引 | 本报告/补充、主计划、M7、MASTER；实际回执可用 | 更新 V10 源码/实际证据和累计方法数，保留 CB 与 T 阶段真实未运行状态 | A/V 无缺号重复；旧历史与主计划 2–8 节保留，不借用并行成绩 | 共享变化读最新后按实际插入合并，不回写旧快照 |
| S5 最终限定检查 | 本批三文档差异、新测试、回执和新链接 | 核对方法集合/禁止调用、保护段落、新增空白和 tracked 文档 diff --check | 本批允许工程目标闭合；不重新哈希/扫描全仓，不重复已通过业务集合 | 具体问题只处理相关差异；不自动启动 CB/真实准备/正式训练等后续阶段 |

设置 `PYTHONDONTWRITEBYTECODE=1`、当前仓库/src 的 PYTHONPATH，TEMP/TMP 指向本批 tmp，然后执行：

```powershell
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-v10-20261109-01/run_acceptance.py'
```

本批预期新增 5 个不同方法；实际累计按与先前 187 个 ID 的并集及真实复验次数登记。CB 提示接口、真实资料/SQL 迁移、正式训练/独立评估/真实校准与发布、历史生产权重/GPU/真实宿主运行继续保留对应阶段状态，T1–T5 不启动。

## 本批实际状态

五个明确方法首次全部通过，0 failure/error/skip/loader error，禁止动作尝试和越界模块均为空，退出码 0；无生产或既有测试修改，没有进入 S3。累计 192 个不同方法有通过结果、231 次物理执行。完整证据见[实际报告](../2026-11-09-axis-generic-m7-v10.md)和任务目录 v10-result.json/acceptance-summary.json；最终限定检查见 document-review.json。

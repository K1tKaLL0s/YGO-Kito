# M7 Q3 与 Q4 事实路径实际验收记录

日期：2026-11-09，香港时间。按用户允许主进程自主安排后续工作的授权，承接已通过的 Q1/Q2，先交付[本批机械执行补充及三次精确修复增量](execution/2026-11-09-axis-generic-m7-q3q4-facts-execution-supplement.md)，再执行 Q3 工程验证和 Q4 不含模型/CB 的事实路径。全部由主进程完成，没有子代理。

## 最终结果

完整检出仍为 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，定位 HEAD `3f57198e5e366152bbb672be8910e6800f8adbb4`。沿用已有 `E:\Ana\envs\pcacgate\python.exe`，Python 3.10.20、Torch 2.2.2；没有安装、升级或更换解释器。

| 范围 | 不同方法数 | 最终具有通过结果 | 证据与边界 |
|---|---|---|---|
| 已有 Q1 | 13 | 13 | [前批报告](2026-11-09-axis-generic-m7-q1q2.md)，本批未重跑 |
| 已有 Q2 | 30 | 30 | 包含 V11/V12；收尾因并行修改另复验共享分配器 1 项 |
| Q3 | 35 | 35 | 本批首次通过，包含 V21 SQL 和四格子进程 |
| Q4 候选/图 | 20 | 20 | 首轮通过，无网络前向 |
| Q4 事实服务 | 23 | 23 | 首轮通过，评分/校准输出由 Mock 提供契约数据 |
| Q4 非 CB 消费者 | 11 | 11 | 经下述修复后最终复验通过，包含 observe 延时与 assist 宿主接线 |
| 合计 | 132 | 132 | 各组中选定的不同方法；整个 M7 尚未完成 |

本轮会话实际测试执行共 166 次，包含修复所需的重复；不能写成 132 项首次全部通过。Q4 最终覆盖集合由首轮 43 个候选/图/服务成功 ID（其中 1 项在并行变更后另行复验），加最后 11 个消费者成功 ID 组成，与初次明确选择的 54 个 ID 完全一致。未重复不受本批或并行变更影响的已通过方法；收尾的两个关联复验单列在下文。

原始结果在 `.cache/axis-generic-m7-q3q4-facts-20261109-01`：`q3-result.json`、`q4_facts-result.json`、`q4_fixture_retest-result.json`、`q4_consumer_retest-result.json`、`q4_complete_fixture_retest-result.json` 及各自 stdout/stderr。`acceptance-summary.json` 保存最终去重集合、完整历史和禁止范围；`selections.json` 保存精确选择器。此前 Q1/Q2 的结果继续保留在其原目录。

## 真实失败、原因与修复

| 次序 | 实际结果 | 原因和处理 |
|---|---|---|
| Q3 首轮 | 35 成功，0 failure/error/skip | 无修复，含 4 个允许的 V21 子进程，退出码均 0 |
| Q4 首轮 | 44 成功，0 failure，10 error，0 skip | 消费者在公共 UTF-8 工程夹具按 cp936 读取后被标签连接符校验拒绝，尚未进入消费者断言 |
| 编码修复复验 | 2 成功，4 failure，4 error，0 skip | 发现 assist 的 None 证据兼容问题，以及计时、Mock 接口和功能夹具问题；一次拦截命中只涉及 provider=None 的 not_run 状态构造，没有执行 CB |
| 第二次修复复验 | 8 成功，3 failure，0 error/skip | 剩余三项都没有已知功能事实；受控诊断确认不完整发动句使 draw 保持 unknown，assist 拒绝空能力正确 |
| 补全本地事实夹具复验 | 11 成功，0 failure/error/skip | 11 个非 CB 消费者最终全部通过，禁止动作尝试为空，无子进程 |

长期代码增量仅三份文件：

- [construction_recognition.py](../../src/ygo_kito/construction_recognition.py) 的 `recognition_quality_evidence.evidence`：没有 existing 证据时，中性回退由 None 改为 `{}`。既有功能规范化器继续严格要求 mapping；已有宿主证据仍原样调用/返回，off/observe 不换 callable；未改任何价格、能力发布或学习政策。
- [test_construction_logic.py](../../tests/test_construction_logic.py) 的 `fixture_assets`：工程 JSON 显式使用 `encoding="utf-8"`，其他内容不变。诊断实际默认编码为 cp936、UTF-8 mode 0；默认读取有 0 个“·”，正确 UTF-8 读取有 3 个，没有切换全局编码模式或放宽标签要求。
- [test_construction_recognition.py](../../tests/test_construction_recognition.py)：只固定关系 profiler 的 perf_counter，保留完整 off/observe 输出及 session 相等断言，monotonic 的 0→10000 延时扰动不变；去重 Mock 使用 callable spec 并验证记录成功；异常政策用例选择实际含功能的候选并确认 mapper 调用；在本模块 wrapper 中补全工程卡的发动句。没有改并行构筑的公共功能夹具或生产解析器。

事实诊断表明 `①：自己从卡组抽1张。` 没有解析器要求的完整发动句，操作 reason 为 unknown；本模块现在使用 `①：自己主要阶段可以发动。自己从卡组抽1张。`。观察器和 assist 的 unknown/准入规则保留，不通过注入学习标签或仅改能力标志使测试通过。没有 draw 卡的首个候选仍为空事实，继续覆盖 `{}` 回退行为。

## 运行边界

运行器对模型调用、trainer 构造/训练、Adam/AdamW step、checkpoint 加载、真实 prepare/来源读取、CB 提议和原生目标核验安装失败拦截。Q3、Q4 首轮及最后消费者复验没有模型/训练/更新/真实准备/CB provider/原生调用尝试。第一次消费者复验的 `cb_entry=1` 是过宽拦截命中了 `provider=None` 的状态构造；保留原回执。核对源码后只放行这一纯 not_run 分支，非 None CB provider 和搜索仍拦截。

V21 只在内存 SQLite 工程源记录上执行 ASC/DESC，比较未经测试端重排的准备记录、known 掩码、来源组和划分。两个 PYTHONHASHSEED × 两个方向共四个独立解释器进程均成功，实际读取方向和哈希探针受断言约束。它没有验证真实 catalog/deck_cache SQL 迁移或真实资料覆盖。

允许的 import、张量编码、工程 `prepare_records`、临时 gzip 清单、确定性事实分析和宿主 Mock 契约调用均已执行；没有模型前向、优化器更新、训练、checkpoint 加载、真实资料准备、CB provider/搜索、原生引擎或 CI。N 盘本批临时目录承接 TEMP/TMP、日志和缓存，未写旧 runs、模型或活动指针。

## 仍未完成的验收

Q4 的神经图编码/预测等变、混批、成员查询和真实评分仍未运行；两个会构造 trainer 的服务评分方法明确排除。Q5 的损失、微型更新、严格 resume/warm_start 和下一步恢复没有执行，V16 双正格梯度仍待验证。四个旧单元评分/训练方法也保留未执行。CB 提示接口方法明确排除；相应 CB 执行、合法性和原生权威没有被工程接线替代。

Q3 工程范围、选定 Q4 事实范围及 observe 延时/assist 宿主政策工程接线已有通过证据，但实际校准器、能力发布、真实宿主政策/兼容、真实牌表与卡效覆盖、旧权重绑定与设备数值尚未验证。A/V 按已测子范围记录，不将整个 Q4、Q5、全部 A01–A10 或 M7 勾为通过。V30 留 T5，T1–T5 均未开始。

当前能够在明确禁令内独立推进的本批工程验收已经完成。后续顺序仍是剩余 Q4/Q5/CB 接口及相应验收，再按主执行书进入 T1–T5；各项保持其实际条件，不能因用户允许自主安排就执行仍被明确禁止的模型、更新、训练、真实准备、CB、原生或 CI。

## 文件保护与收尾

三份共享文档及本批修复文件的局部保存登记于 `manifest.json`，不是全树基线。共享文件均从最新内容增量修改，保留所有 dirty/untracked/deleted 和并行构筑成果；不据 HEAD 恢复文件，不 checkout/reset/clean/stash，不新建 worktree，不提交、推送、合并或发布。训练/课程暂停、活动模型和 LoRA、构筑定价/学习/调度、数据库及原生接口不变。

最终文档/代码差异、已有内容保留、语义检查回执一致性及新增空白检查见同目录 `document-review.json`。本轮没有独立 AST/编译/构建检查，也没有用旧成绩替代新增方法的实际运行。

收尾时 MASTER 被并行构筑任务插入 W1-1 页首摘要，首次旧前缀完全相同检查因此为 false；实际 diff 只有该插入和本批追加，原内容保留。没有删除该摘要或回写旧副本，最终回执分别记录 prefix=false 和识别并行插入后旧内容完整。并行摘要自述规范化 v10，其成绩不转记为识别成绩。

相关共享文件的更新时间早于最后 11 项消费者通过结果，最终消费者使用了更新后的文件。另对较早通过但直接使用后来改动关系模块的两个方法作精确复验：共用分配器委托和单次抽样概率，2/2 通过，0 failure/error/skip、禁止动作尝试为空，见 `q_shared_recheck-result.json`。因此本轮物理测试执行数为 166，仍为 132 个不同方法；其他不受影响方法未重复。首轮文档 requires_review 保留在 `document-review-initial.json`，最终检查见 `document-review.json`。

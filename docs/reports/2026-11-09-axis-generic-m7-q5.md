# M7 Q5 梯度、工程更新与严格恢复实际验收

日期：2026-11-09，香港时间。用户明确允许对应前向、反向、工程更新、保存恢复和必要导入；正式训练、真实资料准备、CB、原生引擎和 CI 继续禁止。已先交付[机械执行补充](../plans/2026-11-09-axis-generic-m7-q5-execution-supplement.md)，实际失败后先追加 S4 精确修复增量再改代码，全部由主进程完成，无子代理。

## 实际结果

复用 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，定位 HEAD `3f57198e5e366152bbb672be8910e6800f8adbb4`；没有按 HEAD 覆盖当前文件。使用已有 `E:\Ana\envs\pcacgate\python.exe`，实际 Python 3.10.20、Torch 2.2.2，CPU、小型 hidden_dim=16 工程模型。没有安装依赖或加载历史生产权重。

| 组/轨迹 | 选择/运行 | 成功 | failure/error/skip | 退出码 | 运行器耗时（含导入） |
|---|---|---|---|---|---|
| q5_masked | 12/12 | 12 | 0/0/0 | 0 | 9.949 秒 |
| q5_deferred 首轮 | 4/4 | 3 | 1/0/0 | 1 | 8.997 秒 |
| q5_legacy | 4/4 | 4 | 0/0/0 | 0 | 9.540 秒 |
| q5_recovery 首轮 | 5/5 | 1 | 0/4/0 | 1 | 9.439 秒 |
| q5_runner | 4/4 | 4 | 0/0/0 | 0 | 5.515 秒 |
| q5_repair：失败五项＋新增竞态 | 6/6 | 6 | 0/0/0 | 0 | 10.141 秒 |

初选 29 个方法首轮 24 通过、1 failure、4 error，失败历史完整保留。精确修复后，只复验五个失败方法并运行一个新增竞态方法，六项全过；本批最终 30 个不同方法都有通过结果，物理执行 35 次。原已通过的 24 个方法和前批 157 个不同方法没有重跑，未解决方法为 0。

累计 187 个不同方法已有通过结果，累计物理执行 226 次（前批 157/191＋本批 30/35）。历史依据见[Q1/Q2](2026-11-09-axis-generic-m7-q1q2.md)、[Q3/Q4 事实路径](2026-11-09-axis-generic-m7-q3q4-facts.md)及[Q4 神经](2026-11-09-axis-generic-m7-q4-neural.md)。本批不是“全部首次通过”。

## 实际通过的行为

V16 专用方法首次通过：同一 LabelSet 的 carrier/enhancer 两个 known/1 格分别编译，BCE 分量为 ln(2)，两个 bias 梯度均为 -0.25；一次工程更新后两格 bias 均增大，steps=1，contribution 头 definition_development 计数只增加一次，其他头不误计。

MaskedLearning 其余 11 项通过：所有 LEARNED_TASKS 的独立损失/来源计数；unknown/conflict/not_applicable 和零置信度不前向、不更新；弱证据缩放不被分母抵消；无监督头参数与计数不变；来源组权重和逐格来源独立；validation/错误协议/非法坐标在更新前拒绝；readiness 保持 deterministic_only、环境头 disabled；明确偏好操作和同定义一致性准入。来源类别 `engine_probe` 在此只是人工工程记录中的字符串，没有调用引擎。

四个此前保留的方法全部取得通过结果：额外训练查询不污染编码或自然推理域、未召回已知轴保持 known 且 skip、缺必要成员禁止泛用标签投射、包标签不广播为成员标签。旧版四项掩码/保存恢复/来源特征/标签协议方法也首次通过。

v3 严格恢复实际通过 Python/Torch RNG、采样游标、下一步更新后全部模型张量逐位相等及头计数一致；数据/划分/recipe/架构等绑定缺失或不匹配拒绝，Adam moments 形状损坏拒绝。warm_start 只复制明确共享编码器，头、优化器、steps 和能力计数重新初始化；既存 checkpoint 文件不覆盖。旧版恢复的参数、优化器元数据、数据游标及下一步结果相等断言保持原文并通过。

Runner 四项首次通过：五条人工 gzip 记录恢复后余下批次顺序相同，不读取最终 test 分片；`main_config({'formal_training':False})` 在资料/设备动作前抛出暂停错误；开发选择分数保持完整类别覆盖语义。没有进入正式 fit/训练循环。

## 两处精确修复和一个新增对照

[graph_training.py](../../src/ygo_kito/multifactor/graph_training.py) 的 `save` 原来在四个 v3 恢复方法中都因 `os.link` 返回 WinError 5，尚未进入 load。现仅在 Windows 分支改用同目录 `os.rename`，其他平台保留原硬链接路径；早期存在检查、payload、finally 清理和恢复校验不变。Windows rename 在目标存在时拒绝覆盖，依据 [Python 3.10 官方文档](https://docs.python.org/3.10/library/os.html#os.rename)；没有改 ACL、提升权限或使用 replace 覆盖目标。

[test_multifactor_units.py](../../tests/test_multifactor_units.py) 的包标签断言原来直接与旧 `None/数值` 元组比较，在 `Targets` 已转为 LabelCell 的当前契约上失败。现在精确断言唯一包 key、四个 unknown/None 格和一个 known/1 格；后续实际工程更新、engineering_only 和成员不继承断言全部保留并通过，没有修改生产标签逻辑。

[test_multifactor_learning_v3.py](../../tests/test_multifactor_learning_v3.py) 新增 `RecoveryTests.test_checkpoint_publish_preserves_a_concurrent_file`：只模拟“发布前另一个写入者刚创建目标”的时序，再调用当前平台真实 publish；实际 FileExistsError、并发文件原字节不变、data_cursor 不提前更新、临时文件清理均通过。现有 V16 和其他原方法没有改写。

## 工程调用与路径边界

六次进程的禁止动作尝试均为空。累计实际 Adam step 22 次、Tensor.backward 22 次、autograd.backward 22 次；后两者是包装/委托层，不能相加为独立反向次数。22 次更新包含首轮恢复在保存前发生的 3 次，以及修复后的正常更新。RoleNetwork.forward 22 次、GraphRoleNetwork.forward 17 次，同样分别记录包装与图层。

torch.save 序列化调用 16 次、torch.load 读取调用 14 次，全部 30 个路径事件在本批 `tmp` 子树内；16 次序列化含首轮发布失败前已完成的 4 次，不能当作 16 次成功 checkpoint 发布。旧版的覆写/损坏样本均是方法自己刚创建的临时文件。临时目录 helper 只在 runner 内重定向，长期 helper 未修改；用例上下文结束后任务 tmp 没有残留条目，原始 JSON/日志仍保留。

正式训练、真实资料准备/来源读取、CB/provider/搜索、原生引擎、子进程、CI 和历史生产权重 I/O 均为 0。活动权重、训练/课程暂停、LoRA、构筑政策和数据库不变。工程方法内部调用 train_supervised/train_preference 已按授权发生，不能继续写成“所有训练 API 未执行”；正式训练阶段未开始，也没有发布模型能力。

## 回执、保护与剩余

任务目录 `.cache/axis-generic-m7-q5-20261109-01` 保存六组 `*-result.json`、对应 stdout/stderr、`acceptance-summary.json` 和 manifest。`selections-before-freeze.json` 保留初次类选择器，当前 selections 将原五个恢复方法冻结为明确 ID，避免新增竞态方法使旧 expected=5 的重放扩成六项；q5_repair 的六个明确选择器另列。

三份共享文档在本批修改前局部保存，三份修复源码/测试在 F1 另存原字节；只登记这些实际对象，没有重建旧基线、备份权重或全仓重复扫描。主计划第 2–8 节、M7 历史/能力设计段及 MASTER 原有与并行内容保留。限定差异、方法集合、路径、新增链接和空白核对见 `document-review.json`。

本批所选 Q5 工程范围已完成，V16/V28/V29 有实际通过证据。仍未完成的 M7 对接范围是排除的 CB 提示接口；真实资料/SQL 迁移、正式训练、独立评估、真实校准/能力发布、历史生产权重绑定和 GPU/真实宿主运行按对应后续阶段继续。V30 的关闭保护工程检查已通过，环境价值/LoRA 实际收益仍留 T5；T1–T5 未开始。

全部由主进程完成，全部现有 dirty/untracked/deleted 及并行成果保留，没有 checkout/reset/clean/stash、恢复既有删除、新建 worktree、提交、推送、合并或发布。

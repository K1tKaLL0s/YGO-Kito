# R5 固定参考评价和阶段续算执行书

2026-11-11，Asia/Hong_Kong。主进程在 `N:\YGO-Kito\_publish_20261030` 实施 F08、F09，沿用原构筑 S3–S5、同一静态事实链和 log2 评分，保留原任务、固定参考、区域和 0.8 比例。范围为 `construction_layer_flow.py`、`construction_fill.py`、`construction_progress.py` 及既有静态测试。真实构筑、训练、权重推理、CB/native 和 run-007 处于原暂停状态。

基线为规范化 v26、字典 b11。固定参考 F08 在本批源码上可复现普通失败。当前 `_construction_cycle` 对参考调用 `binding_provider(session.logic, task, reference_deck)`，迫使参考符合候选的可选图。参考挂起时又将已选择候选回填 `pending_quality`，重做填充、比较、选择。

| 步骤 | 前置、位置和具体动作 | 验收及失败时的处理 |
| --- | --- | --- |
| 1 | R3 及补项 360 个静态测试通过。提取 `ConstructionLayerAdapter` 单库存的归一化、续算、统一评分路径，候选仍传原层评价。参考只传固定任务和实际库存，沿相同入口评估。传入原宿主的必需用途、必需用途间约束和已提供事实，按 `BuildAssets.validate` 检查真实卡表。原路线及必要发动继续是硬条件，明确缺席必需实体时判失败，已有实体但静态未证明时保留未知。 | F08 合法参考缺少候选自选抽卡节点仍有 Evaluation，零分参考照原规则拒绝。增加必需用途在参考中缺失的反例。候选评分或硬条件如有意外变化，先修共享入口。 |
| 2 | 在 `_construction_cycle` 将 S4 完成结果保存到明确的参考待算阶段，候选生成种子与参考游标分开。恢复参考阶段直接使用已经选择的 `stage_3`，从参考的归一化或评分位置继续。时间到期排空既有批次，用户暂停沿原接口优先。 | 执行 12 个候选，测试实际 66 对比较。至少三片 JSON 往返后候选生成、归一化、评分、比较、选择均只执行一次，候选 Evaluation ID、顺序和已选牌表一致。参考未算完时候选仍未通过 S5。如重新进入填充，先修续算状态。 |
| 3 | `construction_layer_flow` 为固定参考计算任务、原来源、政策、规范化、实际参考资产和宿主事实/用途绑定。`restore_progress/revise_quality_policy` 保留已完成候选与历史；旧绑定及实质变更的游标失效，旧的候选待算格式继续可读。后续候选批次复用同一已算完参考。原候选比较和排序保持同一合同。 | 固定参考在候选图变更后复用。同一候选/参考证据换源、政策或资产变化时重新评价，半成品不会写入已算完字段。发现错误复用时先修绑定，保留实际候选数据和失败证据。 |
| 4 | 用原 WSL CPU 环境按方法名和模块显式运行 `test_construction_workflow`、`test_construction_calculation_resume`、`test_construction_binding`、`test_construction_functional_flow`、`test_construction_layer_flow`、`test_construction_entrypoints`、`test_construction_runtime_processing` 的纯静态项。记录一次工作计数、保存恢复、旧合同和合法性证据。 | 通过标准为 F08/F09 转绿、零错误或跳过、无 Torch 或引擎执行。本批文件语法与空白检查通过后进入 R6。测试命令和固定环境沿[总执行书](2026-11-10-design-implementation-repair-execution.md)。 |

扩大到自动主题消费者后发现一条旧验收仍要求给出实际随机送墓命中，才承认接收卡的静态用途。11 月 10 日用户纠正已明确撤回该前提。补充修改 `test_construction_theme.AutomaticThemeTests.test_random_mill_proves_available_cooperation_without_claiming_a_specific_call` 的预期。验收改为完整印刷触发和主题配套可以计分，接收仍按 Main 浓度计算且无指定调用见证。保留主题配套、原分数公式和随机身份的断言。此步只改旧测试；若诊断发现供应被记作实际随机命中，先回到共享关系源头修正。初次受影响组结果保留。 [用户纠正后的静态执行书](2026-11-10-construction-static-entries-execution.md)

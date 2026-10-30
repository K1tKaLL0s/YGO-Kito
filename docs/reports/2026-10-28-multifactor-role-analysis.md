# 独立多因子角色模块交付

2026-10-28。本地分支 `codex/multifactor-roles-20261028`，worktree `N:\YGO-Kito\_migrated\CodexData\2026-10-28\task-14\multifactor-analysis`，从共享源快照 `fefd44cf7d894a670e2c70d94d30d26d225cb264` 建立。未改主工作树或其他任务窗口的文件；未发布、合并或部署。

已实现 `src/ygo_kito/multifactor/`：带来源/未知/可靠度/不确定度的不可变输入、无 ID/名称嵌入的关系集合网络、掩码多标签/适配性损失、整候选成对偏好训练、独立原子 checkpoint/Adam/游标恢复，以及候选评分与局部消融解释。默认网络 **62,264 参数**，现有 PyTorch 即可；无新增依赖或模型下载。

按后续术语校准，输出为 `large_axis / small_axis / strategic_core / support_role / generic_utility`，规模、核心性和依赖分开，允许较大组件服务另一核心，不把大小轴强行等同主辅。工作标注协议可调整，并以 SHA256 绑定标注、模型和 checkpoint。五个角色维度分别记录训练状态；未训练概率只作诊断，工程更新不能释放成已训练生产评分。

父端可后续调用 `CandidateScorer.score_candidates()` 或独立 `python -m ygo_kito.multifactor`，输入由宿主针对当前功能缺口召回的候选快照；不枚举全卡池、不按 ID 填容量、不替换合法性/CB 验证。源码不导入或改写 `construction_model / build_pipeline / build_model / effect_mechanisms / autonomous_construction`。额外模块的训练、标注和质量验证不追加为当前修复的前置条件。

完整标签定义、数值口径、人工标注协议、损失、监督来源、防泄漏、对接示例及独立验证设计见[模块说明](../development/multifactor-role-analysis.md)。[合成 JSON 样例](../examples/multifactor-candidates-v1.json)已通过独立 CLI 实际执行：所有输出维度为 untrained，advisory_score 为 null，未核锁风险与外部合法性仍保留 unknown。

## 实际测试证据

使用已安装 `N:\YGO-Kito\_local_cpu_20261027\venv\Scripts\python.exe`，Windows 11 / CPython **3.12.1** / PyTorch **2.9.1+cpu**，CPU 单线程。运行 `scripts/check_multifactor_roles.py --output .cache/multifactor-check-final`，退出 0，**33 项通过、0 失败、0 错误、0 跳过**：

| 类别 | 数量 | 证明范围 |
| --- | --- | --- |
| 结构性质 | 16 | 重排等变/池化不变、padding、重命名不变、有向关系/对称兼容性、规模重数、未知与零值、掩码梯度、标签协议隔离、CLI、checkpoint/Adam/下一更新一致 |
| 模拟因子路径 | 11 | 实际有限优化、分头/分角色状态、偏好与角色归因分开、候选召回边界、外部规则保留、消融、用途拒绝、同包不同上下文的表达容量 |
| 官方卡效局部契约 | 6 | 三张真实卡的人工局部观察；费用/处理、条件/操作、自肃作用域、未知和版本边界；没有运行引擎或训练角色真值 |

受测模块源摘要为 `69a4ee3510a73e4ca6c491691d9bc620b5b2a43739857dada6782dd81c3ebb1f`。原始日志和逐文件 SHA256 在本 worktree 的 `.cache/multifactor-check-final/tests.log` / `results.json`。测试是在共享 base HEAD 加本增量的受测字节上运行，原始 `tested_head` 保留 base，不把未提交源冒称该 base 内容；提交交付时另核受测字节与提交树一致性。

首轮 30 项中两项保存测试在系统默认重定向临时目录 `C:\Users\27499\AppData\Local\Packages\sandbox.{2c9be181-d450-4a4d-b001-648b22006cd3}\AC\Temp\...` 的 `roles.pt.*.tmp -> roles.pt` 替换操作得到 WinError 5，未成功。未重试这些目标；将测试工件明确放在已授权的本 worktree `.cache/multifactor-test-temp` 后，首次修正版 33 项全部通过。最后增加逐角色状态与偏好/重复保存恢复检查后再次 33 项全部通过。失败与修正收据分别保存在 `.cache/multifactor-check`、`.cache/multifactor-check-workspace-temp` 与 `.cache/multifactor-check-final`，没有删除失败记录。

本地检查没有运行仓库未筛选 discovery、原生测试、正式训练、外部 provider、远端 CI、GPU、陌生主题角色质量验证、同包角色变化的正确率验证或校准。模拟拟合与条件敏感性只证明程序路径/表达容量，不证明学会主辅/规模/泛用概念。缺高质量上下文角色标注及真实配对/干预监督，诚实边界是“可训练模块已交付，能力待训练与独立评估”。

## 观察到的接口与一次受限检查

已读取原训练设计、效果窗口和构筑窗口接口；不假定对方未合代码部署。本次成功读取时记录效果窗口 HEAD `0850819`、构筑窗口 HEAD `041c72b`；文件实际字节单独记录：

| 仅读文件 | SHA256 |
| --- | --- |
| task-7 `effect_mechanisms.py` | `83f3b71aed8554958602632e70835a52564e18596bacf6f4f7c2ac1d7042346e` |
| task-7 `effect_count_limits.py` | `a7c4a414b5c1536d602b78cba156f133650be12ae5b23d0feadb2ab8461026e8` |
| task-3 `construction_candidates.py` | `792f1bacc938d43720bf2b2357a8dd65259dd4047446749354e885804e57bf1d` |
| task-3 `construction_fill.py` | `12e011bead6353a06fe3390b617925d2686d9979c02f656a47b392b4fcaaed11` |

后续只读复核 `git -C N:/YGO-Kito/_migrated/CodexData/2026-10-28/task-7/effect-mechanisms status --short` 与 `rev-parse HEAD` 时，Git 拒绝切入该目录（`Permission denied`）。这两项状态/修订复核 **denied**，没有重试或换入口绕过；没有任何未确定写操作。先前接口读取和文件哈希已完成，独立模块、测试及评分样例均完成，不阻塞本模块交付；也不据此声称掌握对方之后的 Git 状态。

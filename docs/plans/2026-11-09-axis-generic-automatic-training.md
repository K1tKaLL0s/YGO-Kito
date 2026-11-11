# 轴与泛用 v3 正式训练准备及一键运行机械执行书

2026-11-09，香港时间。主进程直接实施，不使用子代理。用户授权本次准备真实资料和交付自动脚本，本轮不启动长时正式训练。用户最新指定本次新文件放在 N 盘项目内。

## 目标和验收

用户在普通 Windows 本地进程中一键开始/恢复基础训练；进程自行准备、预检、训练、保存、可选校准/评估及记录结果，不依赖 Codex/API 值守。默认只准备；正式训练必须显式 Start/--start。原训练器、数据契约、模型和选模语义沿用 v3。缺标签须在模型更新前报告，不能自动删除 selection_tasks。已完成再次启动不得产生新训练更新。

验收逐项为：P1 真实来源可准备且消费历史保留；P2 全任务/类别/输出坐标/来源覆盖及独立划分报告；P3 设备、磁盘、配置预检与正式启动开关；P4 本地日志、阶段、耗时、资源、错误退出码；P5 中断恢复、完成复用、双启动互斥和配置/工件绑定；P6 可选校准/评估复用实际 best 及完整预测工件；P7 有界人工工程验证与准确启动说明。

CB、原生引擎、全仓 CI、环境实验、消融训练、模型发布/活动指针、旧权重、Git 历史和并行改动均不在本次实施范围。额外实验沿现有显式入口，不加入默认链。

## 当前证据

完整工作目录 N:\YGO-Kito\_publish_20261030；大量既有修改保留。prepare_only 调 prepare_v3.prepare；train_v3.fit 已有来源隔离、选模覆盖、checkpoint 游标与早停；workflow_v3 提供 predict/calibrate/evaluate。当前没有跨阶段自动入口。train_v3 在首次周期保存前中断可能留下 experiment 而无 checkpoint；需要初始快照和已发布快照恢复。原配置 formal_training=false、calibration_groups=[]、18 个固定选择任务。

实读旧资料发现 118 个原案例中 20 个 unit=null，prepare_v3.load_legacy_sources 对其 .get 报错；修复输入兼容，不推导缺失标签。只读硬件检查为 Python 3.10.20/Torch 2.2.2/CUDA 12.1，RTX 4060 Laptop 约 8 GiB 显存，CUDA 可用。N 盘约 310 GiB 可用。现有源在 N:\YGO-Kito\data\axis_generic\source。

## 范围、数据流和不变量

允许修改 training/axis_generic 的 prepare_v3.py、train_v3.py、当前两份准备/基础配置；新增 automatic_v3.py、config.automatic.v3.json、scripts/axis-generic-training.ps1 和双击启动 cmd、专项测试及本文/使用报告/总清单。必要修复仅限真实准备及恢复暴露的同链问题，实施前在本文件补记。

新工件统一 N:\YGO-Kito\data\axis_generic\v3 下独立版本目录。原始资料只读，不覆盖旧 run。解释器复用 E:\Ana\envs\pcacgate\python.exe，不下载依赖。编排只调用现有准备、训练、预测、校准、评估 API；没有第二套优化器/训练循环。状态与报告原子保存，OS 文件锁进程退出即释放。配置/数据变化拒绝混入已有实验。校准组按固定种子与来源组确定后冻结，不看最终测试标签调参；最终历史未知资料仍为 retrospective。

## 实施步骤

1. P1：文件 prepare_v3.py 的 load_legacy_sources；前置是已确认 null 来自原数据。把可空 unit 规范为局部空映射，保留 unresolved 功能与原标签迁移；两处 tags/conditions 共用。配置输出路径改到 N 盘独立目录。调用 prepare_only 或新入口 prepare；通过标准是输出 manifest/分片语义一致、消费历史不改标；若来源契约再报错，保留失败记录，只修有实际证据的输入处理，不删样本凑通过。
2. P2：train_v3.py 提取公开 inspect_data 预检供 _fit 和自动入口共用，保留现行选模拒绝条件；增加所有任务的类别/坐标/来源/有效标签统计。automatic_v3 按固定规则预留校准来源并保存 partitions 提案，输出缺口。验证真实覆盖及人工缺类/缺坐标/零权重反例；缺标不调用 RoleTrainer，不缩任务，报告 not_ready。
3. P3/P4：新增 automatic_v3.run/main 和 config.automatic.v3.json；载入现有两份配置，检查目录隔离、磁盘、CUDA、正式开关，持有单实例锁；准备到独立 attempt 再原子发布，已有完整缓存走原校验；状态顺序 prepare→preflight→train→可选 calibration/evaluation→complete。写每次独立日志、events、state、summary，异常落失败阶段并返回非零；Ctrl+C 返回 130。验证假 CUDA、缺标、配置变化、双启动、准备失败保留。
4. P5：train_v3.fit/_fit/save 在首次更新前保存初始 checkpoint；resume 从本实验已发布且通过完整绑定校验的最新完整 checkpoint 恢复，修复缺失 latest/best/partitions 元数据；不覆盖已有 checkpoint。初始元数据部分写入且无权重时只允许匹配配方的零步恢复；未知文件拒绝。验证首步前、中批/epoch 边界中断与连续更新一致，完整结果重入不调用优化器。
5. P6：automatic_v3 可选 postprocess 默认显式配置，加载 best-development 的相容 inference 权重，生成绑定预测、校准与指定 test/retrospective 报告，阶段输出按绑定复用；不调用 release/环境/消融/活动指针。没有独立 test 的真实资料只报告缺口，不能改标。用人工资料验证后处理和工件错绑拒绝。
6. P7：PowerShell 固定仓库/解释器/环境，Start 映射 --start；CMD 双击调用 Start，另一准备命令无 Start。退出码透传，停止后同一命令恢复，完成后重入复用。新增 tests/test_axis_generic_automatic_v3.py 的明确测试方法；以 pcacgate Python、PYTHONPATH=src;仓库、OMP/MKL=2、临时目录在本项目运行，不做 discovery。通过标准为全部选定方法通过、无 skip，并完成 Python AST、JSON、PowerShell 语法和 help/实际准备验证。失败只修本次引入的问题及受影响方法。

## 风险与停止条件

实际实施补充：首轮 13 项工程测试有 11 项通过、2 项 error。一项为测试误读 RoleInput 序列化层级，按公开 from_dict 修正；另一项是 Windows 已成功多次写入的 state.json 在随后原子替换时短暂 WinError 5。write 仅对 Windows 5/32 的同一次原子替换作最多 6 次、总等待 0.75 秒的有限重试，仍失败就抛出，不改 ACL/权限或改用非原子覆写。补测该实际边界。

实际准备补充：完整源为 8643 条、目录选中 2565 卡；先前入口只在准备结束输出，长时间无阶段反馈。prepare/prepare_records 增加可选 emit 的加载、来源组及每 128 条图准备进度，默认 API 保持兼容；本次准备在新目录运行，进度不进入数据内容。第一次无进度完整准备在写文件前停止，诊断原样保留。按原共享组/标签规则执行，不删行或缩小数据来改善耗时。

P1 性能补充（实施前）：实际前 10 个原图为 317–553 节点、约 0.7–1.8 秒/图，首图 profile 中规范化 1.50 秒/总 1.86 秒；8643 条包含 6092 个不同观察。只修改 prepare_v3._canonical_graph：以原完整边多重集交换判定为依据，一次处理所有已证明 twins 的颜色类；全为 twins 时可直接按稳定颜色类编码，否则只对未证明的对称类执行原有 individualization。为不可变 GraphNode.numeric_values 加 8192 项有界缓存，不改因子数学。精确键的字符串排序可变，准备实现绑定因此更新；未提交数据重新准备，原目录不覆写。新增节点改名/排列同键、边结构变化异键、预算耗尽仍拒绝及原数值相等测试；按首图再测实际成本。若不能保持精确同构边界则撤销该优化，不用近似键或丢行替代。

同一 profile 的追加限定：颜色 rank 直接使用完整不可变元组的精确排序，避免每次细化重复 JSON/SHA；叶子比较仅使用精确属性类编号及完整边多重集，选定唯一等价编码后才序列化完整原始数值。数值缓存键取 numeric_values 实际消费的字段，排除不消费的 ref/evidence_refs。输出仍包含原完整数值和边，不以摘要或颜色图替代最终缓存键。用全部 4 节点无向简单图的穷举同构及重命名反例检验该优化，并保留原预算拒绝。

实测第 14 个原案例为成组对称子图，旧递归在等价分支反复序列化。新增精确 automorphism 剪枝：只在完整数值颜色、已个体化颜色、方向及全部并行边属性相同且节点映射被精确同构确认时略过重复分支。使用已安装 NetworkX 3.4.2（仓库 requirements/ci-cpu.txt 原已有 networkx 声明），不安装。单次规范化的同构可行性检查总预算为 canonical_budget × max(节点数,1)，耗尽仍拒绝；训练不依赖该比较器。新增 8 个相同三节点支路的完整交换用例及属性/边差异反例，检查大型原案例耗时后再继续准备。

剪枝匹配只搜索当前非单例颜色节点；单例颜色节点在任何保持颜色的映射中固定不动，其与待匹配节点之间的每条有向边及数量/置信度完整编码为边界标签。固定节点之间的边在同一图自同构比较中原样相同。该缩减不删除约束，可避免每次为已固定的数百节点重新寻找同一映射；上述穷举及锚点支路反例覆盖这一边界。

真实旧标签可能不足以覆盖现行 18 任务，或来源组过少，结果必须具体列出；训练依赖缺口解决，自动脚本与独立工程验证继续交付。无真实更新就不声称已正式训练。磁盘不足/CUDA 不可用/缓存变化/配置错绑时非零退出，不 CPU 回落。断电恢复到最近完整 checkpoint；未提交批次重新计算，不重跑已完成训练。初始不兼容输出、损坏快照不猜测使用旧权重。回滚仅撤销本批新增文件/精确修改；禁止 reset/clean/stash/提交/推送及清空旧工件。

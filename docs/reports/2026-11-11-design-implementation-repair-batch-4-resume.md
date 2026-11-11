# R3共享分配与关系局部续算

交接状态补充：最终254项通过及独立摘要保存后，创建接续聊天的工具调用被自动审批拒绝，未创建/启动新聊天。审批将创建授权判为历史摘要来源，要求当前用户明确授权；下一实施阶段停在安全交接边界，等待“新开并继续”或用户明确的其他接续路由，不绕过工具拒绝。下方修复与验证结果保持。

2026-11-11，Asia/Hong_Kong。在唯一完整检出`N:\YGO-Kito\_publish_20261030`实施，主进程执行，无子代理或新工作树。本批已替换共享分配器的递归生成器，并将关系层局部枚举接入实际facts→uses→joint续算链路。原F04的129供应池反例已转绿，公开关系入口也能在`allocations=1`且每片JSON恢复时完整保留129个见证。

R3尚未整体完成：`_joint_state_order`的拓扑安排/分配游标及随机身份分支、质量完成组合和失分游标仍待实施。R5/F08独立参考反例本批再次执行仍失败；R5及后续包继续。训练、推理、CB/native、完整构筑、GPU/PC实测、安装和run-007保持暂停。

最终十个明确静态模块按完整ID去重254项全部通过，0失败/错误/跳过，约237.17秒，`torch_loaded=false`；去掉了47次重复导入执行。六程序文件AST/逐行空白/末尾换行零错误。全部本主进程测试session已结束。这是R3共享分配与关系局部续算的验证边界，不是整个R3或R0—R11完成。

## 实际接入

`multifactor.conditions._Search`改为显式DFS帧：walk保存待访问节点序列，select保存all/any/at_least_k组合位置，atom保存物理候选槽及下一组合，not保存自己的子栈及已见未知。预约、动态区域、发动源绑定、去向替代、choices和未决条件随分支保存；没有第二求解器。

`solve_requirements`增加可选`continuation`与`should_stop`。树、库存、coverage和state_provided绑定输入；预算只限制当前片，允许换片大小。返回累计唯一branches和稳定branch_id、当前explored_states、total_explored_states及纯JSON续算栈。版本为`shared-allocation-dfs-v1`；错树、错库存、错coverage或版本恢复抛原合同错误。未知观察和否定不会因为预算退出被置真。

关系更新扩展为`relation-updates-v2`，接受原v1队列迁入；外部任务、候选和既有历史不清空。当前fact在完整求值后才出队，uses和joint各自保存完成索引。活动单元仅保留该单元的局部操作游标和已完成子结果，完成后释放。每个组合的started标记避免子分配挂起后重复收费；工作量回归比较切片累计值与一次完成值。

`_partial_allocations`保存池位置、剩余量、已选供应、当前供应分支和下一数量；`_combine`保存笛卡尔/择一位置和已完成分支。回收消费保存子集/来源选择、数量方案、已完成回收分支和返回身份组合；返回后的区域段仍由同一共享分配器预约实体。去掉128个方案及表达式节点的永久语义截断，不通过提高常数取代续接。

`construction_recognition.allocate_relation_group`同步消费共享游标。需供下游选择的替代集枚举到栈空；终端joint对直接、无条件、无恢复或重叠库存展平风险的供应，使用同一共享分配器取得存在性证明，避免先展开各use的巨大笛卡尔积。重复Need身份或不满足原展平前提时仍走原关系分支。20/40端口宽匹配在定点验证中约0.34/1.37秒完成。

非resumable公共读数仍可展示已证明的正向支持，但保留continuation/update_exhausted和不完整分支；该临时读数不写回已保存的完成事实前缀。resumable生产消费者在当前单元完成前返回pending。14层菱形图回归仍确认有界正向读数；它不等于其全部替代集在一个片内完成，本批没有把该读数作为完整Evaluation缓存。

`construction_layer_flow`补齐allocation=0时两个外层循环的退出条件，避免存在停止回调却空片忙等。规范化提升为`construction-function-normalization-v25`，字典仍b9，评分v4和所有既定公式不变。旧完整Evaluation沿已有规范化版本绑定重评；没有加载旧权重做兼容实测。

## 文件、验证和修复过程

六个长期程序文件为：

- `src/ygo_kito/multifactor/conditions.py`。
- `src/ygo_kito/construction_relations.py`。
- `src/ygo_kito/construction_recognition.py`。
- `src/ygo_kito/construction_layer_flow.py`。
- `tests/test_multifactor_conditions.py`。
- `tests/test_construction_calculation_resume.py`。

这些文件在本批开始时已是untracked，不是本轮新建后可删除的临时文件。混杂工作树保持，没有reset/clean/restore、从HEAD重建、提交/推送/合并或清理旧成果。

新增13个有区分力测试：共享分配器7项覆盖129物理选择、all/any/at_least_k、not未知/反证、动态区域/绑定/替代/返回、输入失配和正常停止；关系入口6项覆盖129完整见证、fact队首、数量帧、回收数量/身份/库存、循环支持及零分配片。极小片测试比较最终uses/joint、累计新工作和更新次数，确认JSON恢复不重复已完成的枚举前缀。

证据在`.cache/design-implementation-repair-20261111-resume`。`verification-relations-initial.log`及`verification-relations-initial-summary.json`是初轮253个去重方法：252通过、1个库存tuple被转list的合同失败，0错误/跳过，Torch未加载。已修复`_restore_relation`，保留已有tuple，并恢复JSON中的槽、表达式及库存位置对。早期局部测试中的表达式list恢复错误也已修复，后续129/队首/数量三个专项全通过。中途一个加载旧中间代码的测试进程在宽匹配组合展开处由本主进程对已确认PID473正常SIGINT结束，未全局杀Python。

`verify_resume.py`只载入十个明确静态模块，按完整测试ID去重并检查Torch未加载；最终文件为`verification-relations.log`及`verification-relations-summary.json`。`open-regressions.log/json`另记录F04通过、F08普通失败，0错误/跳过、Torch未加载，不将开放反例计入通过套件。

`artifact-validation.json`覆盖六个实际程序文件，AST、逐行空白、末尾换行零错误。Git按项目CRLF口径检查无错误；由于六文件原为untracked，逐文件检查是实际内容证据。未运行完整CI、完整构筑、参数更新、权重推理或引擎。

下一实施步骤及完整边界见[本批独立接续](../handoffs/2026-11-11-design-implementation-repair-batch-4-continuation.md)。

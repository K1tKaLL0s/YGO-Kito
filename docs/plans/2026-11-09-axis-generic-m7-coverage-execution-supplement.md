# M7 四项专用用例机械执行补充

日期：2026-11-09，香港时间。用户明确授权补齐 M7 报告中 V11、V12、V16、V21 的专用用例和对照，先交付本补充后直接实施。全部由主进程完成，不启用子代理，保留现有修改、删除和未跟踪成果。当前没有待答问题。

## 目标、依据与现状

本批目标是补足四项已经定位的用例源码缺口，并把交付索引更新为“专用用例源码已补、运行待验证”。不修改生产实现，不运行测试、导入、编译、推理、更新或训练，不启动 M7 运行验收或 T1–T5。

使用现有完整检出 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，定位 HEAD 为 `3f57198e5e366152bbb672be8910e6800f8adbb4`，不据此恢复文件。依据为[主执行书](2026-11-08-axis-generic-execution-plan.md)、[M7 报告](../reports/2026-11-09-axis-generic-m7.md)、代码执行细则及本次明确授权。

本次读取到的真实文本证据：

- `tests/test_multifactor_batch1.py` 的 `AllocationTests` 已有 Side、预算和库存用例，`FunctionalBranchTests` 已有逐分支依赖与结构/状态分离用例；尚无 15 张 Extra 仅供费用和删除扩展后保留基础功能的专用方法。`functional_units.assess_unit` 分别返回成员、资源见证、结构完整性和状态 readiness，允许用现有接口构造这两个对照。
- `tests/test_multifactor_learning_v3.py` 的逐头用例只显式标注 carrier。`Targets` 禁止重复的 task/subject 监督作用域，须把 carrier、enhancer 放在同一 `LabelSet` 的两个独立格中；`graph_training.compile_records/train_supervised` 按格准入和二元损失，现有贡献头有两个坐标。
- `tests/test_multifactor_data_v3.py` 已有同进程反序对照。`prepare_v3.prepare_records` 返回规范记录和分组报告；报告中的行索引随输入顺序改变，比较来源组时须转换成来源 ID 到组的映射，不能直接比较位置索引。尚无跨进程哈希种子及真实 SQL 升/降序查询的专用方法。

以上均来自文件/文本读取，没有执行源码或收集测试。

## 文件范围与确定路线

本批只改以下六份既有文件，并新增本补充：

1. `tests/test_multifactor_batch1.py`：在 `FunctionalBranchTests` 增加 V11、V12 两个专用方法。
2. `tests/test_multifactor_learning_v3.py`：在 `MaskedLearningTests` 增加 V16 一个专用方法，不改现有通用夹具或旧用例。
3. `tests/test_multifactor_data_v3.py`：增加局部 SQL/准备快照辅助函数，以及 V21 的同进程 SQL 和跨进程对照两个方法；只增加必需的标准库导入。
4. `docs/reports/2026-11-09-axis-generic-m7.md`：四行用例索引、后续交付状态与本批实际检查记录，首批成绩保留历史语义。
5. `docs/plans/2026-11-08-axis-generic-execution-plan.md`：只更新四项缺口的当前状态与本批补充链接，原第 2–8 节不改。
6. `docs/plans/MASTER-CHECKLIST.md`：只追加本批源码交付与运行待验证条目，保留旧 M7 记录和并行构筑全部内容。

测试数据均为显式工程夹具。V11 从真实形状的 `DeckSpec` Extra 数量生成独立资源，费用条件要求 15 个 Extra 槽位，产生唯一完整支付见证；成员始终只有基础单卡，不将费用资源计为 15 个配套。比较 15、14、0 和 Side 资源，并比较无 Extra 依赖的基础功能，状态 readiness 保持 unknown。

V12 对基础和扩展功能使用各自的 `FunctionalContract`。扩展功能额外需要成员 C 和独立费用；完整配置时两者完整。移除 C 与扩展费用后，仍请求扩展会缺件；删除扩展功能目标后，基础 A+B 的成员闭包、结构完整性与功能范围继续成立，不受扩展缺件污染。

V16 在同一 subject/function 的单个 `LabelSet` 中标注 carrier=1、enhancer=1，核对回读、逐格准入、两个梯度方向与贡献头一次更新计数。用零初始化的贡献输出层取得可解析的两个独立二元损失；这项未来用例会执行一次微型优化器更新，因此本批绝不执行、收集或导入它，也不把夹具数值当作模型能力。

V21 在内存 SQLite 工程源记录表中实际执行 `ORDER BY record_id ASC` 与 `DESC`，确认读取顺序确实相反，再把读取记录送入同一 `prepare_records`。比较未经测试端重排的完整准备记录、显式 known 掩码、按来源 ID 对齐的来源组/划分以及不含位置索引的报告。夹具包含传递来源、重复/冲突标签、known/unknown/conflict/not_applicable 和三个非空划分，避免空数据或单一划分自证。跨进程方法以两个显式 `PYTHONHASHSEED` × 两个 SQL 方向共四个新解释器进程复用该快照，设置字节码关闭、项目路径及 OMP/MKL 各 2；不读取实际牌库、旧数据或权重，不生成真实准备产物。

## 逐步机械执行与验收

| 步骤 | 文件/符号与前置条件 | 具体动作及预期结果 | 不变量、检查方法与通过标准 | 失败/停止或回退 |
|---|---|---|---|---|
| S1 交付与局部保存 | 本补充；六份既有目标均已读最新，本补充原不存在 | 先交付补充，再把六份目标当前字节保存在新的 `.cache/axis-generic-m7-coverage-20261109-01/before`，登记小型清单 | 只保存本批拟改文件，副本逐字节相同；不重建 M0–M7 全树基线、不计算哈希、不读取权重 | 保存目录被占用或字节不一致则停止相关修改；不清理或覆盖旧目录 |
| S2 V11/V12 | `FunctionalBranchTests`；现有 `DeckSpec/Resource/FunctionalContract/assess_unit` 接口已按文本读取 | 新增两个专用方法及上述正/反对照，保留已有方法 | 文本可定位 15/14/0/Side、支付见证、单卡成员、基础/扩展分离及缺件断言；未来运行应分别达到其语义标准，当前只交付源码 | 如发现需要修改生产实现，停在用例和明确未决记录，不擅改生产源码或放宽断言 |
| S3 V16 | `MaskedLearningTests`；单个 task/subject 只允许一个 `LabelSet` | 同一作用域放两个正格，补各格来源及权重，断言两个坐标均准入、梯度均推向正例且按头计数一次 | 不改旧夹具、旧测试或生产网络；当前不实例化模型、不前向、不更新；未来只运行专用方法时核验具体梯度和计数 | 不为适配测试改能力状态、头结构或生产损失；发现不相容写为待验证 |
| S4 V21 | 数据测试辅助函数、两个新方法；现有准备入口和分组文本已读 | 内存 SQLite 升/降序真实查询，建立可逐项比较快照；增加两种哈希种子的四格子进程对照 | 显式断言输入顺序变化、非空三划分/标签状态和传递来源，输出完整记录/掩码/来源组/划分相等；不删除输出字段或重排记录来隐藏差异 | 子进程设计限 `sys.executable -B -c`、当前仓库、固定脚本、固定种子/方向和超时；未来非零退出/超时直接失败，不重试降级或自动安装 |
| S5 文档同步 | M7 报告四行、主计划当前状态、MASTER 末尾；源码补充已完成 | 记录五个新增方法、四项源码缺口已补以及运行仍未验证；登记本批允许的文本检查 | 历史检查/首批“未修改测试”保留其批次语义；不勾选 V/A 运行验收，不启动 T 阶段；并行内容完整保留 | 写前回读共享文档，出现并行变动则只增量合并；不以保存副本整文件覆盖 |
| S6 限定文本检查与交付 | 七份目标；本批修改结束 | 用 PowerShell/`rg` 回读本批新增行、方法名、引用及与保存副本的增量；仅对本批 tracked 路径执行命令级 `git diff --check`，未跟踪文件单独查新增行尾 | 五个方法和补充链接可定位，六份旧内容保留，无新增行尾空白；小型 JSON 回执登记实际文本结果和运行数 0 | 文本问题只修本批增量；不通过 Python/AST/编译/业务用例检查语法，不扩大至全项目；回退只逆向撤销本批自有增量 |

## 当前禁止范围与后续运行方法

生产源码、JSON 配置/协议、真实标签/数据、旧 runs、权重、活动/暂停/课程指针、LoRA、构筑定价/学习政策/调度、数据库、原生接口与用户目标均不改。不 checkout/reset/clean/stash、不恢复既有删除、不建 worktree，不提交、推送、合并、发布或安装依赖。

本批不运行任何测试（包括收集和纯静态业务用例）、Python/项目/Torch 导入、AST/编译、构建、模型前向/推理、优化器微测、训练、实际资料准备、checkpoint 加载、CB、原生引擎或 CI。Git 空白检查只使用命令级 `core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol`，不改配置。源码只用文本工具检查；语法、断言、数值和子进程可用性均待运行验证。

未来获得对应运行授权后，用既有解释器 `E:\Ana\envs\pcacgate\python.exe` 和明确的五个方法逐项运行，不使用 discovery：`FunctionalBranchTests.test_v11_fifteen_extra_cards_are_cost_resources_not_members`、`FunctionalBranchTests.test_v12_removing_extension_keeps_base_function_complete`、`MaskedLearningTests.test_v16_carrier_and_enhancer_are_independent_positive_cells`、`LabelPreparationTests.test_v21_reverse_sql_preserves_records_masks_groups_and_splits`、`LabelPreparationTests.test_v21_hash_seeds_and_reverse_sql_preserve_preparation`。前两者归原 Q2，V16 会前向/更新而归 Q5，后两者涉及工程准备和子进程而归 Q3；本补充不解除相应禁令。

风险和未验证假设：用例尚无语法或运行证据；V16 的解析梯度期望依赖当前独立 BCE 路径，V21 的子进程依赖届时同一解释器/环境可用。SQLite 工程表只验证源记录读取顺序，不等于真实 catalog/deck_cache 迁移已验证。发生具体失败时保留原断言和失败事实，在对应授权内处理；不得把未运行、工程夹具或哈希种子矩阵写成已通过能力验收。

## 本批实施记录

S1–S5 已按上述路线实施：六份目标修改前已逐字节保存；三份既有测试文件共增加五个方法、一个局部快照辅助函数及三个标准库导入；M7 四行索引、主计划当前状态及 MASTER 追加条目已同步。三份旧测试剔除本批新增块后与保存原文完全相同。限定文本检查及命令级 Git 空白检查的最终实际结果登记在 `.cache/axis-generic-m7-coverage-20261109-01/text-review.json`。本批未修改生产源码，运行验收全部待验证，T1–T5 未开始。

# 构筑职责与基础 CB 实施书

> 执行与历史记录。现行行为以 [现行设计](../../current/README.md) 为准；本文的日期状态和当时授权不自动适用于新任务。

本轮接续用户授权，由主进程实施，无子代理。目标是目标模型第一层骨架、优化模型第二层及泛用持续迭代，以及基础 CB 的线性主干边界。训练、CB 提议／推理、native、对局、参数更新仍暂停；不改课程 hold、权重、资源或模型特征布局，不提交／推送。已有未提交修改和删除保留。

当前证据：`construction_fill.construction_cycle` 固定四角色序列，目标角色调用完整牌表求解器；`CourseAdmissionPolicy` 仅按已知库存缺口判断 admitted；`route_search.discover_goal` 在固定 seed 的具体随机命中后继续枚举动作。现有两层评价、效果词典及严格偏好接口继续复用。

| 步骤 | 目标与符号 | 前置及具体动作 | 预期与验收 | 失败处理 |
|---|---|---|---|---|
| 1 | construction_fill、construction_binding、build_pipeline、build_semantics | 读取当前 graph／task；增加部分牌表校验及骨架候选，目标模型评分；优化模型补全实际 Main/Extra/Side | 骨架留泛用位，固定卡／轴意图保留；定点测试检查角色输入输出与张数 | 候选违约即拒绝，不放宽任务 |
| 2 | construction_cycle、ConstructionSession | 删除固定四次终点；保存候选、轮次、反馈、游标；轮数／时间片耗尽挂起，恢复继续优化 | JSON 保存恢复测试；目标角色只执行第一层；未达标无 CB 调用 | 绑定不一致报错，保留原状态 |
| 3 | 构筑通关契约、CourseAdmissionPolicy | 同时检查原任务、缺口、必需用途未知与显式质量指标；缺少质量政策时保持未通关 | 判据版本／阈值／结果绑定候选；无 CB 循环依赖；不引入 70/56 | 缺判据或关键事实返回 pending，不伪造分数 |
| 4 | session 反馈、construction_learning | 来源／候选／问题绑定，进入优化输入；记录消费及处理结果；严格偏好保留真实归属 | 过期反馈、无外接 AI、平局与版本测试；参数更新与牌表迭代分开 | 无证据不生成监督标签 |
| 5 | basic_cb_inference、route_search | 复用 costs／operations／原因，过滤依赖随机命中的动作；独立固定动作继续 | 纯契约测试：堆墓允许、命中诱发禁用、cost/effect 独立、后续固定动作保留 | 不支持语义保留 unknown，不用固定 seed 认证 |
| 6 | controller、autonomous、scenario_course、local_course_collaboration | 真实入口接入挂起／恢复／通关；清理旧四阶段运行状态及测试引用 | 调用链、保存恢复、无提前 CB；rg 检查弃用引用 | 不恢复旧入口，不创建旁路 |
| 7 | 定点测试、当前设计、MASTER-CHECKLIST、报告 | Windows Python 3.12（PYTHONUTF8=1，PYTHONDONTWRITEBYTECODE=1，PYTHONPATH=src），临时目录 N:/YGO-Kito/_local_cpu_20261027/tmp；Torch 仅使用既有 WSL venv | 筛选的 unittest、AST、git diff --check；记录实际数量和未验项 | 不运行 discovery、optimizer.step 整类测试、native_response_buffer 或正式课程 |

完整评价尚未将用户已给参考构筑及评分判断落实为现行质量政策；缺的是实现与标定，不是等待用户重新提供依据。CB 归属不改变：目标模型排序、程序搜索、引擎验证；本轮只实现控制与契约，不执行该链。

## 通用性与参考尺度纠正补充

本次仍由主进程实施，无子代理。当前 `LinearMainline` 没有 3／5 或卡名白名单，已有 7 项纯契约测试；完整质量政策运行时未配置。用户已指出定义不能限于举例，并已提供参考构筑和评分依据，本次撤销“等待用户提供指标及阈值”的状态。

| 步骤 | 目标与前置 | 具体动作 | 逐项验收与失败处理 |
|---|---|---|---|
| 1 | 当前分工设计、准入说明、统一说明、总清单、实施报告和机器摘要；已找回用户原话 | 用动作及其前提是否依赖不确定结果统一基础 CB 定义；恢复参考完整评价至少约 70 分及历史参考／候选 60／40 判断的原适用范围 | 不设卡名、动作种类或数量白名单；诱发、融合等不能一概排除；旧公式删除不抹去用户评价依据；完整政策未实现的事实不改写为已完成 |
| 2 | `tests/test_basic_cb_scope.py`；现有公开 DTO 和合成效果记录 | 增加随机动作种类、数量、卡片身份、cost／effect 变化检查；检查确定送墓产生的诱发和融合处理不因先前随机动作而被一概排除 | 随机结果不供给具体资源，独立已知动作继续，记录保留语义；若失败只修复 `basic_cb_scope.py` 对应边界，不放宽断言；未失败不改变生产控制逻辑 |
| 3 | 上述定点测试与修改文档 | Windows Python 3.12，`PYTHONUTF8=1`、`PYTHONDONTWRITEBYTECODE=1`、`PYTHONPATH=src`，临时目录沿用 N 盘；仅运行 `tests.test_basic_cb_scope`、触及 Python 的 AST 和 `git diff --check` | 保存实际测试数量、失败和跳过数；文档与摘要无待答问题；不执行 CB 提议／推理／重放、native、训练或参数更新，不恢复旧评分模块，不写新数值政策 |

# Adapter 两项 P2 修复

本地独立分支 `codex/multifactor-roles-20261028`，增量基于 `6e0c3d41376b64323e4190672ad45e32c257aca4`。只修改本模块的 adapter/训练状态、专属测试入口及说明；不触碰主训练/集成窗口，不发布，不重开泛化预检，不改变文件权限。

独立复核证据已读取：`N:\YGO-Kito\_migrated\CodexData\2026-10-28\task-19\readonly-v2-probes.json`、`review_multifactor_v2_probes.py`、`readonly-v2-tests.log`。其 33 项非训练检查与零增量/空 Adam 恢复是工程证据，不包含真实监督基模或非空 Adam 下一更新验证；本轮未修改或重跑该目录的探针。

## P2：加载失败会残留状态

原路径先创建 bank、冻结基模、安装 hooks、激活新版本，再恢复权重/Adam；异常后 fresh 模型和已有活动版本都可能改变。

现先在 detached `AdapterEntry` 中校验并恢复全部权重、Adam 及元数据。校验包含权重键/shape/dtype/有限值、Adam 分组/设置/参数对应、非空状态与步数一致性、step 与动量 tensor 的 shape/dtype/有限值。PyTorch `Adam.load_state_dict()` 不完整检查动量 shape，因此不能只以它返回成功为依据。

完整恢复后才注册 entry 并切换；fresh bank 安装 hooks 自身失败时撤销本次 handles、逐位恢复原 requires_grad 标志。错误权重、错误 Adam、部分/完整恢复后注入异常均不改变原模型/bank/活动版本、已有优化器、hooks、梯度标志、RNG 或推理结果。正常加载继续恢复原 Adam、游标和数据摘要，没有重置动量。

## P2：活动 adapter 借用基模训练状态

正常模式的训练与工件加载均拒绝 `engineering_fixture` / `definition_development` 更新；工程模式保留原有隔离。活动版本不再回退到基模 head_status：没有对应真实监督更新的头/角色维保持 untrained，公开概率/评分 null；任何开发/工程混入的活动版本全局只作 engineering_only 诊断，避免共享 readout 让其他头获得错误背书。

停用 adapter 或未启用 adapter 时，继续使用基模原有逐头状态，不因 bank 存在而强制有效基模拒判。`adaptation` 列出 inference_source、base_head_status 与 active_head_status。监督/更新记录仍不等于模型学会概念或质量通过。

## 实测与边界

先运行新增针对性文件，首批 16 项通过；加入正常工件携开发来源的拒绝反例后，运行明确白名单的 `scripts/check_multifactor_roles.py --output .cache/multifactor-p2-final`。实际 CPython 3.12.1、PyTorch 2.9.1+cpu、Windows 11、CPU 单线程，退出 0，**72 项工程/隔离检查通过，0 失败、0 错误、0 跳过**。

原 55 项工程检查保留，新增 17 项：fresh/existing × 权重/Adam × 无效内容/恢复后异常的 8 种组合；hooks 安装失败回滚；丢失非空 Adam/错误设置；实际非空 Adam 恢复及下一工程更新；携开发来源的正常工件拒绝；活动未训、停用基模、正常来源拒绝、混合来源诊断及逐头状态组合。

非空 Adam 成功路径使用少量实际工程优化产生动量，确认动量非空且非零，恢复后再执行同一更新，损失、权重、Adam、数据摘要逐项一致；不是伪造空状态或只比较零增量。有效基模/真实来源计数的输出组合使用明确标记的模拟状态夹具，没有假装使用真实训练/校准过的基模。

受测模块源摘要：`d028504a10755b3853954d2acbdc5542f2ae40ded9ed8860d4de8e3a57fa61ea`。逐文件 SHA256、实际版本、分组结果在 `.cache/multifactor-p2-final/results.json`，完整日志为同目录 `tests.log`；提交交付另核受测字节与提交树相同。tested_head 保留实际运行时的 base 加未提交增量事实，不冒称原 base 已含修复。

本轮无正式训练、真实监督基模、泛化/校准成绩、原生测试、远端 CI 或发布。历史 `6e0c3d4` checkpoint 继续由旧源码复现，没有为此次修复关闭源码绑定或隐式迁移。真实标签、概念学习、LoRA 收益与独立能力验收仍待原计划后续工作；本模块继续不阻塞主训练。

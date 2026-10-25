# 构筑逻辑：可训练与实际调用增量

基于首次框架提交 `5d4336bbfe453d5eb97db654487e6f23a4841777`，分支 `codex/construction-logic-entry`。本次按用户继续授权补齐可训练实现和具体适配，不把缺具体实现写成只缺权重。旧原生故障/绑定、故障注入、导出、预算修复及 DP 任务没有接管。

## 已完成

- [x] **CL11-A 实际可训练分类器。** 标准库线性 softmax，字符 ngram/英文词＋词典作用域辅助特征；实际梯度拟合、预测、分数/margin/OOV拒判、JSON保存加载和配置/词典/权重绑定。分类结果取学习分数，旧规则置信不进入最终分数。反标签拟合测试证实规则不直接决定类别。新会话/CLI缺模型时未训练拒判，不自动用固定规则代替。
- [x] **CL11-B 现有模型的具体图适配。** `LogicCodec`无卡ID图编码/解码；程序按开放基本标签生成有限粗图，现有目标/优化同一组 `BuildRanker` 真实评分选择。`LogicModelAdapter.from_builder`直接复用 `BuildTrainer` 的模型、编码器配置和优化器，不新增网络。已有numeric/kind/position层编码图标签/边/入口/目标/反馈，卡ID槽为0，不错用旧卡嵌入。图偏好训练实际更新两角色参数；新checkpoint保存模型/Adam状态及特征/任务/词表绑定，恢复连续更新一致。
- [x] **CL11-C 实际图到卡绑定及统筹连接。** `CatalogBindingAdapter`从具体牌表读取目录事实/完整卡文；种族/字段用公开属性，功能词仅召回；显式当前来源审核或真实静态事实支持节点，否则unknown/拒绝。实际选择分支并集，结构上覆盖所有明确required tags。`ConstructionController`调用实际图适配/绑定/旧填卡评分、已有 `CoordinatorTrainer` 网络；已核验候选通过旧 `Coordinator.handoff.submit` 与 `route_with_model` 写入SQLite、取得规则权威路由和实际网络建议。
- [x] 目标/图词表钉住、父版本与反馈修订；狭义才第二阶段，广义跳过第二阶段但保留第一阶段，歧义/未知仍阻止填卡。当前主题/required tags不允许静默变更。卡文不支持、源不符或未审继续拒绝/反馈，不用关键词命中证明合法CB。
- [x] CLI：`construction-intent-fit`、模型化 `construction-plan/fill-check`、实际 `construction-run`。完整 CLI 集成测试没有图或绑定 provider 夹具；仅卡数据使用明示合成目录，目标使用实际旧计数接口，不执行native。

规则与模型的分工：**程序枚举粗图候选和候选卡表，模型评分选择；可训练图偏好评分已实现，不是自由自回归生成完整图。** 自动卡绑定是目录检索/约束程序，功能语义依赖显式审核数据，未提供通用卡文解释器。标签覆盖、审核支持、具体任务合法性和图边真实执行分开报告，`graph_execution_verified`保持false。

## 验证

独立审查复验63项相关CPU测试通过，并推动修复入口节点未编码、优化器错绑、加载失败后部分覆盖、运行期codec改变要求和路径跳过必需标签。最后增加的实际CLI整链接口测试另通过。最终完整回归与实测损失见下方完成记录。

合成分类训练18句，不是生产/独立语言测试集；图偏好训练使用合成卡库和明确合成偏好，只验证参数更新、损失、恢复及接口。卡绑定审核是明示合成来源记录，不当真实卡效知识。计数目标、两种构筑评分、图选择和统筹账本为真实旧实现调用；原生路线未执行。

复现：

```bash
cd /workspace/YGO-Kito-construction
PYTHONPATH=src OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  /workspace/YGO-Kito/.venv/bin/python -m unittest \
  tests.test_intent_model tests.test_construction_model tests.test_construction_binding \
  tests.test_construction_logic tests.test_construction_cli tests.test_build_intent \
  tests.test_build_contracts tests.test_build_semantics tests.test_catalog_discovery \
  tests.test_combined_goals tests.test_cli -v
```

## 剩余与具体依赖

- [ ] 正式标签数据、独立语言集、置信校准、正式图偏好/决斗反馈训练和竞技能力。**这里现在是缺可靠数据/正式训练与验证，不再缺上述训练/预测实现。** 小合成成绩不外推。
- [ ] 完整真实资源下的新增流程原生路线/真实卡组/决斗反馈端到端。本环境当前未找到 `cards.cdb`，未下载或构建引擎；运行 `BuildAssets`需要原项目锁定的完整core/scripts/cards/banlist资源组合。不得以修复原生问题补此依赖。
- [ ] schema4从空牌表求解还依赖旧模块的可选 `scipy==1.16.3`，当前venv未安装；未安装新依赖。已有合法 `--base` 可复用旧有界编辑路径，测试已实际使用，不伪装从零求解。通常目标原生成路径保持兼容。
- [ ] 当前功能标签绑定依赖来源绑定审核表，未知效果不自动判真；任意粗连接的合法CB执行、生产自然语言泛化、PC/战力及全卡池仍未验。此处不新增完整卡效形式化任务。
- [ ] 既有统筹正式权重、预测校准及完整实战闭环未验。无已核验候选时只做预构筑上下文的实际网络建议；有合格候选且配置真实账本才走旧托付/路由。未执行自动决斗或正式预测登记。

没有付费训练/外部API、凭据权限变更、native绑定修改、故障注入、推送或合并。当前额度仍无法从执行环境读取，不能把父代理17:07:12UTC的78%当作当前值；父代理负责20%停线核查。

## 最终完成记录

最终回归 **104/104通过，无失败/错误/跳过**，墙钟测试18.389秒，始于2026-10-24 17:43:39 UTC；[逐项日志](2026-10-24-construction-trainable-tests.log)、[实际训练证据](2026-10-24-construction-training-evidence.json)。分组：入口模型8、图模型/统筹9、绑定10、原构筑逻辑20、新CLI6、词典/作用域11、旧构筑/语义/召回/组合18、旧CLI22。

18句/301特征/180步合成分类拟合，损失1.098612→0.038450。图偏好两角色各4步示例，目标损失1.951073→1.933323、优化1.947078→1.933899；参数摘要实际变化，保存后恢复的分数及下一次参数更新一致。其余测试也会执行独立小拟合及恢复对照，这些数值仅对应所记录样例，不作总训练量或能力成绩。

整组验证后仅调整训练状态说明输出，相关 `tests.test_construction_model tests.test_construction_cli` **15/15复验通过，1.997秒**；没有新增训练能力主张。

云端增量提交号以交付时 `git log -1` 为准。不推送、不合并。

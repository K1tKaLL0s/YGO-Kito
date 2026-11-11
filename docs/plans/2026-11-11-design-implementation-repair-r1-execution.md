# R1剩余语义执行书补充

2026-11-11。用户明确恢复修复。继承R0—R11方案、原执行书和不变量；本补充由主进程实施，gpt-6.1-sol/max，无子代理。源码仅在N:\YGO-Kito\_publish_20261030，沿用混杂工作树，不提交、推送、合并、安装或恢复旧运行。

目标是让已存在的五类完整中文卡文经过effect_records、字典、库存、关系和默认统一评价得到正确处理身份及静态配套。当前证据是首批r1-card-projections.json及真实源码：旧式次数/触发未知，衍生物被当作场上库存，不同卡名未绑定支付，翻开选择误投影为除外/指定检索，去向替代未消费。评分公式、权重和0.8比例不变。不运行训练、权重推理、CB/native、完整构筑、run-007或Pro辅助验证代码。

允许修改effect_count_limits.py、effect_records.py、effect_blocks.py、construction_inventory.py、construction_relations.py、construction_layer_flow.py及其现有专项测试；必须同步生产消费者。其余既有改动、权重、原卡库/参考/大型运行档禁止写入。语义变化提升字典修订和规范化版本；旧计算按原版本检查失效，原结果不覆盖。

| 步骤 | 文件与符号、前置、具体动作和不变量 | 检查、通过与失败停止条件 |
| --- | --- | --- |
| 1 | effect_count_limits:parse_count_limits、effect_blocks:activation_parts、effect_records:_refine_record；已有原文。识别效果开头“1回合1次”为该实体该效果次数，从条件中只移除已识别次数原句；补攻击宣言/破坏效果响应/按本效果除外后的结束阶段触发，保留引用的效果编号、banished来源和时点；将无效后的破坏对象绑定响应卡，不能虚构自己场上对象。 | text_completion和static_entries的正反例；独立效果次数不串用，不识别的时间限定仍未知，延迟回场不能投影为无条件立即召唤。失败只停止相关语义，不改评分。 |
| 2 | effect_records条件/操作、effect_blocks.block_view、inventory.specs；识别空场/空墓为发动前状态条件，静态不将“没有”解释为牌表不允许投入；衍生物从明示规格生成，不消耗牌表实体；可选放置保留独立条件、卡名、deck来源和field去向；默认消费者必须检查被放置实体库存。 | text_completion/static_entries：存在与缺失可选搭档、同形匿名卡、空墓先检查后支付；生成衍生物不要求把Token放进Main。不能清除未被完整匹配的条件。 |
| 3 | effect_records:_cost_records/_refine_record/_scope_choices；inventory:processing_check；识别“其他的”为不能支付发动的同一实体，保留同名另一副本；对“和支付怪兽卡名不同”绑定对应cost_index。用现有整数分配按有限支付名字分支检查完整处理，不增求解器；不同实体/不同名字和同名副本区分。 | text_completion/static_entries/inventory：无支付、只有同一副本、额外同名副本、同名支付与目标、不同名合法目标及两个option分别验收。无法匹配完整引用时保持局部未知。 |
| 4 | effect_records支付分支与完整翻开选择；effect_blocks扫描、relations:_record_outputs、layer_flow:_function_semantics；支付数量绑定翻开总数，选1后余数回底并保留顺序。翻开、选取、返回是同一处理；只计实际加入手牌功能，不产生多次除外/回卡组收益，不把随机翻开中的选卡变成指定卡调用。伤害减半只计伤害修正，不计造成伤害。 | text_completion/static_entries：3/6成本分别翻3/6、加1、回2/5；同一功能家族，缺Extra支付失败；随机不能支持指定检索对象；金满壶现有分支不回退。 |
| 5 | effect_blocks/effect_records、relations:_restriction_contract、layer_flow:_restriction_match/_bind_mandatory_impacts；把全局送墓改除外记录为有持续时间的去向替代，既不投影立即送墓/除外实体，也不删除其功能；复用现有用途限制/可满足顺序消费。支付严格要求送墓时受替代影响，解放/破坏本身仍能执行；同一效果先支付不被自身后续处理禁止。 | static_entries/runtime_processing：空墓加自身手卡送墓成本；独立可选用途可安排在替代前，必需联合且强制替代后送墓不能仍记原送墓收益；无关解放/破坏不误禁。失败时不以现状未知替代已确定语义。 |

统一检查前缀P：既有WSL Chaos-Ubuntu-26.04，目录/mnt/n/YGO-Kito/_publish_20261030，PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. OMP_NUM_THREADS=2 MKL_NUM_THREADS=2，解释器/mnt/n/YGO-Kito/_local_cpu_20261027/venv-linux/bin/python -B。每步执行明确方法名，局部完成后执行text_completion、static_entries、inventory、functional_flow、effect_block_dictionary、runtime_processing等受影响纯静态模块；不跑未筛选discovery或完整CI。新证据写.cache/design-implementation-repair-20261111-r1，不覆盖首批或原运行档。AST与diff空白检查覆盖实际新增差异；不重复无变化的344组。

官方依据为KONAMI卡片库：cid9117（四个独立效果及除外后回场）、cid16748（无Token条件及可选放置）、cid15973（支付与不同卡名选择）、cid15756（3/6支付与翻开选择回底）、cid14740（空墓发动条件与截至下一回合结束的全局替代）。使用对应card_search.action?ope=2和faq_search.action?ope=4，request_locale=ja；不以当前禁限覆盖历史任务。尚未验收的共享名字分支/全局替代消费者是本次实施事项，不向用户索要盘面或同义卡文。

失败只修当前动作的本次差异，禁止reset/clean/restore或覆盖既有成果；测试意外触发训练/引擎即停止该检查。每个完整动作验收后记录结果再进入下一步。用户再次暂停则安全结束当前原子步骤；必要新聊天沿已有授权、同模型单主进程并携完整独立摘要。

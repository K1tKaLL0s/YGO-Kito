# 轴／泛用识别：新材料实际表现检测

2026-11-10。第18轮开发最优权重＋原校准，CPU推理；没有更新、激活或重启模型，也没有干扰并行构筑任务。

## 结论

当前模型尚未学会用户需要的稳健功能、联动与构筑角色区分。换成新功能单元后，出现机制乱加、冲突一律当兼容、自然组合候选漏掉、核心/支援不随目标切换等系统性错误。历史18头平均F1 87.68%没有反映这些新材料中的缺口。

## 材料与实际运行

- 46例：43个配置/关系查询，3个真实双配置比较。9份本地回放牌表，主卡组40、41、42、43、60张；5例无额外卡组。
- 34种不同“成员＋所问功能”，与1819条训练来源中的同类签名交集为0；9份基础牌表也均不等于原63份。这里检验新查询，不把所有卡片或系列都称为训练未见。
- 包括泡影、遮蒙者、锁鸟、月书、旋风/双龙卷、墓指、一滴、威吓、陨石、瞬移、粗人预料、简融/简素、三眼怪连接、歌后、救援猫、补缀、勇者、黄金国、闪刀、左右起子、壶、吸引者、旅鸟完整机制与关系冲突。不是重复14个训练单元，也没有再围绕伽马展开。
- 卡文、功能问题、目标与标签先固定，再加载模型。观察图没有手工功能种子或答案注入；标签依据完整卡文和明确功能场景审阅。
- 权重为base-full18-20261110-001/checkpoint-e0018-b0000000-s000000378-f0.pt，model_id为3c4a97a6fdd9a8d04c37a70dd7a8f3b791e4f3e11f7e8ee177ffb19d650ab71b。
- 使用原准备绑定的图/卡效源码快照和原校准。CPU、2线程，46例编码与判别合计29.10秒，没有使用GPU训练资源。
- 原公开train_v3.predict_saved入口另行核对3例、36格，最大概率差1.79×10^-7，判定一致。

## 关键实测

1. **机制基本退化为“有效果就什么都有”。** 144格判对91格；效果卡48个明确功能负例仅判对1格。泡影被额外判断成破坏、抽卡、检索、特召；遮蒙者被判断有破坏和抽卡；旋风/双龙卷被判断有无效和抽卡。正例召回高，不能抵消不存在能力的附会。
2. **兼容头32次全部输出compatible。** 24个兼容例正确，8个冲突全漏：无额外的金满壶/谦虚壶、无融合目标的简融、无低星念动力目标的瞬移、零通召预算的三眼怪/歌后入口、无勇者衍生物来源的单狮鹫，以及吸引者与墓地型珠泪接收构筑。表面75%来自本组24:8的标签比例。
3. **新泛用5/16、迁移性19/35。** 13个完整泛用正例只认出3个；泡影、遮蒙者、墓指等部分open被判closed，勇者等conditional被判open。金满壶和吸引者能保持conditional，但接收冲突没跟上。
4. **指定自然组合仅4/18个配置命中。** 对13种不同组合，命中3种：粗人预料＋岩石巨兵、歌后＋海皇重装兵、左右起子。三眼怪＋独角兔、简融/简素目标、勇者、救援猫、黄金国、闪刀及旅鸟完整组合没有相同成员/所问功能候选，135格轴相关判断因此无输出。该计数衡量指定组合提议，不是整副牌所有轴的完备召回。
5. **目标切换没有带动核心/支援。** 同一三眼怪连接单元、同一勇者单元从support换为明确main目标，仍输出“非核心＋支援”。完整旅鸟机制的两个较大轴正例都判否；较大轴11/13的表面成绩只是11个负例正确。
6. **双配置比较偏右。** 40张牌中，旋风由1张增加、反向减少、保持数量三例，应为right/left/equal，实际全答right，只对1/3。
7. **清晰正确处。** 粗人预料/歌后/左右起子能形成新自然组合；月书、双龙卷部分open判断正确；旋风/双龙卷在单一后场破坏用途的替代关系、红药与旅鸟特召限制冲突等关系判断正确。

## 具体原因

**训练缺少效果卡的功能负例。** 实际读取冻结准备数据的train分片：mechanism在卡节点上的8498个效果卡/其他卡标签全部为正，48816个负标签全部来自通常怪兽；不同效果卡的“不抽卡、不检索、不破坏、不取对象”等对照没有进入该头。只有118种效果卡/坐标正例，以及两种通常怪兽的54种坐标负例。这个分布与本次效果卡47/48负例被判有功能的表现吻合。

**卡文到图确有信息丢失，不能只归因于权重。**

- 金满壶额外卡组除外代价被解析为payment，from_zones为deck/banished，“额外”资源要求没有正确表达。谦虚壶同样没有正确保留来源。
- 简融的fusion_summon操作保留extra，但通用special_summon操作却写deck，也没有形成具体融合目标组合。
- 瞬移特召reason为unknown；三眼怪检索reason也为unknown，来源还混入hand。图构造排除reason非effect的操作，关键能力/关系没有自然展开。
- 勇者之仪放置旅路与相关限制未完整保留；吸引者“送墓改除外”在operations中为空。
- 新增接收兼容标签主要按通召预算产生正负，缺少额外、目标、墓地替代/限制等同功能对照。

这些卡的完整卡文已经在本地，不是用户少给盘面或手牌。解析发现基于原训练绑定版本，原文和实际解析保存在card-evidence.json、failure-effect-facts.json。

## 直接改进顺序

1. 在现有流程补齐已证实的资源来源、对象/素材匹配、限制与替代规则，使自然候选能连接这些新组合；不另建架构。
2. 效果卡补同卡多功能的明确正负对照：“无效≠破坏、检索≠抽卡、费用≠效果、取对象≠选择”。通常怪兽不能承担全部反例。
3. 同一功能配有/无额外、有/无合法目标、有/无通召余量、墓地与除外适配的构筑对照；完整组合、缺件、可替代成员分开。泛用标签仍属于相关完整单元，不能传给每个成员。
4. 继续用原网络规模，以上材料作为已消费回归组，再取新卡文/功能检测。重复14类模板或只增训练轮数补不上这些区分。本轮只检测，没有执行修复或重训。

## 分项与逐例计数

下表可判格不包括候选漏项；漏项另外保留在端到端分母。raw、calibrated、applied及混淆矩阵见metrics.json。18个训练头直接覆盖17个，旧legacy:pairs未另计分。

| 项目 | 输出判对/可判格 | 候选漏项 |
|---|---:|---:|
| mechanism | 91/144 | 0 |
| transferability | 19/35 | 0 |
| receiver_compatibility | 24/32 | 0 |
| legacy:compatibility | 24/32 | 0 |
| function_role | 50/80 | 0 |
| legacy:generic_utility | 5/16 | 0 |
| axis_function | 12/17 | 70 |
| axis_position | 4/4 | 14 |
| axis_origin | 2/3 | 11 |
| axis_membership | 5/8 | 40 |
| contribution | 15/15 | 0 |
| legacy:small_axis | 11/13 | 0 |
| legacy:large_axis | 11/13 | 0 |
| legacy:strategic_core | 3/6 | 0 |
| legacy:support_role | 3/6 | 0 |
| pair_relation | 9/12 | 0 |
| copy_preference | 1/3 | 0 |

574个预先标定判断：289个正确、150个错误、135个因候选缺失无输出，本组端到端289/574。46例中3例全部判断正确。这些题刻意覆盖新功能、缺件与约束变化，不能用50.35%推算真实卡池/实战总体比例。贡献15/15都是carrier正例，没有证明完整贡献区分。

| 案例 | 主/额外张数 | 判对/标定数 | 候选漏项 |
|---|---:|---:|---:|
| probe-001:imperm_storm40 | 40/15 | 6/13 | 0 |
| probe-002:imperm_tear60 | 60/15 | 6/9 | 0 |
| probe-003:veiler_sky42 | 42/15 | 7/11 | 0 |
| probe-004:droll_floo43 | 43/15 | 3/7 | 0 |
| probe-005:book_moon_monarch_noextra | 60/0 | 6/11 | 0 |
| probe-006:mst_eldlich60 | 60/14 | 7/10 | 0 |
| probe-007:twin_twisters_mixed41 | 41/15 | 6/9 | 0 |
| probe-008:called_by_sky42 | 42/15 | 7/10 | 0 |
| probe-009:compulsory_noextra | 60/0 | 4/10 | 0 |
| probe-010:droplet_tear60 | 60/15 | 4/10 | 0 |
| probe-011:threatening_roar_floo40 | 40/15 | 4/9 | 0 |
| probe-012:nibiru_mixed60 | 60/15 | 2/8 | 0 |
| probe-013:teleport_wheeleder_sky42 | 42/15 | 8/20 | 9 |
| probe-014:unexpected_dai_normal_storm40 | 40/15 | 36/46 | 0 |
| probe-015:instant_fusion_thousand_eyes | 41/15 | 11/24 | 11 |
| probe-016:ready_fusion_theseus | 60/15 | 11/23 | 10 |
| probe-017:sangan_almiraj_support | 41/15 | 12/24 | 10 |
| probe-018:diva_heavy_infantry | 41/15 | 18/22 | 0 |
| probe-019:rescue_cat_two_beasts | 60/15 | 9/21 | 10 |
| probe-020:patchwork_search_package | 60/15 | 8/20 | 9 |
| probe-021:adventure_negate_support | 41/15 | 11/27 | 14 |
| probe-022:eldlich_sanguine_recruit | 60/14 | 16/30 | 13 |
| probe-023:engage_widow_search | 42/15 | 8/21 | 12 |
| probe-024:righty_lefty_materials | 41/15 | 17/24 | 0 |
| probe-025:extravagance_storm40 | 40/15 | 8/9 | 0 |
| probe-026:prosperity_storm40 | 40/15 | 4/8 | 0 |
| probe-027:extravagance_monarch60_noextra | 60/0 | 6/9 | 0 |
| probe-028:prosperity_monarch60_noextra | 60/0 | 3/8 | 0 |
| probe-029:shifter_tear60 | 60/15 | 3/9 | 0 |
| probe-030:shifter_floo40 | 40/15 | 5/9 | 0 |
| probe-031:sangan_almiraj_no_normal | 41/15 | 1/6 | 3 |
| probe-032:diva_no_normal | 41/15 | 3/6 | 0 |
| probe-033:instant_fusion_no_extra | 60/0 | 0/3 | 0 |
| probe-034:teleport_no_psychic_target | 40/15 | 1/3 | 0 |
| probe-035:adventure_gryphon_alone | 40/15 | 1/3 | 0 |
| probe-036:sangan_almiraj_main | 41/15 | 7/13 | 3 |
| probe-037:adventure_negate_main | 41/15 | 3/11 | 4 |
| probe-038:floo_full_primary | 40/15 | 5/30 | 19 |
| probe-039:floo_full_support_goal | 40/15 | 2/13 | 8 |
| probe-040:mst_twister_substitution | 41/15 | 3/3 | 0 |
| probe-041:two_normal_starters_conflict | 41/15 | 2/3 | 0 |
| probe-042:shifter_bulb_conflict | 60/15 | 1/3 | 0 |
| probe-043:sanguine_robbina_conflict | 40/15 | 3/3 | 0 |
| probe-copy:right | 40/15 | 1/1 | 0 |
| probe-copy:left | 40/15 | 0/1 | 0 |
| probe-copy:equal | 40/15 | 0/1 | 0 |

## 工件

保存目录：N:/YGO-Kito/data/axis_generic/v3/evaluation-new-material-20261110-001/。

- report.md：本报告。
- probe-casebook.json：46例功能范围、标签依据、实际改卡、自然候选情况。
- probe-records.json：送入编码器的图与冻结标签。
- predictions.json、metrics.json：逐格raw/calibrated/applied及计数、混淆。
- card-evidence.json、failure-effect-facts.json：完整卡文及失败相关实际解析。
- training-label-diagnosis.json、query-novelty.json：训练标签分布与新功能签名交集。
- inference-binding.json、public-entry-validation.json：权重/校准/源码及原公开入口核对。
- probe.py、validate_and_summarize.py：可复现CPU检测脚本。

原checkpoint、校准、活动指针和源码均未修改。

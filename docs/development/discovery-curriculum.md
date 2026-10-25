# MSG26、公开目录搜索与真实比较课程

依据统一规范1.1及原定稿：效果/主题/情境交叉召回，按缺口再检索；独立目标/优化网络和目标→优化→目标→优化保持。LLM、付费资源和用户尚未提供的3＋8牌表均不是本工程例的依赖。

## 一条 CPU 验收命令

```bash
.venv/bin/python -m ygo_kito discovery-curriculum-acceptance \
  --root .cache --state-root .cache/discovery --run-id <未用过的ID>
```

需要现有锁定核心资源及CPU PyTorch；不下载模型、不启动云资源。命令用Unix内核600秒总上限，各工作进程另有宿主累计墙钟上限。目录身份禁止覆写，失败工件保留。实际运行证据与资源在[报告](../reports/2026-10-23-discovery-curriculum.md)。本地停止不确认腾讯云资源或计费停止。

命令依次执行真实MSG26取消/添加/移除/完成及重放、v3无预写意图的同调/超量探索、缺口召回扩池重验、真实比较课程四模型双周期，并杀死一个自有CPU工作进程后显式recover/resume，与连续运行对照。

## 可组合的结构化入口

```bash
.venv/bin/python -m ygo_kito catalog-recall --root .cache \
  --task configs/build-extra-discovery-v3.json --query <查询JSON>
.venv/bin/python -m ygo_kito goal-discover --root .cache \
  --task configs/build-extra-discovery-v3.json --deck <main/extra/side的JSON> \
  --seconds 20 --attempts 16
```

查询示例是工程条件，非语义理解结论：

```json
{"effect_terms":["特殊召唤"],"theme_terms":["银河"],"context_terms":["调整","通常怪兽"],"preferred_level":2,"preferred_type":4113,"zone":"main","limit":8}
```

`CatalogQuery`拒绝隐藏状态/未知字段。环境资格是硬过滤；三个轴独立匹配并交叉计分，未匹配某轴的卡也可返回。命中包含真实公开效果、静态属性、匹配理由、卡库/文本/可用脚本哈希；不把字面匹配称为费用、次数限制或裁定理解。`expand_pool`产出新的任务/词表哈希及父修订收据，目标、硬约束和环境保留；旧编码器明确拒绝新词表。当前每次任务仍有128卡CPU边界，不声称无限动态词表训练或旧权重已迁移。

v2额外目标仍要求显式意图；v3可省略`goal.route`，由`discover_goal`搜索实际合法动作。ranker只接玩家DTO、任务和公开目录；控制器的种子、全轨迹和对手配置另存审计。默认24次重开分支、每分支100决策、10秒和16个起手种子；允许上限为30秒和64个起手种子，副本通过原生前缀重放重建，无隐藏状态快照。通过的轨迹只说明声明起手下、工程通过对手下达成首回合目标。预算/未知协议返回未找到或明确未支持，不生成“不可能”监督。不是局内未知状态搜索、稳定性估计或竞技搜索收益验收。

## 显式真实比较课程

宿主`--local-cpu-control`及trainer权限仍由既有JSON接口显式启用。选择`--local-training-config configs/group-real-curriculum-v1.json`启用新源；原`group-runner-v1.json`保留旧弱代理且在日志明示。

- `construction-real-curriculum-v1.json`绑定训练和验证源，各自含两份合法工程候选、固定规则驱动、对手及成对种子/双方席位；并非用户卡表或合格强对手。
- bootstrap实际执行并重放8场BO1，目标由核心重验，优化偏好来自这批真实比较；随后基模冒烟和四角色LoRA交替。固定小样本监督可明确复用，绝不当成PPO的当前策略数据。
- 每个构筑角色/阶段记录消费源、摘要和工件指纹，检查点保留来源与消费游标；验证比较另存`construction_validation`，不产生训练标签。验证同时冻结模型、优化器及训练RNG。
- 构筑内循环实际调用两个网络四次并逐步重验；预算内最佳版本按明示的小样本规则驱动比较保存，神经分数未校准。未知路线、平局比较不冒充负例或严格偏好。
- 决斗PPO仍由当前决斗策略重新采样本席位DTO，额外/副卡组随选择的候选一起绑定。v1可显式携带可选sides作为BO1元数据，主＋副卡合并核OCG/张数/别名禁限，副卡不插入core或进入观察；仍拒绝extras且保持v1版本。无sides的旧profile不补写字段，v2行为保持。既有checkpoint/模型/LoRA/全部优化器/随机状态/台账和累计预算保持完整。

卡库/脚本/核心/协议固定于现有资源锁；新的构筑特征版本为`build-task-catalog-candidate-v3-discovery`。源码和特征不兼容的旧检查点拒绝，需在原提交重现或另做显式迁移；不覆写旧权重。

仍缺完整效果结构/三语裁定索引、学习检索及一般CB/混轴、完整协议、冻结学习策略/合格对手的构筑能力评测、三期课程/独立终验与正式吞吐。工程通过不改变阶段1A/1B、PC、外部provider或正式训练ready门槛。

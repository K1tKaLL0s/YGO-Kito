# 额外/素材与实战纠偏CPU验收

本入口沿用固定核心/脚本/卡库，在当前云端非付费CPU执行；不启动腾讯云、API、GPU或100h训练。三组任务都是工程样例，不能当用户将在工程后提供的3＋8套卡组，不能用本命令的样例胜负宣布竞技达标。先读[统一规范](../plans/2026-10-22-unified-development-spec.md)及[总清单](../plans/MASTER-CHECKLIST.md)。

## 一条命令

```bash
.venv/bin/python -m ygo_kito extra-feedback-acceptance \
  --root .cache --state-root .cache/extra-feedback \
  --run-id UNIQUE-EXTRA-ID
```

ID目录必须不存在，工件按独占创建，拒绝覆盖。CLI有180秒Unix内核总期限；内部另有搜索/对局预算，预算不足失败，不生成虚假终局或偏好标签。该期限只限制本地验收进程，不确认腾讯云停止计费。函数不提供云资源生命周期或付费启动能力，现有外部agent白名单和权限不扩大。

命令实际执行：同调first/last两种素材与超量条件路线；三场从路线继续到自然终局、逐响应/事件重放及双方观察审计；两份合法构筑×两个固定种子×先后手对照，共8场实际BO1，每场再次重放；由实际结果形成工程比较数据，两个独立构筑Transformer真实更新、检查点续训匹配及选择后真实目标重验。其余协议的失败仍明确暴露。

输出目录包含`acceptance.json`、条件路线、完整内部审计重放、`comparison.json`、`construction-train-data.json`及三份双角色权重/优化器/RNG检查点。stdout给出检查点/数据的长度/SHA和本次测量；完整轨迹含审计种子/对手牌表，属于私有控制记录，不能给策略作观察。模型只接收合法席位DTO或显式BuildTask/DeckParts，`seed=null`。

## 数据和模型的真实边界

`build-extra-engineering-v2.json`与`build-xyz-engineering-v2.json`保存目标、额外固定张数、真实起手要求和路线意图。执行器只从引擎提供的合法动作中选匹配项，卡片发动、费用、对象、处理和素材资格仍由真实脚本/core裁决。没有自动发现一般组合，也没有估计起手概率或抗打断。未知/不支持/预算没找到不得成为目标负例；额外目标可最多搜索64个实际种子、30秒，固定的初始16次不保证条件出现。

`build-real-feedback-v1.json`冻结两份工程候选、对手牌表、驱动版本、种子和双方先后。标签来自8场实际结果，**不读取印刷攻击力作为训练比较标签**。驱动仍是明确的可见规则基线，未称训练决斗策略或合格机器人；只有牌表合法性，历史环境/竞技强度资格均未通过。失利归因保留为驱动与构筑相互作用未知；单场失利不作构筑缺陷。平分、不完整、错版本或验证分区均拒绝成为优化训练标签。

成对样例只作`construction_train`监督，置信门槛和独立终验为false；描述性标准误为0也不代表真实胜率无不确定性。真实比较记录与原有`engineering_mean_printed_attack_proxy_only`严格分源。构筑监督可复用为有限pairwise批次，**不能作为当前策略PPO样本**。当前四模型交替默认课程仍明确使用原通常召唤/弱代理；新实战数据路径通过BuildTrainer显式接入，不静默替换已冻结课程。

双模型检查点包含任务/环境/监督/源码哈希、各自网络/优化器/调度器、batch游标及Torch/Python/批次RNG。第二批恢复与连续运行完全比较；这不等于长训练中途任意指令恢复。旧特征/源码检查点拒绝加载，本次没有自动迁移、覆盖旧权重；复现旧版本需要原源提交及其资源。决斗特征为`legal-player-dto-v2-extra-sum`，构筑为`build-task-catalog-candidate-v2-routes`。

## 单条完整对局与重放

```bash
.venv/bin/python -m ygo_kito native-effect-duel \
  --root .cache --profile configs/extra-material-engineering-v2.json \
  --route-task configs/build-extra-engineering-v2.json \
  --seed 1 --trace outputs/UNIQUE-extra-game.json
.venv/bin/python -m ygo_kito native-effect-duel-replay outputs/UNIQUE-extra-game.json
```

此例先验证真实起手条件，按显式路线达成目标后才交给可见规则基线继续。起手不满足直接报错，不注入手牌、强置场面或用模拟返回成功。重放保存路线/资源版本与真实响应；旧v1重放格式继续兼容。

正式仍缺：盖放宿主和更广协议、一般效果/主题/CB交叉召回及缺口再检索、自动路线探索、合格bot/冻结学习策略和三期分布、独立统计/BO3、一般构筑/抗打断/迁移能力、PC/标准回放、外部provider实际端到端。完整阶段1与正式ready保持false。用户学习TODO和原件保留，额度不可实时读取时必须说未知，剩余20%保存停止，不使用重置卡。

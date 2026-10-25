# Schema4 长周期课程与有界真实CB目标

本入口沿[统一设计](../plans/2026-10-22-unified-development-spec.md)扩展既有四模型运行器，不另建模型组。此前的[列表语义/数据索引/对手入口](semantic-indexed-opponents.md)继续保留；本批把它们接到基模预热→目标→优化→真实PPO→统筹→冻结评估→反馈的逐阶段事务中。

**发布状态：用户已明确批准本批静态工程配置随代码存储到原私密仓库；[完整代码bb50555](https://github.com/K1tKaLL0s/YGO-Kito/commit/bb50555136c8d7bf40b7626a68ffb698587177e7)已进入PR #1。** 代码树对应云端40d3e65及原文档保存点。此前拒绝有历史记录，获批后按原路径发布，未编码、改名或转存规避；完整私有对局/监督/权重仍留云端。

## 运行与输出边界

在本云端及既有`.venv`执行，运行ID必须为新值：

```bash
.venv/bin/python -m ygo_kito group-runner-acceptance \
  --root .cache --state-root .cache/combined-course \
  --run-id course-new --recipe configs/group-combined-v1.json

.venv/bin/python -m ygo_kito build-train-cpu \
  --root .cache --state-root .cache/combined-build \
  --run-id build-new --task configs/build-combined-native-v4.json
```

第一条是两周期工程验收：管理中断/连续/阶段预算三次有限运行，每次总活动预算180秒；包括实际暂停、只终止自己拥有的worker、恢复和对账。180秒不是整个验收命令的总墙钟，也不是正式100h训练。第二条单独执行双构筑模型两批更新/恢复与四步构筑。两条输出都可能包含私有路线、种子或牌表，**完整输出留云端**。发布只取严格共同公开历史及聚合证明，见[最终报告](../reports/2026-10-23-schema4-course-and-cb.md)。

原纯计数配置`configs/group-semantic-v1.json`继续可用；`group-combined-v1.json`显式选择组合目标，不静默替换旧课程。外部LLM或腾讯云均不是这两条命令的依赖，未配置凭据或启动付费资源。

## 组合目标的实际含义

schema4的`deck_constraints`可选：

- `route_goal`：严格的条件同调/超量目标、指定真实起手条件；复用schema3搜索，不预写操作路线。
- `required_activations`：最多4张公开卡号，要求本席位实际合法发动。
- `required_chain_resolutions`：最多4张公开卡号，要求本席位至少一次对应连锁已处理，且没有NEGATED/DISABLED广播。已处理不自动代表取得具体收益；另有真实终场目标必须同时满足。

对应卡号、目标、起手和类型进入构筑网络编码。构筑特征升级为`build-task-catalog-candidate-v5-combined-native-objectives`，旧特征权重须旧源码复现或明确迁移。网络仍为独立小Transformer，未新增LLM或共享权重。

列表先通过张数/卡池/禁限/主题属性计数，随后由未改核心/脚本裁决真实路线。只有两者和指定发动/连锁条件都通过才返回`constraints_and_route_verified`。纯计数仍为`constraints_satisfied`、`effect_execution_verified=false`；搜索预算内未找到仍是unknown，不编成“不可能”负例。优化比较的两侧都必须有已验证的完整目标见证，不能只保留列表合法而丢掉CB。

公共目录交叉检索仍明确是中文文本/静态事实召回，附卡文及脚本哈希；不是全文卡效语义解析。搜索只按合法本席位DTO和公共卡库提出动作，实际起手满足后才探索；不读对手暗牌或未来牌序。组合验证借现有显式v2路线观察契约，同一物理核心/脚本/卡库保持；真实训练/对手对局用v5，两个契约和回放分别标记，action_id不跨适配版本复用。

工程样例要求救援猫发动、相应连锁处理、兽族计数及真实超量终场。核心实际执行墓地费用及从卡组特殊召唤，通用搜索找到路线；不是为该卡手写假规则。样例不能证明任意卡效、复杂混轴、合理构筑、稳定性或竞技能力。偏好仅为明确的工程属性偏好，不拿它替代真实强度标签。

## 索引、恢复与统计身份

每个schema4基模/构筑适配更新都重新核训练索引准入；注册对手PPO还需训练器自己新采样的密封、当前策略及索引准入。保留验证数据和重新标用途的PPO均在损失计算/随机流消耗前拒绝。静态构筑数据的有意监督复用，与PPO实时重采样分开记录。

组checkpoint新增已提交SQLite索引的字节快照和SHA，与四模型、优化器/LoRA、阶段游标、RNG、已消费标记和累计预算一同保存。恢复写入新的工作目录；被终止worker留下的较新SQL、未提交采样或临时文件不能污染旧checkpoint。每次恢复核对索引工件数、用途/目标/实际对手、阶段消费与轨迹收据；当前实际课程的索引包含2个构筑工件及5份完整决斗数据。私有审计另存，策略和公开报告只看允许的投影。

索引幂等按实际保存的JSON表示比较，DTO tuple/list往返不再误判覆盖。统筹身份递归排除路线计时：计时仍在私有原始证明/资源收据中，变化不产生新候选或新账本身份。目标、证据、牌表、模型或资源变化仍不允许靠该处理绕过版本核验。

## 三期和对手的真实边界

此课程的`period_id=engineering-custom`，绑定实际自定义资源与空发行截止日。当前资源不能改标签变成2022年7月、2022年10月或已冻结2026正式课程；输入检查拒绝此种重标。**三期实际发行数据/官方禁表/卡池及跨期加载器尚未通过**，不能因当前SQL恢复通过就勾选三期隔离。

本批对局实际使用两个注册规则对手；原本地冻结模型入口保留。DSH固定来源`mellfy-puppy/ygo-tools-for-dsh@ab963c1cb9776bea4262ae1bba38f541ec70e357`已核到0BSD插件、MIT WindBot源码/外部策略协议及GPLv3 AI.Server许可边界。它的`ygoagentskill-external-policy-v1`、actionIndex/selectionIndexes和YGOPro2房间不是本工程的版本化action_id/固定core会话；存在exe不代表可运行或兼容。

没有运行随包exe、导入其卡库替换锁定资源或声称合格bot已接入。后续CPU工程须从可核源码构建、桥接固定core/房间消息、核合法观察/非法动作/超时，并按具体时期×牌表×驱动验证操作及强度。源码已提供的部分不能说成缺DeepSeek凭据才可开发；真正CodeBuddy/DeepSeek端到端和目标腾讯云硬件/成本/停机仍需相应环境。用户后交3＋8牌表不阻塞上述工程；收到后再主动对照机器人实际可用性及历史三期覆盖建议补充主题。

正式阶段1A/1B/PC、能力训练与独立BO3仍未通过。20%保存停止，不用重置卡；此云端无实时额度读取工具。本地停训练不等于腾讯云停止计费。

# 原生协议与合法公开历史：修订 3

本入口承接[统一设计](../plans/2026-10-22-unified-development-spec.md)，保持固定 core/scripts/cards/萌卡协议组合和普通 8000 LP 起局。工程牌表是测试输入，不是用户稍后交付的 3＋8 套牌表；脚本发动资格、费用和处理仍由真实核心裁决。

## 启用与复现

只有显式 v2 牌组增加 `"adapter_revision": 3` 才启用新协议与结构化历史。示例为 [effect-history-engineering-v3.json](../../configs/effect-history-engineering-v3.json)。主卡、额外、副卡验证保持不变；旧 v1/v2 牌组不自动升级，也不改写历史轨迹。

```bash
.venv/bin/python -m ygo_kito protocol-history-acceptance --root .cache --output outputs/protocol-history-20261023
.venv/bin/python -m ygo_kito native-effect-duel --root .cache --profile configs/effect-history-engineering-v3.json --seed 3 --trace outputs/history-duel.json
.venv/bin/python -m ygo_kito native-effect-duel-replay outputs/history-duel.json --root .cache
```

第一条命令要求全新的输出目录，拒绝覆盖旧证据。它执行 14 类真实工程路线、其中 3 类的另一合法选择、一条自然终局和原有通用 effect-duel 入口的终局；每条独立重放，共写出 19 份私有审计轨迹及 proof.json，逐份回读。CLI 有 120 秒 Unix 内核墙钟上限，每个工程案例另有 30 秒／2200 响应上限。它不训练模型、不调用 provider、不创建云资源；本地退出不等于云计费停止。

轨迹包含种子、双方响应和工程牌表，仅用于审计／重放。`DecisionRequest` 才是可交给策略或外部 agent 的输入，不能直接把轨迹当作合法席位训练样本。

## 动作语义

| 消息 | DTO 与响应 | 真实覆盖及限制 |
| --- | --- | --- |
| 23 求和 | `SumSelection.mode/target/mandatory/optional`，保留单值／双值贡献；响应数量、必选填充及可选原生索引不出适配器 | 英雄到来实际支付半 LP 后，鼬鼠大暴发产生至少求和，可选择退回两张不同怪兽之一；调和支援士实际按 2 星配合 3 星调整同调 5 星并触发抽卡。高位打包大数仍只有单元证据 |
| 22 指示物 | `counter_type` 与每个 `card_ref` 对应的 `quantities`，原生为 uint16 数量向量 | 防御者＋破坏者各一指示物，地碎触发代破，两个不同分配均真实接受；最多 32 候选／64 字节／2048 分配，DFS 也有限额 |
| 18／24 区域 | 单选 `destination`，多选 `destinations`；每区 controller/zone/sequence 对应三个字节 | 地盘沉下实际禁用两个区域，与核心 FIELD_DISABLED 掩码一致；童妖茶壶真实移动区域。18 多区共用固定核心同一线格式，但多区18只有单元证据；18 数量0保留取消 |
| 25 排序 | 临时 `SearchChoice.scope="ordering"`，按卡号展示，`order.card_refs` 表示完整顺序；原生逐候选返回名次 | 魔导书整理改变下一次真实抽卡，遗式锁链龙覆盖私有查看后排序；原牌序／响应索引不暴露；最多 6 张全排列，另保留原生取消 |
| 140／141 | `number.value` 为种族／属性位掩码，返回同一位值 | 深渊的宣告者实际支付 1500 LP、宣言及对方按规则送墓；组合超限整窗拒绝 |
| 142 卡名 | `number.value` 为卡号，返回卡号 | 禁止令全目录及世纪大盗过滤声明实际接受；翻译固定核心的公开 stack predicate、别名／衍生物／setcode 语义，未知或溢出拒绝；上限 50000，不截断为部分合法列表 |
| 143 数字 | `number.value` 为数值，原生返回选项下标 | 念力之刃宣言 2000、实际支付并装备后攻守变化，不能把数值当下标 |
| 132 猜拳 | 1／2／3 原生值，独立绑定双方窗口 | 变则齿轮真实双方响应、133结果及里侧除外；对方尚未响应时看不到第一方答案。通用弱基线以公开席位打破重复平手，不称模型能力 |

9 组损坏响应分别由真实核心返回 MSG_RETRY；伪造／过期动作在适配器先拒绝。MSG132 核心本身没有对应的范围重试检查，保证来自只允许提交当前合法 action_id，不能声称已测出不存在的核心检查。

## 公开历史与信息边界

`PublicEvent.details` 是严格的 `PublicEventDetails`，记录原消息种类、玩家／回合／阶段、公开位置、费用／处理原因、LP、连锁编号与描述、数值及结果。字段白名单不接收 raw 状态、种子或全局事件下标。编号只对已经发布的公开事件连续递增。

普通非 tag 对局的事件读取包括移动／表示／盖放／交换、召唤及完成、连锁发动／处理／否定／结束、目标／装备、LP、指示物、战斗、公开随机结果、卡组／手牌／额外洗切和公开确认。必须区分线格式已实现与每种机制实际出现在真实轨迹中；逐项证据见[矩阵](native-protocol-matrix.md)及[本批报告](../reports/2026-10-23-protocol-history-v3.md)。未知事件、tag、调试重载／AI名／自定义消息明确失败。

可见性依据锁定客户端 `single_duel.cpp` 的接收方处理核对，而不是凭消息名猜测：

- 普通抽卡和手牌／额外洗切不发布隐藏身份。历史仍保留过去合法公开的身份，洗切清除当前位置关联，不反过来删除历史。
- ConfirmCards 的首张卡在主卡组时仅指定玩家可见，不写入共同公开历史；ConfirmDecktop／Extratop 及该客户端广播的非卡组 ConfirmCards 才记公开事实。
- 私有排序候选只出现在当前选择者窗口。主卡、手牌、额外的原序号不进入历史；额外区宿主上的临时素材索引也不发布。卡组查询继续禁止。
- 未发动的选项、候选数量、单方 missed timing 和私有 HINT 不写入公开历史。6～9 号 HINT 只有与刚提交的宣言结果严格匹配时，才作为双方已经知道的结果；CARD／ZONE 广播按其公开语义记录。
- 猜拳只在双方回答后的 MSG133 发布；手牌和盖卡未知身份／原所有者保持未知。位置的 POS_REVEAL 标记用于判断公开，序列化剥离该传输标志。

真实隐藏世界测试改变私有排序区内容而保留公开状态，下一位对手的请求指纹与模型张量完全相同。已公开额外身份则保留为历史知识，即使额外随后洗切、当前卡背不再带身份。

## 特征、版本与剩余门槛

上下文及通用 effect-duel 轨迹明确使用 `native-protocol-history-v3`，旧 profile 仍用原版本。决斗编码器为 `legal-player-dto-v3-public-history-protocol`：新增历史事实、指示物分配与多区域特征；整数高／低16位分别编码，避免效果序号被 float32 的大数精度吞掉。旧特征权重须使用旧源码重现或另做明确迁移，不能直接加载。

小型神经原型的 2048 动作／token 预算仍有效。全卡名宣言可能超过此限制，协议完整提供目录，但神经策略明确拒绝，尚无分层选名策略；不能静默删动作或称全卡池已可训练。

主卡盲选／对方手牌盲选、混合隐藏区域、盖放宿主素材等仍需合法接口与真实回归。完整一般效果卡池、三期数据／合格对手、标准客户端回放与 PC 门槛、实际 CodeBuddy/DeepSeek 及竞技能力均未通过。新版共同公开历史不是独立猜手／私有历史记忆模型，也不自动改写旧课程的数据边界。用户学习 TODO 不动，LLM 非核心、LoRA 常规持续适配，20% 保存停止。

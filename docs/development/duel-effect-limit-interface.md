# 决斗次数规则窄接口交接

此文件说明当前代码接口与未接项。完整官方手册及机器规则资料由父端整理，本窗口不代替该资料，也不自动把 FAQ 绑定到当前卡池。

`duel_effect_limits.rule_reference()` 返回本次明确范围的 FAQ 元数据与来源链接。`EffectLimitBinding` 要求精确 `(card_id, native effect_description)`、公开卡文摘要、共享计数主体、起止回合及明确适用范围。实体副本共享次数时使用同一 `subject_key`；不同效果保持不同主体。缺少完整范围时 `scope_complete=False`，查询返回未知。

已纳入的窄范围分别为：使用次数的 [17200](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=17200&request_locale=ja)、[17377](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=17377&request_locale=ja)、[17376](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=17376&request_locale=ja)；Trap Trick 作用后特定陷阱卡发动范围的 [22010](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=22010&request_locale=ja)；卡利古拉范围的 [7813](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=7813&request_locale=ja)；交差する魂与運命のドロー各自限制的 [23158](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=23158&request_locale=ja)。只实现各记录已确认的结果；未确认的无效类型保留 `None`。不从“発動”一词推导退款，不把 22010 推广为普通卡名发动次数规则。该普通表述的直接官方证据仍待父端核实。

`EffectLimitTracker` 只读 actor 合法 DTO 的公开发动与链消息。锁定 core 的 `common.h` 定义 75 为 `MSG_CHAIN_NEGATED`、76 为 `MSG_CHAIN_DISABLED`，代码保留两者区别；链结束清除链号关联，回合按独立计数范围查询。全局限制中出现未分类的公开发动、卡利古拉适用前已有发动但范围不明、卡文变化或效果身份不明时，返回未知。

绑定可经 `CourseGameAdapter(effect_limit_bindings=...)` → `CpuTrainer.sample_episode` → `DuelPlanner` 传递，按公开卡文摘要复核并纳入规划上下文封印。规划收据含 `counter_queries`、来源、剩余次数和未知状态。CB 可提供与步骤对应的精确 `effect_descriptions`；假设后续受已绑定计数约束。次数为未知时不猜可执行，交后续真实窗口；引擎当前已提供的合法动作保持可选。

资源与次数独立：`_Projection.committed` 保存响应窗口前已经承诺的资源，`resolved` 保存成功后果。失败不返还已支付素材，也不复制成功召唤素材事件。父端转交的 [11269](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=11269&request_locale=ja) 对应超量素材在失败后从素材状态送墓；[23083](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=23083&request_locale=ja) 提醒卡普壳的解放与成功 S/L 素材事件要求不同。因此模型状态分别保存资源区域和素材事件分类；仅处于墓地不证明素材触发条件成立。上级召唤解放、完整连接/融合程序和所有具体触发条件未在本窗口扩展实现，由真实引擎及后续明确规则处理。

待接：父端完整机器表、真实卡号/效果编号/卡文摘要及范围证明的 reviewed binding 生成器、未覆盖的普通卡名发动次数与具体触发规则。当前默认绑定为空；代码与合成绑定测试不等于当前所有实体卡已获得机器规则覆盖，也不代表全能力验收通过。不得据此恢复训练或绕过 checkpoint 源码绑定。

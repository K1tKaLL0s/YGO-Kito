# 固定席位正常引擎到 WindBot LAN 的宿主投影

`windbot_projection.WindBotProjectionEngine` 是已有 `NativeNormalEngine` 的 Python 子类。`install_projection(engine, observer=seat)` 也能在 `PeriodNativeEngine` 首次决策前接入，保留该实例的时期资源检查与版本。它只用 Python 代理包裹原 library 对象：正常 `get_message` 返回既有有界缓冲后，宿主立即解析允许的命名事实并丢弃局部字节，不修改 CDLL、函数签名、ABI、响应方法或原 `submit`/guard。完整消息、原生响应映射、种子和卡组顺序都不进入 transport frame。

宿主从开局前开始记录连续事件。Start 使用真实初始牌组张数和既有固定 8000 LP/MR5 设置，只发送一次。后续 Draw/Move、精确 phase、召唤、chain、battle、LP、计数物及 target/equip 使用已实现的玩家可见事件。对手从未公开的手牌和额外只保持匿名 LAN 占位，未知对象移出时选独立本地匿名槽，不传原隐藏序号；事件里的牌组位置统一为局部 0。当前合法 DTO 允许的公开手牌/正面额外及 ConfirmCards 使用稳定局部别名，首次公开按公开身份排序分配，不编码原暗牌次序。自席手牌/额外位置可以精确保留。卡片查询先匹配当前合法 `CardView`，只对自席可见或公开卡查询固定大小的动态 type/level/rank/attribute/race/attack/defense/base/status/scales/link 等字段，不查询牌组或隐藏身份。记住敌手手牌的身份不授予其隐藏动态状态，历史确认的手牌仅发送 DTO 已知的 code/owner。counter/target/equip 来自开局以来连续事件；field relocation 保留并重映射这些关联，不调用变长目标/计数物 native 查询。

提示额外事实来自当前正常提示实际载荷，包括 idle 两种 set 模式、battle direct-attack、chain flag/forced/hints/special-count、position 卡号、tribute weights、counter caps 和 declaration opcodes。它们绑定当前 pending request 摘要，单窗只产生一次 frame。Room 将 LAN 回复唯一映射到现有 `LegalAction`，最终仍由宿主提交原 guard。

公开 overlay 的宿主/素材索引从已有合法 `extra_observation` 注册表映射，素材身份与顺序只来自当前合法 CardView。query 更新包含完整可见素材列表，不查询原生素材的隐藏信息；隐藏宿主仅可重发完整且已公开的素材，不能夹带宿主身份或动态值。额外区匿名宿主的素材附加和随后移到场上会保持同一本地对象。search/temporary/ordering 候选采用 `公开 zone count + DTO ordinal` 的窗口内虚拟槽，永不使用 native 候选序号或牌组位置；固定客户端对超出当前列表的 SelectCard 槽创建临时 `ClientCard`，因此不会改写真实牌组占位。32/33/39 shuffle 分别更新匿名/本人及公开身份，并保留真正的公开额外对象。

私有确认以 revision 5 的 `PrivateReveal` 为证据：只接收本席位的确认，将其身份多重集按 controller/卡号排序绑定到本地已有 Deck 占位，从0连续编号，不复制原牌组位置。非接收席位不保存确认卡号，也不建立别名。下一次不确定的 Move/Draw/Shuffle 之前，先发完整 `redact=True` 缓存擦除，解除身份、静态/动态旧值、目标/装备和素材缓存，再使用匿名本地对象。这里的零是“未知”哨兵，不是真实零攻击力或卡效。仅清 code 不足：固定 `ClientCard.SetId` 保留 Type/Level/ATK 等字段；擦除必须排在客户端 `OnMove`/`OnDraw` 使用旧对象之前。hand shuffle、已知敌手手牌/隐藏额外移出、带绑定匿名对象的 extra shuffle 同样执行这个过程，不查询真实暗牌身份或新排列。当前合法的自席/公开快照随后重填可见信息。

公开31即使在下一次决策前已经移出或被洗成未知，也可使用历史对象：Journal 将当时独立分配的本地槽绑定到当前帧新增且未消费的公开 `event_id`。`public_ref` 精确匹配卡号/controller/zone多重集；场上、墓地和除外的原本公开 sequence 必须相同，hand/extra 的证据 sequence 必须剥离，不恢复原暗牌顺序。`public_history_range` 和最终 `message_index` 绑定这一帧；Room 在成功响应后推进已见历史长度和前缀摘要，拒绝旧引用跨窗口重证、篡改前缀及单帧重复消费。确认按消息顺序先于后续完整擦除/Move/Shuffle，末态 DTO 无需继续保留已公开对象的身份。

chain 保留触发 controller/zone，但私有原触发 sequence 固定为0：固定 Ice/Pure `OnChaining` 直接丢弃原 zone/sequence 两字节，只用第一组当前 handler 对象。hand/extra/deck 当前公开的 handler 使用独立本地对象；在回调前初始化公开卡号及固定目录的种类。自席或公共区域有同槽、同卡号的合法动态 query 时，先将其真实当前 Type 更新到客户端，不能用目录原始 Type 覆盖已有变形状态。

70 后同缓冲内的支付代价 MOVE 可能已令最终 DTO 不再保留原槽。例如真实 Rescue Cat 序列为 field70→field-to-grave50，此时 C# 按消息顺序先调用已有 field 对象，再移动它。只有先前真正合法可见 query 的同槽、同卡号 Type，且在70前没有任何状态变更事件，才保留该客户端已有值；来源及原 request SHA 写在 `prompt_facts.last_visible_type`。任意非 hint/70 状态事件都会清除此缓存。不会把墓地末态、打印 Type 或没有证据的历史属性推回场上；这表示最后合法显示值，不声称另有历史动态快照。隐藏手牌的当前动态属性没有因此变成公开信息。

35 用开局以来已公开的墓地顺序和锁定 CDB 的 immutable `data.type`，先刷新旧墓地的 Extra 分类，再让固定客户端交换对象；交换前也擦除旧 Deck 无序对象，交换后只从合法公共墓地 DTO 重填身份。36 仅接受固定核心的同玩家、同区域、2–5个主区盖放槽，清完整旧缓存，公开原槽排序且不转发隐藏目的置换。37 切换客户端已有 reverse 标志。30/38/42 只保留合法公开 history 的无序身份事实，原私区偏移归零；固定 Ice/Pure 明确没有注册这些 handler，不能称机器人因此掌握牌顶或额外卡组顺序。95 只有 legacy LAN CPU 编码，当前锁定 core 未启用发送，不声称原 Native 支持该消息。

仍有明确边界，不能称全卡池或全部 Executor 兼容：

- private confirmation 缺少相应 `PrivateReveal`（例如较旧 adapter 版本）或混合私有区域；既有合法 DTO 没有该证据，拒绝。
- 不含合法新增公开历史证明、引用过时或历史前缀改变的确认会被拒绝；这是证据校验，不再以“末态对象不在原槽”作为不支持的理由。混合 public-deck 确认的无序本地牌组契约未在本轮扩展，不能把原 deck 序号送回。
- 同一缓冲中反复35，旧墓地来自刚公开但尚未有可见 DTO 的整副牌组，缺旧墓地身份/分类证据；拒绝，不查询35后暗牌猜回此前身份。
- 70 当前 handler 是 overlay：固定 C# `Duel.GetCard` 每次创建临时素材对象，前置 Query 的 Type 无法保留到下一次 `OnChaining` 取对象；需要消费者支持持久素材对象，不能冒用宿主身份替代。
- 70 公共 handler 既无当前同槽、同卡号的合法动态记录，也无连续有效的上次合法可见 query；没有历史动态快照，拒绝。其他尚未逐字段实现的实际可达消息同样拒绝。

不可达保护另列：本 pin 的 `core/field.cpp::swap_card` 在任意一张卡不属于 ONFIELD 时直接返回，55只有该函数一处发送，因此私区 vector55 不是当前软件待实现门槛。95 在锁定 core 中宏已注释且没有发送，legacy CPU 编码也不能冒称实际 Native 支持；不把这两项当新增验收要求。

实际复杂 Executor 运行仍须有自己的连续合法路径与完整构建证据。本模块不赋予历史卡池、规则或强度资格，不能从快照补猜历史或退回另一个 AI。

`WindBotOpponent` 复用 `FrozenOpponent` 类型边界。构造参数为 `root, profile, seat, versions, binding, runtime_validator, room_factory`（均 keyword-only）。registry 提供固定来源/编译审计/DB/牌表的实际物理 seal validator；没有默认成功验证器。`room_factory(opponent)` 必须是管理实际 launcher/accept/close 的 context manager。`policy.choose(request)` 返回真实现有 `LegalAction`；`select` 包装为 `ActionSelection`。`managed_engine_factory(base_factory, root, **options)` 在原 factory 创建的正常/时期实例接投影并管理 room，结束或异常时清除请求连接。CPU sampler 只对这个明确类型调用 managed factory，其他对手路径不变。

Room launcher 仅管理自己创建的那个 `Popen`：关闭连接、短暂等待，必要时 terminate，再必要时 kill/reap；不枚举其他 PID、不触及原生核心实例。正常清理和超时 watchdog 用明确进程 fixture 验证，无法确认回收则记录 uncertain 并拒绝继续；没有据此声称实际 C# 执行成功。

CPU 检查：`PYTHONPATH=src .cache/ci-cpu-venv/bin/python -m unittest tests.test_windbot_projection -v`。其中 fake library/socket/host 只证明解析、隐私和生命周期；明确两窗口 fixture 验证真实 `CpuTrainer.sample_episode` 会走 managed adapter，没有 PPO update，也不证明 native 或 C#。

单列普通真实引擎正向检查：`PYTHONPATH=src .cache/ci-cpu-venv/bin/python -m unittest integration_tests.test_windbot_projection_normal -v`。包含既有工程 normal 40 卡表的一局自然终局、既有 Rescue Cat 检索→XYZ（只验召唤完成）、既有 crescent-private 确认→洗牌→匿名选择、rescue-confirmed 确认→未洗牌已知选择，以及既有 confirm-extra 双方公开31→立即39洗牌。后者真实证明敌手额外在末态 DTO 全未知时仍按历史证明编码此前确认。私有两组须经合法提交后再编码下一本席位窗口。均不运行 C#、训练或故障实验。每次将资源、完整 Python source-tree 摘要及局部关键实现摘要、窗口/消息聚合和实际结果写到 `.cache/windbot-projection-normal/*attempt-<UTC>.json`，保留旧尝试；旧冻结证据为 `normal-and-search-xyz.json`、`private-continuity-and-normal.json`，最后公开31增量及全部五机制同树证据见同目录 `public-confirmation-and-final-mechanisms.json`。normal 历史路径有218次合法提交、110席位帧、7回合自然终局；XYZ历史路径有22次提交、18帧及两个公开素材。实际结果以各次匹配源码 SHA 的新收据为准。最早 `report.json` 保留第一次在尚未实现的 room 提示18处停止的记录。

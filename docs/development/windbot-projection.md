# 固定席位正常引擎到 WindBot LAN 的宿主投影

`windbot_projection.WindBotProjectionEngine` 是已有 `NativeNormalEngine` 的 Python 子类。`install_projection(engine, observer=seat)` 也能在 `PeriodNativeEngine` 首次决策前接入，保留该实例的时期资源检查与版本。它只用 Python 代理包裹原 library 对象：正常 `get_message` 返回既有有界缓冲后，宿主立即解析允许的命名事实并丢弃局部字节，不修改 CDLL、函数签名、ABI、响应方法或原 `submit`/guard。完整消息、原生响应映射、种子和卡组顺序都不进入 transport frame。

宿主从开局前开始记录连续事件。Start 使用真实初始牌组张数和既有固定 8000 LP/MR5 设置，只发送一次。后续 Draw/Move、精确 phase、召唤、chain、battle、LP、计数物及 target/equip 使用已实现的玩家可见事件。对手从未公开的手牌和额外只保持匿名 LAN 占位，未知对象移出时选独立本地匿名槽，不传原隐藏序号；事件里的牌组位置统一为局部 0。当前合法 DTO 允许的公开手牌/正面额外及 ConfirmCards 使用稳定局部别名，首次公开按公开身份排序分配，不编码原暗牌次序。自席手牌/额外位置可以精确保留。卡片查询先匹配当前合法 `CardView`，只对自席可见或公开卡查询固定大小的动态 type/level/rank/attribute/race/attack/defense/base/status/scales/link 等字段，不查询牌组或隐藏身份。记住敌手手牌的身份不授予其隐藏动态状态，历史确认的手牌仅发送 DTO 已知的 code/owner。counter/target/equip 来自开局以来连续事件；field relocation 保留并重映射这些关联，不调用变长目标/计数物 native 查询。

提示额外事实来自当前正常提示实际载荷，包括 idle 两种 set 模式、battle direct-attack、chain flag/forced/hints/special-count、position 卡号、tribute weights、counter caps 和 declaration opcodes。它们绑定当前 pending request 摘要，单窗只产生一次 frame。Room 将 LAN 回复唯一映射到现有 `LegalAction`，最终仍由宿主提交原 guard。

公开 overlay 的宿主/素材索引从已有合法 `extra_observation` 注册表映射，素材身份与顺序只来自当前合法 CardView。query 更新包含完整可见素材列表，不查询原生素材的隐藏信息；隐藏宿主仅可重发完整且已公开的素材，不能夹带宿主身份或动态值。额外区匿名宿主的素材附加和随后移到场上会保持同一本地对象。search/temporary/ordering 候选采用 `公开 zone count + DTO ordinal` 的窗口内虚拟槽，永不使用 native 候选序号或牌组位置；固定客户端对超出当前列表的 SelectCard 槽创建临时 `ClientCard`，因此不会改写真实牌组占位。32/33/39 shuffle 分别更新匿名/本人及公开身份，并保留真正的公开额外对象。

这不是完整核心到 WindBot 的通用转换。仍拒绝 private deck confirmation 的原位置表达（既有 DTO 只保证历史身份多重集，固定 C# ConfirmCards 又要求现存真实槽，不能用虚拟槽代替）；公开确认与当前 pending DTO 已无法精确对应；已知敌手手牌在一次隐藏移出后的关联歧义；已知但现在隐藏的额外对象移出所需不可证明的关联；带已绑定匿名对象的 extra shuffle；35 deck/grave swap、36 set shuffle、37 deck reverse、30/42 top confirmation及其他未逐字段实现的事件。chain 的原始触发位置若落在不支持的敌手私有区域也拒绝。不能从快照补猜历史或退回另一个 AI。实际复杂 Executor 运行仍须有自己的连续合法路径与完整构建证据，本模块不赋予历史卡池、规则或强度资格。

`WindBotOpponent` 复用 `FrozenOpponent` 类型边界。构造参数为 `root, profile, seat, versions, binding, runtime_validator, room_factory`（均 keyword-only）。registry 提供固定来源/编译审计/DB/牌表的实际物理 seal validator；没有默认成功验证器。`room_factory(opponent)` 必须是管理实际 launcher/accept/close 的 context manager。`policy.choose(request)` 返回真实现有 `LegalAction`；`select` 包装为 `ActionSelection`。`managed_engine_factory(base_factory, root, **options)` 在原 factory 创建的正常/时期实例接投影并管理 room，结束或异常时清除请求连接。CPU sampler 只对这个明确类型调用 managed factory，其他对手路径不变。

Room launcher 仅管理自己创建的那个 `Popen`：关闭连接、短暂等待，必要时 terminate，再必要时 kill/reap；不枚举其他 PID、不触及原生核心实例。正常清理和超时 watchdog 用明确进程 fixture 验证，无法确认回收则记录 uncertain 并拒绝继续；没有据此声称实际 C# 执行成功。

CPU 检查：`PYTHONPATH=src .cache/ci-cpu-venv/bin/python -m unittest tests.test_windbot_projection -v`。其中 fake library/socket/host 只证明解析、隐私和生命周期；明确两窗口 fixture 验证真实 `CpuTrainer.sample_episode` 会走 managed adapter，没有 PPO update，也不证明 native 或 C#。

单列普通真实引擎正向检查：`PYTHONPATH=src .cache/ci-cpu-venv/bin/python -m unittest integration_tests.test_windbot_projection_normal -v`。包含既有工程 normal 40 卡表的一局自然终局，以及既有 Rescue Cat 检索→XYZ 工程意图（只验召唤完成，不冒称终局）。不运行 C#、训练或故障实验。每次将资源/实现摘要、窗口/消息聚合、终局或明确 unsupported 原因写到 `.cache/windbot-projection-normal/*attempt-<UTC>.json`，保留旧尝试；发布的聚合摘要见 `docs/reports/2026-10-25-windbot-projection-evidence/normal-and-search-xyz.json`。normal 路径实际有 218 次合法提交、110 席位帧、7 回合自然终局，覆盖提示 11/18/16/10/15；Rescue Cat 路径确实经过虚拟检索候选及公开两素材的 XYZ 状态。这只证明 Python LAN codec 到正常真实核心的该范围，不声称 WindBot 已启动。最早 `report.json` 保留第一次在尚未实现的 room 提示 18 处停止的记录。

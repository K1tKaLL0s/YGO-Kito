# WindBot 表示形式消息与本地向量边界

腾讯执行端在 `06674eb` 的冻结 CPU 模型计时窗口首局报告：第174个决策窗口，`_local_vector_bound` 对消息53的 `previous=2` 执行 `tuple(...)`，产生 `TypeError`。该窗口0完成、11未尝试，不能用于平均用时或训练数量。

固定源码核对：core `operations.cpp` 的 `MSG_POS_CHANGE` 写入 code32 和 controller/location/sequence/previous_position/current_position 五个字节；Ice/Pure `GameBehavior.OnPosChange` 按同样布局读取。消息53的 `previous` 是位置标量，消息50 `MSG_MOVE.previous` 才是四字节位置槽。表示形式变化不会使卡片离开牌组／手牌／墓地等向量。

修复仅在消息50分支使用既有 `_wire_slot` 校验并读取旧位置；53不参与向量长度增加。90抽卡及35牌组／墓地交换的公共边界计数保留。非法移动槽继续拒绝，表示形式消息的字段／位置仍由原编码器校验，没有通用类型兜底或隐藏信息放行。未改native绑定、guard、C#源码或响应缓冲区。

回归为明确CPU协议夹具；真实冻结模型／WindBot窗口由腾讯执行端另行复验，不以本地回归或先前规则策略终局代替该证据。新源码摘要使旧资格报告失配时，需按新提交重做正常资格，不能绕过版本绑定。

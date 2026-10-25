# 公开证据边界与索引

此目录来自`foundation-acceptance`的`output/public`，不是完整私有对局重放包。依据[验收报告](../2026-10-23-semantic-indexed-opponents.md)和[运行指南](../../development/semantic-indexed-opponents.md)，仅保存：

- `delivery-proof.json`：锁定资源/源码哈希、实际更新与恢复、分区聚合计数、固定MSG18/24调用分类、资源实测及未通过门槛。
- `train-first`、`train-second`：两个规范训练整局的共同公开历史；恢复验证的`recovery-second`为同一第二局的物理重复，不算额外能力样本。
- `validation`、`final`：不同实际对手/种子分区的工程整局；名称final不代表正式能力终验。
- `snapshot-validation`：真正更新后的冻结模型对手整局；公开胜负不证明强度。
- `msg24-0`、`msg24-1`：实际MSG24首/末两种双区回应和对应公开区域禁用结果，均在云端独立重放。

以上历史文件统一后缀`.public-history.json`。导出逐字段比较双方公共历史并校验严格PublicEvent；不复制牌表、种子、双方动作、私有确认、视图键、原生候选索引/牌序或加载脚本清单。文件中原始SHA和字节数仅用于与云端私有原件校验，不能据此在仓库复原完整审计。

完整私有JSON、索引、监督与checkpoint保存在云端`.cache/foundation-delivery-v2/private`，不是用户下载链接，不上传。此前完整私有JSON上传被拒，未重试或编码改写；本批只沿已经允许的共同公开投影和聚合证据边界交付。

精确命令、计时、退出码、源码SHA及日志哈希见上级[测试收据](../2026-10-23-foundation-test-results.json)。独立命令和恢复对照均不冒充新的能力训练，`full_phase_1_delivered`、`formal_training_ready`及竞技能力保持false。

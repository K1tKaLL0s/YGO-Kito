# v5 可审查公开证据

此目录只提交从真实轨迹提取的共同公开历史与聚合收据，不是完整私有回放。

- [delivery-proof.json](delivery-proof.json)：源码/资源/特征版本、7条机制及重放摘要、计时/RSS和MSG18静态调用审计；`real_msg18_multizone_verified`、`full_phase_1_delivered`、`formal_training_ready`均false。
- [魔导书库 first](crescent-private-first.public-history.json)、[last](crescent-private-last.public-history.json)、[完整终局](crescent-private-first-complete.public-history.json)：双方一致的公共事件及公开结果，不含仅对手可见的卡组确认。
- [救援 first](rescue-confirmed-first.public-history.json)、[last](rescue-confirmed-last.public-history.json)：确认窗口的身份/候选不复制到这里，真实处理中的公共移动沿客户端广播语义投影。
- [盖放超量宿主](facedown-xyz-first.public-history.json)、[盖放后破坏](facedown-destroy-first.public-history.json)：公开召唤、附着/盖放和离场，不暴露额外原序号。

每份投影记录云端原始审计的SHA/大小。导出先比较双方完整共同历史相等，再按严格PublicEvent契约校验；不根据脚本或期望另造事件。原始审计含牌组、种子、双方响应、私有确认与视图键，保存在同一云端`.cache/knowledge-delivery-v2/private`，不作为GitHub文件或用户下载链接。

此前完整私有JSON上传已被拒绝，未重试、改名或编码绕过。本目录沿后续已允许的公共投影/摘要边界发布。[实际测试、失败与剩余门槛](../2026-10-23-private-knowledge-v5.md)另列；重放/工程规则驱动不算独立竞技样本。

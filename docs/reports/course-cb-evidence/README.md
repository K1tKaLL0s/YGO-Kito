# 云端课程/CB的合法公开证据

本目录对应[报告](../2026-10-23-schema4-course-and-cb.md)中的云端代码`40d3e65`。**新源码/config发布被拒，本次PR只增加公开证据/文档，不能把这些通过结果绑定到PR旧代码。** 云端完整回归172单元/172集成及独立CPU命令通过。

- `delivery-proof.json`为明确白名单选择的聚合计数、非零参数更新、恢复/隔离结果与资源记录；不含卡池候选、具体任务约束、版本环境对象或私有牌表。CB原生见证只保留重放成功/公开费用时序/实际终场布尔值和SHA，不导出完整路线。
- `bootstrap`、两份`duel_train`及两份`evaluate`的`.public-history.json`来自同一次已完成中断恢复流程。每局在云端独立重放后才比较双方全部共同PublicEvent历史并导出。它们是公开投影，不是完整私有回放包。
- 上级[测试收据](../2026-10-23-course-test-results.json)包含命令/源码/原日志哈希；CLI完整stdout涉及私有证据，保留在云端，没有复制到仓库。

目录不包含双方响应、私有DTO、隐藏手牌/牌序、视图键、种子、确认记忆、载入脚本清单、索引或checkpoint。原件在云端`.cache/course-final-artifacts-v1`和`.cache/course-final-build`，这些路径不是用户下载链接。被拒静态配置也没有通过此目录、补丁或其他编码变相上传。

三期实际资料、合格bot/DSH、CodeBuddy/DeepSeek端到端、PC和独立能力仍待验，所有正式ready标志为false。恢复/重放和弱工程对手的胜负不算新增独立能力样本，本地stop不等于腾讯云计费停止。

# 第五批修复记录

2026-11-11，Asia/Hong_Kong。实施位置为 `N:\YGO-Kito\_publish_20261030`。本批完成 R3 状态安排、随机身份、质量完成和失分解释的可恢复计算，并修复固定中文卡库中牌顶随机支付、按实际支付量增益、被破坏且送达墓地触发三处语义缺口。

共享分配保存下一随机组合及该组合之后的动作栈。所有身份均可满足为真，所有身份均失败为假，有真假差异或证据不足时保留未知。翻开得到的集合供后续选择，支付和要求实际送达的衔接按替代后的去向核对。空状态的安排枚举及共享分配分别保存游标。质量评分逐个处理一致补全，解释完当组失分即释放详细证据，完成后才生成 Evaluation。公式及加权沿用正式设计。

牌顶送墓费用保留随机身份与合法的 1 到印刷上限，增益按同一效果实际支付张数计算，多个支付量共享同一计分功能。字典原有规则误把费用数量、同名选取限制等识别为卡组投入限制。收窄投入限制到明确投入措辞，独立保留未绑定的效果选取数量条款和原文，只消费已结构化的随机牌顶费用片段。卡片炮击士的默认入口回归得到三个有见证的支付选项，一个增益功能及一个破坏送墓抽卡功能。 [KONAMI 卡片炮击士问答](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=6939&ope=4&request_locale=ja)

随机送墓、翻开选择以及送墓被替代时的处理边界均与印刷条款核对。 [KONAMI 牌顶送墓卡文](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=17414&ope=2&request_locale=ja) · [翻开后选择问答](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=15756&ope=4&request_locale=ja) · [去向替代问答](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?fid=23915&ope=5&request_locale=ja)

规范化 v26、字典 b11，十三个显式静态模块按方法 ID 去重后 360 项通过，零失败、错误、跳过，Torch 未加载，249.715 秒。本批 11 个程序文件的 AST、尾随空白和末尾换行检查通过。证据位于 `.cache/design-implementation-repair-20261111-resume` 中的 `verification-state-quality-card-text-b11-summary.json`、同名日志及 `artifact-validation-state-quality-b11.json`。b10 的 139 通过和 1 失败日志保留，失败为现已修正的费用误标。混杂工作树中另有本批以外的 `construction_effect_blocks.py` 文件尾部空行。

## R5 固定参考与已选候选

固定参考和候选通过同一单库存归一化及评分。参考从固定任务、真实牌表和宿主必需用途计算。可选候选图变动后复用同一参考 Evaluation，实际参考卡文、宿主证据、来源或政策变化时重新评价。参考续算沿独立阶段恢复，保存的候选 Evaluation ID、次序和选择在 12 个候选、66 对比较及三片 JSON 恢复中保持一致。F08 原普通失败已转绿，缺少原任务必需用途和参考分零的用例仍得到相应门槛拒绝。规范化 v27、字典 b11。

首次扩大验证误纳入一个包含临时 CPU 模型 forward 的既有测试，在到达该测试后中止批次，保留 `verification-reference-v27.log`。后续按完整方法名剔除它并阻止 Torch 导入。八模块静态组执行 153 项，152 项通过，一条旧随机主题测试仍以实际命中为计分前提。依据用户 11 月 10 日明确纠正更新该验收，只调整这条测试。定向复验中，主题测试及默认静态入口对照均通过。保留随机标记、指定调用见证缺席、Main 浓度和精确分数的断言。六个本批文件的 AST 和空白检查通过。 [用户纠正后的静态执行书](../plans/2026-11-10-construction-static-entries-execution.md)

证据前缀为 `verification-reference-v27-static` 和 `verification-reference-v27-static-theme-correction`，文件检查为 `artifact-validation-reference-final-v27.json`。R6 及后续未完成项目按独立接续继续。 [R6 起独立接续](../handoffs/2026-11-11-design-implementation-repair-after-reference.md)

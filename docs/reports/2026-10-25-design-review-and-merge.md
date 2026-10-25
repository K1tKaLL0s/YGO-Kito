# 已确认设计复核与条件合并接续

用户已授权在必要设计落实、最终CI通过且没有未审阻塞后，按PR #1→#2→#3合入main。2026-10-25本轮实际起点为main@8914e8055d45f3825fc56f67141750bd5067c2aa，PR1@654971726c96469069a623c7bd366370b9b3a896、PR2@a7085e23a74fb04bff571c1c679e0097dd1ae430、PR3@9be766876a26c1b5692c87c196bf98b007c9051d；三个PR均open/mergeable，PR2/3为draft，审查线程为空。起点和授权不等于实际合并，本批尚未合并任何PR。

## 独立审查与实际修正

[构筑审查](2026-10-25-construction-design-review.md)核实际图/标签、粗连接、狭义路由、可训练非LLM分类/拒判、原双模型评分/训练、卡文绑定拒绝与统筹/manager连接，20项针对CPU通过；不以mock或小样本成绩代替核心实现。[Agent/数据与机器人复核](2026-10-25-agent-data-and-bot-review.md)另核通用接口、3＋8、分期、隔离与恢复，74项针对CPU通过，区分本地真实对局、fixture和仅源码。以上分组重叠，不累加成统一总数。

[模型组审查](2026-10-25-model-design-review.md)与[独立验收](2026-10-25-independent-software-acceptance.md)发现并推动修正真实接线问题：

1. 分期验证原来按局序取对手，但统筹按规范化scope抽样；现按实际租用的id/牌表/驱动身份找到真实adapter，核精确scope、游戏seed和policy_seed，实际记录不再错配。
2. 预警后已有优化候选的route=build_optimizer不应被runner当异常中止；现允许其继续预测与验证，仍拒诊断/停止等不相符路径。
3. 强制重构不能仅以“候选曾有parent”为依据。新候选记录host-owned的当前全部mandatory forecast锚点，验证须确在这些告警后产生且改卡；当前失败牌表不能改parent/环境/驱动冒充重构。旧告警/预测/计数不清除，也不要求构筑永久新颖。独立公开dispatch复核了两次mandatory共250个合成结果与新旧子候选；它们是账本契约，不是实战胜率。
4. 原主模型没有跨期权重初始化入口。新增[显式初始化](../development/group-initialization.md)，复用原四角色，按稳定卡ID/注释身份映射并显式选择有效LoRA或base；新run不继承源优化器、RNG、数据或账本。旧restore门禁不放松。

跨期模块8项与宿主声明3项CPU检查通过；另以真实已更新组工件构造新GroupState、保存、删除source临时副本并恢复，四角色参数与provenance相同、新run更新0、原source不变。独立验收者用weights_only读取实际保存工件核对四hash与bootstrap零游标。源是旧工程期上下文，不声称未来或正式历史池；没有新训练或native。聚合回执附本报告同名前缀evidence目录。

## 新增完整机器人部署范围

用户本轮追加：部署需包含已明确维护范围内全部现有bots，不能只盘点旧dsh副本。现固定IceYGO/purerosefallen/libWindbot及YGOMobile配置四源，完成[815文件源码包、完整发现/校验/惰性安装器与typed源码注册表](../development/maintained-bot-deployment.md)：73/74/73个Executor文件，220条来源、81组代码字节身份、144条YDK路径、211条发行配置别名；14个二进制资源仅锁定未取。相同字节仍保留原来源/构建上下文，不声称运行等价或历史强度。

根MIT及原依赖声明保留；GPL移动端只含LICENSE和bot.conf资料，不整搬客户端。Horus是旧黑炎龙Lv6/Lv8；ChaosRitual为光与暗之仪式，Elfnote为耀圣，不能据旧副本没有文件否定整个生态，也不把纯轴存在当巳剑混轴更强的证明。未替用户填正式八套牌表。

新增范围**尚未全部完成，当前不能执行条件合并**。源码准备与815成员重验已过，14项CPU只验证惰性安装/发现/版本/裁剪拒绝，不能当真实机器人运行。仍缺全量完整C#构建、必要二进制/工具链、YGOPro LAN房间消息到本项目ctypes合法单席位的真实桥接及逐bot正常加载/对局验证。没有以泛化占位、ExternalPolicyOnly或一个外部代理代替全部Executor。

[专项审批packet](2026-10-25-bot-build-run-approval-packet.json)已列固定来源、完整exe的build argv、仅127.0.0.1的测试argv和风险。当前Mono/MSBuild/xbuild/dotnet均无；只读apt-cache policy又因系统APT配置权限不足未能取得候选版本，未安装工具、编译或执行第三方代码。安装会改系统软件目录，MSBuild/SQLite/C#会执行第三方逻辑，按用户指定的专项边界等待批准；不是一次平台执行审批拒绝，不伪造拒绝记录，也不换工具绕过。lib Android PostBuild、公网Test1和付费调用不在拟执行范围。

## 合并检查与接续

GPU安装、性能调优、能力训练归第二阶段；PC/可选LLM/DP另取历史全库不作为新软件合并门槛。这里暂停来自新增机器人真实软件接线与专项执行边界，不能将其改称缺GPU或仅缺权重。

闭合后先核最终头提交与CI，再逐项检查有无他人新增变更；PR1合main后，将PR2明确retarget main、复核diff并以expected_head_sha合并；PR3同样retarget main，确认最终tree包含全部差异后合并。保留原作者commit和分支，不强推/删分支/自动合并/部署。若具体动作被审批拒绝，只停止该动作并准确报告。

当前没有实时Codex用量读取工具；父任务的历史59%不当成当前值，≤20%保存停止，不使用重置卡。最终统一CPU与远端CI另按真实收据报告，不能引用9be7668的362项替代本批检查。

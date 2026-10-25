# 2026-11-01截止、来源补充与阶段纠正

本批接续59dfda0与原PR #3分支，仅落实用户新确认的日期、必要发行门禁、百鸽来源核查及阶段边界。未重做训练、调用付费模型、修改native绑定、合并或更新被拒绝的PR标题/说明。旧原始证据、null测试夹具和旧包保留当时事实，不改写成已在当时选择11月1日。

## 已完成的软件修改

- 三期截止显式为2022-09-30、2022-12-31、2026-11-01；第三期含日本当地（Asia/Tokyo）当日正式OCG发售。禁限仍固定2026-10-01生效/2026.10，没有改用未来禁表。
- deck_intake、分期runtime和训练输入共享实际JST时钟门禁。未来截止的完整环境仍pending，不注册为完整输入；未选2026不影响selected-period 2022。内存完整性检查也重验日期，没有配置/RPC时钟绕过入口。动态今天不写入持久period_context/Versions绑定。
- 独立审计允许先整理未来候选，分别列unknown、after_cutoff、not_yet_released与已知静态禁限违规。公开文字不等同正式发行；未来期的available_in_period保持false，覆盖矩阵保留staging blocked状态。到日只解除时间限制，仍检查发行manifest、来源SHA、卡库和所选禁表，final_card_pool_verified不自动变true。
- 动态核对日期只留在即时审计/预检，不改变不可变registry记录格式，隔天重复登记与旧记录身份保持兼容；Token及非OCG卡不会因发行日满足而标为可用。
- 预检显示已选截止、JST核对日和未来pending状态，GPU工作明确归stage2_training，不作为当前软件完成前置。README、AGENTS、设计、当前交接和总清单同步纠正。

## 来源取得与边界

[百鸽局部来源核验](2026-10-25-baige-source-review.md)记录实际URL、UTC观察时间、社区聚合性质、API文档与HTML的不同证据级别。两个公开卡效样例实际为OCG未发售、TCG已发售，不能用公开卡效、英文发行或先行ID代替OCG正式日期。可靠社区资料可作开发和交叉核验，不再把取得官方原HTML作为唯一资料门槛；未知与可信程度仍明确保存。

两个普通JSON GET（`/api/v0/card/16178681?show=all`、`/api/v0/limits.json`）被云代理Tunnel 403拒绝，均已停止，未重试或换工具取被拒内容。公开HTML与API文档可读不等于JSON正文已取得；未下载全库、未编造历史完整禁表，也未把百鸽接为可运行release manifest。旧官方路径未再访问。具体来源观察已加入official-source-evidence的community_supplements，不改变官方验证标志。

## 验证

针对性CPU命令：

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONPATH=src .cache/ci-cpu-venv/bin/python -m unittest \
  tests.test_deck_intake tests.test_historical_listing tests.test_external_policy_bridge \
  tests.test_period_runtime tests.test_training_input tests.test_period_host -v
```

实际 **91/91通过，9.408秒，0失败/错误/跳过**。覆盖JST10月31日23:59:59与11月1日00:00边界、含截止日而排除11月2日、完整未来资料仍pending、到日缺来源/坏SHA仍关闭、缓存日期复核、前两期selected加载兼容及未来审计状态投影。时间/卡库为明确合成fixture，不能作为真实未来卡池证据；native没有运行，也未重跑完整训练或旧引擎验收。

实际锁定文件只读审计另对8样例×3期生成当前报告；只是重新核对当前配置与已有资料，不认证最终发行。日志、按模块计数和审计聚合在本报告同名前缀evidence目录；CI以该提交平台实际状态另读，本地91项不冒充CI。

实际CPU预检退出0，显示cutoff_selected=true、cutoff_reached=false、final_card_pool_verified=false，禁表保持2026-10-01/2026.10；GPU验证归stage2_training、gpu_checks_block_software_completion=false。它只做CPU张量/SQLite及锁定资源文件核对，没有加载native、训练或启动云资源。[测试与预检](2026-10-25-cutoff-and-source-evidence/tests.json)、[预检原始输出](2026-10-25-cutoff-and-source-evidence/preflight.json)、[当前只读审计聚合](2026-10-25-cutoff-and-source-evidence/listing-summary.json)。

## 接续与阶段归属

此前把腾讯云GPU实测、调优、正式训练或能力验收当作当前软件开发完成前置的说法有误，已经纠正。它们属于第二阶段：用户提供3＋8牌表后按现有导入/训练入口/恢复交接进入腾讯云，安装目标依赖并执行相应运行步骤；PC产品归阶段3，provider和第三方bot仍是可选路径。没有新增泛化或硬件验收门槛，也没有用尚未开展第二阶段工作否定软件交付。

本批已知可独立执行的软件修改已完成。数据接续为用户牌表，以及11月1日JST当日或之后对第三期实际正式发行、可信来源、资源哈希和所选10月禁表作最终核对；预告/延期/未知发行不得自动补入。该待办不是新增软件阻碍，不创建定时任务。

代码与当前文档已保存为c6af3753d986e9c15b3a17a96747d060882664b6。测试与预检在提交前同一工作树执行；预检原始local_commit仅记录当时HEAD，不冒充提交后运行。新源码包为`.cache/ygo-training-source-c6af375.tar.gz`，271文件/676640字节，SHA256为b683ae3a3315a110a620450f5da6dcf0a8f5074c0626a7871e23420d203b0cf0，已逐成员校验并与当前包内源码逐字一致；不含运行资源、权重、私有轨迹或凭据。[包回执](2026-10-25-cutoff-and-source-evidence/source-bundle.json)。旧0c7b537包不含本批门禁，保留为历史快照，不作最新版交付。

本环境没有即时Codex额度读取器，沿用20%保存停线且不使用重置卡。父任务04:18:23UTC实读59%仅是该时刻观察，不冒称当前余额。

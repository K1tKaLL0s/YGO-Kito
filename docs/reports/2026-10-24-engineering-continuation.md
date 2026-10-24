# PR3继续工程准备：CI、Agent、3＋8收件与训练交接

在已有完整整合候选129baa4及[草稿PR3](https://github.com/K1tKaLL0s/YGO-Kito/pull/3)继续，未另建任务或分支；实现提交为 **`c724a29fd93f978ea4826130f7c4a809783b8d81`**，CI检出兼容修正为 **`60fbb0209989416d059b938b6e8e719d57562788`**。依赖仍为PR1@6549717 → DP草稿PR2@a7085e2 → PR3。首次发布审批拒绝已在新明确授权后解除，历史bf2fd03保留，不是当前阻碍。未合并、自动合并、强推、删分支或修改权限。

## 先盘点、再补缺口

| 项目 | 原有实现 | 此次真实增量 |
| --- | --- | --- |
| EP-01 CI | 安全白名单188项，无workflow/依赖锁 | 只读权限workflow、固定action SHA、Python3.12.14/CPU Torch2.9.1全哈希锁、零skip门槛、固定cwd、日志和资源收据。 |
| EP-02 通用Agent | DP Client/Bridge、状态/控制/持久去重 | 5项完整fixture生命周期与真实UTF-8 JSON Lines管道测试；未再造厂商SDK或训练后端。 |
| EP-03 3＋8配置 | JSON/YDK、环境/对手registry、既有牌表合法性 | 固定11槽空模板、三期显式截止/历史卡库/发行/禁表来源检查、控制方分型及整批准备记录；不部分导入、不自动激活训练。 |
| EP-04 训练交接 | 固定CPU后端、四模型checkpoint、监控/恢复接口 | 完整源码自包含指南、哈希锁安装、只读资源/checkpoint inventory、启动墙钟/CPU/RSS；6项检查包括坏/空制品和未提供状态。 |
| EP-05 构筑逻辑 | 可训练分类器、图候选评分/绑定、反馈与统筹 | 6项开放主题、组合/否定/歧义、低置信、跨多轮重构及积木/连接分离场景；不冒充模型泛化。 |

对应[总清单EP-01～05](../plans/MASTER-CHECKLIST.md)。原EA-06与CL-00不因新增切片就晋升为正式能力或阶段交付；原有模型/训练架构未大改。新增生产模块仅`deck_intake.py`，不修改native绑定/guard或预算系统。

## 最终源码验收

在新建独立`.cache/ci-cpu-venv`中，`pip install --require-hashes -r requirements/ci-cpu.txt`实际成功，`pip check`通过；Python **3.12.14**、Torch **2.9.1+cpu**、NumPy **2.3.5**。没有用原环境Torch2.14.1的结果冒充CI锁版本。依赖缺Torch的独立负例立即exit1，未加载测试，不能用skip制造绿灯。

受测实现c724a29执行：

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONHASHSEED=0 \
  .cache/ci-cpu-venv/bin/python scripts/check_merge_candidate.py \
  --output docs/reports/2026-10-24-continuation-evidence
```

**217/217通过，0失败、0错误、0跳过，18.239秒**；2026-10-24 21:27:49 UTC开始。分组为原整合188＋Agent生命周期5＋构筑场景6＋收件12＋训练交接6。源码聚合SHA256为 `6af98ff7450fd16236dc64dbd3c96e7629f57731bfaad9f573c2cc380418a47c`。后续收据/报告提交仅文档，源码不变；CI应以实际head结果另验。

- [逐项测试日志](2026-10-24-continuation-evidence/tests.log)
- [测试/版本/DP双文件/资源回执](2026-10-24-continuation-evidence/results.json)
- [实际只读启动与交接报告](2026-10-24-continuation-evidence/handoff.json)

首轮远端CI暴露工作分支依赖后，60fbb02只修正既有交接测试的隔离，不改生产源码或workflow检出。该提交在同锁环境重跑仍为**217/217通过，0失败/错误/跳过，17.864秒**，2026-10-24 21:31:18 UTC开始；见[最终收据](2026-10-24-continuation-evidence/final/results.json)和[逐项日志](2026-10-24-continuation-evidence/final/tests.log)。原c724收据保留，源码摘要相同。最终父进程CPU2.373秒、峰值约335MiB，仍不含子进程合计。

父测试进程CPU为2.355秒、峰值RSS约332MiB；不含子进程资源合计。独立handoff的status/help分别约0.106/0.114秒，实际退出0且engine ready=false。这些是短CPU工程检查的占用/速度，**不是训练吞吐、游戏速度或硬件压力上限验收**；GPU指标/样本吞吐/PC延迟均未测。

独立审查复验收件12项通过，未发现普通工程阻碍。另独立审查发现空制品即使空SHA匹配也会被原字节监控认可，本次在handoff入口明确拒绝并补测试；它不反序列化模型，不改变既有恢复实现。字节完整不能替代真实恢复/资源/特征绑定。

## CI发布与边界

新workflow在PR synchronize和main push运行，15分钟总超时、安装10分钟、测试4分钟；CPU线程各2，只有`contents: read`。已静态核对YAML/固定action版本并用相同锁环境本地运行；本报告写入时尚未推送，**远端CI结果待读取**，以后以PR3对应head的workflow结论为准。本地收据`ci_verified:false`保持原证据类别，不随远端状态改写。

后续实际发布043c5bc触发[首轮Actions 40134446833](https://github.com/K1tKaLL0s/YGO-Kito/actions/runs/40134446833)：依赖安装成功，217项执行，1 error、0 failure/skip，job失败，[平台日志聚合回执](2026-10-24-continuation-evidence/ci-first-run.json)保留失败而非覆盖。源码检查及独立临时仓库复现定位到旧test_agent_tools交接正例直接依赖当前ROOT工作分支，Actions默认detached PR合并检出与生产门禁冲突。60fbb02将该测试移至无远端临时Git仓库，关闭fixture hooks/签名，并真实验证工作分支成功、detached/main拒绝；未放松生产门禁、未跳过或改CI检出规避。修正后第二轮远端结果由PR3实际head回读确认。

首轮artifact12576881086的connector下载动作生成了临时文件引用，但云端读取该ZIP时HTTP代理隧道返回403 Forbidden，未取得ZIP字节；停止该读取，不换工具重试。其job日志与聚合JSON已成功读取，足以区分CI失败/修正和本地通过；完整首轮逐项artifact只可由有权限的仓库界面另查。此访问失败不是原生故障操作或审批解除。

未新增付费服务/账户/SDK/权限；GitHub包含分钟和计费状态未读取，不能保证任何runner分钟免费。只上传7天测试日志与聚合JSON，不上传模型、数据库、用户牌表或私有轨迹。整个`tests.test_native_response_buffer`、真实`integration_tests`、原生加载、故障注入/崩溃复现及未筛选discovery均未运行，排除项不计通过或skip。未恢复此前受限任务。

## 仅剩本轮准备之外的资料与目标环境验收

- 用户真实三套主构筑和八套对手牌表、各对手明确时期、实际模型/driver；模板目前11槽、0牌表。三期均缺显式发行截止、卡库、发行清单和指定禁表证据，实际空模板预检全为pending，`complete_user_input=false`。
- 完整锁定core/scripts/cards/banlist及receipt；当前检出缺资源且ready=false。历史资料即使静态核对，也仍需官方来源审计、真实规则/PC/驱动兼容和对手资格。准备记录始终runtime/formal_training_ready=false，不冒充可执行课程。
- 可选SciPy未装；legacy schema4从空表求解需此依赖。当前合法base编辑及本白名单已验。
- 实际外部编程Agent/provider配置、权限与额度；JSON Lines/SQLite夹具不代表真实外部模型端到端。
- 正式腾讯云GPU机型/CUDA依赖锁、采购/执行授权、吞吐/显存、模型能力与独立胜率验收；当前后端为CPU工程课程，未做正式训练。G-01/G-02/P-01等门槛未因此通过。

可自包含接续文档：[CPU CI](../development/safe-cpu-ci.md)、[收件](../development/deck-intake.md)、[训练交接](../development/training-handoff.md)、[厂商无关Agent](../development/generic-agent-integration.md)。剩余项不靠编造牌表、猜截止日或恢复受限原生操作补齐。

额度：父任务于2026-10-24 21:19:41 UTC实际核实每周剩余73%，5天20小时重置；仅该读取时点有效。本环境无实时额度接口，不将该值称为当前余额；≤20%保存停止，不使用重置卡。

# 训练前工程接续：实现、真实运行与外部依赖

本轮沿用`codex/integration-merge-prep`和草稿PR3，依赖PR1→PR2→PR3，不合并。用户要求完成可在云端独立完成的训练前工程，真实3主＋8对手牌表后交；不购买GPU、调用付费模型、改凭据权限或重做DP的故障实验。最终实现6d23fc9与受测82fdfde的生产源码SHA256均为ae247a5b656d972c55db2fa69df60838e2faf5286d813bc28ff13f4fa7f79b09；后续证据提交不改生产源码。

## 本次实际补齐

| 范围 | 实际实现与调用 | 边界 |
| --- | --- | --- |
| 模型和设备 | 原CpuTrainer、BuildTrainer双独立模型、CoordinatorTrainer、LogicModelAdapter及AdapterSession传递显式device；迁移batch/targets/位置索引，绑定执行精度、优化器和设备RNG | CPU代码实际更新；CUDA仅代码接口，无GPU数值/吞吐/恢复证据。旧CPU检查点不自动迁移 |
| 学习输入 | 构筑/统筹更新数可配置；统筹显式日志目标训练/保存恢复，group bootstrap和LoRA消费同一绑定监督；nullable forecast不伪造概率标签，单样本优势保留信号 | 默认工程样例来源可见。带hash的日志仍不是已认证的胜率监督 |
| 三期运行 | training_input编译/加载3＋8分区，PeriodBuildAssets核对真实物理资源，PeriodNativeEngine使用所选禁表/发行允许池/非null截止，host接入既有schema4索引课程 | 合成日期只测接线；正式历史卡池、旧勘误/裁定、用户构筑尚未认证。普通旧课程不得静默绕过period数据准入 |
| 对手与隔离 | 真实已有PublicRulePolicy/FrozenOpponent兼容对象，实际driver实现摘要；构筑编辑后重绑actor/对手profile，seed/用途/别名/牌序隔离，多对手数据集身份进入索引 | 正常规则baseline可运行，但不称强bot/DSH/真实DeepSeek；外部Agent生命周期仍明确fixture |
| 构筑与求解 | 狭义1→2→3、广义1→3保留原轻量图；复用已有双构筑评分器/填卡/合法性/统筹；SciPy1.16.3加入CPU哈希锁，实际MILP求解与独立合法性检查 | 程序枚举和模型评分分开；小合成拟合不是概念掌握，未知效果不补造合法CB |
| 私有重放 | 条件路线每次搜索复用私有动作key，保存于可信私有审计；公开回执剥离key；已有candidate按原身份返回不可变证据，避免随机审计破坏重试 | 不把key、raw trace、双席位私有数据放入策略输入或公开PR；不是新凭据/外部服务 |
| 源码交接 | deployment_prepare确定性源码包/manifest，逐字校验，拒绝未提交源码、symlink/路径逃逸/成员篡改；支持无Git安装验收；真实主机静态依赖/资源/硬件/恢复字节门禁 | 包不含原生缓存、牌表、轨迹、权重、凭据；静态通过不等于可付费正式训练 |

DP原生响应/ABI和guard保留，唯一native扩展为两处禁表读取调用独立hook，可精确还原到DP固定SHA。没有运行`tests.test_native_response_buffer`、未筛选discovery、原生故障注入或故意终止worker验收。

## 真实引擎为何此前未验及本轮结果

此前本检出缺整个`.cache`原生资源，217项本来是纯CPU/协议白名单；没有为当前版本安排普通引擎验证。旧任务拦截被过宽沿用为正常运行限制，已纠正。当前锁定源码构建、正常召唤、自然终局、重放和16项正常接口均实际获准并执行。完整事实和资源hash见[当前诊断](2026-10-24-native-current-diagnosis.md)。这没有重做DP修复，也不证明旧SIGSEGV唯一根因。

首次正常最小对局7回合/217决策，真实胜负和逐响应/事件/终局重放一致。分期工程样例已实际加载三期资源/基线、选取冻结对手、保留截止并完成条件通常召唤；它不是官方历史数据认证。具体最终分组如下；[每项名称/源码版本](2026-10-24-pretraining-evidence/normal-results.json)、[CPU逐模块与资源收据](2026-10-24-pretraining-evidence/cpu-results.json)、[新增/改动文件](2026-10-24-pretraining-evidence/changed-files.json)均已保存。

## 仍需真实资料或目标环境

| 依赖 | 具体缺项及接续 |
| --- | --- |
| 用户卡组 | 11份真实主/额外/副卡与目标，逐期归属；空收件模板不造牌表 |
| 历史和官方资料 | 三期明确发行截止、逐卡OCG发行证据、官方完整累计禁表/旧文本/裁定及使用权；当前固定社区禁表含2022.7/2022.10/2026.10，但不等于官方全表核对 |
| 原始资料访问 | 云端shell对官方日文OCG禁表HTML的HTTPS GET实际被代理403拒绝，下载已停止，未改工具绕过。网页已读的日期不扩大为全表认证；正常native没有这个拦截 |
| 对手覆盖/可选外部模型 | 本地规则和冻结模型基线不依赖LLM；正式代表性需逐期牌表/驱动资格。DeepSeek专属路径才需真实provider，未接通不阻塞本地基线；分期snapshot与纯DTO桥接准备另见本轮增量 |
| 腾讯云硬件 | 现有获准实例、CUDA/驱动/依赖锁、实机吞吐/显存/数值/恢复及计费停机确认；当前仅CPU环境，未采购或启动GPU |
| PC产品/客户端互操作 | 后续阶段3核对目标客户端动作/连锁/标准回放与本地性能；不作为基础腾讯云headless训练前置 |
| 正式学习与统计 | 模型规模/课程配比/阈值经实际2A小试冻结、分类校准及独立能力/BO3/LoRA迁移验收；工程参数更新、几局胜负不是能力证明 |

官方日期核验只包括：[2022年7月公告](https://yu-gi-oh.jp/news/oid-1313/)明确2022-07-01生效、[2022年10月公告](https://yu-gi-oh.jp/news/oid-1388/)明确2022-10-01生效、[官方日文OCG页面](https://www.db.yugioh-card.com/yugiohdb/forbidden_limited.action?request_locale=ja)显示2026/10/01。两份历史公告是变更公告，不是完整累计列表。逐项状态在[机器可读来源记录](../../configs/official-source-evidence-v1.json)。

因此不能宣称“只剩用户卡组即可正式付费开训”。已完成的是可复验的云端工程准备；G-01/G-02/B-02整体正式训练目标保持未通过；P-01另属阶段3。后续Agent从[训练交接](../development/training-handoff.md)、[分期宿主](../development/period-runtime.md)、[部署说明](../development/deployment-preparation.md)与总清单接手，保留全部绑定，不通过改环境名/null截止/删除receipt消除缺项。

当前工具没有即时额度读取能力；不沿用旧73%为当前值，交父任务核实。达到20%保存停止，不使用重置卡。

## 最终实际验证（不混用不同性质的证据）

| 类别 | 实际结果 | 不代表什么 |
| --- | --- | --- |
| 本地CPU/合成契约 | 82fdfde完整白名单311/311，0失败/错误/跳过，24.679秒；Python3.12.14、Torch2.9.1+cpu、NumPy2.3.5、SciPy1.16.3 | 小合成文本/图训练只是实现路径，不证明泛化；无原生/外部provider |
| 正常真实引擎 | 6d23fc9上23/23，125.055秒；包含合法终局、精确回放、Agent动作边界和7项分期真实检查 | 当前锁定资源工程池，不认证全卡池/历史规则/目标PC |
| 实际CPU训练恢复 | 同一生产源码15/15，97.962秒；决斗、双构筑、四网络、LoRA实际非零更新、优化器/调度器/RNG和下一步恢复 | 有些构筑/统筹标签仍为明示工程监督；不是正式训练或胜率 |
| 真实group课程/恢复 | 普通2/2，59.534秒；分期3/3，169.470秒（含准备/多次恢复核对）。分期实际完成7阶段、8优化更新、2训练局、1冻结评估；运行计时133.612秒，原180上限和reserve未改；5个索引工件恢复 | 三期日期清单为工程样例；仅选中一期短测，不声称三期正式课程完成 |
| 设备/硬件 | 分期worker CPU119.050秒、setup CPU14.571秒、进程峰值RSS718692352字节；CLI status/help分别0.105/0.102秒且退出0 | RSS是所报进程峰值，不是全进程树；无GPU压力/显存/吞吐测量 |
| 源码包 | 82fdfde首份255文件/623455字节包校验通过；在/tmp以无.git安装运行完整311/311，0skip，生产源码摘要一致 | archive来源提交单列，tested_head=null；归档哈希不认证发布者，不含运行数据 |
| 远端CI | da0130b的[Actions 40141837656](https://github.com/K1tKaLL0s/YGO-Kito/actions/runs/40141837656)实际completed/success，311/311、0失败/错误/跳过，23.401秒；安装与artifact步骤成功 | runner临时PR合并检出881e9a9不表示PR已合并；前次217仅历史 |
| 能力验收 | 未执行正式GPU训练、独立BO3/胜率、分类校准、LoRA迁移或真实外部模型 | 不填写“能力通过” |

普通/分期完整group回执分别为[group](2026-10-24-pretraining-evidence/group-normal-proof.json)与[period](2026-10-24-pretraining-evidence/period-group-normal-proof.json)，无私有selection key或raw trace；[启动与资源清点](2026-10-24-pretraining-evidence/handoff-verified.json)是只读清点，不能覆盖真实引擎测试结论。

首轮失败保留在[历史收据](2026-10-24-pretraining-evidence/initial-normal-results.json)：先为测试annotations缺失，随后重复资料加载使运行在153.549秒按原预算预留正常停止（0已发布更新）。单次操作复用并加出版前完整门禁后，prepare CPU降至14.571秒并完成周期；其间另一次严格偏好门禁拒绝无差异的工程样例，已改成明确对比偏好，而非放松生产检查。没有把失败删除或换成模拟成功。

## 最终可交接包与主机预检

最终源码包为`.cache/ygo-training-source-59dd60b.tar.gz`，来源59dd60b7c4081c4bf54e53b716abfe307cabf922，255文件、623594字节，SHA256 `ae154ea20975b89134b113322c563e2f304dc402418018707cf8ec5cbff3c96f`。[逐项包回执](2026-10-24-pretraining-evidence/source-bundle.json)。包已在无.git目录从/tmp执行完整311/311（25.785秒），[归档回执](2026-10-24-pretraining-evidence/archive-results.json)的tested_head为null、source_archive_commit另列；生产源码摘要与Git检出一致。后续本报告/CI证据提交不改变包内源码文件；不要把包来源提交说成最新PR head。

[当前真实CPU主机静态预检](2026-10-24-pretraining-evidence/cpu-deployment-proof.json)退出0，来源actual_host：4个cgroup可用核、16GiB内存上限、约30.5GB可用磁盘、CPU Torch实际依赖/资源哈希均匹配。所用1核/128MiB/16MiB阈值只是明示的最小工程预检，不是正式课程容量推荐。未填的[GPU配置模板](2026-10-24-pretraining-evidence/gpu-template-blockers.json)按预期退出2：本机无CUDA、CPU wheel不能作GPU锁，目标硬件/参数尚缺；未自动回退、采购或启动GPU。两份报告均formal_training_ready=false，静态报告不反序列化权重或加载核心。

腾讯接续顺序：取得已核对源码/包→按哈希锁建CPU环境并运行安全检查→按lock准备/验普通native资源→填写收件/分区/period host和真实task→目标GPU锁/主机静态预检→获准2A小试及恢复/吞吐记录→冻结三期正式课程。具体命令和恢复协议在包内training-handoff/period-runtime/deployment-preparation，无厂商SDK或本机路径依赖。正式牌表到达后仍须验证所需机制与驱动；遇unsupported要明示并适配，不能以本轮通常怪兽/有界超量通过预先保证珠泪全机制。

[平台CI与原始聚合收据](2026-10-24-pretraining-evidence/ci-da0130b.json)保留PR head与临时受测提交的区别；源码摘要ae247a5b与本地/归档一致。后续证据提交的最新head检查仍须另读平台，不能只凭此历史运行声称所有后续head通过。

阶段澄清：此前将PC和provider一概并列为开训阻碍过宽，现按最新授权修正。PC产品/标准客户端互操作后置，LLM非必需；2A可用明确合法工程数据做硬件/吞吐小试，2B正式分期课程才需对应历史资料/牌表/驱动。两个2022设计截止不是待用户选择，2026具体截止仍须选择。当前源包59dd60b是前批快照；本轮新增源码完成后另生成新包，不能把旧包称作含有本轮新代码。

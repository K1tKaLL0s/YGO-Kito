# 训练前工程接续：实现、真实运行与外部依赖

本轮沿用`codex/integration-merge-prep`和草稿PR3，依赖PR1→PR2→PR3，不合并。用户要求完成可在云端独立完成的训练前工程，真实3主＋8对手牌表后交；不购买GPU、调用付费模型、改凭据权限或重做DP的故障实验。本报告的最后测试回执将指明受测提交；开发中检查不充当最终验收。

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

首次正常最小对局7回合/217决策，真实胜负和逐响应/事件/终局重放一致。分期工程样例已实际加载三期资源/基线、选取冻结对手、保留截止并完成条件通常召唤；它不是官方历史数据认证。最终CPU、正常引擎、训练恢复与源码归档的具体分组将在固定提交上单列。

## 仍需真实资料或目标环境

| 依赖 | 具体缺项及接续 |
| --- | --- |
| 用户卡组 | 11份真实主/额外/副卡与目标，逐期归属；空收件模板不造牌表 |
| 历史和官方资料 | 三期明确发行截止、逐卡OCG发行证据、官方完整累计禁表/旧文本/裁定及使用权；当前固定社区禁表含2022.7/2022.10/2026.10，但不等于官方全表核对 |
| 原始资料访问 | 云端shell对官方日文OCG禁表HTML的HTTPS GET实际被代理403拒绝，下载已停止，未改工具绕过。网页已读的日期不扩大为全表认证；正常native没有这个拦截 |
| 合格对手/外部模型 | 已有规则baseline可执行，强度未资格化；真实provider配置、获准费用/额度、8套由DeepSeek驱动的实联尚缺。厂商无关stdio已实测，不把fixture称接通 |
| 腾讯云硬件 | 现有获准实例、CUDA/驱动/依赖锁、实机吞吐/显存/数值/恢复及计费停机确认；当前仅CPU环境，未采购或启动GPU |
| PC门槛 | 既定目标YGOPro/萌卡分支动作/连锁/标准回放对照需目标客户端；内部JSON精确重放不能代替 |
| 正式学习与统计 | 模型规模/课程配比/阈值经实际2A小试冻结、分类校准及独立能力/BO3/LoRA迁移验收；工程参数更新、几局胜负不是能力证明 |

官方日期核验只包括：[2022年7月公告](https://yu-gi-oh.jp/news/oid-1313/)明确2022-07-01生效、[2022年10月公告](https://yu-gi-oh.jp/news/oid-1388/)明确2022-10-01生效、[官方日文OCG页面](https://www.db.yugioh-card.com/yugiohdb/forbidden_limited.action?request_locale=ja)显示2026/10/01。两份历史公告是变更公告，不是完整累计列表。逐项状态在[机器可读来源记录](../../configs/official-source-evidence-v1.json)。

因此不能宣称“只剩用户卡组即可正式付费开训”。已完成的是可复验的云端工程准备；G-01/G-02/P-01/B-02整体门槛保持未通过。后续Agent从[训练交接](../development/training-handoff.md)、[分期宿主](../development/period-runtime.md)、[部署说明](../development/deployment-preparation.md)与总清单接手，保留全部绑定，不通过改环境名/null截止/删除receipt消除缺项。

当前工具没有即时额度读取能力；不沿用旧73%为当前值，交父任务核实。达到20%保存停止，不使用重置卡。

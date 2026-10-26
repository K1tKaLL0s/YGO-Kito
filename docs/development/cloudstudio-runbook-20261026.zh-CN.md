> 历史运行记录：2026-10-26 上午 A10 主机；后续已由用户切到 CPU 4核8G。当前交接状态见 [项目入口](../../CLOUDSTUDIO_GUIDE.zh-CN.md)。

# YGO-Kito：CloudStudio 操作与训练交接

最近核查：2026-10-26 UTC；北京时间加8小时。工作区：https://cloudstudio.net/a/39250693079592960/edit 。

## 0. 2026-10-26 当前状态

详细实测与实际接续：[CPU/GPU对照](../../GPU_COMPARE_20261026.zh-CN.md)。当前工作树/workspace/.cache/codex-gpu-20261026，HEAD 6cef642cc840120fc6d445cfbf7b8bc082b61f0d。A10/20核配额/116GiB配额；独立CUDA环境/workspace/.cache/cuda291-venv，Torch2.9.1+cu128，原.venv保留。

16/16真实机器人小局完成，CPU/GPU均值67.312/66.986秒；四角色整轮1.851/2.466秒。当前串行流程选CPU，GPU批量推理有优势，混合调度待接线与复测。正式训练量0。

完整工程四模型起点现已存在并核验：/workspace/.cache/training-prep-20261026/state/runs/four-model-source-20261026b/checkpoints/local-step-7.weights，四角色各1次base＋1次LoRA更新，尚无正式能力成绩。明确引用见.cache/gpu-compare-20261026/source-group-reference.json。实际分期manifest、允许池、课程配置及独立对手分区仍待补齐；现存course-host.partial.json预检blocked。先读新报告的准确路径与命令，再继续。

## 1. 2026-10-25 历史代码和环境

- 原项目：/workspace，main，7e92994d28b8f075092fc68f30848dd6e4855ca2。已有未提交 bot 资格报告保留在 docs/reports/2026-10-25-bot-deployment-normal-duel-qualification.md。
- 本轮测试代码：/workspace/.cache/codex-pr4-final，独立 Git 工作树，6cef642cc840120fc6d445cfbf7b8bc082b61f0d（PR #4，含正式消息字段修复）。main 保持原提交。
- 2026-10-25历史环境：AMD EPYC 9K84；容器配额4核、8 GiB；Python 3.12.3；Torch 2.9.1+cpu；NumPy 2.3.5；SciPy 1.16.3；Mono 6.8；mcs；.NET；G++ 13.3；MSBuild /workspace/.cache/toolchain/msbuild，17.2.0.20702。
- 复用 /workspace/.venv/bin/python。当时机型为CPU，短测Torch单线程。引擎和bot安装在 /workspace/.cache；本轮工件在 /workspace/.cache/codex-20261025。

每次先核实际状态，再执行新任务：

    cd /workspace/.cache/codex-pr4-final
    git status --short --branch
    git rev-parse HEAD
    export PYTHONPATH=$PWD/src
    export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
    /workspace/.venv/bin/python -m ygo_kito status

保留已有改动、权重、数据与他人进程；更新代码使用新工作树。恢复旧检查点须保留对应源码和资源版本。

## 2. 项目和四模型如何工作

目标是训练可迁移的游戏王决斗、构筑模型组。规则引擎负责合法动作和真实胜负；模型使用正常玩家可见信息。

1. 构筑目标模型：自然语言目标进入轻量分类器，先形成无具体卡ID的标签逻辑图；狭义主题筛主轴，广义主题直接填卡；候选由程序枚举，模型评分，读取卡文，调用当前支持的规则目标核验接口；任意逻辑图到完整合法CB的自动核验仍待实现。
2. 构筑优化模型：在保留原目标和硬约束的条件下，修改单卡、小轴与数量，改善启动、废件、抗打断、续航和环境表现；与目标模型交替循环。
3. 决斗模型：独立小Transformer读取己方合法观察、公开历史和当前合法候选，输出动作策略及价值；引擎核对选项后执行。PPO只消费当前策略新采样的本席位轨迹。
4. 统筹模型：轻量网络建议阶段和预算；确定性程序管理状态、权限、日志、预测胜率、托付和恢复。实时对局由决斗模型直接接引擎。

数据流：目标→逻辑图→候选卡与卡文绑定→规则核验→构筑版本→冻结决斗策略评估→实战反馈→构筑修订或决斗训练。训练、验证、独立终验、计时预跑分区；隐藏卡和牌序保留在控制器，进入模型的是合法DTO。

## 3. 卡库、牌表、权重起点

- 原生核心：3209cd866a55e8501a0ed358d3064d9ae0ae6b30；脚本：b83db1cc3f512d3bec2faafb9ecf199143332be1。
- 卡库：/workspace/.cache/engine-src/database/locales/zh-CN/cards.cdb；SHA256 ff52f585de24a762a4e613ac37654b1a7fb15a58990c14f5eada85f28c3be152。完整构建与资源摘要：/workspace/.cache/engine-build/receipt.json。
- 用户牌表：测试代码 configs/user-deck-intake-received-v1.json，三主＋六对手；来源和授权修订见 user-deck-received-provenance-v1.json、user-deck-references/。对手为神碑、随风、雷精、升月、巳剑修订版、狱神奥艺；原始版和修订版分开保存。
- 两历史主表和六对手已通过提交中所列静态卡号、数量及社区禁表检查。第三主参考表在当前卡库缺100268022、101307067；2610自主主题可使用其他已核可用卡。第7、8对手槽仍空。
- 本CloudStudio工作区开始时未找到已有 .weights 训练工件。本轮决斗模型由随机种子123起步，用普通40张工程牌组完成2次PPO更新，另做一次恢复对照，恢复结果一致。训练种子1724、24；策略种子456；batch种子789。
- 决斗测试检查点：.cache/codex-20261025/agent/runs/smoke-normal123/checkpoints/step-2.weights（相对 /workspace）；模型SHA256 202430015c848dcbf0de4b04dd4131d58401a72e8cc901591fe63ab275e6aa8b。后续计时全部冻结此模型，更新数0。
- 构筑目标、优化和统筹在本机尚无正式训练检查点；新建运行默认独立随机初始化。尚未训练的模型角色和工程两步决斗权重须分别记录。跨时期使用完整四角色检查点显式继承effective/base权重，目标期重新建立优化器、RNG、数据游标；方法见 docs/development/group-initialization.md。

## 4. 各阶段规则和通过条件

| 阶段 | 训练内容 | 通过与推进 |
|---|---|---|
| 2A启动与吞吐 | 核卡库/脚本/协议、版本和设备；小规模模型＋引擎对局；核保存恢复 | 按目标硬件实测时长、数值、资源和完整终局；先修失败，再冻结正式配方 |
| 2207 | 珠泪主训练；卡池截止2022-09-30；先同期外战、再递增强参考珠泪内战 | 含换备BO3外战≥60%，强参考内战接近50%；独立≥200外战＋200内战BO3，报告95%区间和分项 |
| 2210 | 珠泪主训练；卡池截止2022-12-31；对手递进比例先冻结 | 原BO3目标和独立样本要求同上 |
| 2610第一段 | 继承前期模型，自主主题→构筑与CB推理→实际可用bot的BO1 | 完成第一段课程并保留构筑、模型和对手版本，再进入第二段 |
| 2610第二段 | 对2610常见卡组完成真实BO3 | 冻结评测的实际小局先手胜率严格>49%、后手严格>39%，两项同时；平局计入完整小局分母，不计胜 |
| 2C迁移/终验 | 陌生卡组LoRA，比较未适配基线与旧环境退化 | 冻结模型、对手、种子和分区；记录胜率、资源、恢复与未达项 |

2610禁表为2026.10，完整卡池截止2026-11-01日本当地当日正式OCG发售；截至本次核查仅已选择截止日，最终池需到日后按真实发行来源冻结。当前开发可用已发行、时期合法且本机卡库/脚本可用的交集，未知逐卡排除。

所有环境分别计完整大场：均值≤60秒时至少1000 BO1＋100 BO3；均值>60秒时至少1000大场且BO1:BO3=6:4（最小600＋400）。计时预跑和独立评测均单列。BO3需要局间换备、输者选先后及先赢两局的大场终局，记录局数、每小局实际先后手、异常和耗时分布。

总正式训练预算≤100小时，原分配5/25/25/20/10/15小时覆盖启动、2207、2210、2610、迁移终验和故障预留。先实测再调整分配；保留失败耗时。原“接近50%”容差和区间判定、2210对手递进比例、2610独立评测分组在正式验收前冻结。

## 5. 启动命令和当前缺项

安全代码回归（已在06674eb运行546项，失败/错误/跳过均0）：

    OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 /workspace/.venv/bin/python scripts/check_merge_candidate.py --output /workspace/.cache/新的回归目录

普通两步CPU更新及恢复对照（使用新run-id，输出不覆盖）：

    /workspace/.venv/bin/python -m ygo_kito duel-train-cpu --root /workspace/.cache --state-root /workspace/.cache/新短测状态 --run-id smoke-new-001 --profile /workspace/.cache/codex-20261025/actor.json --training-config configs/cpu-training-smoke.json

冻结模型＋WindBot计时，先读实际配置和预检：

    /workspace/.venv/bin/python scripts/training_pilot.py --workspace /workspace --native-root /workspace/.cache --config /workspace/.cache/codex-20261025/pilot-spec.json --output /workspace/.cache/新预检.json

预检ready后，加 --run 并使用新输出文件，外层使用timeout限制整进程。配置显式绑定检查点、完整C#审计、实际正常终局资格、牌表、席位和隔离种子。换源码后重做资格，不改旧摘要。

三期正式启动前逐期填写真实发行清单、禁表、卡库资源、主牌表、实际对手和train/validation/final_eval分区；period-host-template-v1.json以selected-period可先启动资料齐的单期。完整group配方填写period_inputs、task、模型配置、预算和设备，保存到新路径。

9db417d已提供自主构筑、合法换备BO3、输者选先后、逐小局LoRA、完整大场计数、恢复及冻结评估的课程入口。腾讯工作区加本地消息字段修复后614项CPU回归通过，零跳过。2026-10-25当时缺项：source_group完整四模型源检查点、bootstrap_task、已核分期active_environment与发行清单、available_cards、独立bot分区及course完整配置。现有两步standalone决斗检查点只含决斗角色；四模型源工件需要先通过已有四模型短训练/恢复流程生成，或导入原版本可追溯的完整工件。

本轮已生成 /workspace/.cache/codex-20261025-9db417d/course-host-template.json；同目录course-host-cloudstudio.partial.json已填写真实native_root，其余真实工件按下列缺项补齐，预检结果在同目录course-preflight.json。按 docs/development/scenario-course-runner.md 填写全部真实引用后保存为 /workspace/.cache/actual-course-host.json，依次执行：

    /workspace/.venv/bin/python scripts/scenario_course.py --workspace /workspace --config /workspace/.cache/actual-course-host.json --output /workspace/.cache/course-ready-001.json
    /workspace/.venv/bin/python scripts/scenario_course.py --workspace /workspace --config /workspace/.cache/actual-course-host.json --output /workspace/.cache/course-group-pilot-001.json --pilot

完整预跑成功后，将其真实SHA与小局均值填回宿主配置；2207/2210分别使用历史参考模式，2610自主模式先BO1再BO3。各分期、阶段/分区、设备与种子按课程配置冻结。用户授权正式训练后，现有命令每次可限1大场启动：

    /workspace/.venv/bin/python scripts/scenario_course.py --workspace /workspace --config /workspace/.cache/actual-course-host.json --output /workspace/.cache/course-invocation-001.json --run --purpose train --max-matches 1

恢复现有课程在宿主配置明确resume:true，并保留完整checkpoint与DataIndex；有in-flight或未裁决异常先检查状态。新课程的四模型/LoRA预跑使用独立状态目录。

现有四模型训练器入口（配方全部核好后）：

    /workspace/.venv/bin/python -m ygo_kito agent-serve --role trainer --root /workspace/.cache --state-root /workspace/.cache/训练状态 --local-cpu-control --local-training-config /workspace/.cache/已核完整配方.json

经UTF-8 JSON Lines先调用capabilities，再training.prepare，读取runs.read的当前revision，最后training.control/start。现有group-runner-v1.json是工程课程；各期正式内容须按上一段接入。CUDA目标机另冻结相应依赖和驱动，在完整配方中明确device=cuda:0、dtype=float32、allocated_gpu_count；当前CPU机使用CPU配方。

## 6. 暂停、恢复、更新、失败处理

- 先runs.read取得当前revision；training.control支持pause、save_checkpoint、resume、stop。暂停/保存等到完整对局和已提交阶段边界。
- failed先training.recover，核验后paused再resume。uncertain先查状态和工件，原control重试保留同一id和参数。
- 保存整个state-root中的SQL、四角色权重、LoRA、优化器、调度器、RNG、阶段/数据游标、sidecar和累计预算。完整原生半局从上一提交边界重做。
- 更新源码/卡库/脚本/牌表先新建工作树、复跑相关检查并重新绑定。旧检查点在原版本恢复；跨期模型迁移使用显式initialize_from。
- 对局异常保留原报告、种子、阶段及日志；先定位并修复，再开有新ID的新验证窗口。正式样本与失败数量完整记账。

## 7. 本轮实测与文件位置

第一轮结果位于 /workspace/.cache/codex-20261025；总览session-summary.json，文档差异documentation.patch。19:30 UTC核查自建测试进程为0。

| 文件 | 结果 |
|---|---|
| regression-06674eb/results.json、regression.log | CPU白名单546项通过、零跳过；运行38.42秒；完整模块结果在同目录tests.log |
| agent/runs/smoke-normal123/proof.json | 2次规范PPO更新，3次物理optimizer调用（含恢复对照）；恢复一致 |
| qualification-seat0.json、qualification-seat1.json | Ice Blackwing/Burn各两个席位，4局真实终局；时长31.13、98.05、41.63、43.44秒；策略为原普通规则代理 |
| pilot-spec.json、pilot-preflight.json | 冻结模型、4组合、12小局计划；预检ready |
| pilot-result.json、pilot.log | 模型对Burn首局33.70秒后失败，174决策窗口；0完成、11未尝试；错误loopback decision transport failed |
| diagnostic*.log、diagnostic-result*.json | 保留异常重现；精确根因：windbot_room.py:464将位置变化消息的整数previous转tuple；完整栈在diagnostic-3.log，隔离候选已修复，协议回归35项通过；真实模型对bot复验待进行 |
| rule-timing-result.json、rule-timing.log | 同一冻结模型对公开规则策略，两个实际席位各6局，12局全完成；小局均值1.222秒、p50=1.048、p95=2.008、最大2.889；1426次模型前向平均2.257ms |

规则基线牌组为40张普通工程怪兽；WindBot资格与模型对战使用bot原配牌组。三期珠泪、2610自主构筑、BO3及GPU尚无本机计时结果；正式配方补齐后各自重测。正式训练局数仍为0。

## 8. 给CodeBuddy的极短例句

- “按项目说明准备四模型课程，先补齐工件并预跑。”
- “准备2207训练，列出实际缺项，先跑小规模计时。”
- “查看最近训练结果，保存并暂停。”
- “从最近完整检查点恢复，沿用原预算和数据分区。”
- “接续2610自主主题训练，先核BO1完成条件再进入BO3。”

详细协议与配方格式见所选工作树 docs/development/training-handoff.md、period-runtime.md、group-initialization.md；原设计规则见 docs/plans/2026-10-22-unified-development-spec.md 第7、12、18节。

## 9. 最终交付与真实复验

后续工作目录：/workspace/.cache/codex-pr4-final，提交6cef642cc840120fc6d445cfbf7b8bc082b61f0d。原main仍为7e92994，已有修改与所有历史工件保留。消息53标量位置修复已进入最终提交；本地原始差异仍留在 /workspace/.cache/codex-20261025-fixed/windbot-position-scalar.patch。

真实四小局在9db417d＋本地同语义修复上运行；Burn、Blackwing各两个实际席位。4/4完成，失败0；时长64.814、38.885、43.209、50.915秒，均值49.456、p50=47.062、p95=62.729、最大64.814秒；完整attempt墙钟均值50.087秒。457次模型前向均值2.875ms。使用原两步CPU工程决斗检查点，冻结且模型摘要不变，正式量计数0。该CPU/standalone工程窗口均值≤60秒；正式四模型/LoRA、三期实际牌组、BO3及目标设备分别执行课程计时。

结果：/workspace/.cache/codex-20261025-9db417d/pilot-result.json；新源码的4局资格证据在同目录qualification-seat0.json、qualification-seat1.json。原失败报告保留在 /workspace/.cache/codex-20261025/pilot-result.json。最终6cef642的完整Python源码身份有变化，正式课程准入前为该提交重新生成bot资格和四模型课程计时引用。

2026-10-25收尾时source_group缺完整四模型源检查点，当时course-partial-preflight.json明确返回source group checkpoint path must be a nonempty string。已填实际native_root的宿主草稿为 /workspace/.cache/codex-20261025-9db417d/course-host-cloudstudio.partial.json。其余缺项按第5节及scenario-course-runner.md补齐。

生成工程四模型起点可使用仓库现存配方，启动控制入口后按JSON协议prepare、read、start，在完整组边界保存工件；记录初始化为随机、实际更新数及数据用途：

    /workspace/.venv/bin/python -m ygo_kito agent-serve --role trainer --root /workspace/.cache --state-root /workspace/.cache/group-bootstrap --local-cpu-control --local-training-config configs/group-runner-v1.json

实际请求形状：

    {"schema_version":1,"id":"prepare-bootstrap-1","method":"training.prepare","params":{"run_id":"group-bootstrap-001"}}
    {"schema_version":1,"id":"read-bootstrap-1","method":"runs.read","params":{"run_id":"group-bootstrap-001"}}

读取当前revision后，再以training.control/start及该revision执行；同run完整恢复沿用原binding。完成组工件后按group-initialization.md明确effective/base、文件SHA和source_binding_sha256，填写source_group；两步standalone决斗权重仍单独保留。

最终本地CPU回归：617项；success=True，失败=0，错误=0，跳过=0。回执在/workspace/.cache/codex-20261025-final/regression/results.json。
自建测试停止核查时间：2026-10-25T19:48:00.400494+00:00；活跃匹配进程数=0。

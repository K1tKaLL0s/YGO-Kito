# YGO-Kito：CloudStudio CPU 接手入口

用户已决定回 CloudStudio，可使用已授权的 CodeBuddy／DeepSeek 或其他具备文件读取和本地命令执行能力的编程 Agent 推进。先读本文件、[AGENTS.md](AGENTS.md)及[总清单](docs/plans/MASTER-CHECKLIST.md)；本地训练链不以外部模型 SDK 为依赖。用户用自然语言指挥编程 Agent，与项目调用外部模型充当对手是两件事；后者的 provider 接通状态须另验。文件存在不证明 CodeBuddy 自动读取，用户应明确要求读取本文件。

## 当前代码与环境

本次代码审查基准是 PR #6 的 `da7d4d8657b7ec2fba1d0d9cbf9c8458ec45fad0`。2026-10-26 已核实 PR #4／#5／#6 全部合入 main `9c914b3ac37ab8baf8bfb83f953f6697cd1c7ddc`，且该 main 的 [CPU CI 成功](https://github.com/K1tKaLL0s/YGO-Kito/actions/runs/40366489841)。接手时在完整源码根执行以下只读命令，确认更新后的 HEAD 包含此 main，保留用户改动、权重、缓存和已有进程，不重复合并：

```bash
git status --short --branch
git rev-parse HEAD
git merge-base --is-ancestor 9c914b3ac37ab8baf8bfb83f953f6697cd1c7ddc HEAD
/workspace/.venv/bin/python -c 'import sys, torch; print(sys.executable, torch.__version__, torch.version.cuda, torch.cuda.is_available())'
PYTHONPATH=src /workspace/.venv/bin/python scripts/takeover_readiness.py
```

`/workspace` 是原 CloudStudio 完整项目根，CPU 解释器原为 `/workspace/.venv/bin/python`；独立工作树也使用经核验的该解释器，工作目录改到实际完整源码根。路径失效先报告，不静默使用 CUDA 环境或安装依赖。Codex 容器缺 Mono／附件导入失败不能外推为 CloudStudio 也缺；在 CloudStudio 重新核实本机文件、Mono、完整 WindBot 构建和资格报告。

da7d4d8 的本地及同提交远端安全 CPU CI 均为 **727/727，零失败／错误／跳过**；[CI 回执](https://github.com/K1tKaLL0s/YGO-Kito/actions/runs/40342173187/job/121639500014)不证明真实模型终局、C# 联调或训练能力。本次没有启动正式训练。

## 起点、资产与实际配方

- 四模型源：`/workspace/.cache/training-prep-20261026/state/runs/four-model-source-20261026b/checkpoints/local-step-7.weights`，4,147,863 字节，SHA256 `fcb4a3b970e8b834be69c0d0ee3ff26a53eb1e067b946f5cb11a63e82cea4f87`。四角色各 base1＋LoRA1，正式更新0，不称竞技模型。来源声明为 [source-group-reference.json](docs/reports/cloudstudio-20261026/source-group-reference.json)，含完整 source binding 和 `weights:effective`。
- 路径是原 CloudStudio 记录，必须现场验证字节／SHA；Git 清单不是权重。对照[迁移清单](docs/reports/cloudstudio-20261026/migration-assets.json)与[资源要求](docs/reports/2026-10-26-cpu-transfer-inputs.json)核 core、CDB、Lua、逐期发行／禁限、完整 bot、牌表及资格；已有同哈希资源可复用，无需先迁往 Codex。
- [已收牌表](docs/development/user-deck-dataset.md)含三主及六对手，另两槽、实际驱动与覆盖仍须核清。巳剑只用授权修订版，原版隔离；原件和旅鸟补版保留。2610 用户珠泪仅可选参考，缺卡逐张排除，不因此禁用其他主题。
- `configs/training-scenarios-v1.json` 是准备声明，`configs/cpu.toml` 的 engine 未配置，均不是可直接训练的课程。按 [runner 文档](docs/development/scenario-course-runner.md)填每环境独立 host／course、真实工件摘要、完整种子、LoRA 容量及 train／validation／final_eval 对手分区；实际 host 文件尚未在 Git 交付。正式慢档至少预留1800小局的训练种子及决斗 LoRA 更新容量，不能照用工程 `max_updates=2`。

四角色仍为目标构筑、优化、决斗、统筹，不新增大模型。构筑先无卡 ID 粗图→仅狭义主题筛主轴→具体卡文填卡和合法 CB 核验；低置信拒判、目标保持、反馈调整／重构、有效 LoRA 和数据隔离沿用[现有设计](docs/development/construction-logic.md)。不硬编码训练主题，不把程序候选写成模型能力。

## 三环境规则

| 环境 | 主题／发行设计截止 | 独立验收 |
| --- | --- | --- |
| 2207 | 珠泪；2022-09-30 | 含换备 BO3 外战≥60%，冻结强参考珠泪内战接近50%；本期独立至少200外战＋200内战 BO3，报告95%区间及先后手／对手分项 |
| 2210 | 珠泪；2022-12-31 | 与2207相同规则，单独训练与评估，不合并分母 |
| 2610 | 模型自主选主题／构筑／CB；设计截止2026-11-01，日本当地含当日 | 先合格现成人机 BO1，完成后才当期合法常见卡组 BO3；第二阶段冻结评测按实际小局实际先后手，先手胜率严格>49%且后手严格>39%，两项同时满足 |

来源为[统一设计§12.1](docs/plans/2026-10-22-unified-development-spec.md)及 `configs/training-scenarios-v1.json`。49%／39%不套给2207／2210；2610不以先手开局的大场胜率替代小局分组。平局不算胜利，异常／超时保留，不剔除美化分母。历史“接近50%”容差、置信区间通过规则、重复观察、BO3 draw 裁决，以及旧200外＋200内向2610自主主题的映射仍未冻结，保留 pending，不能自行宣告达标。

三个环境共同沿用已确认慢档：**每环境至少600完整 BO1＋400完整 BO3大场**，不跨环境抵扣；`pilot_mean_seconds:null`，`timing_pilot:null`，将 `configs/cpu-takeover-slow-basis-v1.json` 完整对象放入 course 的 `timing_basis`。不重新测时，不填假均值。BO3含合法换备、输者选下局先后、先得两胜；预跑、独立冻结评测和新增自对抗不抵正式最低场数。

2610禁表仍为2026-10-01生效表。11月1日前仅允许已实际正式 OCG 发售、对应期合法且卡库／脚本可用的集合；未来公开卡文只 staging，不能提前放行或宣称最终池完整冻结。萌卡仅取热门主题和实际统计日期，不取构筑或把陈旧数据当当日环境。

## 先诊断未终局，再开展训练

三次新增真实双模型检查均 **0终局／0更新／0正式场**：两次1501决策窗口达到原1500上限，一次1046窗口 token>256。审计见[失败证据](docs/reports/2026-10-26-cpu-takeover-audit.json)及[诊断边界](docs/development/cpu-takeover-and-selfplay.md)。原始私有轨迹未入 Git，不能声称 CloudStudio 已有或已读。重复 MSG16 pass 不证明取消循环或回合卡住；旧记录缺 turn／phase／LP／牌库余量，根因尚未闭合。

先审查现有证据，用已补公共进度／token 分项诊断定位并修复实际问题；不盲目重跑相同窗口、增加上限、用规则策略替模型或把超时当平局。`history_events:32→8` 保持 NN 张量但改变输入，旧四模型初始化拒绝静默配置迁移。之后单列正常真实终局、模型 BO3 换备及小规模更新／保存恢复的功能证据，不重新测时、不计正式训练量。单测和旧 bot 终局不能代替这些结果。

`scripts/model_match.py --spec <真实快照spec> [--output <新报告>]` 默认只预检；显式 `--run` 是冻结推理功能检查，其换备仅 `keep_side_baseline`，不能充当模型换备训练通过。`SelfPlaySeries` 是两组真实模型的宿主 API，双方用优化模型换备、轮换学习席位并保留初始／历史冻结池，默认训练关闭；新增配比／场数／预算与独立验收尚未分配。先保留辅助阶段，不替代2610常见卡组、第一阶段机器人或冻结终验，不以自打50%证明能力。

## 课程入口、暂停和恢复

以下从完整源码根、使用核验过的 CPU 解释器执行；配置／报告路径必须是新建且真实的，不把示例文件名当已存在：

```bash
PYTHONPATH=src /workspace/.venv/bin/python scripts/scenario_course.py --help
PYTHONPATH=src /workspace/.venv/bin/python scripts/scenario_course.py --template --output .cache/course-host-template.next.json
```

填齐模板后默认 `--config <host文件> --output <新报告>` 只预检；只有启动清单核准、收到本次明确开始指令后才用 `--run --purpose train --max-matches 1` 有界推进。后续 validation／final_eval显式分区、冻结模型／牌表／对手／种子，禁止拿评测数据更新；一次命令返回不等于全课程完成。

- 新课程从上述完整 `.weights` **effective 初始化**只继承参数，重建优化器、RNG、索引和台账；不是旧任务 resume。真正恢复旧 group 需整个原 `state/`、登记、账本、索引及精确原源码／配方／资源，见[初始化说明](docs/development/group-initialization.md)。
- 当前新课程暂停：向实际 host 的 `state_root/course/pause.request` 写停止请求，在小局提交边界保存，等待进程退出并核报告；不得中途杀进程假称已保存。恢复保留完整 state_root、最新 checkpoint 与 DataIndex，核同源码／工件绑定后明确 `resume:true`；确认没有 worker 后只移除自己建立的 `pause.request`，在新报告路径续接。
- `in-flight.json`／`feedback-in-flight.json`、未裁决异常或 checkpoint／DB不一致先检查，不能删标记、清索引或自动重打。旧 `training.control`／`training.recover` 服务控制另一条 local-training/group 链，不直接控制 `scenario_course.py`。

## 空间、预算与停止

绑定真实 state／temp／外部环境用量和 `storage_envelope`，整个 CPU 环境、资产、检查点、轨迹／索引、日志与临时峰值严格 **<30,000,000,000字节（约27.94GiB）**。`configs/cpu-storage-plan-v1.json` 的25.63GB只是条件预算，不能直接作为 envelope 配置或全程容量认证。逐期绑定主DB／工件限额和 checkpoint 保留策略，保护initial／latest／milestone；默认不删用户数据，SQLite journal、未包裹日志和其他写入另计，容量不足在新局前保存停止。

原100小时上限及5／25／25／20／10／15分配不悄悄扩大；原计划是 GPU-instance-hours，CPU墙钟、核时、并发和累计预算需在启动清单分开，不假定4核线性加速或降低场数。启动清单给出 HEAD、CPU与资产摘要、三环境配置、合格对手、真实功能／恢复结果、场数、实际预算计量、空间及暂停恢复命令；先通知用户，收到开始指令再正式训练。

本轮 Codex 文档审查不代调用 CodeBuddy／DeepSeek 或外部付费 API，不新增付费服务；这是本轮执行范围，不是永久禁止用户使用这些工具接手。用户可在已授权的 CodeBuddy／DeepSeek 中继续指挥本地开发和训练准备。若另需项目级 provider 调用、对手驱动或新增费用，核对相应授权、配置与边界，不默认已经接通或免费。

Codex额度只用当时实读值，剩余≤20%保存停止，确认重置到账才恢复，不用重置卡；转到 CodeBuddy 后需另核其实际额度／费用规则，不能沿用 Codex 历史读数。记录运行ID、PID、日志、最新检查点和累计用量；退出训练不等于云实例停计费。遇权限／访问拒绝停止具体动作，不换工具绕过。

最短接手请求：“读取 CODEBUDDY.md，在当前 CloudStudio 的 CPU 环境继续：先诊断双模型未终局，补齐三环境配置和恢复验证，再按既定规则推进；正式训练前给我启动清单。”


## 2026-10-27 本机接续（后续明确授权优先）

用户现已授权迁移到本机 N:\YGO-Kito、安装必要项目隔离依赖、持续真实训练，并将 CloudStudio
增量与恢复资产保存为独立草稿 PR。当前权威设计见
[设计复核](docs/plans/2026-10-27-training-design-reconciled.md)、
[基准源码差异复核](docs/reports/2026-10-27-training-design-code-gaps.md)；
实际本机入口与恢复源见[本机接续](docs/development/local-cpu-continuation.md)。
旧文中的正式训练审批、固定 learner 参考表或 LoRA-only 解释不能覆盖后续用户纠正。
不新增预检/功能场/资格套餐或重新测时；运行具体出错后针对修复。
原始导出 base 更新为 goal=1、duel=1、optimizer=0、coordinator=0，正式 BO1/BO3=0；
四段推理已发生，优化质量训练、效果积木、珠泪融合 CB 与统筹学习尚未完成。
参考只作独立评价；合法动作、隐藏信息隔离、预算、原状态与完整边界保存仍执行。

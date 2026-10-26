# 显式工件课程入口

2026-10-26 CPU 接管按[当前说明](cpu-takeover-and-selfplay.md)执行：用户取消重新测时，明确沿用慢档。课程可设置 `pilot_mean_seconds:null` 并填写 `configs/cpu-takeover-slow-basis-v1.json` 的完整 `timing_basis`；此时 `timing_pilot:null` 合法且不调用计时预跑，仍严格检查每环境600完整BO1＋400完整BO3、1800小局的种子／LoRA容量及其他资产。当前 CPU 精确速度保持未知。下文真实计时协议保留供其他显式选择该方式的宿主使用，不是本次新增门槛。

`scripts/scenario_course.py`接宿主工件、实际`CourseModels`、分期资产、构筑kernel、BO1／BO3状态机和真实game adapter。默认只预检；模板中的null必须由真实工件填充，不会初始化随机替代模型、安装工具、下载数据或自动开始训练。`--pilot`和`--run`均须显式选择，彼此互斥。

```bash
PYTHONPATH=src .venv/bin/python scripts/scenario_course.py --template \
  --output .cache/course-host-template.json
PYTHONPATH=src .venv/bin/python scripts/scenario_course.py \
  --config .cache/course-host-template.json --output .cache/course-preflight.json
```

模板保留2610设计截止2026-11-01。`active_environment`引用实际已核的时期卡库、发行清单、禁表和选定禁限节；当前可用子集截止须已经到达日本当地日期，且不超过设计截止。它没有旧main-slot要求，也不把当前子集叫作未来最终卡池。2207／2210仍用各自确认的完整设计截止和参考主题。

工件引用均为workspace内文件路径及SHA256，另有Mono的明确绝对可执行路径。必须提供：

- `source_group`：原项目完成边界的四模型group工件，明确base或effective选择和原binding摘要；这是新课程的权重初始化，不是绕过旧源码绑定恢复训练。
- `bootstrap_task`：与实际分期资产匹配的语义`BuildTask`；`duel_config`必须显式列全训练game seeds；`adapter_configs`沿用四role配置文件的`adapters`数组，不得丢LoRA。正式快档最坏需1300小局、慢档1800小局的种子与duel LoRA更新容量；旧工程配置的max_updates=2不够，正式预检提前拒绝，不等第3局再失败。单独pilot不要求这份正式容量。
- `available_cards`：`{"schema_version":1,"card_ids":[实际候选ID]}`。宿主逐卡核时期允许池、卡库、禁限和实际脚本；只有纯通常怪兽可明确不需脚本，缺失项逐张排除，不能把整个其他主题禁用。
- 每个bot的固定源lock／完整安装树、实际构造审计、同Executor与原牌表的真实正常对局资格报告及profile、明确YDK或DeckParts JSON、stage／partition／先后手基线／实际覆盖说明。仅源码存在、registry或fixture不是运行资格。验证／终验须增加明确独立条目，不能用别名跨split复用同实际对手。
- `timing_pilot`：在选择实际测量分支时，引用 `course-group-bo1-timing-pilot-v1` 完整声明窗口，同四模型、实际LoRA、设备／词表／配置、分期／资源／完整源码及真实bot case绑定。缺失或不匹配会blocked，不能任填均值；本次明确慢档 `timing_basis` 免除此项测量，不免除其余门禁。
- `course`：root课程配置文件，包括course_id、period_id、mode、实际pilot均值、完整training_seeds、独立validation／final_eval seed-pairs、每次match数量、wall上限、实际GPU数、历史固定牌表或自主模式null、交替首局先后、预声明独立评测场数及明确对手不换备基线。device显式`cpu`或`cuda:0..7`，CPU的allocated_gpu_count=0、GPU为1..8；wall×max(1,GPU数)不得超过2610的20h或历史每期25h分配，原100 GPU小时不变。没有租用算力或设备fallback。

未选择已确认慢档 `timing_basis` 时，`timing_pilot:null` 及 `pilot_mean_seconds:null` 表示待测，正式运行拒绝。`pilot_pairs`列测量窗口的私有game／policy seed对，须与训练、validation及final_eval全部分开；约12局只是建议。本次不执行下列测时命令；其他单独获准的测量可使用：

```bash
PYTHONPATH=src .venv/bin/python scripts/scenario_course.py \
  --config .cache/actual-course-host.json --output .cache/course-group-pilot.json --pilot
```

它初始化同一实际四模型和LoRA，使用另一个全新私有状态／DataIndex，不能resume正式课程或给训练量记账。报告真实完成后，填入报告ref／SHA和观测均值再做默认preflight。计时ref、均值配置和resume开关不进入模型初始化身份，避免“为了填入报告而改变被测模型”的循环；报告自身仍核完整源码、模型执行及真实对手。恢复已训练课程时按checkpoint保留的初始执行身份核原计时报告，不错误要求更新后的权重等于初始权重。

所有case预检真实通过且主机已有执行授权后，才显式运行：

```bash
PYTHONPATH=src .venv/bin/python scripts/scenario_course.py \
  --config .cache/actual-course-host.json --output .cache/course-invocation-001.json \
  --run --purpose train --max-matches 1
```

输出独占创建，旧报告不覆盖；dispatch后未知执行保留partial／unknown。私有DataIndex、完整match状态及模型checkpoint保存在显式`.cache`状态目录，不上传私密轨迹。重新进入已有课程必须明确`resume:true`，由精确工件／模型／源码binding、自包含模型checkpoint和现存DataIndex恢复，旧初始化source文件可已删除而原spec／provenance仍保留；有in-flight或未裁决异常不得自动重跑。默认resume预检只读已有索引，不创建训练状态。一次调用结束不等于完整训练量或正式验收达标，所有公开结果仍保持`formal_training_success_verified:false`。

第二阶段对手可显式选 `driver:local_model_snapshot`，提供固定有效推理快照、`same-period-inference`／`explicit-inference-migration`、合法牌表及精确 `common_deck_evidence`。模型词表须覆盖实际分期资产；sample 模式另给宿主私有 `opponent_policy_seed`，其状态不进入模型特征。快照／种子和同一BO3绑定；历史快照、模式或标签不能伪造独立评估对手。此驱动只适用于 `common-decks-bo3`，不会以任意自弈替换第一阶段现成机器人；明确审阅来源也不认证策略强度。

BO3 draw裁决、历史“接近50%”容差、区间方法和重复观察规则未冻结时保留pending。2610严格>49%／>39%只属于第二阶段冻结实际小局先后手统计；stage1、pilot和训练结果不抵独立评测。继承工程更新不证明竞技能力。当前 Codex 容器缺真实C#运行资产，模板预检应blocked；新增普通核心功能结果另列，不能据CPU机制测试宣称完整课程、速度、能力或100h够用。

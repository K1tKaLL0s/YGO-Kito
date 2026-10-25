# 三环境训练规则与计时预跑

本次更新落实2026-10-25用户的后续确认；方案见`configs/training-scenarios-v1.json`。它是**不可启用的准备配置**，不是现有group recipe。原100 GPU小时`training-plan-v1.json`、2207／2210参考主题、用户原输入及修订版均保留，不启动正式训练。

| 环境 | 构筑／课程 | 独立验收 |
| --- | --- | --- |
| 2207 | 原珠泪参考主题与同期外战→递增参考内战课程 | 统一规范§12.1：含换备BO3外战≥60%，强参考珠泪内战接近50%；至少200外战＋200内战独立BO3，报告95%CI及分项 |
| 2210 | 原珠泪参考主题；原对手递进比例仍未单独冻结 | 同上；不改成49%／39% |
| 2610 | 目标模型自主选主题、构筑逻辑及CB；优化模型保目标改进，决斗模型执行，统筹安排与汇总。先实际可用bot BO1，完成后常见卡组BO3 | 仅第二阶段冻结评测，实际小局先手>49%且后手>39%；两项同时；draw不算win；stage1不替代stage2 |

2610不固定成珠泪，也不把别的主题写死。选卡是已有时期合法、当前已发行且实际卡库／脚本可用证据的交集；缺失卡逐张排除，不要求先补齐那两张用户参考牌表中的卡才允许其他主题。未来截止的最终卡池与当前可核子集分开，未发售不提前入池。`eligible_card_ids`仅交集检查，不替代完整牌表、卡效或CB验证。原两期参考不变，既有构筑逻辑先图→仅狭义主轴→具体卡文绑定／核验的职责不变，不加LLM必需项。

所有训练场景共同按完整大场计数：均值≤60秒时1000 BO1＋100 BO3；>60秒时总≥1000、6:4（最小600＋400）。预跑和独立评测不抵扣正式量，也不跨环境抵扣。`volume_requirements`、`volume_met`和2610专属strict算术检查已有CPU测试；它们不是已接入正式worker的成功宣告。异常、零分母不判通过；未解决异常仍报告，不能剔除美化。旧两个环境的“接近”容差、CI判定及重复观察规则仍需在正式验收前冻结；2610如何映射旧200外战＋200内战独立样本分组也未被新训练量自动解决。

## 可执行的有界预跑

`scripts/training_pilot.py`默认只预检。当前复用`CpuTrainer.sample_episode`，实际神经模型前向和正常引擎／typed WindBot路径；无update，不写训练索引、optimizer或训练游标。它只支持**显式已更新的standalone CPU决斗checkpoint、BO1**；拒初始随机权重、group／LoRA工件和BO3，不静默丢adapter或迁移GPU到CPU。因此当前CPU pilot不能冒充正式GPU／group／BO3速度。

从项目根生成未完成模板，再按腾讯云真实工件填充；不能把null或合成fixture当作配置完成：

```bash
PYTHONPATH=src .venv/bin/python scripts/training_pilot.py --template \
  --output .cache/pilot-spec.json
PYTHONPATH=src .venv/bin/python scripts/training_pilot.py \
  --config .cache/pilot-spec.json --output .cache/pilot-preflight.json
```

模板需要精确checkpoint文件／原binding／model SHA、卡表profile、完整bot构建审计及同bot已实际终局的正常资格报告引用、Mono绝对路径和隔离seed。资格报告必须与source、CDB、profile、工具及当前完整Python实现绑定相符；只有构造审计或源文件存在不够。所有case预检成功后，才在获准腾讯云主机显式加`--run`，输出另用新文件：

```bash
PYTHONPATH=src .venv/bin/python scripts/training_pilot.py \
  --config .cache/pilot-spec.json --output .cache/pilot-result.json --run
```

建议在一个声明窗口里计划约12小局，多个已正常验证bot、双方实际先后手和不同种子；这只是小样本建议。首个异常停止并保留partial、未尝试数量、所有attempt及完整局分布，不能用剩余快局选择快档。用于60秒分档的`game_seconds`来自既有sampler的实际模型／引擎小局计时；另记`wall_seconds`含外层完整性复核、bot清理等全部attempt开销，不能用这部分开销替换游戏均值。模型加载／预检不算作小局。记录实际首回合turn-player证据，无证据则先后手unknown，不能从席位号猜。计时上限可到300秒以观察慢局，仍受自管bot会话限时，不声称能硬中断卡住的native调用。所有输出独占，未完成／中断状态保留，不覆盖旧报告挑快样本。

当前云端没有Mono、真实完整C#构建审计或正常WindBot资格证据；本轮只执行明确CPU单元／fixture及不运行的模板预检，**未执行真实计时**。也没有真实均值可证明100h预算足够；目标硬件、有效group／LoRA和BO3试跑未覆盖前，不据CPU均值填写正式GPU预算结论。部署依赖见`maintained-bot-deployment.md`与`bot-qualification.md`，不重试此前被拒的安装源。

## 具体尚未实现的执行链路

现有group读取固定task，评估固定BO1及actor seat0，不能仅把JSON写成BO3就执行新课程。仍需：自主theme/task到group的实际准入；完整BO3 match／输者选先后／局间换备；实际小局先后手胜率接入冻结评测；正式worker的完整大场数量门控；与目标group／LoRA／GPU一致的计时入口。现有独立评估种子上限也不能靠反复不同模型的训练周期累计成同一次冻结终验。已有四模型指纹与train/validation/final分区隔离继续复用，不绕门禁。上述是明确代码缺口，不归咎于“缺权重”，本轮不将方案写成已全部生效。

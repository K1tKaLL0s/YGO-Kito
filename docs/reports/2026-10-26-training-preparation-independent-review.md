# 训练准备与有界 pilot 独立复核

结论：本轮声明的**不可启用场景配置、范围／算术校验及 standalone CPU BO1 pilot 准备接口**通过本地独立复验。没有证据表明自主训练课程、BO3 或正式验收已经生效。复核基线为 `7e92994d28b8f075092fc68f30848dd6e4855ca2` 上的本轮工作；实际代码调用链已读，不以配置文字或作者测试结论替代实现。

场景边界符合最新确认：2207／2210保留珠泪参考主题及原§12.1含换备BO3外战≥60%、强参考内战接近50%、每期独立200＋200和95%CI要求，尚未冻结的容差／CI判定／重复观察规则保持空值。2610自主主题→构筑逻辑／CB→已实际可用bot BO1→常见卡组BO3单独记录；严格>49%／>39%只属于该第二阶段冻结评测，分母为实际完整小局，draw不算win。`check_2610_rates`只输出算术结果，始终 `formal_training_success_verified=false`，拒绝历史期、stage1、train和timing_pilot口径。

共同数量规则保留完整大场单位：≤60秒含恰60，为1000 BO1＋100 BO3；>60秒为总≥1000且6:4，最小600＋400。预跑与独立评测不抵训练量。原100 GPU小时计划未改；本轮没有真实速度或预算足够的结论。约12小局仍是建议，不是新最低门槛。

`TrainingPilot._prepare`实际读取项目完成边界且已有更新的standalone决斗checkpoint，校验权重／词表／资源摘要，冻结CPU推理模型，不恢复optimizer、训练RNG或游标。所有case先经真实registry完整构造审计门禁，并以原正常资格报告的精确source／profile／牌表／资源／工具／完整Python实现binding重建核对，之后显式`--run`才调用既有 `CpuTrainer.sample_episode(..., purpose="validation")` 和typed managed WindBot路径。无随机模型或策略fallback，也没有update调用。测试中的registry／engine／room替身均明确标为fixture，不能据此声称C#或正常core已运行。

独立发现并复验闭合两处边界问题：

- 聚合助手原来对“2个完成＋1个失败、planned=2”仍发数量建议且剩余计数为负。现超出声明窗口直接拒绝；有失败、未完成或缺失／非正计时均不给建议。60秒分档使用sampler的 `summary.elapsed_seconds`，外层wall及清理耗时单列；没有挑选快成功样本代替完整窗口。
- 场景校验器原来放行历史容差／CI规则任意赋值及把2610旧200＋200采样改为0。现未确认规则保持null、旧独立样本要求及尚待映射状态精确保留，不把准备配置当作冻结新统计方案。

独立执行 `tests.test_training_scenarios` 7项与 `tests.test_training_pilot` 14项：**21/21通过，1.592秒，0 skip**。其中小网络人工张量单步仅用于生成checkpoint加载夹具，不是游戏训练或能力证据；真实神经前向和真实sampler接两个合法fixture窗口的组合已测。另以独立CLI进程生成null模板后执行默认preflight：模板退出0、preflight退出2／blocked，native=false、C#=false、training_updates=0、formal_games=0。没有运行真实pilot、引擎、C#、GPU或新游戏训练。`native.py`、`native_response_guard.py`、`cpu_training.py`与基线差异为0；本地定点通过不冒称后续提交CI已通过。

实际尚缺：现有group仍从固定task进入、评估BO1且actor seat0；未实现自主theme/task到group的准入、完整BO3 match／输者选先后／局间换备、实际先后手结果到冻结验收的接线、正式worker完整大场数量门控。当前pilot不支持group／LoRA／GPU或BO3，亦未取得可执行本轮真实计时所需的完整C#构造审计及同绑定正常资格；当前null模板blocked是准确边界，不归因于缺用户牌表或宣称只剩权重。上述为明确执行链路缺口；本轮可交付准备功能，不能称全部训练设计已实现。

复验源码摘要：

| 文件 | SHA256 |
| --- | --- |
| `configs/training-scenarios-v1.json` | `9483859a3b87580aeca1eb835a5e6a2a95420d3df72dfbce6ffe21c8de76a232` |
| `src/ygo_kito/training_scenarios.py` | `42c42454c66b508e2cea727bcc2279548a6ace043ed317512d03c948c1fba3d7` |
| `src/ygo_kito/training_pilot.py` | `9c4739751b5588be7980759811f5a14ea80c927cd1197fa505d5d82afbe116e4` |
| `scripts/training_pilot.py` | `241da3d912a4623ffcd5a6a928d4b7be42c24be0741855cf11dfb6b2e37b07c3` |
| `tests/test_training_scenarios.py` | `2e94869c21fc1148ef81476d4306b4649558b8ba636b2d6438e13d16363f60b2` |
| `tests/test_training_pilot.py` | `c79cfc58f7e36d128302b9244e25e8823629f934e15bf5caf2ea6501ffdc55fa` |

本验收者仅写本报告；未改生产源码、执行Git写操作、改网络／权限或运行正式训练。后续draft PR与CI由父任务单列核实。

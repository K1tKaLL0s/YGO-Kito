> 历史运行记录：2026-10-26 上午 A10 主机；后续已由用户切到 CPU 4核8G。当前交接状态见 [项目入口](CLOUDSTUDIO_GUIDE.zh-CN.md)。

# CloudStudio CPU／GPU实测与接续（2026-10-26）

## 结论

现有小模型与串行流程优先使用CPU。A10在batch=32的真实输入批量推理上约快3.91倍；单局串行推理更慢，完整机器人对局约持平，四角色工程训练整轮在GPU上约慢33.2%。CPU采样＋GPU批量学习可作为后续优化方向，混合调度尚待接线和完整吞吐复测。本轮正式训练量0，所有自建短测和监测进程已退出。

## 环境和版本

- 页面：https://cloudstudio.net/a/39250693079592960/edit 。工作目录：/workspace/.cache/codex-gpu-20261026；HEAD 6cef642cc840120fc6d445cfbf7b8bc082b61f0d。/workspace的main仍为7e92994d28b8f075092fc68f30848dd6e4855ca2，已有用户文件与旧工作树保留。src差异为空。
- NVIDIA A10，23028MiB显存，驱动580.178.04；驱动支持CUDA13.0，镜像nvcc12.2；本次Torch使用自带CUDA12.8运行库。
- EPYC7K83；可见28逻辑线程，容器CPU配额20核；memory.max为116GiB，可见系统内存约111.7GiB。
- 原CPU环境/workspace/.venv保留。对照共用/workspace/.cache/cuda291-venv/bin/python：Python3.12.3，Torch2.9.1+cu128、NumPy2.3.5、SciPy1.16.3；cuda.is_available=True，计算能力8.6。完整freeze在cuda-freeze.txt。
- 所有对照FP32、TF32关闭、Torch/OMP/MKL单线程、相同权重/牌表/种子/实际席位/批量与完成条件；先真实预热，GPU测量前后同步。CPU/GPU顺序在case和重复轮次间交替。

## 冻结模型＋真实WindBot

原独立决斗模型由随机起步、工程PPO更新2次；模型SHA 202430015c848dcbf0de4b04dd4131d58401a72e8cc901591fe63ab275e6aa8b，文件SHA 66c35abd70b0effe28a306c5d1d5b76ecd283ffd9230115f973227ecf6203396。采用原40张通常怪兽工程actor，Ice Burn/Blackwing原配牌表，双方实际先后手，各重复2次。声明16局，完成16，失败0，超时0，未尝试0；CPU/GPU各8局，8对轨迹摘要全部一致。每端914次神经前向，参数保持不变。

| 指标 | CPU | A10 |
|---|---:|---:|
| 小局平均（模型＋引擎＋bot生命周期，秒） | 67.312455 | 66.985854 |
| 小局P50／P95（秒） | 63.337／89.188 | 63.014／91.282 |
| 整次attempt平均（含清理，秒） | 67.794017 | 67.471404 |
| 单次模型forward均值（毫秒） | 2.644 | 4.023 |
| 单次完整actor推理均值（编码/传输/采样，毫秒） | 3.949 | 5.798 |

GPU平均小局仅低0.49%；配对差值范围-2.147至4.009秒，重复样本发生方向反转。当前窗口没有可靠整体GPU优势。

每局完整actor推理合计CPU 0.451秒、GPU 0.662秒；直接原生API区间约1.17秒，其余耗时主要在CPU侧协议、校验和控制流程。Python进程平均消耗约59.7 CPU秒/局，模型计算不是当前主要耗时。尚未对各控制函数执行性能剖析。

## 真实PPO与四角色更新

独立决斗模型：两端从相同两步权重建立独立优化器和RNG，各1次真实预热＋8次完整原生对局/PPO更新。8对轨迹一致，每步32样本，均完成且有非零梯度和参数变化。

| 指标 | CPU | A10 |
|---|---:|---:|
| PPO完整update平均（秒） | 0.370972 | 0.286525 |
| update样本/秒 | 86.26 | 111.68 |
| 采样＋更新整轮平均（秒） | 2.651402 | 2.862437 |

完整四角色起点：复用用户已生成的.cache/training-prep-20261026/state/runs/four-model-source-20261026b/checkpoints/local-step-7.weights，文件SHA fcb4a3b970e8b834be69c0d0ee3ff26a53eb1e067b946f5cb11a63e82cea4f87，binding SHA c9cf28d7efcb1ed5569144379b1157f2ed5188f2c8f442e7628ec8ab9614cb0b。原始状态为随机初始化后四角色各1次base更新和1次LoRA更新，周期1、提交阶段7、done边界。选择effective，按已有初始化接口物化源LoRA，目标优化器/RNG重新建立。两端初始四角色参数摘要完全相同，原文件不变。目标参数数目：{"build_goal": 17729, "build_optimizer": 17729, "duel": 266050, "coordinator": 648}。

四角色两端各1轮预热＋3轮测量，8个真实工程决斗终局全部完成，4对轨迹一致。构筑监督复用实际条件引擎目标的4条记录和2条弱偏好；统筹沿用明示工程聚合监督。

| 三轮测量均值（秒） | CPU | A10 |
|---|---:|---:|
| 实际模型/引擎采样 | 1.742544 | 2.296558 |
| 决斗PPO更新 | 0.088334 | 0.124909 |
| 目标＋优化两个构筑更新 | 0.017849 | 0.038185 |
| 统筹更新 | 0.002487 | 0.006193 |
| 整轮 | 1.851368 | 2.466088 |

批量推理另用同一批32个真实合法决策DTO：batch=1各96次，CPU 2.290ms、GPU 4.432ms；batch=32各20次，CPU 59.977ms、GPU 15.340ms。最大logit误差1.79e-07、value误差1.49e-07，贪心动作一致。决斗实现允许batch≤32，本轮已测32，未扩大网络或上限。

CUDA决斗恢复：完成1次实际更新后保存完整检查点，再分别连续执行与重载后执行同一下一局；终局轨迹和更新后模型位级一致。路径：/workspace/.cache/gpu-compare-20261026/cuda-recovery/after-1.weights。原始独立决斗检查点及四模型起点均未覆写；测试更新只保存在本轮目录。完整分期四模型课程恢复仍随实际课程资产核验。

## 资源与预算

- 冻结对局Python平均CPU约88.2%单核；宿主可见28线程平均忙占比4.41%、采样峰值8.31%。整机日志含实际WindBot进程RSS/CPU时间。
- GPU对局1Hz采样平均利用率0.045%、峰值3%；该频率会漏掉短计算脉冲。显存观测峰值445MiB；Torch峰值allocated 89.59MiB、reserved 102.00MiB。
- 比较进程峰值RSS 1.653GiB。GPU对局平均功率约56.2W。
- 本轮安装/核验/短测操作窗2026-10-26T07:55:00.655871+00:00至2026-10-26T08:34:38.122075+00:00，约0.660单卡实例小时；此前实例时长保留unknown，累计账单未读取。正式总上限100小时，安装、空转、失败和评测同样记账。
- 当前工作流在A10机器选择CPU执行仍占用这台实例。切换CPU机型后的吞吐需重新实测。

## 三期接续和实际缺项

已有source_group-reference.json与course-host.partial.json。后者已填真实native_root和完整组来源，当前预检blocked：active_environment等实际工件路径为空。缺项：

- 逐期真实OCG发行manifest（卡号、正式发行日期、来源与哈希）。
- active_environment及已核允许池available_cards。
- 与分期资产匹配的bootstrap_task和合法参考牌表。
- 历史/当期实际对手的合法牌表、运行资格及train/validation/final_eval独立划分。
- 完整course配置、种子/LoRA容量及同四模型/设备/对手的course-group计时报告。
- 正式课程完整检查点恢复实测及累计实例预算核对。

2207/2210仍为珠泪参考课程、截止2022-09-30/2022-12-31，BO3外战≥60%、强参考内战接近50%，独立200外战＋200内战BO3及95%区间。2610自主主题→构筑/CB→可用bot BO1→当期常见卡组BO3；仅2610第二阶段按实际小局先手>49%、后手>39%。2610设计截止2026-11-01 JST含当日，禁表2026.10；当前已发行核实子集可另立active环境，未来最终池到日后核验。

每场景实际四模型预跑另测：均值≤60秒至少1000完整BO1＋100完整BO3；>60秒至少600 BO1＋400 BO3。预跑、恢复对照、冻结评测分别记账。BO3含合法换备、输者选先后与先赢两局终局。本轮BO3完成0。

容量推算：若实际分期课程也约67秒/小局，慢档训练需1400–1800小局，串行约26.1–33.5小时/期，尚未加入构筑与独立评测；历史独立400个BO3另约14.9–22.3小时。原25/25/20小时分配不能据当前串行样例认定足够。实际分期预跑、CPU侧性能剖析和可复现优化后再冻结规模/预计时间，保留100小时总上限。

准确预检命令（输出路径须新建）：

```bash
cd /workspace/.cache/codex-gpu-20261026 && PYTHONPATH=src /workspace/.cache/cuda291-venv/bin/python scripts/scenario_course.py --workspace /workspace --config /workspace/.cache/gpu-compare-20261026/course-host.partial.json --output /workspace/.cache/gpu-compare-20261026/course-preflight-next-001.json
```

当前结果停在准备与测量。正式启动前先报告实际环境、模型起点、规模、完整课程计时和累计预算，再按用户当次授权执行。可对CodeBuddy说：“按最新GPU报告补齐2207实际资料，先预跑并汇报启动方案。”

## 文件与复现

本轮目录/workspace/.cache/gpu-compare-20261026：comparison.json/log为16局与16步PPO；group-update-comparison.json为四角色；exact-input-and-cuda-recovery.json为真实DTO/恢复；analysis-summary.json为配对/资源汇总；host-utilization.jsonl为整机记录；qualification-seat0/1.json为4局当前源码资格；training-proposal.json列当前方案与阻碍；observed-budget-window.json记已观测时间。

compare_actual.py、postcheck.py、group_update_compare.py保留完整采集代码；after_main.py用于顺序运行；最终进程回执final-process-state.json。重新复现实验先复制脚本到一个新输出目录并修改其OUT，保留本轮日志、配置、原权重与固定依赖。

依赖来源：[PyTorch官方安装版本](https://pytorch.org/get-started/previous-versions/)，官方cu128索引；数值依赖来自PyPI。没有更改原环境、驱动、凭据或网络设置；未合并PR。

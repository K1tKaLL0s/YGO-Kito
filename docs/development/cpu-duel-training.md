# 决斗模型 CPU 最小训练与恢复

本入口对应总清单 MD-01～MD-05、T-01～T-04 的**有界子项**。最新用户指令已授权本云端修改、测试和非付费 CPU 参数更新；旧报告中“本轮不启动训练”描述其当时范围，不否定本批授权。付费训练仍须 G-01/G-02/P-01 及具体采购授权，本批不启动腾讯云、GPU 或外部 API。

## 实现与输入边界

`duel_model.py` 是独立初始化的小 Transformer：默认 1 层、宽 32、4 个注意力头、卡片 embedding 宽 16、前馈宽 64；策略头按引擎候选打分，价值头估值。它没有下载或依赖 LLM。参数及损失权重是可复现**工程试验配置**，不代表 Q-01 已为最终模型组冻结参数。

`PlayerEncoder` 只接收 `DecisionRequest`，拒绝带 RNG seed 的请求及原始审计字典。输入是本席位合法观察、公开历史和当次合法候选：可见卡片 ID、位置/已知攻守、相对所有者/控制者、LP/手牌与牌堆数量、阶段、最近 32 个公开事件；候选包括种类、公开效果描述、数值、落点及对合法引用的指针。完整公开卡库只用于建立固定词表，不将对手当前牌表或未来抽卡放入特征。

隐藏身份/攻守无法通过 DTO；暗牌 owner 也不会成为模型特征。检索候选只能属于当前观察席位。运行/对局/窗口/事件/动作 ID 用于绑定和提交，不作为网络特征。种子、请求指纹与双方控制器审计保留在采样控制器，不能充当策略数据。历史截取、尚不支持的动作协议和区域等边界仍按协议矩阵执行；候选超预算直接失败，不能截掉动作后假称通用覆盖。

batch 使用布尔动作掩码，补齐候选概率严格为 0；全无合法候选拒绝执行。模型选中候选后，仍通过真实引擎会话的 `ActionSelection` 校验。掩码与接口单测不等于真实核心或模型强度测试。

## 在当前云端执行

本批复用实际 CPython 3.12.14、PyTorch 2.14.1+cpu、NumPy 2.3.5 及已固定/源码构建的原生资源，没有新增安装。基础 CLI 仍可只用标准库；Torch 仅在以下命令或模型模块导入时加载。移植到其他环境前须核实相容的官方 CPU 依赖，不默认安装含 CUDA 的发行包。

```bash
cd /workspace/YGO-Kito
.venv/bin/python -m ygo_kito duel-train-cpu \
  --root .cache --state-root .cache/agent \
  --run-id my-cpu-proof \
  --profile configs/effect-duel-v1.json \
  --training-config configs/cpu-training-smoke.json
```

必须使用新 run ID；重复 ID、checkpoint 名称会拒绝覆盖。缺 Torch/真实资源时非零退出，缺资源不产生伪造成功记录。每次最多两个声明的工程种子、每局 1500 次原生决策/30 秒（可配置但有上限）、CPU 单线程、小批量不超过 32。时限检查位于核心调用之间，**不能替代阻塞原生调用的进程看门狗或正式比赛时钟**；R-12 仍部分完成。

当前工程效果牌组每方 40 张，既不是用户稍后提供的 3＋8 套，也不代表三个历史环境的卡池。固定合法可见规则代理操控对手；仅本席位当前策略采样进入 PPO。只有真实 `MSG_WIN` 终局才给终局胜/负/平奖励；预算失败不伪造奖励或更新成功。GAE、PPO clip、价值误差和熵项均执行真实 autograd/AdamW 更新，每局抽取最多 32 个本席位决策作一次小批量更新，其余当前样本未用作本次梯度。

每次更新前校验策略版本和参数指纹，历史审计、规则/外部代理轨迹或已消费 rollout 不得直接混入 PPO。该实现是进程内可信采样器契约，不是接收任意来源宣称“真实”数据的证明服务。尚无分片数据加载器、跨对局训练/验证划分或完整评测器，T-01/T-04 保持部分完成。

## checkpoint 与真实恢复验证

命令实际依次执行：

1. 模型采样第一局真实对局，更新一步，保存并登记 `step-1`。
2. 当前更新后的策略采样第二局，更新第二步，保存 `step-2`。
3. 读取 `step-1`，恢复模型、AdamW、StepLR、Torch/Python/采样/小批量 RNG 与对局游标；重新采样第二局并更新。
4. 要求恢复分支的实际轨迹指纹、损失/更新结果及最终参数指纹与连续运行完全相同，否则失败。

规范训练计数为 2 次更新/2 局；恢复对照另实际执行 1 次采样和更新，**物理 optimizer.step 共 3 次**，不能作为新增第三步训练。仅支持完成一局并已更新后的边界，不能恢复半局原生引擎状态。

checkpoint 含配置、全公开卡库词表与哈希、参数、优化器、调度器、RNG、游标、更新数及绑定信息。绑定包括 Python/Torch、Python 实现源码摘要、原生核心/脚本/卡库/协议/禁表哈希及牌组配置摘要；不兼容绑定拒绝加载。使用 `torch.load(..., map_location="cpu", weights_only=True)` 读取项目自身 checkpoint；监控端只检查文件长度和 SHA-256，不反序列化。尚无 LoRA、多模型、通用分片游标或付费预算恢复，不能把这项勾为完整 T-03。

真实文件保存在 `STATE/runs/RUN/checkpoints/{step-1,step-2}.weights`，每份约 3.3 MB，包含项目自行生成的小型权重及优化器状态，不上传 Git。`proof.json` 记录实际参数变化、恢复结论、资源与文件哈希；PR 提供证据和复现命令，云端路径不是用户下载链接。

## 监控与外部 agent 边界

训练端通过既有 `RunReporter` 原子发布递增状态，来源为 `trainer`；更新后 checkpoint 立即登记，失败也发布实际已保存进度。以同一 state root 启动现有只读工具即可查看，无需 LLM：

```bash
.venv/bin/python -m ygo_kito agent-serve \
  --role monitor --state-root .cache/agent
```

输入为 JSON Lines，例如：

```json
{"schema_version":1,"id":"inspect","method":"runs.read","params":{"run_id":"my-cpu-proof"}}
{"schema_version":1,"id":"weights","method":"checkpoints.read","params":{"run_id":"my-cpu-proof","checkpoint_id":"step-1"}}
```

`duel-train-cpu` 是明确的本地训练命令，**还没有连接 `training.control` 后端**；该工具默认仍报未配置，不能声称 CodeBuddy/DeepSeek 已接管、可暂停或恢复生产训练。provider 端到端、8 套 DeepSeek 用户牌组、历史对手资格均待后续验收。外部 LLM 不成为此训练闭环的依赖。

记录的 elapsed/process CPU 从初始模型和优化器建立后开始，包含 checkpoint 和实际恢复对照；`samples_per_second` 是两个规范 rollout 的样本数除以整个证明用时，包含恢复开销，不是纯训练吞吐。RSS 为整个进程生命周期峰值，包含 Torch/优化器；网络前向时延不代替 PC 端到端时延。记录没有新开付费实例和外部 API 调用，平台云端开发 CPU 费用不可见，不能宣称无限免费。没有 GPU 时不编造 GPU 读数。

本入口原始结果见[M3a](../reports/2026-10-23-duel-cpu-m3a.md)。后续[M3b](cpu-building.md)增加构筑原型，[M3c](coordinator-model-group.md)已有学习统筹建议/规则闭环，[M3d](lora-and-cloud-handoff.md)已有实际四角色LoRA更新与组恢复；均不等于完整模型能力。决斗命令的`models_in_this_run`只报告本次执行角色。搜索、正式LoRA迁移、三期数据、BO3、PC兼容和完整资源门槛继续保留，学生原ZIP/TODO不改写。

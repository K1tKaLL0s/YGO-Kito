# 计数构筑、数据隔离与可执行对手

按[统一设计](../plans/2026-10-22-unified-development-spec.md)实现的有界CPU增量，接在既有真实核心、独立构筑网络和PPO接口上。原设计、原学习包和学生TODO不变。此入口不连接外部模型或云控制台，不放行正式训练。

## 可重复命令

在本云端仓库及既有`.venv`中运行，输出目录必须不存在：

```bash
.venv/bin/python -m ygo_kito foundation-acceptance \
  --root .cache --output .cache/foundation-delivery-new
```

命令有180秒独立进程墙钟期限；每局仍有决策数与30秒采样预算，超限报错，不伪造终局或奖励。它依次执行实际构筑更新/恢复、四步构筑、真实注册对手采样/PPO、恢复对照、验证/终验隔离、冻结模型对手对局和MSG24多区重放。工程终验分区用于测试隔离，**不是正式独立能力终验**。完整结果及最终源码记录见[本批报告](../reports/2026-10-23-semantic-indexed-opponents.md)。

新增CPU依赖仅`scipy==1.16.3`，已从官方PyPI安装到此`.venv`，未改原PyTorch/NumPy。依赖声明在`pyproject.toml`的`semantic` extra；MILP使用[官方公开接口](https://docs.scipy.org/doc/scipy-1.16.2/reference/generated/scipy.optimize.milp.html)，本批实际测试安装的1.16.3，不据新版本文档推定兼容。没有安装CUDA或下载预训练权重。

## 通用公开事实约束

`BuildTask.schema_version=4`新增`goal.kind=deck_constraints`；可直接用于`build-check`、`build-train-cpu`、`alternate_build`，例子为[工程配置](../../configs/build-semantic-engineering-v4.json)。原schema1～3仍保留。新目标不强塞虚构的召唤卡、起手或效果路线。

- 1～12条硬计数约束，0～8条显式软偏好；计数可跨main/extra/side。
- 原子谓词：卡号集合、真实setcode、type全包含、race/attribute位交集、等级范围；all/any/not有深度及宽度上限。
- 主/额外/副卡张数、卡池、OCG身份、类型、别名合并禁限和固定卡要求仍独立检查。setcode按固定核心的低12位及高4位子类语义匹配，不用卡名子串猜主题。
- 有界MILP只提议合法列表，最多8候选、10秒/调用及10000节点；可在旧列表上约束替换数。解必须再次独立校验；超时/未找到为unknown，不变成“不可能”的负标签。infeasible只指声明的列表约束矛盾，不指效果路线不可行。
- 目标/优化仍分别使用独立Transformer排序；硬约束、匹配成员和偏好真正进入编码。两个角色没有变成LLM或共享训练权重。特征升为`build-task-catalog-candidate-v4-semantic-constraints`；旧权重须旧源码或明确迁移，不静默兼容。

成功列表返回`constraints_satisfied`，明确`effect_execution_verified=false`。目标→优化→目标→优化仍检查目标哈希、主/额外/副卡和逐项改动。偏好是用户声明的偏好，不能冒充稳定性、抗打断或胜率。当前schema4尚未接入长周期四模型课程的效果比较/LoRA阶段；既有schema1～3课程、真实比较源与恢复保留，下一批需显式扩展而不是改标签放行。

## 数据索引与准入

`DataIndex`在本地SQLite中冻结用途、环境、目标和实际对手版本，保存私有payload及哈希。train、validation、final_eval分开；跨用途拒绝相同物理核心/脚本/卡库/禁表范围中的随机种子、相同构筑列表、相同实际对手版本。改数据集名、任务/约束显示名、牌表记录名或牌序不能制造新分区。实际对手身份绑定牌表多重集合、驱动实现/版本及模型SHA，不能仅靠主题名称区分。

构筑监督来源为`catalog_constraint_and_explicit_preference_v1`：合法计数正例、明确硬失败负例、显式偏好对；没有捏造效果成功或胜负。schema4的`BuildTrainer.step(..., data_admission=...)`必须取得索引的训练准入，held-out用途或改过payload拒绝。`build-train-cpu`已实际创建索引并用同一准入验证恢复。

注册对手采样的PPO数据只保存本席位合法DTO；训练器另密封自己实际新采样的内容，改用途的验证数据、旧版本、重复更新均拒绝。索引准入同时核用途与payload；验证不更新权重。既有工程路径兼容保留，本索引尚未替换所有旧课程数据加载器，三期大数据/吞吐与全流程隔离仍需单独验收。宿主自己改写数据库不在此可信宿主完整性边界内，索引不是权限沙箱。

## 实际可执行的对手

`OpponentRegistry.runtime_environment(5)`绑定当前固定资源与v5观察；注册牌表可含额外与副卡，BO1不把副卡塞进引擎。`FrozenOpponent`将注册记录转成可执行版本并在每局前回读验证；过期资源/记录/席位/牌表拒绝。

- 本地规则基线：`visible-effects-first-v1`、`visible-effects-last-option-v1`。
- 本地冻结模型：`local_snapshot`＋`frozen-duel-greedy-v1`，必须显式提供注册目录内的本地checkpoint及文件SHA。验证完成对局边界、资源/特征、模型及词表；只把模型形状、权重、公开词表交给策略，不交牌表、引擎句柄、训练种子、优化器或审计。权重eval/冻结，加载不推进训练随机流。
- `FrozenOpponentPool`固定版本和轮转顺序，以checkpoint中的episode_cursor选择；manifest标记`strength_qualified=false`和`formal_training_ready=false`。

策略只接收本席位正常合法`DecisionRequest`和公共目录。`bot`/`external_llm`注册不会获得可执行资格，未核实的传输在`FrozenOpponent`入口明确拒绝。既有外部JSON工具的超时、非法动作拒绝/回退和成本记录继续保留；本批没有声称DSH/WindBot/CodeBuddy/DeepSeek已联调或免费可用。一般bot桥接、强度测试和历史覆盖盘点仍是自主工程。

## MSG18/24与证据导出

`place_classification`记录完整资源版本、三个C++文件哈希、调用行号，并验证固定core HEAD及相关文件未改。7处直接PROCESSOR_SELECT_PLACE调用只请求0/1；10处`Duel.SelectField`中2处六参数走18且都是1，其余走24，存在可变多区计数。`select_place`本身支持多计数的线格式；不能把缺上游调用说成协议绝不支持多区。

在此固定普通非tag、非debug BO1调用范围，MSG18多区没有现成调用入口；更换核心或脚本时需重新审计。用户额外提供牌表不能制造不存在的源码调用。本批不改核心或注入自定义脚本制造通过。MSG24用未改上游地盘沉下分别选择首/末两区，真实FIELD_DISABLED掩码与提交区域逐位一致，均独立重放。

`output/private`含完整牌表、种子、双方响应、视图键、数据索引、监督及权重，留在云端；不作为用户下载链接。`output/public`仅含双方逐字段相同的合法PublicEvent历史和聚合证明。严格白名单导出不复制私有DTO、加载脚本清单或未公开牌序。此前被拒的完整私有JSON不重试上传；仅此public目录可进入PR，重放在云端完成后才导出。

正式1A/1B/PC、三期能力、一般效果/CB/混轴、合格bot和外部实际联调仍未通过；本地安全停止不等于腾讯云计费停止。剩余20%保存停止，不用重置卡；当前无实时额度工具。

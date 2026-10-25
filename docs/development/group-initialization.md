# 显式跨期主模型初始化

`group_initialization.initialize_group_weights` 复用现有BuildTrainer、CpuTrainer、CoordinatorTrainer的四个角色网络，为新任务/时期导入明确来源的模型参数。它与同绑定 `GroupState.restore` 分开：旧恢复的源码、资源、任务、账本和游标门禁继续保留。本入口不恢复旧优化器、RNG、数据、对局或统筹账本，也不开始训练。

宿主配置格式：

```json
{
  "path": ".cache/managed-source/checkpoints/local-step-N.weights",
  "sha256": "<源文件64位小写SHA256>",
  "weights": "effective",
  "source_binding_sha256": "<源checkpoint binding规范JSON的SHA256>"
}
```

`weights` 必须显式选择 `effective` 或 `base`。前者按保存的LoRA A/B、alpha/rank物化有效Linear权重；后者明确只继承基模，但同样验证保存的适配器身份和矩阵，不默默丢弃损坏或不相符的适配器。源文件必须在明确workspace内，SHA匹配后通过 `torch.load(weights_only=True,map_location="cpu")` 读取；不改源文件、不打开源账本。

```python
from ygo_kito.group_initialization import initialize_group_weights

provenance = initialize_group_weights(builder, duel, coordinator,
    workspace=workspace, spec=explicit_spec, target_binding=new_group_binding)
```

调用时三个现有trainer必须是新建状态：四个独立模型、空优化器、初始调度和零游标，没有挂载LoRA。模型对象和optimizer持有的参数对象保持不变。源须为已完成 `four-model-alternating-v1 / complete-workflow-stage` 组检查点，done游标和提交阶段一致；核对四角色、特征版本、模型结构、词表、模型哈希、适配器base/role/context/权重哈希及源binding内真实物理/时期字段。整个预检和映射完成后才原位加载；加载异常回滚四角色参数。

卡嵌入按稳定卡ID交集复制，注释嵌入按完整规范注释身份复制；新增卡/注释、padding行保留新目标的初始化值，源独有身份丢弃并记数。其余参数名、维度、dtype、特征版本和结构必须匹配，不能把词表第N行误当另一张卡。当前物化使用CPU FP32；不宣称CUDA位级复现。

返回provenance记录源文件/binding/任务/时期、目标binding/任务/时期、各角色前后参数摘要和映射数量。未带period_context的旧工程源可显式使用，但来源时期记录为null，`historical_training_verified:false`。同/逆向时期迁移也只按明确上下文记录，供旧环境复习；不擅改目标cutoff、引入源牌表答案或增加方向门槛。

group recipe可显式加入`"initialize_from": "configs/实际初始化声明.json"`，文件内容为上例。`validate_recipe/binding_for`读取并绑定规范声明摘要；GroupState创建四个新trainer后、训练或创建工作账本前调用初始化。provenance随新检查点保存并在同绑定restore重新核对，但不重读源模型文件；旧未声明初始化的配方和恢复格式仍兼容，新期优化器、RNG和数据隔离重新开始，LoRA按既有bootstrap→冻结基模→新适配器生命周期运行。

本轮另用项目先前实际完成CPU更新的完整组工件进行真实接线检查：source SHA `ac8f1a048a9cf9b01a5f544944b5fa4663338aa54f00a7688f121ef99ad21863`，四角色基础更新各1步并有保存的LoRA。显式effective初始化新的普通工程GroupState、save_to后删除临时source副本，再restore，四模型摘要/provenance一致，新run更新数仍0，原source未改。源声明为旧2022-10工程cutoff10/01，不伪装确认的12/31正式池；未执行新训练、native或能力验收。公开聚合回执在本轮设计审查报告中，原权重不进仓库。

CPU验证：`PYTHONPATH=src .cache/ci-cpu-venv/bin/python -m unittest tests.test_group_initialization -q`。8项使用自有小合成checkpoint形状夹具，直接赋参数，没有optimizer更新、引擎、故障或付费任务；验证有效/基模选择、四角色迁移、稳定身份/新行、源绑定拒绝及目标状态保持。夹具的done字段仅测试文件契约，不证明真实训练、历史资格或能力。

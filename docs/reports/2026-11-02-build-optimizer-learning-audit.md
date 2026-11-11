# 构筑优化模型正式学习记录核验

结论：暂停课程的构筑优化模型没有完成过一次已保存的学习更新。历史流程实际调用了优化模型做图／牌表评分，也执行过配对比较，但没有产生可供优化角色消费的严格偏好样本，因此没有进入成功更新并保存参数的环节。当前`build_optimizer=0`是真实状态，不是计数漏记，也不是迁移时把已训练计数清零。

用户要求先查清历史原因，训练和CB继续暂停。本轮只读检查历史JSON、SQLite数据索引和checkpoint，没有启动课程、构筑、CB、对局、反向传播或优化器更新，也没有修改生产Python源码或任何模型文件。本轮证据整理日期为2026-11-02。

## 1. 执行书与证据范围

主进程依次核对历史课程目录001—006的初始状态、latest指针、实际执行脚本及学习账本；从历史比较追到样本入库和`apply_construction`条件，再检查保存的参数和Adam状态。验收是区分前向评分、比较、生成学习样本、参数更新和保存五个阶段，不以当前实现替代历史执行事实。

允许写入仅本轮诊断记录和文档；checkpoint、数据库、训练hold、课程配置与生产源码只读。SQLite使用`mode=ro`，按construction数据集读取5份小型构筑记录，没有将全部对局轨迹读入报告。checkpoint使用现有WSL CPU Torch的`torch.load(weights_only=True, map_location='cpu')`反序列化，仅比较张量和读取字典，不构造CourseModels或训练器。缺失证据单列；没有执行“试着训练一次”来替代历史诊断。

本轮脚本及完整提取结果位于`.cache/optimizer-learning-audit-20261102/`。可携带摘要见[机器回执](2026-11-02-build-optimizer-learning-audit.json)。

## 2. 参数证据：优化角色确实没有学习

实际检查12份状态：正式课程前`2207-base-006/migrated-initial.weights`，课程001—006各自的`initial-full.weights`，以及002—006现存latest checkpoint。001没有course/latest，仅有迁移初始状态。

| 保存状态 | 目标更新 | 优化更新 | 对局更新 | 协调更新 |
| --- | ---: | ---: | ---: | ---: |
| 正式课程前base-006 | 2 | 0 | 1 | 3 |
| course-001初始状态 | 2 | 0 | 1 | 3 |
| course-002／checkpoint-100 | 4 | 0 | 22 | 30 |
| course-003／checkpoint-5 | 4 | 0 | 23 | 30 |
| course-004／checkpoint-10 | 4 | 0 | 25 | 32 |
| course-005／checkpoint-16 | 5 | 0 | 27 | 37 |
| course-006／checkpoint-1 | 5 | 0 | 27 | 37 |

12份状态的优化器`state`均为0条，Adam步数列表均为空。当前优化模型的29个旧参数张量与正式课程开始前逐元素完全相同；006迁移新增的`mechanism.weight`形状为32×18，全部为零。目标模型则有29条Adam状态，当前步数为5，可以排除诊断脚本对所有角色一律误报为空。

当前课程反馈账本中，已消费角色为`build_goal: 3`、`coordinator: 34`，没有`build_optimizer`，`pending`为空。这里3次目标更新是课程内消费，另外2次目标更新、3次协调更新已在课程开始前写入模型计数；因此上表是累计模型更新数，不应把全部数值都说成正式课程新增。构筑图专项更新计数也为目标0、优化0。

初始化来源记录为`explicit-fresh-untrained-course-models`，迁移记录保留旧参数和优化器状态。综合计数、参数相等、空Adam状态与消费账本，当前优化角色仍处于未学习的初始化状态；整个四模型checkpoint包含其他角色的训练参数，不能笼统推导四个角色都训练过。

## 3. 历史流程具体停在哪里

### 3.1 课程启动前比较：全部失败，没有严格标签

历史原始记录：`_local_cpu_20261027/source/.cache/local-base-training-20261027/2207-base-006/paired-comparison-001/comparison.json`。

两副候选各执行4个seed×2个座次，共16局，均收到原生终局且重放验证成功。16局分数全部为0，两副均分`[0.0, 0.0]`，8组配对差值全部为0，`preferred_index=null`、`status=no_strict_label`。

当时保存的`local_foundation_comparison-0c1458818298824807a96408f6dd8953cff9f3ad8c1d6dfdb2d599b86be7d3ff.py`第145—148行在preferred为空时直接保存“没有严格训练偏好、model_updates=0”并返回。后面的监督样本、`apply_construction(...roles=('build_optimizer',))`及`after-real-model-optimizer.weights`保存分支没有执行。

### 3.2 正式课程第16场后：比较执行了，学习条件仍未满足

历史原始记录：`2207-course-002/collaboration-000016/fixed-model-pairs/comparison.json`。同样是两副候选、16局全部0分、均分`[0.0, 0.0]`、`preferred_index=null`。对应`complete.json`明确记录`actual_four_stage=true`、`optimizer_updates=0`和`paired_training_status=no_strict_label`。

当时归档的`local_course_collaboration-74c63df753dde95b80298e2ab7f13b616e4c54af88cd4d196b8cadb38c4803b0.py`第85行只在非initial且有两副候选时进行比较，第94—99行只在preferred非空时入库严格pair并调用优化角色更新。实际执行停在这个条件之外。课程003—005保留了同一份第16场比较，不是又执行了三次新的比较。

### 3.3 起始构筑与修正流程重启：更新了其他角色，未形成优化样本

初始协作与后来的`collaboration-v2-000000`都按initial处理，完成四阶段并消费目标／协调监督，摘要为`initial_separate_comparison_preserved`。旧执行脚本的比较条件是`if not initial and len(candidates)==2`，因此initial本身不会触发新的优化比较。

最后一次正式worker使用的归档入口为`83dac147977f5c8358322615578bec823cf28a636ee4cf6d8598bbf98dcc5057-local_foundation_course.py`。其第183—185行在每16场或预测差异到期时调用协作。修正课程在原有24场完整对局历史后重新计算流程数量，随后新增2场便暂停；保存状态没有下一轮非initial优化学习消费。暂停状态见`reports/local-training/local-course-001/status.json`。

### 3.4 数据索引验证

当前正式课程SQLite中只有以下5份construction artifact，全部purpose=train，全部pairs为空：

| artifact | goal样本数 | pair数 |
| --- | ---: | ---: |
| pearl-actual-construction-001 | 2 | 0 |
| pearl-fusion-actual-goal-001 | 2 | 0 |
| course-0-native-goal | 2 | 0 |
| course-16-native-goal | 2 | 0 |
| course-v2-0-native-goal | 1 | 0 |

目标角色可以使用合法性／目标满足标签学习；优化角色需要明确better/worse对。`CourseFeedbackUpdater.apply_construction`会拒绝用空pairs更新优化角色。因此，“有构筑训练数据”“目标模型在更新”和“四阶段已完成”都不能作为优化模型学过的证据。

## 4. 它有没有参与构筑选择

有。第16场后的历史四阶段记录中，第2和第4阶段均标为`build_optimizer`与`existing_role_model_uncalibrated`，实际保存分数均为`-0.14170025289058685`。修正流程初始构筑的优化阶段也保存了实际模型分数；这是前向评分路径的执行证据。

当前fill的已核对路径是在`torch.no_grad()`下调用相应角色模型，取得scores后进入候选排序；它本身不调用反向或优化器。真正学习位于反馈消费后的`BuildTrainer._apply`，需要先有合格样本才会依次执行backward、optimizer.step、增加计数并由课程保存。

因此准确判断是：评分调用已接通，正式学习链在样本产生处长期没有进展，评分使用的是未学习的优化参数。程序枚举、合法性筛选，以及后来新增的两层重排所带来的结果变化，不能算成优化模型已获得构筑改善能力。

## 5. 为什么10月31日又有“优化更新成功”的报告

`reports/optimization-20261031/implementation-validation-003/summary.json`确实记录过一次优化角色真实更新：step=1、loss=0.6931191087、13,267个参数元素改变、后续评分读取更新后的副本。

但同一回执明确写有`formal_training_started=false`、`production_state_preserved=true`，生产checkpoint仍为当前这份。它是隔离验证中的模型副本，更新没有写回正式课程，不能算作当前checkpoint的学习经历。本轮仅读取这份历史证据，没有重做该更新或其CB／对局。

## 6. 根因与待处理项

直接原因是历史学习信号只在严格配对比较出现胜负差后产生，而两次真实比较均为全败平局；起始轮又跳过新的优化比较，所以没有任何优化pair进入正式消费。拒绝将平局捏造成严格优劣本身正确，但系统允许优化角色持续零更新，同时继续完成课程与构筑流程，未把“优化模型没有学习进展”作为显著、独立的未完成状态。这是学习链有效性的问题，不能用“四阶段调用完成”代替验收。

旧正式入口还在调用整个协作循环之前就记录`actual_collaborative_role_learning`，但优化更新只是循环内部的条件分支；即使仅更新目标和协调角色、优化角色被跳过，这个外层状态仍会出现。诊断时必须查看逐角色消费记录和参数，不能将这个阶段名称作为优化模型学过的证据。

后续修复应针对可用且有来源的差异监督、样本实际消费、更新后参数及下一次选择读取、正式保存与恢复闭环，并明确报告无有效样本／无更新的停滞；不能只清零计数、重命名checkpoint、把全败平局强标成优劣或直接恢复训练。

本次核验期间，当前工作区的学习接线正在发生变更：已观察到`rubric_learning.py`被`construction_learning.py`替代，协作入口转向新的candidate_pairs／rank_candidates。本报告不对这些并行变更作完成验收，也不把它们当成历史执行代码；上述结论依据冻结历史记录和实际保存参数，不受当前源码变化影响。

本轮未修复生产代码，训练和CB继续暂停，无待答问题。下一步需要修复并验证学习闭环后，再由用户决定正式恢复训练；本报告本身不构成恢复授权。

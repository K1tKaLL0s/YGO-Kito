# 2026-11-11 基线整合与设计归一

本次以 _publish_20261030 为唯一开发基线，外层仓库作为资料与资产归档。源码保存、旧树吸收、设计归一和工作树清理均在本地进行，不推送远程。

## 保存与吸收

| 来源 | 保存提交/依据 | 处理 |
| --- | --- | --- |
| 当前开发树 | 297da84，451文件 | 保存既有修改/删除及322个新增源码、配置、测试、资料文件；389个Python语法通过。 |
| 外层资料树 | 2a17c51 | 保存README/忽略规则及10月29日原件。 |
| 旧CPU source | d9856ba | 保存32个实质修改及34个新增文件，忽略换行噪声；资产保持原位。 |
| github-source | 4b70191 | 保存11文件监督WIP与下游CB修订；全部分支导入archive/github-source。 |
| 构筑旧树 | 041c72b | PR #8 / d01f07f 已吸收该最终修复，后续S0—S6取代四次交接。 |
| 统筹旧树 | 77b5c55 | PR #8已吸收调度/共享adapter/课程修复，局部审查日志保留本地。 |
| 决斗旧树 | 2933367及99567f4 | PR #8已吸收真实采样、CB计划读取、LoRA动作分页；后者保存迁盘路径。 |
| 效果旧树 | 45fb85a | PR #8已吸收效果条件、次数及Adam迁移相关修复。 |
| 多因子旧树 | 9368c76及edae0ef | PR #8明确吸收该版本；后续识别模块演进由当前树保留，迁盘路径保存。 |

完整输入清单与原整合证据见 configs/repair-integration-inputs-20261028.json、提交d01f07f的PR #8说明和历史整合报告。旧source与github-source中的监督、task/Side/proof保护及基础CB分离已由该整合与后续修订承接；旧固定四次交接、局限候选词表和已删除私有评分账本不回灌。旧脚本audit_model_auxiliary.py由v1_1/v2继承，local_foundation_fusion.py已由后续课程入口替代，均可从archive/outer分支恢复。

4份迁盘报告已分别保存至edae0ef/99567f4并导入历史分支，无须重复覆盖。旧缓存/日志不强制加入Git；自动审批拒绝该项后改为原位保留证据，只有已保存源码和登记进入清理。

## 文档

现行正文为 [设计入口](../current/README.md) 下6份专题文件。16份被替代设计文件退出当前开发树，46份执行/来源/示例资料分类迁移；详细清单见 [迁移记录](2026-11-11-document-migration.json)。保留有效公式、量词、条件、原任务和后续修订，不将旧阶段状态并入正文。

原始设计DOCX/PDF以Git历史保留；技术参考和学习文档继续保留。10月27日原始用户消息及附件分类独立存入design-sources，具体牌组/CB例子存入examples。

## 并行工作边界

本轮保存提交形成后，另一项认知训练工作新增 docs/plans/2026-11-11-axis-generic-v30-b19-training.md，并修改training/axis_generic/automatic_v3.py、full18_sources.py、prepare_v3.py、readiness_v3.py，随后还修改full18_annotations.json。它们属于进行中的训练工作，保留当前目录原位，不纳入本次整理提交、不覆盖、不重启或终止其作业。基线提交以本轮保存的版本为准，待该工作完成后按实际结果合入。

## 验证与剩余运行问题

安全CPU白名单正在项目已有Linux CPU-only Torch2.9.1环境执行，结果将写入本报告。源码语法已核对；文档迁移链接和工作树登记在清理后核对。

既有GPU短试运行仅完成24次前向和两份40/15/15候选，静态评价/参考/S4/S5/CB未完成；静态评价性能瓶颈仍为后续工作，本次不开展性能优化。run-007保持原停止存档；构筑/卡库历史局部测试不替代完整运行成绩。

## 旧树清理

已注销外层7棵旧工作树，并退役github-source独立仓库。删除范围限于已保存提交中的5,210个跟踪文件及旧Git入口；未递归清空资产目录。精确路径和保存提交见 [清理回执](2026-11-11-retired-worktrees.json)。外层目前只剩其资料归档主树；外层归一提交为c3b458a，现行仓库archive/outer/main已同步。

GPU补检结果见 [GPU环境报告](2026-11-11-gpu-environment.md)：四角色CUDA小样更新与恢复通过，但现有GPU Python3.10低于项目>=3.12要求，旧CPU课程入口和训练状态迁移未完成。后续训练、正式运行使用GPU，CPU检查仅是软件回归。

外层独立DSH插件8文件已另行保存，安装路径保持原位；未纳入游戏程序。外层OCG规则3文件与现行已跟踪规则正文/资源逐字节相同，已删除重复副本。

## 三棵开发树

| 职责 | 分支 | 实际目录 |
| --- | --- | --- |
| 统筹、跨模块整合与当前并行作业 | codex/coordinator | N:\YGO-Kito\_publish_20261030 |
| 决斗 | codex/duel | C:\Users\27499\.codex\worktrees\ygo-duel\_publish_20261030 |
| 构筑 | codex/construction | C:\Users\27499\.codex\worktrees\ygo-construction\_publish_20261030 |

后两棵由Codex应用创建和登记，只含受版本控制的源码与文档；模型、数据、运行日志和大体积生成物继续使用N盘现有资源路径，不复制进新树。三分支以本次整合提交统一，main用于稳定整合基线。统筹树保留并行认知工作的未提交内容；其未完成部分不进入另两树。

文档迁移附带3处代码/配置同步：deployment_prepare.PREFIXES加入docs/current与docs/examples，课程配置与ScenarioCourse的验收来源指向现行训练正文，未改评分或训练数值。Python语法、JSON及打包收录/缓存排除检查通过。Windows定向20项中17通过，2项因该Windows Python缺少锁定Torch/Scipy依赖失败，1项因沙箱无创建symlink权限错误；训练场景7项全部通过。完整CPU白名单在具有锁定依赖的WSL环境独立执行，结果另记。

真实打包入口已从干净决斗树执行：571个成员验证通过，现行设计包含在包内，缓存排除。Windows中文路径需PYTHONUTF8=1或-X utf8；初次默认GBK解码失败后以UTF-8重试通过。整合文档相对链接最终检查无断链。

清理后入口核验发现local-training.ps1的supervisor旧路径，已改为当前$linuxSource。PowerShell解析通过，真实只读Check返回source_root=/mnt/n/YGO-Kito/_publish_20261030、resource_base=/mnt/n/YGO-Kito/_local_cpu_20261027、training_held=true、worker_started=false，既有course-006状态仍可定位。对应旧操作说明已改为当前入口；未启动/恢复作业。外层独立插件保存提交为49cd2b6，archive/outer/main已包含。

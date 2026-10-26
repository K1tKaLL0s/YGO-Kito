# CloudStudio 同步范围与云端接管

基于 6cef642 的独立分支仅同步说明、实测汇总、原采集脚本和资产来源。原生资源与 checkpoint 未放入 Git；migration-assets.json 记录保存路径、SHA-256、角色和工程更新次数。CPU 准备停在来源获取，下一任务从实际资产核对开始。

| 能力 | 已有证据／入口 | 当前边界与后续动作 |
|---|---|---|
| AI 真实对战 | normal_duel.py、cpu_training.py；历史 16 局 CPU／GPU 配对终局 | 当前工程权重和指定 bot／牌表的实际覆盖；继续核用户真实牌表 |
| 训练与保存恢复 | cpu_training.py、group_runner.py、group_initialization.py；真实梯度更新与 CUDA 恢复记录 | 工程更新次数已登记；正式训练与能力验收尚未开展 |
| 自主构筑和课程 | scenario_course.py；docs/development/scenario-course-runner.md | host、历史卡池、bootstrap_task、允许池与独立对手仍缺 |
| BO3 | match_runner.py 的 MatchRunner／换备与先后策略 | 代码与回归已有；本轮 CloudStudio 新机功能 BO3 未完成 |
| 学习边界 | active_environment、source binding、合法动作 DTO、训练／冻结评估分账、100h budget | 必须用实际工件和分期数据继续核验 |
| 模型相互对练 | 已有单席位模型动作、工程采样与比赛组成模块 | 完整双模型课程和独立联赛／评估须代码审查及功能验收；本次未新增对抗训练或用其取代未执行的外部对练 |
| 可视化产品 | 原设计与客户端互操作任务 | 当前交付以 headless／CLI 为主，用户图形对战操作面需单独实现核验 |

原采集脚本保留在 scripts/experiments/cloudstudio_20261026/，供审计其测量方法。它们依赖历史绝对路径并会采样和更新独立副本；本次只做语法检查，没有执行。后续重用先按 README 改到新输出目录，避免覆盖旧证据。

静态核查与发布记录以最终提交／PR 为准。基线 617／617 是此前记录，本次未重跑。受控资产交付由用户选择授权目标后再迁移；不向不明第三方上传。源表若无明确再分发许可，按收据从原来源获取。

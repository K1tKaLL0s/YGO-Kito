# 2026-10-27 基础模型学习实录

代码基线main c1157ca5add6c29149eccf7106226b1099e63d8c加工作区补丁。CPU4核8G，0.5机时/小时。

- 参考卡表仅供独立评估。旧参考learner技术分支及失败记录保留，正式计数0；本轮未继承其参数、优化器或RNG。
- 2207固定珠泪主题；公开合法卡池/禁表、字段385、空表输入。程序提出任务/候选，目标与优化网络评分，约束求解填卡。完整卡表见[实际生成卡表](2026-10-27-generated-pearl-base-deck.zh-CN.md)。牌表质量差，无关组件多、关键珠泪怪兽放在副卡。
- 新鲜随机四角色起点，无源检查点。16:51 UTC目标base更新1：loss0.7269343，14,057参数元素变化，L2 0.1182228。优化/决斗/统筹当时均0，未挂LoRA。
- 本次标签来自公开硬约束：实际合法候选与确定缺一张主卡的非法样本。未知路线未当负例，没有竞技偏好或胜率标签。融合CB、整图执行、竞技质量均未验证。正式课程BO1/BO3计数均0。
- 17:10:57 UTC已进入真实引擎采样与全参PPO；当前目录为`.cache/base-training-20261027/2207-autonomous-v4/duel-001/`，完成/失败以最终status/result为准。

## 修正与恢复

历史fixed_deck不再作为learner输入；珠泪主题约束在kernel排名截断前应用。host/model/feedback支持明确fresh/base、无adapter状态与全参优化器。目标可独立学习，优化必须有严格比较标签。

旧机器人资格把全Python包源码纳入指纹，本次学习文件改动使其失配。原绑定已精确重建：机器人源/程序集/牌表/工具/资源等原字段相同，仅学习/课程文件变化。显式非driver兼容收据保留原终局、原binding_sha256、完整旧/新源码图和绑定前像；driver、观测、隐私、规则实现变化不能由此通过。没有重跑资格对局，没有改写为新源码已完成终局。

- 新鲜初始状态：`.cache/base-training-20261027/2207-autonomous-v2/initial.weights`，SHA256 `80f434c70cdb99d3361679809dfe17808c34abff59789b8809a6a3db282e4477`。
- 第一目标更新：同目录`latest.weights`，SHA256 `fb693e40d14811869777aed26296319afadf865b95582b230956203e4c613811`。
- 当前继续目录：`.cache/base-training-20261027/2207-autonomous-v4/`。两次显式源码迁移保留所有角色参数、基础优化器、调度器、RNG和游标；原文件保留，`source-migration.json`记录来源。搜索缓存按新绑定重建，实际更新数保留。
- 保留完整checkpoint、`index/`、`feedback-state.json`、binding、配置、迁移收据和运行结果。`train_duel.py`以`adapter_session=None`执行全参PPO；已有in-flight/result时禁止自动重放同场。

直接继续真实构筑/基础学习，出错修该错误，不新增预检、资格批次或测时。四角色分别起步后协作；LoRA用于后续适配。优化竞技比较须固定策略、对手和预算。三期顺序、每期600完整BO1+400完整BO3与独立验收保持，见[需求复核](../plans/2026-10-27-training-design-current.md)。

## 预算

本次最多20机时，不加购。初始28.58，保留余额下限8.58。17:00 UTC面板22.67、倍率0.5；按账户全部差额保守计已用5.91、授权余量最多14.09，不能把这些全归因于本实例。平台自动关机2026-10-27 17:39 UTC，留保存/归档缓冲。

17:08:34 UTC Codex周剩余57%；20%保存停止，不用重置卡。空间保持30GB范围。用户已同意代码、权重、优化器、RNG和恢复账本公开到既有YGO-Kito仓库；仅按白名单归档，排除凭据、个人数据、core dump及无再分发许可第三方文件。

## 17:14 UTC首场真实基础PPO结果

完成1个真实BO1基础学习小局，无异常。决斗base实际更新1次，22,845参数元素变化，L2 0.1501346；目标base1，优化/统筹0。实际197个learner决策样本、429个引擎决策窗口。完整状态为.cache/base-training-20261027/2207-autonomous-v4/latest-after-duel-001.weights，SHA256 543801acd1e9a57361c0cee9f5d591db565456e533a6ba26ad576bb8ac937520。正式课程计数仍0，CB与构筑质量未验收。胜负与种子见同目录milestone-001.json。

## 17:35 UTC构筑循环修正

原链已实际执行目标→优化→目标→优化，四段入表/提案/保留表/diff与真实失利反馈均保留。无独立比较证据时保留incumbent，不强制改卡，不把最后产物称最优。本轮未训练参数：累计目标base1、决斗base1、优化/统筹0。真实优化训练、效果积木、融合CB仍待完成。当前完整恢复点为.cache/base-training-20261027/2207-autonomous-v5/latest-after-four-stage.weights，SHA256 410c60009fb0748300fad8b2315fbf3ec9b1d696140c630a6894cecace77e3b5。参见[四段记录](2026-10-27-actual-four-stage-construction.zh-CN.md)。第二场未运行：子进程缺PYTHONPATH，未采样/未更新，旧错误保留。

# CloudStudio 恢复源与本机 CPU 接续


2026-10-27。本分支从 `c1157ca5add6c29149eccf7106226b1099e63d8c` 接入用户导出的
`20261027-foundation-002`，保留原始包、清单、源码补丁和恢复状态。后续以本仓库分支为来源。

当前设计依据为 [训练设计复核](../plans/2026-10-27-training-design-reconciled.md)
和 [源码差异复核](../reports/2026-10-27-training-design-code-gaps.md)。后者描述基准提交，
其中部分缺口已由此分支的源码补丁处理，不能把历史差异全部当作当前仍缺。

## 恢复包与真实进度

包位于 `artifacts/checkpoints/20261027-foundation-002.tar.gz`，7,368,936 字节，
SHA256 `872047224d99ff069fec7aeb12d2a98319efc7cab27cf49a02b60c2cacd27fde`。
清单 SHA256 `2539298a7e31d55839fd081f7100a8e3373cb20d060d5d61161782516513ca87`。
47 个有效载荷文件另加包内 README/manifest 两份控制文件，总解包字节 24,830,703。

最新完整 state 为 `.cache/base-training-20261027/2207-autonomous-v5/latest-after-four-stage.weights`，
7,490,687 字节，SHA256 `410c60009fb0748300fad8b2315fbf3ec9b1d696140c630a6894cecace77e3b5`。
它保存四角色参数、base 优化器/调度器、RNG、游标和内核状态；DataIndex/反馈状态分别随包保存。
实际 base 更新为目标 1、决斗 1、优化 0、统筹 0；正式 BO1/BO3 均为 0。
四段目标→优化→目标→优化曾完成推理，未形成真实质量监督，保留 incumbent；
不能把四段前向或单场胜负称作优化学习或质量提升。

当前自产构筑是初稿。效果积木接线、珠泪融合 CB、可归因构筑比较监督、统筹学习与统计反馈仍需继续。
参考构筑仅供独立评价，不输入 learner，也不拆成候选池或训练答案。
旧参考 learner 分支的更新不计入本分支训练量。保留 2207→2210→2610、各期 600 完整 BO1
加 400 完整 BO3 和独立评估规则；不另设预检、资格套餐或重新测时。

## 从 GitHub 取回与解包

```bash
git clone --branch codex/cloudstudio-foundation-20261027 https://github.com/K1tKaLL0s/YGO-Kito.git
cd YGO-Kito
python3 scripts/unpack_foundation_export.py --destination .
```

解包器先核原始包与每个成员哈希，再写入；遇到已有不同内容会停止并保留原文件。
当前分支已经包含源码修改，**不要再次应用包内 source-final.patch**。
该补丁的 SHA256 为 `15a43b3f43f2400ac84649b747b66cfb2aecda94363aa8a8e28292b9a1108c1a`，
用于追溯原 CloudStudio 差异。

## 必需环境和原生资产

Linux x86_64 使用 CPython 3.12.14 和 `requirements/ci-cpu.txt` 的官方 CPU 哈希锁。
本机已有 Windows venv 保留；Windows wheel 不能充作 Linux 安装完成。

```bash
python3.12 -m venv .venv-local
.venv-local/bin/python -m pip install --require-hashes -r requirements/ci-cpu.txt
PYTHONPATH=src .venv-local/bin/python scripts/prepare_native_engine.py --root .cache
```

`configs/native-sources.lock.json` 给出 client/core/Lua/脚本/卡库的精确上游 commit；
`prepare_native_engine.py` 从固定来源取得源码并用 g++ 构建，生成实际本机 receipt。
已有同身份源码、卡库与脚本可复用。N 盘本机本次复用它们，已有 Linux g++ 编译的核心为
`42b468cced6e472c0df4b2561f71c63e52bdbda01b49c0ccc11230f83878a731`。
重编译导致的二进制哈希变化须显式记录，不能直接修改旧 checkpoint 的绑定后冒称同绑定 resume。

恢复包**没有**第三方 CDB、Lua 脚本、core 源码/二进制、WindBot 源码/程序集、Mono/.NET、
Python 环境或凭证。`configs/bot-sources-v1.json` 给出机器人固定来源和逐文件身份；
[维护机器人部署说明](maintained-bot-deployment.md) 给出源码取得/构建入口与许可证边界。
原云端 bot audit/qualification 随包保留，包含 `/workspace` 和原工具路径；
本机须取得对应真实资源并显式迁移，不能把这些 JSON 的存在称作本机已运行合格。
本次一次正常源码取得在 `Decks/AI_Rank8.ydk` 发生传输错误，未发布半成品目录；
这是待修复的依赖问题，不以弱规则对手或 fixture 充抵正式人机课程。

## 训练接续边界

原始状态和绑定留在包中；本机续训保存到新目录，保留完整优化器、RNG、数据索引与已提交游标。
源码、原生资源或路径变化使用明确迁移收据，原值和新值并存。
包内 `run_next_duel.py`、`run_four_stage.py` 是原实际运行脚本，恢复入口须设置 `PYTHONPATH=src`。
这些脚本仍需要真实 bot 与本机绑定迁移，**不是免依赖的一键启动器**。
训练运行时按实际错误针对修复；不放松合法动作、隐藏信息隔离、完整大场计数、预算或断点边界。

本保存批次未跑新增预检、单测、功能场、资格批次或时长测试；未声称 CI 或训练验收通过。
本机准备、实际学习、独立评估与最终验收分别记录。CloudStudio worker 退出不证明实例停止计费；
网页关闭/实例停止须有独立现场证据，本机任务没有越过浏览器安全限制继续操作。

# M2a：真实规则核心的最小召唤闭环

此入口确实加载本云端从上游源码构建的 YGOPro core，并调用 `create_duel_v2/process/get_message/set_responsei/set_responseb/query_card`。它只支持固定通常怪兽测试范围，**不是完整决斗、效果链路或 PC 客户端兼容验收**。完整对局入口 `duel-run` 仍拒绝执行。

来源由 [native-sources.lock.json](../../configs/native-sources.lock.json) 固定。客户端 `mycard/ygopro` 的 `ocgcore` 和 `script` Git 子模块分别指向锁中的核心与脚本提交；构建脚本会检查这两个关系及协议 `0x1362`。核心同一提交从 Fluorohydride 上游取得；Lua 从 Lua 团队官方开发仓库的 5.4.8 提交构建。没有运行下载的引擎、premake 或其他第三方可执行文件。

## 复现

要求本仓库 checkout、Python 3.12+、Git、G++ 和网络。使用现有项目虚拟环境；没有新增 Python 运行依赖，也不需要 PyTorch、CUDA、CMake 或 Ninja。

```bash
cd /workspace/YGO-Kito
PYTHONPATH=src .venv/bin/python scripts/prepare_native_engine.py
.venv/bin/python -m ygo_kito native-smoke --root .cache --seed 7
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s integration_tests -v
```

构建下载并检出固定源码，使用客户端子模块关系校验后编译，生成 `.cache/engine-build/libocgcore.so`、`build.log` 和 `receipt.json`。源码、卡库与生成库都保存在忽略的缓存目录，不提交上游素材或二进制。已有生成库需显式 `--rebuild` 才会被替换；已修改的上游跟踪源码会被拒绝。`--root .cache/native-clean` 可在另一个干净缓存复现，本次已经实际验证。

`receipt.json` 包含来源锁哈希、来源提交、编译器/命令、库/卡库/脚本集/禁表/协议文件哈希。运行前校验这些资源；缺失、改动或未准备时失败，没有自动下载或模拟后备。库哈希是本次具体构建产物的实测值，不承诺不同编译器或路径生成相同二进制。

## 当前真实验证范围

- 从固定真实卡库选择 40 张不同的、OCG 标记、1–4 星通常怪兽；每张 1 枚。选出的 ID 会写入结果，形成明确的自定义卡池，不声称它是历史课程或合理构筑。
- 固定社区 `lflist.conf` 的 `2026.10` 节，检查张数与禁限数量；没有伪造官方禁表校对已通过。卡库含 15,071 条记录，本测试只覆盖上述 40 张。
- 双方从 40 张主卡组、5 张起手、8000 LP 开始，使用规则 5；不启用 `DUEL_TEST_MODE` 或 `DUEL_SIMPLE_AI`。种子驱动真实核心 RNG。
- 解码真实 idle 候选、单个选区、表示形式和空连锁通过提示；原生响应只在适配器内部保存。非空效果连锁、其他消息或选择组合会明确失败。
- 选择核心提供的通常召唤，跨多个窗口提交。读取到 `MSG_SUMMONED` 后，再以核心查询确认手牌 5→4、己方怪兽区 0→1，没有 `MSG_RETRY` 或 Lua 诊断。
- 公开状态和己方手牌进入观察。对方手牌只给数量，牌组只给数量；对方场卡先查表示，再决定是否查询身份。实际 RNG 种子从原生策略请求中删除（`context.seed=null`），只保留在独立复现结果中。普通日志只记录消息类型，不保存原生隐藏载荷。
- 单个进程只允许一个原生实例，上游全局回调不能并发混用。结束和错误路径释放引擎；提交绑定活动窗口并拒绝重复/迟到/候选外响应。

31 项标准库单元测试与 4 项独立原生集成测试分开运行。后者资源缺失会失败，不 skip，不用 fixture/mock 替代引擎；验证两次同种子真实召唤一致、实际观察、响应窗口、卡池/禁表检查、生命周期和 CLI 子进程。

## 尚未完成

完整对局、效果和复杂连锁、回放、真实 PC YGOPro／萌卡联机/单机验收、独立比赛计时认输、所有隐藏区域的完整信息边界仍待实现。当前只检验通常怪兽范围，不推论珠泪或其他效果卡可用。观察的 LP/所有者等字段按当前无伤害/无控制权变化的限定场景提供，不可直接扩展至一般对局。

当前卡池是显式自定义子集，未冻结三期发行截止日或训练牌表；社区禁表尚待官方原文对照。素材库未找到明确许可，卡片文本等权利没有确认，不作为可分发素材。核心 MIT、脚本及客户端的 GPL-2.0 文本和 Lua 头文件许可已读取并记录来源；正式发行仍须单独审查实际组合。本次仅发布自有适配代码、元数据与测试记录。

模型、PPO、构筑训练、LoRA 实现与硬件性能验收保持后续阶段；学生练习文件原样保留。此处的通常怪兽牌组只服务接口验证，不替代用户的构筑目标，也不作为模型表现。

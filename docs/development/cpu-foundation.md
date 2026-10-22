# CPU 基础骨架（M1）

本实现由 Codex 辅助生成，用于工程基础，不计作用户亲手完成 Python 课程。遵循[统一说明 1.1](../plans/2026-10-22-unified-development-spec.md)与[阶段清单](../plans/2026-10-22-phase-1-cpu-checklist.md)。

## 运行

要求 Python 3.12+；运行时和测试均只依赖标准库。云端工作目录为 `/workspace/YGO-Kito`。

无需安装即可检查：

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -m ygo_kito --config configs/cpu.toml status
```

本云端已有 setuptools，实际离线安装命令已经通过，不下载额外依赖：

```bash
uv --cache-dir .cache/uv pip install --python .venv/bin/python --no-build-isolation --offline -e .
.venv/bin/ygo-kito --config configs/cpu.toml config-check
.venv/bin/ygo-kito --config configs/cpu.toml db-init
.venv/bin/ygo-kito --config configs/cpu.toml status
```

配置路径相对配置文件解析；示例数据库落在仓库 `.cache/ygo-kito/index.sqlite3`。`status`、`config-check` 不创建文件；`db-init` 显式建立空索引，重复执行不清空数据。不兼容或外部 SQLite 文件会被拒绝，没有自动迁移或覆盖。

`cards-import <JSON>` 原子导入，`card-show <整数ID>` 查询。导入文件包含 `schema_version: 1`、`cards` 数组与 `annotations` 数组；没有默认下载器、真实卡池或预置构筑。相同记录可重导，ID 冲突且内容改变会失败并回滚整批；目前更新卡效需建立独立版本数据库，尚无多版本原地升级功能。

`request-check <JSON>` 校验请求结构；`action-check <请求JSON> <选择JSON>` 校验决策窗口与候选成员关系。两者明确返回 `validation: "contract_only"` 和 `rules_verified: false`。`duel-run` 返回错误 `ENGINE_NOT_IMPLEMENTED`、退出码 2；没有创建对局。成功退出码为 0，结构/存储/未接入错误为 2，错误 JSON 输出到 stderr；命令行参数语法错误由 argparse 处理。

## 数据契约

| 对象 | 当前字段与意义 |
| --- | --- |
| `CardRecord` | 稳定整数 ID、按语言记录名称/原始效果、别名、类型、来源引用与版本 |
| `Annotation` | 独立 annotation ID、card ID、effect/theme/role 维度、原子标签、情境条件与来源 |
| 标签层 | fact / model_inference / llm_review / human_correction 分别保存，不覆盖卡片事实；显示用 `·` 联合标签 |
| `Versions` | core、scripts、cards、protocol、card_pool、banlist 的独立版本引用；不是实际文件哈希验证器 |
| `RunContext` | run ID、种子、环境版本；可选模型/LoRA 版本元数据，支持四种角色，不实现模型或适配器加载 |
| SQLite | cards、card_names、annotations、runs；schema version 与 application ID，来源冲突拒绝、事务回滚 |

缺失语言可以不填，不编造翻译。当前只是最小原始文本与来源/标签底座；详细属性、完整效果结构（费用、时点、对象、自肃等）、情境关系图、卡组合法性、官方禁表导入与轨迹分片尚未实现。标签命中不代表卡效、路线或构筑合法。

## 观察与动作契约

`DecisionRequest` 的 schema version 为 1，包含 context、duel ID、decision ID、observation 和 actions。Python 类与严格 `from_dict` 入口见 `src/ygo_kito/contracts.py`。

观察只允许两个玩家的公开计数、当前回合/阶段、卡片视图和公开历史。卡片使用不暴露身份的实例 `ref`，标记 public、observer 或 hidden；hidden 的 card ID 必须为 null。observer 私有卡必须属于当前观察者的可见侧。牌组内容/顺序不是可表达区域；未知额外字段会失败。对方盖卡仍可用 opaque ref 成为目标，不要求暴露卡 ID。公开历史是适配器明确标记的已公开事实，与未知信息估计分开；本次没有概率估计模块。

这些是 DTO 的结构检查，**不能识别被错误标成 public 的暗牌、藏在字符串中的秘密或错误来源的历史**。真实适配器必须从玩家视角投影并接受真实核心的泄漏测试；当前没有接入，不宣称实际策略输入无泄漏。

动作是引擎已展开的候选，由 action ID、类型、卡片引用及可选数值组成。模型只选择候选 ID，原生响应字节由未来适配器私有持有。数量、对象、素材与顺序等复杂选择将通过多个决策窗口衔接；当前不实现完整原生提示解码或组合选择规划。

`ActionSelection` 绑定 run/duel/decision ID，拒绝错局、错窗口和候选之外的动作。纯函数校验不提交响应，不消费窗口，也不提供实际规则合法性证明。真实适配器还须维护活动窗口、拒绝重复响应，完成连锁/回放一致性以及独立超时认输控制。

## 验证边界与下一步

29 项 unittest 使用专门的 `tests/fixtures.py` 合成记录；不是原学习包，不使用学生 TODO，不实现或模拟游戏王规则。覆盖结构拒绝、可见标记检查、合法候选成员关系、SQLite 持久化/回滚/数据库识别、配置、CLI 安装后执行与未接入失败。测试成绩不代表真实对局、规则、模型强度或性能目标通过。

下一步是 M2：核对并锁定 PC YGOPro／萌卡相容组合，接入真实 core，取得真实提示并提交一次合法响应，再完成对局/回放与真实信息边界测试。CMake/Ninja 仍未安装；当前无核心来源阻碍判断，也没有已验证兼容性。三执行模型、轻量统筹学习、PPO 与 LoRA 实现均留在后续阶段，LLM 不作为前置。没有付费 GPU、腾讯云、API 购买、大模型下载或 CUDA 安装。

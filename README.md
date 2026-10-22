# YGO-Kito

游戏王 AI 项目的私密设计、资料与 CPU 基础开发仓库。

## 当前开发入口

**请先阅读 [统一开发说明与训练交付计划（2026-10-22，UTC+8）](docs/plans/2026-10-22-unified-development-spec.md)。** 本文承接《游戏王AI项目设计定稿.docx》1.0（2026-10-19），合并本轮逐项确认；明确更新处以统一说明为准，未更新的原定稿意图继续保留。原件不是实现完成证明。

- 模型组：决斗模型＋构筑目标/优化两个子模型，由轻量统筹模型和确定性程序包裹；三个执行模型独立小 Transformer，共享数据规范，不强制共享权重。
- 先训练基本模型组，LLM 后置且非必需。**LoRA 是基模后的常规持续适配路线**，不是旧文所说的完全可不开展。
- 开发使用云端 Codex，训练计划使用腾讯云；约 100h 总上限，初始分配 5/25/25/20/10/15 小时，按吞吐实测调整，不保证达标、不自动授权付费或训练。
- 珠泪哀歌三期课程：2022 年 7 月、2022 年 10 月、2026 年 10 月；目标→改进循环、合法可见信息、独立 BO3 与跨牌组迁移验收。
- 第一阶段真实规则核心，第二阶段训练前验证 PC YGOPro／萌卡兼容。**手机端及 YGOMobile 暂移出本期范围**；云端训练与 PC 推理/微调的硬件压力仍必须记录。
- 构筑预测与实战反馈：百场内明显落后预警、千场内明显落后强制重构；具体统计阈值实施前冻结。

当前已完成 CPU 工程骨架及首个真实原生规则小里程碑：结构化数据/来源/标签、SQLite、观察/动作契约、配置与 CLI，并从固定上游源码构建 core，跑通一次真实通常召唤（手牌 5→4、怪兽区 0→1）。31 项单元测试与 4 项真实引擎集成测试通过。**完整对局、效果/回放及 PC 兼容门槛尚未通过；模型与训练尚未开始。** 具体版本、模型大小、超参数、兼容性和资源指标须实测；本云端开发不表示离线本机已同步。

运行与验收见 [CPU 骨架说明](docs/development/cpu-foundation.md)、[阶段任务清单](docs/plans/2026-10-22-phase-1-cpu-checklist.md)及[云端启动实证](docs/reports/2026-10-22-cloud-bootstrap.md)。本云端可执行：

```bash
cd /workspace/YGO-Kito
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -m ygo_kito --config configs/cpu.toml status
```

`duel-run` 当前以 `ENGINE_NOT_IMPLEMENTED` 失败；[native-smoke](docs/development/native-smoke.md) 需显式准备原生资源，只覆盖一次真实召唤。纯接口测试与合成夹具不计入真实引擎证据。原学习包保持不变，学生 TODO 与亲手新增测试仍由用户完成。

[2026-10-21 旧阶段计划](docs/plans/2026-10-21-development-and-training-budget.md) 与 [旧技术复核](docs/reviews/2026-10-21-technical-route-review.md) 保留决策历史，不再作为最新选型入口。尤其旧文的 LoRA 可选、移动端后续排期、预算未分配和架构待讨论表述，不覆盖统一说明。

## 现行文档

- [游戏王AI项目设计定稿.docx](docs/current/%E6%B8%B8%E6%88%8F%E7%8E%8BAI%E9%A1%B9%E7%9B%AE%E8%AE%BE%E8%AE%A1%E5%AE%9A%E7%A8%BF.docx)

## 学习材料

- [游戏王AI项目亲手实作手册.docx](docs/learning/%E6%B8%B8%E6%88%8F%E7%8E%8BAI%E9%A1%B9%E7%9B%AE%E4%BA%B2%E6%89%8B%E5%AE%9E%E4%BD%9C%E6%89%8B%E5%86%8C.docx)
- [游戏王AI亲手练习包.zip](docs/learning/%E6%B8%B8%E6%88%8F%E7%8E%8BAI%E4%BA%B2%E6%89%8B%E7%BB%83%E4%B9%A0%E5%8C%85.zip)

## 技术参考

- [游戏王AI_技术选型调研_2026-10-18.docx](docs/reference/%E6%B8%B8%E6%88%8F%E7%8E%8BAI_%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B%E8%B0%83%E7%A0%94_2026-10-18.docx)
- [游戏王AI_技术选型调研_2026-10-18.pdf](docs/reference/%E6%B8%B8%E6%88%8F%E7%8E%8BAI_%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B%E8%B0%83%E7%A0%94_2026-10-18.pdf)
- [游戏王AI_现有技术与混合部署调研.pdf](docs/reference/%E6%B8%B8%E6%88%8F%E7%8E%8BAI_%E7%8E%B0%E6%9C%89%E6%8A%80%E6%9C%AF%E4%B8%8E%E6%B7%B7%E5%90%88%E9%83%A8%E7%BD%B2%E8%B0%83%E7%A0%94.pdf)
- [游戏王对战AI_项目核验与自建路线_2026-10-18.pdf](docs/reference/%E6%B8%B8%E6%88%8F%E7%8E%8B%E5%AF%B9%E6%88%98AI_%E9%A1%B9%E7%9B%AE%E6%A0%B8%E9%AA%8C%E4%B8%8E%E8%87%AA%E5%BB%BA%E8%B7%AF%E7%BA%BF_2026-10-18.pdf)

## 历史草案

- [YGO模型设计草案_小幅修订版(1).docx](docs/archive/YGO%E6%A8%A1%E5%9E%8B%E8%AE%BE%E8%AE%A1%E8%8D%89%E6%A1%88_%E5%B0%8F%E5%B9%85%E4%BF%AE%E8%AE%A2%E7%89%88%281%29.docx)
- [YGO模型设计草案_小幅修订版.docx](docs/archive/YGO%E6%A8%A1%E5%9E%8B%E8%AE%BE%E8%AE%A1%E8%8D%89%E6%A1%88_%E5%B0%8F%E5%B9%85%E4%BF%AE%E8%AE%A2%E7%89%88.docx)
- [YGO模型设计草案.docx](docs/archive/YGO%E6%A8%A1%E5%9E%8B%E8%AE%BE%E8%AE%A1%E8%8D%89%E6%A1%88.docx)
- [标签驱动游戏王AI_设计草案.pdf](docs/archive/%E6%A0%87%E7%AD%BE%E9%A9%B1%E5%8A%A8%E6%B8%B8%E6%88%8F%E7%8E%8BAI_%E8%AE%BE%E8%AE%A1%E8%8D%89%E6%A1%88.pdf)

## 归档说明

- [原件清单与 SHA-256](archive-manifest.json) 记录 11 份原件的来源 ID、字节数和哈希。
- 练习包保持 ZIP 原样，原归档时已静态检查其中 6 个教学文件；本次工程测试独立于学生练习，不解包覆盖或代填学生 TODO。
- 原件归档时未开始开发；现已新增上述 CPU 骨架，仍未启动训练或下载模型。未收录密钥、账户配置、模型权重、大型数据或无关私人资料。未核实的 ygo_work_handoff.zip 未收录。
- 原件均保留在原来源；两个小幅修订版的字节和哈希不同，分别归档。
- PDF 中原有的 C2PA Content Credentials 来源元数据保留在文件内。


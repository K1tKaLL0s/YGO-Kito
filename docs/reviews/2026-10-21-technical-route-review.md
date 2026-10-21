# 2026-10-21 技术路线复核

状态：本轮建议，未通过原型验证。本文记录本轮公开资料复核的建议，不改写 2026-10-19 的 1.0 定稿，不把候选技术当作已确定方案。

## 路线与选型

建议按“兼容规则引擎闭环 → 规则/搜索基线 → 小候选排序或策略价值网络 → 可选 LoRA”推进。Python、PyTorch、SQLite 是合理候选；客户端框架和 Android 推理后端仍需原型验证，旧稿中的 Flutter 推荐不视为确定选型。

原型应冻结同一兼容组合的 core、scripts、cards.cdb、禁限规则、协议和 bot 版本。EDOPro core 明确说明与非衍生分支不兼容；WindBot 属于 C#、YGOSharp/SRVPro 生态，不能直接当作通用 Python 内嵌库使用。[EDOPro core 说明](https://github.com/edo9300/ygopro-core/blob/master/README.md)、[WindBot 项目](https://github.com/IceYGO/windbot)。

许可必须按实际组合核查：EDOPro core 为 AGPL-3.0-or-later，Fluorohydride core 和 IceYGO WindBot 为 MIT。发行前还须分别核对所用组件与素材的许可；代码许可不能代表素材许可。

## LoRA 与评估

LoRA 优先用于离线意图结构化、基于已验证结果的复盘解释；积累足够轨迹后再试动作排序。它不替代规则引擎，小型策略网络可直接训练。QLoRA 仍需容纳基座与激活显存，不能保证 8 GB 显存可训练任意规模模型。[PEFT 量化训练说明](https://huggingface.co/docs/peft/developer_guides/quantization)。

比较实验须固定时间预算、对手和先后手设置，以完整对局隔离训练与评估数据。策略输入仅包含合法可见信息，不能包含暗牌或未来抽牌。

## DeepSeek DeepInfer

DeepInfer 主要优化推理吞吐与延迟，当前公开范围以 V4.1-Flash、SM100/Ascend 950 和离线推理为主；本项目现阶段不建议迁入。未见官方 LoRA 支持声明，不能据此承诺可用。文档所述“64 卡 prefill + 64 卡 decode”是最小高效部署配置，不应误写为最低离线运行要求。[DeepInfer 项目](https://github.com/deepseek-ai/DeepInfer)、[部署问答](https://github.com/deepseek-ai/DeepInfer/blob/main/doc/inference_deployment_qa.md)。

本次仅归档原件和复核记录，未进行原型开发、模型下载、训练或性能测试。

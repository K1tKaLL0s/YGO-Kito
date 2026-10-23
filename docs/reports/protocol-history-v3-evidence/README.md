# 真实协议／公开历史 v3：可回读证据

本目录保留独立 `protocol-history-acceptance` 的原始 `proof.json` 及19份 JSON 轨迹，文件内容不作重排或脱敏改写，便于按收据核验字节数和SHA-256。完整命令、源码、失败历史和未完成范围见[本批报告](../2026-10-23-protocol-history-v3.md)。

这些是**工程牌组的私有审计轨迹**，包含种子、双方响应和工程牌表，不是合法席位策略输入、用户3＋8套牌表、19场独立竞技评测或模型学习成绩。仅支持范围的 `DecisionRequest` 可交给策略。每条轨迹已经在生成时独立执行真实核心重放；本目录的哈希核验本身不执行规则。

`proofs` 包含14类机制、三种另一合法选择及一条完整终局；`generic_effect_duel` 另记录原通用入口的真实终局。两者合计19条审计轨迹、38次真实执行（含各一次重放）。目录中 `trace_receipts[].path` 相对于本目录。

可用Python标准库核对已保存的收据，不会启动训练或外部服务：

```python
import hashlib
import json
from pathlib import Path

base = Path("docs/reports/protocol-history-v3-evidence")
proof = json.loads((base / "proof.json").read_text())
for receipt in proof["trace_receipts"]:
    raw = (base / receipt["path"]).read_bytes()
    assert len(raw) == receipt["bytes"]
    assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
```

未知协议、隐藏区域及超预算动作仍明确拒绝；阶段1A/1B、正式训练就绪、全部机制与PC兼容均未据此通过。

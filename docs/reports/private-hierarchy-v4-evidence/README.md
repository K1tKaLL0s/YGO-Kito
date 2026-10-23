# v4 合法公开证据投影

本目录保存10份共同公开历史／终局投影、无私有样本的训练摘要和`delivery-proof.json`。[报告](../2026-10-23-private-hierarchy-v4.md)记录最终源码、真实测试、失败／修复及发布边界。

完整私有对局JSON的一次GitHub上传被自动审批拒绝，未执行或换路径重试。原始轨迹、seed、牌组、双方响应、视图置换键、原始CLI stdout/proof及权重留在云端 `.cache/private-hierarchy-delivery-v1`。这些路径不是下载链接。

本目录投影仅从双方完全一致、经过严格`PublicEvent`重建的共同公开历史提取，不包含私有手牌／卡组、候选、原生响应／索引、seed或置换键。通用effect-duel原审计未存公开历史，因此其投影只含公开终局摘要。训练摘要只有配置容量、聚合损失／参数变化／恢复结果，没有私有采样请求。

`delivery-proof.json`中的`trace_projections`与`training_summary`收据相对于本目录；原始云端文件的哈希仅用于绑定来源，不代表原始文件已上传。可用标准库核验本目录：

```python
import hashlib
import json
from pathlib import Path

base = Path("docs/reports/private-hierarchy-v4-evidence")
proof = json.loads((base / "delivery-proof.json").read_text())
for receipt in proof["trace_projections"] + [proof["training_summary"]]:
    raw = (base / receipt["path"]).read_bytes()
    assert len(raw) == receipt["bytes"]
    assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
```

原始10条轨迹在云端各独立真实重放；另外3次实际采样用于2次规范参数更新和恢复对照。23次真实执行含重放和恢复，不是23场独立竞技评估。导出投影本身不产生新引擎证据；完整阶段和正式训练就绪仍false。

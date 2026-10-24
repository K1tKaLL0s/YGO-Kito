# 用户 3 主卡组＋8 对手收件准备

本模块补充 EA-06 已有工程入口的收件缺口。现有 `OpponentRegistry` 已支持环境登记、JSON/YDK、三部分张数和别名禁限、对手控制方登记及版本冲突拒绝；本次继续复用这些格式和校验，不改变当前运行环境的准入规则。

`configs/user-deck-intake-template-v1.json` 固定 `main-01`～`main-03` 与 `opponent-01`～`opponent-08`。主卡组模板按三个时期各列一份；实际牌表均为 `null`。八个对手的时期归属为 `null`，只保留用户已确认的 `preferred_provider: DeepSeek` 用途，实际 controller/model/driver 尚未配置。偏好不代表连接、操作能力或训练就绪。

三环境为 `2022-07`、`2022-10`、`2026-10`。前两期 `release_cutoff` 已依确认设计§7显式填写 `2022-09-30`、`2022-12-31`；这只是实验范围决定，不是发行资料已核实。2026-10仍为null，须另选具体ISO日期；缺失时保持pending，不用表生效日、当前日或月末代填。月份不充当卡池截止日。所选禁限节通过 `banlist_section` 明确指定，`banlist_effective` 绑定所属月份第一日。节名可根据真实文件修改，模板节名没有官方来源认证含义。

## 输入与检查

`deck_intake.validate_intake()` 校验固定编号、时期和控制方配置；允许未收到的资料留空。每份牌表填写 `deck: {format, content, source}`，格式为 `json` 或 `ydk`。JSON `content` 继续使用 `main/extra/side` 三列表。`source` 填写实收来源引用，不把工程夹具标成用户牌表。

每个环境的 `catalog/releases/banlist` 都要求 `{path, sha256, source}`，文件必须位于调用者明确给定的 workspace 中。SHA-256 不符、路径越界、卡库异常或所选禁限节异常均拒绝；缺文件和未填资料保留 pending。不会回退读取当前 native 卡库或当前禁表。

- `catalog`：只读 SQLite `cards.cdb`，使用已有 `datas` 表的 `id/alias/ot/type`。
- `banlist`：现有 `lflist.conf` 格式。复用 `native.banlist_limits(path, section=...)` 读取显式所选节，不启动引擎。此前置检查拒绝选中节中的缩进数字行、未知正文、缺数量、非法数量、重复卡号及重复同名节，避免被旧解析器静默忽略；空行与 `#` 注释允许，卡号/数量后可跟 `#` 或 `--` 注释。
- `releases`：JSON `{schema_version: 1, period_id, release_cutoff, cards}`。每项 `cards` 为 `{card_id, ocg_release_date}`；日期明确到日。清单的时期和截止日必须与环境一致。仅明确列出且 OCG 发行日期不晚于截止日的卡号进入允许卡池，缺发行资料的卡不会默认放行。

`prepare_intake(config, workspace)` 对每份牌表的所有显式时期归属分别调用现有 `validate_deck_parts`，核对 OCG 身份、区域、Token、张数以及主/额外/副卡合计别名禁限。跨时期复用牌表必须逐项通过，不能用另一时期的通过结果替代。输出包含固定 3＋8 映射、环境证据、控制方和未满足项；`training_configuration` 标明只是输入映射，不是可执行训练配方。

控制方采用现有四种类型：`external_llm` 需显式 provider/model/driver_version；`rule_baseline` 和 `bot` 至少需 driver_version；`local_snapshot` 还需显式 model 身份。本地控制方无需虚填外部 provider/model。完整配置仍不证明驱动已实现、provider 可访问或强度合格。

## 使用与保存边界

```python
from pathlib import Path
from ygo_kito.validation import read_json
from ygo_kito.deck_intake import prepare_intake, store_intake
from ygo_kito.agent_registry import OpponentRegistry

workspace = Path("/workspace/YGO-Kito-construction")
config = read_json(workspace / "configs/user-deck-intake-template-v1.json")
report = prepare_intake(config, workspace)  # 只读检查；空模板返回缺失清单。
# 实收全部 11 份、三个历史环境与各自控制方齐备后，再显式调用：
# registry = OpponentRegistry(workspace / ".cache/intake", workspace / ".cache")
# store_intake(registry, completed_config, workspace)
```

`store_intake` 在所有 11 份和三个环境通过准备检查后才调用既有 registry 的 `put` 保存一个不可覆盖的 `deck_intake` 准备记录。缺任何一项都在登记前拒绝；不部分导入，不创建可运行的 environment/deck/opponent 记录。同 ID 内容变化须新版本 ID。

来源文件的哈希与静态牌表检查不能证明官方资料真实性、历史规则核心兼容、真实卡效、对手能力或外部模型连接。因此输出始终保留 `official_sources_verified=false`、`historical_rules_verified=false`、`runtime_compatible=false`、`formal_training_ready=false`；后续实际登记和运行仍需既有环境、资源与驱动准入。本轮没有收到用户牌表，没有运行原生核心、故障测试、付费训练或外部 API。

本范围 CPU 验证：`PYTHONPATH=src /workspace/YGO-Kito/.venv/bin/python -m unittest tests.test_deck_intake -v`。使用明示合成卡库、发行清单和禁表，不代表真实历史数据已核实。

# 历史来源索引与逐期静态牌表审计

`configs/historical-listing-sources-v1.json` 记录当前锁定 CDB、社区 `lflist.conf`、两份现有工程 profile，以及固定第三方版本的六份 YDK。每个来源独立保存本地路径、SHA-256、上游 repository/commit/path/URL；六份 YDK 另保存并核对原 Git blob SHA-1。没有下载或拼造官方全禁表，也没有补猜逐卡发行日期。

第三方来源为 `mellfy-puppy/ygo-tools-for-dsh@ab963c1cb9776bea4262ae1bba38f541ec70e357` 下 `skill/resources/ygopro2-bridge/windbot/source/Decks/AI_{Tearlaments,Albaz,Labrynth,Horus,Swordsoul,Kashtira}.ydk`。原字节保存在 `configs/third-party/windbot/*.ydk.txt`；扩展名只为源码包携带纯文本，内容没有改写。`dataset_kind=third_party_sample_not_user_deck`：这些文件不是用户实收牌表、历史主流推荐或合格对手。只读取卡号列表，不运行第三方程序。数据使用许可未核实，代码的 MIT 等许可不能代替卡数据许可，输出保留 `data_license_verified:false`。

## 运行

```bash
PYTHONPATH=src .cache/ci-cpu-venv/bin/python scripts/historical_listing_audit.py \
  --index configs/historical-listing-sources-v1.json \
  --workspace . --output .cache/historical-listing-audit/report.json
```

脚本只读索引列明的文件、写显式报告；不联网，不启动规则核心，不注册环境/牌组/对手，不启动训练。成功退出表示审计报告已生成。索引缺文件、摘要不符、禁表节异常分别保留不可用/无效，不能回退到别的资源。报告不替代 [3＋8 收件](deck-intake.md) 或训练 runtime 准入。

已确认截止为 `2022-07 → 2022-09-30`、`2022-10 → 2022-12-31`、`2026-10 → 2026-11-01`；函数不按月份推断截止。第三期包含日本当地（JST）11月1日当日正式OCG发售，禁表仍为2026-10-01生效的 `2026.10` 节。截至2026-10-25仅日期已选（`date_selected`），最终卡池尚未到日/未核；11月1日JST当日及之后须按实际正式发行记录补齐逐卡出处和日期、更新来源摘要并重新审计。所选社区禁表节独立为 `2022.7 / 2022.10 / 2026.10`；节名和固定哈希不证明已与完整官方表核对。

可靠社区资料可以用于开发和交叉核验，正式结论须有可追溯的可信依据；不要求每项都从官方原HTML取得，官方核验与未知项仍分别记录。已公开未发售的卡效只可作为staging资料：`announcement/public_text` 与正式OCG `release_date/available_in_period` 分开，不能因公开卡文而提前纳入允许池。[百鸽局部来源审阅](../reports/2026-10-25-baige-source-review.md)仅核对站点/API文档和少量单卡HTML；JSON正文、全库及完整历史/发行清单未取得，不据此补成已验证来源或正式池。

## 输出分项

报告包含 `periods` 和 `samples[].checks[]`。每份样例都有独立 `deck_sha256 / dataset_kind / source`，每个检查带 `period_id`。各项分别报告：

- `structure`：复用已有 `validate_deck_parts` 的区域、OCG 身份、Token、张数和标准三张合计别名限制；缺卡库身份时为未验，不能只凭卡号列表称结构合法。
- `catalog_unknown_card_ids`：未在所选锁定 CDB 找到的卡号。当前 CDB 中存在不代表历史已发行。
- `release`：已给可靠清单时区分截止内、`after_cutoff_card_ids`；没有对应发行记录列入 `unknown_card_ids`。不从卡名、卡效、主题或第三方文件名推断发行时间。
- `banlist`：复用 `deck_intake` 的严格所选节 reader 和既有合计别名语义。`violations` 明列 alias 卡号、数量和上限；未限卡仍遵守标准三张限制。节缺失/重复/异常时未验。
- `rows`：逐卡列出 YDK 原行号与行 SHA-256（不含行终止符），或 profile JSON pointer；另有 CDB 行、发行记录、禁表限额记录的来源文件 SHA-256 与独立规范行摘要。行出处与卡效判断分离，`card_effects_inferred:false`。

`historical_listing_status` 可为 `rejected / unverified / blocked_cutoff_unspecified / checked_under_supplied_evidence`。缺截止的旧输入仍保持 blocked，并显示已知结构及禁表拒绝；日期已选也不能补出缺失的发行证据或最终卡池。最后一种仅指输入的列表证据相互一致；始终保留 `official_sources_verified:false / historical_rules_verified:false / formal_training_ready:false`，也不认证来源真实性或对手强度。

可选 `release_source` 使用既有收件 manifest 格式：`{schema_version:1, period_id, release_cutoff, cards:[{card_id, ocg_release_date}]}`，要求来源文件和哈希，时期/截止精确匹配；缺记录的卡不能默认放行。当前索引三个发行来源均为 `null`。

## 此前审计验证范围（旧快照）

CPU 测试：`python -m unittest tests.test_deck_intake tests.test_historical_listing -q`，共 24 项，旧严格收件检查保持通过。合成发行日期只验证拒绝/未知及来源绑定代码，不是历史数据证据。

此前实际锁定 CDB/三个社区禁表节的只读审计覆盖 8 份样例 × 3 时期。24 份结构检查通过、卡号均在该轮 CDB；发行来源全缺，因此没有一项升格为历史合法。`2022.7` 拒绝 Albaz；`2022.10` 拒绝 Tearlaments、Albaz；`2026.10` 拒绝 Tearlaments、Albaz、Labrynth、Swordsoul、Kashtira。其余只表示未违反这份社区节的静态限额。当时所有 2026 总状态因 cutoff 空而 blocked；细项卡号/数量/出处以该轮原报告为准，不追写为当时已选11月1日。该审计没有运行原生对局或第三方驱动。

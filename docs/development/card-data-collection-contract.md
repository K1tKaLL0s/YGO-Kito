# 卡库采集交接：现有格式，不改训练代码

从项目根读取 `configs/user-deck-intake-template-v1.json` 和 `configs/historical-listing-sources-v1.json`。新增采集资料放独立的 `data/staging/` 目录，保留原始响应、URL、UTC读取时间、来源性质与SHA-256；不要直接覆盖已绑定的 `.cache/engine-src/` 或修改原生构建收据。正式3＋8牌表仍由用户提供。

现有读取格式：

| 资料 | 实际格式与字段 |
| --- | --- |
| 卡库 | YGOPro SQLite `cards.cdb`；完整 `datas(id,ot,alias,setcode,type,atk,def,level,race,attribute,category)` 与 `texts(id,name,desc,str1…str16)`。收件检查只读部分列，不代表精简库能供真实引擎使用。当前资源路径 `.cache/engine-src/database/locales/zh-CN/cards.cdb`。 |
| 禁限表 | `lflist.conf`：显式 `!2022.7`、`!2022.10`、`!2026.10` 节，条目 `<card_id> <0..3>`。需要各期完整累计状态，不能只转变更名单；检查别名合计，拒重复和畸形条目。当前路径 `.cache/engine-src/client/lflist.conf`。 |
| 逐期发行允许清单 | 严格JSON：`{"schema_version":1,"period_id":"2022-07","release_cutoff":"2022-09-30","cards":[{"card_id":123,"ocg_release_date":"YYYY-MM-DD"}]}`。另两期分别 `2022-10/2022-12-31`、`2026-10/2026-11-01`。不加额外字段或null日期。 |

三个截止均含日本当地当日正式OCG发售；禁表生效日分别为2022-07-01、2022-10-01、2026-10-01。2026-11-01尚未到达时只整理候选，最终池待到日及可信发行来源核验。未发售、日期不明、仅公开卡效的记录留在独立staging资料，不能进入运行允许清单。不要把TCG或简中先售日期填成OCG日期；先行ID变更保留映射与来源。

把验证后资料的工作区相对路径、SHA-256和来源按模板原有 `{path,sha256,source}` 字段登记。源码中 `deck_intake.prepare_intake`、`training_input.compile_training_inputs` 使用这些资料；`deck.import` 不是完整历史训练导入器。卡库与核心/scripts兼容性另核，不改代码或哈希伪造通过。

现成静态来源/合法性审计入口：

```bash
PYTHONPATH=src python scripts/historical_listing_audit.py \
  --index configs/historical-listing-sources-v1.json \
  --workspace . --output data/staging/historical-audit.json
```

先复制并填实来源索引再审计，不能把仓库里缺发行来源的示例索引当已核全库。保留 `unknown`、未到截止和逐卡来源缺项，不编造正式牌表或来源。

百鸽已实际核验的入口是 [关于](https://ygocdb.com/about)、[API文档](https://ygocdb.com/api)、[卡包列表](https://ygocdb.com/packs)和少量 `/card/<id>` HTML。API文档列 `/api/v0/card/<id>?show=all`、`/api/v0/limits.json?show=all`、`/api/v0/releaseDates.json`；后两项全量原始结构未取得，必须实际读取后再映射，不能凭文档猜键。它是社区聚合来源，可开发与交叉核验，不冒称官方发布或完整规则认证。[已有读取与403边界](../reports/2026-10-25-baige-source-review.md)保留；遇访问拒绝停止相应动作，不换代理或身份绕过。

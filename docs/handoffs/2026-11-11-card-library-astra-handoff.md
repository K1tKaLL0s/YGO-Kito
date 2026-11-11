当前后续补修已完成：正式词典 b19；迷宫变化的费用与发动时点已依据[官方调整](../reports/2026-11-11-magical-labyrinth-ruling.md)确定。下文为原安全交接记录。

本交接已执行完成：确认问题修复、正式 b18 词典替换和最终本地验证已完成，当前以[最终结果](../reports/2026-11-11-card-library-repair.md)为准。迷宫变化的精确数量及 CI／引擎状态分别保留。以下为接续前的历史安全点，不再代表当前未完成事项。

# 卡库修复：Astra max 接续

任务未完成，当前是安全交接点。用户新指令：后续修复改用 Astra max，最多使用 50% 额度；进度不足不能写成完成。当前 worker 没有即时切换模型或读取实时额度的工具，未声称已经切换、也未编造额度。请由父线程设置 Astra max 和额度限制后续接。不得重启电脑、打断写入、恢复训练或原运行。

## 已完成的核对

- 全部本地 CDB 15,071 行逐字段核对；14,299 张独立非衍生物卡、507 张相同别图、265 条衍生物。
- 本地百鸽 14,423 条，14,297 条密码匹配；14,111 条可比字段相同、186 条差异，82 条固定快照缺卡、44 条无可用密码／数据。不逐卡网页搜索。
- 原待复核的 1,945 张卡、2,223 个片段已经逐项阅读完整卡文及递归分支并裁定：1,722 个确认问题，271 个已有覆盖，230 个为条件／引用。旧批 1,070 条问题与新增片段合并涉及 2,212 张独立卡；不要把 2,792 条台账直接说成互不重复的代码缺陷。
- 逐项结果位于 `docs/reports/2026-11-11-card-library-review/completed-adjudications.jsonl/.csv`；`completed-summary.json`、`additional-confirmed-findings.jsonl` 保留理由与原疑点动作。
- 迷宫变化的解放费用性质已确认，支付实体数量在卡文与本地 Lua 之间有一处出入。见同目录 `uncertain-details.json`。保留未知数量，不补卡号特判或声称合法 CB。
- 其余无字面差异记录不自动升级为全细节语义认证或官方裁定。来源版本／译名差异不能直接当作 CDB 数值错误；没有覆盖固定卡池、权重或发行清单。

## 当前修复

修改已经在当前完整检出接入 `MechanismCatalog.effect_records/effect_blocks`，并由现有构筑标签、库存和关系适配器使用。没有卡号或主题分支。

本轮修改的运行文件：

- `src/ygo_kito/effect_blocks.py`：边界、原文动作筛选、并列来源、召唤无效、衍生物、分支数字、规则同名卡建库筛选等；当前 `BLOCK_REVISION=local-library-review-20261111-b14`，尚未定最终修订。
- `src/ygo_kito/effect_block_rules.py`：旧词和复合效果、查看、素材资格、规则及限制。
- `src/ygo_kito/effect_records.py`：费用、目标、怪兽描述分区、前言、分支记录及 JSON 数组一致性。
- 新 `src/ygo_kito/effect_text.py`：共用文本边界、费用、手续、维护、可选费用、条件费用、胜利规则等投影。修复剩余问题时沿现有接口改，不另造框架。
- `src/ygo_kito/construction_relations.py`：展示／改变表示形式的状态费用不当作消耗整张卡；补现有旅鸟共享限制的文本适配。

核心已修：`可以`、`以上／以下` 中的“以”不能被当成取对象开头；后半句“场合”不能吞掉前半句加攻；召唤无效不贴特召；衍生物不是搬用场上现成怪兽；前言真实功能不丢弃；比较对象不能覆盖新怪兽的卡组／额外来源；仪式素材资格不是仪式召唤能力；费用代替不是独立除外。召唤手续、激活费用、维护、可选追加费和被赋予效果内的费用分别记录。

**前言处理的最新状态：**现在先解析完整前言，只在有真实功能、费用、手续或召唤说明时保留独立记录。只有次数限制、素材公式或 P 刻度的标题不会额外造功能；共享限制仍留在编号效果及卡片资料。维护费用、不能维持的自毁和胜利条件因此得到补记。P 标题曾多造一个“无 P 效果”记录，已经修正并通过下面的最新回归。

## 当前验证与产物状态

- 最新源码的三个明确纯 CPU 模块共 **102 项通过、0 失败、0 错误、0 skip，Torch 未加载**。回执：`.cache/card-library-repair-20261111/selected-tests-handoff.json` 和同名 `.log`。这是本地测试，未记作 CI。新测试在 `tests/test_card_library_repairs.py`，已登记到 `scripts/check_merge_candidate.py` 白名单。
- `.cache/card-library-repair-20261111/pass-05/summary.json`：此前代码的一轮整库结果，15,071 原始行、14,299 独立卡，解析／来源／索引／导出合同错误均为 0，保存条目与 live 差异为 0。它验证了 draft 的全库读回。
- 该轮之后又修了维护前言、完整前言分类、指定效果的召唤条件及少数旧语法。因此 **pass-05 和下面 draft 不能当作最新源码最终验收**。
- draft SQLite：`.cache/card-library-repair-20261111/candidate/effect-blocks-v1.sqlite3`，manifest 同目录。它包含 14,299 卡，**尚未替换正式词典**。
- 正式文件仍在 `N:\YGO-Kito\_local_cpu_20261027\assets\effect-blocks\effect-blocks-v1.sqlite3`。需在最后代码稳定并验证后原子替换；保留一份当前正式库备份在任务 cache。
- `.cache/card-library-repair-20261111/targeted-06/live.jsonl.gz` 是 2,212 张确认问题卡的中间投影，写入已经正常结束。它早于最新前言修正，需用最新源码重生成后再判断剩余项。
- `.cache/card-library-repair-20261111/check-04/` 是较旧的回归定位表，2,792 条台账中 2,475 条结构检查通过、317 条待检查／未映射。**317 不等于 317 个仍存在的错误**：有些类型未写检查规则，有些当时确实未修。不要仅为了清零而扩大通过条件。
- `scripts/check_card_library_repairs.py` 是定位工具，显式不作为独立裁定 oracle；例如检视可被手卡／额外检视或相应公开动作覆盖，费用可能正确存在于可选／条件费用块而非父记录强制费用中。应读实际记录和原理由，正确区别表示变化与缺陷。
- `src/ygo_kito/effect_mechanisms.py` 的旧 18 维定义未改。没有训练、推理、CB、native 引擎启动、权重更新或部署。审计导入 Python native 包装模块不等于执行引擎。

## 继续做什么

1. 承接已完成裁定，不重读全库或重做原核对。以当前源投影确认问题卡，阅读旧定位表中未闭合的实际问题；按原宽粒度补必要规则，不按卡号特判。剩余类别包括少数费用／分支、表示形式限制、去向代替、战斗处理和其他罕见句式；前言修正已经解决其中一批，不能再套用旧数量。
2. 每次有实质源码变更后运行对应选定正常回归。最终三个模块均须无 skip；不运行 discovery、故障注入、响应缓冲测试、完整构筑、训练或 CB。
3. 代码稳定后重建 draft，并用 `scripts/audit_card_library.py` 逐条读回。必须确认全部 14,299 卡、来源引用／原文位置／索引／合同／解析错误为 0、保存与 live 差异为 0。不要额外重查已有充分结果，只有新修改或具体问题需要重跑。
4. 最终修订可定为 b15；同一代码输出正式词典，更新实际路径和报告。原始 CDB／卡池／checkpoint 不盲写。若发现真实未决问题，明确保留并报告，不称全修复。
5. 更新 `README.md` 的 b13 版本说明、`docs/reports/2026-11-11-card-library-repair.md`（当前是进展稿）、`MASTER-CHECKLIST.md` 的 CARD-LIBRARY-REPAIR 项及最终证据。旧语义报告顶部已标原队列完成、下方为历史基数。
6. 当前树含大量其他 R0—R11 未提交／未跟踪改动。不要 reset、提交整树或覆盖他人内容。任务前运行文件备份在 `.cache/card-library-repair-20261111/baseline/`，可用于隔离本次差异；由父线程整合提交／CI。完整 CI 没有本轮回执，不能记通过。

## 直接可用的运行方式

工作目录 `N:\YGO-Kito\_publish_20261030`，PowerShell，CPU Python：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='src'
$env:OMP_NUM_THREADS='2'
$env:MKL_NUM_THREADS='2'
& 'N:\YGO-Kito\_local_cpu_20261027\venv\Scripts\python.exe' -B -m unittest tests.test_effect_block_dictionary tests.test_construction_text_completion tests.test_card_library_repairs
```

建库入口 `scripts/build_effect_block_dictionary.py --assets N:\YGO-Kito\_local_cpu_20261027\assets\native --output <新draft路径> --report <manifest路径>`。

读回入口 `scripts/audit_card_library.py --assets N:\YGO-Kito\_local_cpu_20261027\assets\native --dictionary <新draft路径> --mirror N:\YGO-Kito\data\axis_generic\source\cards.cdb --output <未存在的新报告目录>`。输出很多，重定向到 cache 日志即可。

本地百鸽完整包及下载回执在 `data/staging/baige-20261111/`。固定 CDB 卡 hash 为 `ff52f585de24a762a4e613ac37654b1a7fb15a58990c14f5eada85f28c3be152`，database commit `217ae165c1886af2fc36b823fc08f9fc3ec13185`。此前校验已充分，不为换模型重做下载或逐卡网页搜索。

# Mechanism inputs at the course boundary (local, unverified)

## Local OCG reference addendum

The separately supplied rule package at `N:\YGO-Kito\ocg-negation-rules-2026-10-28` is now copied into this source: the manual in `docs/rules/`, and its two original JSON files in `src/ygo_kito/resources/rules/`. Setuptools includes the JSON files in installed packages. This adds 25 research rules, 35 source entries, 23 documentary cases and four unresolved topics; it does not execute the 23 cases or add a course-admission requirement.

`ygo_kito.rule_references.lookup_rule(rule_id)` and `MechanismCatalog.rule_reference(rule_id)` expose exact entries with official-source links, applicability conditions, scope guidance, evidence category and unresolved caveats. Parsed effect records carry reference requests tied to card, effect index, public-text identity, structured count scope and an explicitly unknown event outcome. Generic text or card-name matches never select a ruling. The existing real `DuelPlanner.evaluate -> EffectLimitTracker.view` receipt now exposes the reference library and, for an existing reviewed counter binding, its exact native-description selectors, application event, scope boundary and observed activation outcome. These references do not alter any counter policy, legal action, model feature, weight or training label.

The named-card activation entry remains an official-rule synthesis without a direct named-card Q&A. Unknown parser policies remain unknown. Source references and hypothetical planner outcomes are not native engine validation; the engine remains the authority for legal actions. Three new direct lookup/receipt tests in `tests/test_rule_references.py` are authored but **not_run**. The earlier 27 tests remain **not_run** because their original evidence-file write was denied; this addendum does not retry that action or run Python elsewhere. No formal training, weight migration, CUDA work, publication or merge occurred.

Base: d56ba0edc912b3da1a5a7326e621b1807102f48c. This worktree imports the task-21 mechanism/recall and task-22 decision/CB deliveries, with minimal course-caller integration. Neither delivery is independently reimplemented here. Nothing in this round is published, merged, or authorized to train; the formal hold stays active.

## Actual new-generation path

Use `configs/scenario-course-mechanism-base-template-v1.json` as an incomplete host configuration. It explicitly selects `learning_stage=base`, `initialization_mode=fresh`, no source group, and `coordinator_mechanism_inputs=true`. Required resources, bot evidence, timing and permission checks still need their normal inputs; the template starts nothing.

The production `ScenarioCourseHost` forwards that flag into the exact model binding. `CourseModels.initialize` then constructs `CoordinatorModelConfig(mechanism_inputs=True)`. Its added projection is zero initialized and recorded as new/untrained, with no learned-ability claim. A source checkpoint cannot be passed to this initialization path as if it already had the new parameters.

Both `CourseForecast.before` and `before_training` call the same selected input producer. A v3 model receives `public_scope_input(...)`: the legacy 64-vector plus 32 own and 32 weighted registered-public-opponent mechanism fields, with explicit feature and summary versions. Forecast windows and pre-game training records retain the complete envelope. Existing base feedback forwards the recorded envelope into `CoordinatorTrainer.step`; it is not reconstructed from later outcomes. Model routing also consumes the same input through `control`.

The decision patch consumes `MechanismCatalog.effect_records` through the existing `course_game_adapter -> planning_facts=assets.rows -> DuelPlanner` path. No extra training-file forwarding is needed. Records without an established native-description mapping stay unknown for ambiguous multi-effect cards. The foundation and collaborative callers now also require actual completed inference before admission/comparison: completed unknown remains allowed, `not_run` is stopped, and incomplete retained candidates cannot borrow a success flag. The saved incomplete trace is retained before refusal.

The source binding and model configuration must agree. Controller files bind their coordinator feature generation; a different generation, or a legacy vector inserted into a v3 saved window, fails closed. Historical frozen windows and pending observations are never relabelled or silently reset.

## Old state and explicit migration

- Missing `coordinator_mechanism_inputs` remains legacy v2. The host does not insert a default False into an old specification or its input digest. Old v2 checkpoints and old LoRA courses keep the original 64-vector path.
- V3 is currently enabled only for base courses. New v3 course LoRA and old-adapter rebinding are rejected until their loss/adapter migration is explicitly supplied. Dynamic adapter feature metadata prevents a future v3 architecture being labelled v2.
- For an already validated, closed **base** course export, the existing `migrate_closed_course(..., enable_coordinator_mechanisms=True)` composes the supplied v2→v3 upgrade with the existing migration. V1 first follows the explicit v1→v2 extension. The source-change set and actual target source map remain checked; no checkpoint manifest is edited to bypass validation.
- The separate new state changes only the specified coordinator architecture/configuration, its new source binding and derived full-state identities. Existing tensors and Adam moments are checked unchanged, the appended Adam slot stays lazy, old scheduler/cursors/RNG streams stay intact, and the new module inherits the saved root mode. The new generation is saved and strictly restored paused. Existing adapters, unfinished transactions, active final evaluations and existing frozen monitor windows remain rejected by the established migrator guards.
- Original checkpoint/source and historical training records remain intact. This source path is not evidence that the actual old course was migrated. The inherited WinError5, 0xC0000005, WSL/CIM/Git/WindowsApps restrictions were not retried or bypassed.

## Direct verification status

The incoming nine cases in `tests/test_mechanism_records_recall.py`, fourteen in `tests/test_cb_chain_regressions.py`, and four added course contracts in `tests/test_course_mechanism_inputs.py` are all **not_run**. The course contracts cover real forecast/prospective-record producer dispatch for v2/v3, explicit fresh-v3 state roundtrip, old-v2 restoration versus forbidden tensor relabel, and caller inference-completion semantics. No interpreter/path/tool was selected to bypass an inherited execution restriction. The previous 770-test CI belongs to d56ba0e, not this new source. No smoke test, full preflight, full suite, formal training, publication or merge ran in this round.

### Direct attempt: 2026-10-28 08:32:55Z

The preceding **not_run** record is retained as the history before this attempt. On the original `require_escalated` path, `whoami /groups` succeeded and confirmed Medium integrity (`S-1-16-8192`). The original interpreter then started this command:

```text
N:\YGO-Kito\_local_cpu_20261027\venv\Scripts\python.exe -B N:\YGO-Kito\_migrated\CodexData\2026-10-28\task-13\run_nine_point_regressions.py
```

The external runner records the command and intended test list: `tests.test_mechanism_records_recall` (9), `tests.test_cb_chain_regressions` (14), and `tests.test_course_mechanism_inputs` (4). Before loading any test, its `Path.open('w')` for `N:\YGO-Kito\_migrated\CodexData\2026-10-28\task-13\evidence\nine-point-direct-20261028T083255Z.log` failed with the tool-reported error `PermissionError: [Errno 13] Permission denied`; the process exited 1. That log was not produced and is not available as evidence.

Result: **passed 0, failed 0, not_run 27**. Medium recovery and denied log creation are separate findings; this is a denied prerequisite, not 27 failed tests. The attempt stopped without retry or substitution of interpreter, log directory, path, or tool. Source remains at `c571d4e` with no source change from this attempt. The formal hold remains active; no training, publication, or merge occurred.

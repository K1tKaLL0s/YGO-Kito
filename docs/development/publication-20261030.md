# Publication of existing code through 2026-10-30

This source-only integration continues PR #8 and retains the training hold. It does not run a production migration or resume training.

## Included sources

- PR #8 base `d56ba0e` and all sixteen subsequent core commits through `dbf8faf`, including the `fbf9c04`/`05aa5a9` parents.
- Construction `041c72b`, duel `2933367`, coordinator `77b5c55` and effect mechanisms `0850819`/`45fb85a` were already integrated before that PR head; they are not reapplied over the follow-up fixes.
- Optional multifactor commits `ddaf81e`, `6e0c3d4`, `9368c76`, including failure-atomic adapter loading.
- Reference-scoring delivery: the five implementation modules already match the core integration; its four previously omitted test files are included. The test requiring private reports is a separately named class excluded from public CI.
- Migration path corrections in six existing handoff documents, and the legacy worker's additional orchestration snapshot filenames, combined with the current supervision/source-root support.
- Explicit CPU coverage for the new modules and a pinned review of the controlled-CB initialization. The response guard and ABI behavior are unchanged.

## Deduplication and retained local material

The old local execution worktree has 66 substantive changed/untracked files: 32 exactly match this integration, 26 match its saved snapshot baseline, and the remaining eight were compared with saved history or the current implementation. Four remaining source files are older paths of the same code; only the worker's additional snapshot filenames needed carrying forward. No old source replaced the newer admission/forecast/controlled-opening repairs.

The task-21 mechanism and task-22 CB/duel deliveries are included in the core lineage. The conflicting task-20 preliminary patch remains archived locally: its effect-identity/shared-prefix work is superseded by task-22 and later core fixes. It was not applied wholesale to replace the reviewed implementation.

One-off publication/migration scripts, private evaluator generators/reports, historical execution snapshots, GPU environment diagnostics, art, caches, virtual environments, credentials and training data remain in their original local directories. Three checkpoint archives, one feedback archive and fifteen historical test logs previously present on PR #8 are removed from the proposed tree; their original copies and old PR commits are preserved. Restore utilities and manifests remain available and require separately supplied archives.

## Validation and remaining limitations

The final PR commit must pass Safe CPU contracts before merging. Local CPU and remote CI results are reported independently in the PR. No native engine, C# bot, GPU run, production checkpoint migration or formal training is performed by this publication.

The existing learner's construction score and CB result remain unknown, so training admission remains deferred. Optional multifactor scoring is an isolated module and is not represented as a validated replacement for the active pipeline. Previously unstarted optimization work is outside this publication.

"""M4 regression sources only; execution awaits authorization."""
from contextlib import contextmanager
from dataclasses import replace
import gzip
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ygo_kito.multifactor import (AnalysisContext, DeckSpec, Factors, LabelCell, LabelSet, RoleInput,
    UnitSpec, assign_group_splits, binary_metrics, build_analysis_graph, build_leakage_groups,
    categorical_metrics, macro_f1_report, axis_set_metrics, group_bootstrap)
from ygo_kito.multifactor.contracts import GRAPH_VERSION, TASK_DOMAINS, digest
from ygo_kito.multifactor.splits import SPLIT_VERSION


@contextmanager
def preparation_modules():
    root = Path(__file__).resolve().parents[1]/'training'/'axis_generic'
    with patch.dict(sys.modules), patch.object(sys,'path',[str(root)]+sys.path):
        yield importlib.import_module('prepare_v3'),importlib.import_module('assessment')


def config(**split):
    return dict(feature_schema=GRAPH_VERSION,dataset_version='axis-dataset-v3',split_version=SPLIT_VERSION,
        label_protocol='axis-generic-label-v3-m4',source_versions={'fixture':'1'},seed=17,
        split=dict(protocol='unseen_deck',train=1,dev=0,test=0,**split))


def example(cards=((1,1),(2,1)), *, mode='deck_analysis', focal=((1,1),)):
    return RoleInput('fixture-context',Factors('context'),(),analysis_mode=mode,
        analysis_context=AnalysisContext(format='ocg',period='2026-11'),
        deck=None if cards is None else DeckSpec(cards,(),()),
        unit_definition=UnitSpec('focal',focal,'function:search'))


def record(name='a', *, inp=None, value=1, **meta):
    return dict(schema_version='axis-source-record-v3',record_id=name,
        observations={'input':(inp or example()).to_dict()},
        targets={'roles':[['query:unit',[LabelCell(value,'known').to_dict() for _ in range(5)]]]},
        supervision={'kind':'definition_development'},provenance=dict({'source_namespace':'fixture','previously_consumed':False},**meta))


def protocol():
    root = Path(__file__).resolve().parents[1]/'training'/'axis_generic'
    value = json.loads((root/'ASSESSMENT_PROTOCOL.v3.json').read_text('utf-8'))
    value['bootstrap']['repetitions'] = 4
    return value


def _v21_sql_preparation_snapshot(direction):
    """Engineering source rows only; no catalog, shards, model or persistent DB."""
    if direction not in ("ASC", "DESC"):
        raise ValueError("fixed SQL direction required")
    sources = []
    for index in range(12):
        source = record("source:" + str(index).zfill(2), inp=example(((1, 1), (index + 2, 1))),
                        final_eval_eligible=True, previously_consumed=False)
        source["targets"]["roles"][0][1] = [LabelCell(index % 2, "known").to_dict(), LabelCell().to_dict(),
            LabelCell(status="conflict").to_dict(), LabelCell(status="not_applicable").to_dict(),
            LabelCell(1, "known").to_dict()]
        sources.append(source)
    sources[0]["provenance"]["reference"] = sources[1]["provenance"]["reference"] = "v21-reference"
    sources[1]["provenance"]["source_rowid"] = sources[2]["provenance"]["source_rowid"] = 41
    conflict = json.loads(json.dumps(sources[0]))
    conflict["record_id"] = "source:conflict"
    conflict["targets"]["roles"][0][1][0] = LabelCell(1, "known").to_dict()
    sources.append(conflict)
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("create table sources (record_id text primary key, payload text not null)")
        connection.executemany("insert into sources values (?, ?)",
                               [(source["record_id"], json.dumps(source)) for source in sources])
        selected = connection.execute("select record_id, payload from sources order by record_id " + direction).fetchall()
    finally:
        connection.close()
    raw = [json.loads(payload) for _, payload in selected]
    settings = config()
    settings["split"].update(train=.5, dev=.25, test=.25, near_duplicate_swaps=0)
    with preparation_modules() as (prep, _):
        prepared, report = prep.prepare_records(raw, settings)
        masks = {row["record_id"]: [dict(task=task, coordinate=list(coordinate), known=cell.known)
                 for task, coordinate, cell in prep.iter_target_cells(row["targets"])] for row in prepared}
    source_groups = {source["record_id"]: group for source, group in zip(raw, report["grouping"]["row_groups"])}
    splits = {json.loads(identity)[1]: row["supervision"]["partition"]
              for row in prepared for identity in row["provenance"]["source_record_ids"]}
    # Raw grouping row indices describe input positions; compare stable source IDs instead.
    return dict(read_order=[identity for identity, _ in selected], snapshot=dict(records=prepared,
        known_masks=masks, source_groups=source_groups, splits=splits,
        report={key: value for key, value in report.items() if key != "grouping"}))


class SourceComponentsTests(unittest.TestCase):
    def test_transitive_keys_and_namespaces(self):
        rows = [dict(source_namespace='s',record_id='a',reference='R'),
                dict(source_namespace='s',record_id='b',reference='R',source_rowid=8),
                dict(source_namespace='s',record_id='c',source_rowid=8),
                dict(source_namespace='other',record_id='c',source_rowid=8)]
        result = build_leakage_groups(rows)
        self.assertEqual(len(result['groups']),2)
        self.assertEqual(len({result['row_groups'][i] for i in range(3)}),1)
        labels,_ = assign_group_splits(rows,require_three=False)
        self.assertEqual(len(set(labels[:3])),1)

    def test_cross_namespace_parent_link_is_explicit(self):
        rows = [dict(source_namespace='s',record_id='a'),
                dict(source_namespace='t',record_id='b',parent_id='a',parent_namespace='s')]
        self.assertEqual(len(build_leakage_groups(rows)['groups']),1)

    def test_near_duplicate_closure_without_common_card_union(self):
        def row(name,deck):
            return dict(record_id=name,format='ocg',period='2026-11',deck=dict(main=deck,extra=[],side=[]))
        rows = [row('a',[[1,3],[2,3]]),row('b',[[1,3],[2,2],[3,1]]),
                row('c',[[1,3],[2,1],[3,2]]),row('d',[[1,1],[7,5]])]
        result = build_leakage_groups(rows,near_duplicate_swaps=1)
        self.assertEqual(len(result['groups']),2)
        self.assertEqual(len(set(result['row_groups'][:3])),1)

    def test_unknown_side_does_not_equal_known_empty(self):
        a = dict(record_id='a',deck=dict(main=[[1,1]],extra=[],side=None))
        b = dict(record_id='b',deck=dict(main=[[1,1]],extra=[],side=[]))
        c = dict(record_id='c',deck=dict(main=[[1,1]],extra=[],side=None))
        groups = build_leakage_groups([a,b,c])['row_groups']
        self.assertEqual(groups[0],groups[2])
        self.assertNotEqual(groups[0],groups[1])

    def test_budget_exhaustion_never_claims_complete_split(self):
        rows = [dict(record_id=str(i),format='ocg',period='now',deck=dict(main=[[i+1,1]],extra=[],side=[])) for i in range(3)]
        with self.assertRaises(ValueError):
            build_leakage_groups(rows,max_near_pairs=0)

    def test_receiver_card_and_time_holdouts_are_distinct(self):
        rows = [dict(record_id='a',receiver_family='alpha',available_at='2026-01-01',reserved_card_ids=[99]),
                dict(record_id='b',receiver_family='beta',available_at='2026-12-01'),
                dict(record_id='c',receiver_family='gamma',available_at='2026-01-01'),
                dict(record_id='d')]
        receiver,_ = assign_group_splits(rows,protocol='unseen_receiver',heldout_receivers=['alpha'])
        card,_ = assign_group_splits(rows,protocol='unseen_card',heldout_cards=[99])
        period,_ = assign_group_splits(rows,protocol='cross_period',time_cutoff='2026-06-01')
        self.assertEqual(receiver[0],card[0])
        self.assertEqual(receiver[0],'test')
        self.assertEqual(period[1],'test')
        self.assertNotEqual(period[0],'test')
        self.assertEqual(receiver[3],period[3])
        self.assertEqual(receiver[3],'quarantine')

    def test_heldout_combination_moves_whole_parent_component(self):
        rows = [dict(record_id='a',reserved_card_ids=[9,10]),
                dict(record_id='b',parent_id='a'),dict(record_id='c'),dict(record_id='d')]
        labels,_ = assign_group_splits(rows,protocol='unseen_card',heldout_combinations=[[9,10]])
        self.assertEqual(labels[:2],['test','test'])

    def test_cross_period_checks_annotation_time_and_missing_dates(self):
        targets = {'roles':[['q',[LabelCell(1,'known').to_dict() for _ in range(5)]]]}
        rows = [dict(record_id='a',available_at='2026-01-01',label_available_at='2026-12-01',targets=targets),
                dict(record_id='b',available_at='2026-01-01',targets=targets),
                dict(record_id='c',available_at='2026-01-01',label_available_at='2026-01-01',targets=targets)]
        labels,_ = assign_group_splits(rows,protocol='cross_period',time_cutoff='2026-06-01')
        self.assertEqual(labels[0],'test')
        self.assertEqual(labels[1],'quarantine')
        self.assertNotEqual(labels[2],'test')

    def test_receiver_mechanism_combo_does_not_guess_missing_signature(self):
        rows = [dict(record_id='a',receiver_family='alpha',mechanism_signature='x'),
                dict(record_id='b',receiver_family='alpha'),dict(record_id='c',receiver_family='beta')]
        labels,_ = assign_group_splits(rows,protocol='unseen_receiver',
            heldout_receivers=[dict(receiver_family='alpha',mechanism_signature='x')])
        self.assertEqual(labels[0],'test')
        self.assertEqual(labels[1],'quarantine')
        self.assertNotEqual(labels[2],'test')

    def test_reverse_order_keeps_group_assignment(self):
        rows = [dict(record_id=str(i),source_rowid=i//2) for i in range(16)]
        a,_ = assign_group_splits(rows,seed=5)
        b,_ = assign_group_splits(list(reversed(rows)),seed=5)
        self.assertEqual(a,list(reversed(b)))


class LabelPreparationTests(unittest.TestCase):
    def test_v21_reverse_sql_preserves_records_masks_groups_and_splits(self):
        ascending = _v21_sql_preparation_snapshot("ASC")
        descending = _v21_sql_preparation_snapshot("DESC")
        self.assertNotEqual(ascending["read_order"], descending["read_order"])
        self.assertEqual(ascending["read_order"], list(reversed(descending["read_order"])))
        self.assertEqual(ascending["snapshot"], descending["snapshot"])
        snapshot = ascending["snapshot"]
        self.assertEqual(set(snapshot["splits"].values()), {"train", "validation", "test"})
        self.assertEqual(set(snapshot["source_groups"]), set(ascending["read_order"]))
        self.assertEqual(set(snapshot["splits"]), set(ascending["read_order"]))
        self.assertGreater(len(set(snapshot["source_groups"].values())), 3)
        for name in ("source:01", "source:02", "source:conflict"):
            with self.subTest(source=name):
                self.assertEqual(snapshot["source_groups"]["source:00"], snapshot["source_groups"][name])
                self.assertEqual(snapshot["splits"]["source:00"], snapshot["splits"][name])
        self.assertGreater(snapshot["report"]["stats"]["merged_rows"], 0)
        cells = [cell for row in snapshot["records"] for _, values in row["targets"]["roles"] for cell in values]
        self.assertEqual({cell["status"] for cell in cells}, {"known", "unknown", "conflict", "not_applicable"})
        self.assertEqual({cell["value"] for cell in cells if cell["status"] == "known"}, {0, 1})
        self.assertEqual({cell["known"] for values in snapshot["known_masks"].values() for cell in values}, {False, True})

    def test_v21_hash_seeds_and_reverse_sql_preserve_preparation(self):
        root = Path(__file__).resolve().parents[1]
        baseline = json.loads(json.dumps(_v21_sql_preparation_snapshot("ASC")["snapshot"]))
        python_path = os.pathsep.join([str(root / "src"), str(root)] +
                                     ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))
        script = ("import json, os, sys\n"
                  "from tests.test_multifactor_data_v3 import _v21_sql_preparation_snapshot\n"
                  "value = _v21_sql_preparation_snapshot(sys.argv[1])\n"
                  "value['hash_seed'] = os.environ['PYTHONHASHSEED']\n"
                  "value['hash_probe'] = hash('axis-v21-controlled-hash-probe')\n"
                  "print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')))\n")
        hash_probes = {}
        for seed in ("1", "97"):
            for direction in ("ASC", "DESC"):
                with self.subTest(seed=seed, direction=direction):
                    environment = dict(os.environ, PYTHONPATH=python_path, PYTHONDONTWRITEBYTECODE="1",
                                       PYTHONHASHSEED=seed, OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
                    result = subprocess.run((sys.executable, "-B", "-c", script, direction), cwd=str(root),
                        env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
                    self.assertEqual(result.returncode, 0, msg=result.stderr)
                    value = json.loads(result.stdout)
                    self.assertEqual(value["hash_seed"], seed)
                    self.assertEqual(value["read_order"], sorted(value["read_order"], reverse=direction == "DESC"))
                    self.assertEqual(value["snapshot"], baseline)
                    self.assertEqual(hash_probes.setdefault(seed, value["hash_probe"]), value["hash_probe"])
        self.assertEqual(len(set(hash_probes.values())), 2)

    def test_consumed_holdout_is_retrospective_and_frozen_final_never_trains(self):
        with preparation_modules() as (prep,_):
            old = record(previously_consumed=True,final_eval_eligible=True)
            old['supervision']['partition'] = 'final_eval'
            rows,report = prep.prepare_records([old],config())
            self.assertEqual(rows[0]['supervision']['partition'],'retrospective_test')
            self.assertFalse(report['new_independent_final'])
            self.assertFalse(rows[0]['supervision']['trainable'])
            fresh = record(final_eval_eligible=True)
            fresh['supervision']['partition'] = 'final_eval'
            rows,report = prep.prepare_records([fresh],config())
            self.assertEqual(rows[0]['supervision']['partition'],'test')
            self.assertTrue(report['new_independent_final'])

    def test_changed_receiver_does_not_copy_role_targets(self):
        with preparation_modules() as (prep,_):
            source = record()
            source['variants'] = [dict(record_id='b',observations={'input':example(((1,1),(3,1))).to_dict()},
                                       supervision={'kind':'definition_development'})]
            rows,_ = prep.prepare_records([source],config())
            self.assertEqual(len(rows),2)
            self.assertEqual(sorted(len(r['targets']['roles']) for r in rows),[0,1])
            self.assertEqual(len({r['provenance']['leakage_group'] for r in rows}),1)

    def test_only_declared_intrinsic_transferability_is_inherited(self):
        with preparation_modules() as (prep,_):
            source = record(inp=example(mode='unit_analysis'))
            source['targets'] = dict(task_labels=[LabelSet('transferability',('query:unit',),
                (('portability',LabelCell('conditional','known')),)).to_dict()])
            source['variants'] = [dict(record_id='b',observations={'input':example(((1,1),(3,1)),mode='unit_analysis').to_dict()},
                invariance_scope={'transferability':'unit_definition'},supervision={'kind':'definition_development'})]
            rows,_ = prep.prepare_records([source],config())
            self.assertTrue(all(len(r['targets']['task_labels'])==1 for r in rows))

    def test_absent_focal_and_state_failures_do_not_create_structural_negatives(self):
        with preparation_modules() as (prep,_):
            raw = record(inp=example(((2,1),)))
            targets,changes = prep.migrate_targets(raw,RoleInput.from_dict(raw['observations']['input']))
            self.assertEqual([c['status'] for c in targets['roles'][0][1][2:4]],['not_applicable']*2)
            self.assertEqual(len(changes),2)
            raw = record(value=0,readiness_only=True)
            targets,_ = prep.migrate_targets(raw,example())
            self.assertEqual([c['status'] for c in targets['roles'][0][1][2:]],['unknown']*3)

    def test_actor_absence_retracts_instead_of_labeling_zero(self):
        with preparation_modules() as (prep,_):
            raw = record(value=0,plan_actor_absent=True)
            targets,_ = prep.migrate_targets(raw,example())
            self.assertEqual([c['status'] for c in targets['roles'][0][1][2:4]],['unknown']*2)

    def test_legacy_context_label_requires_its_plan_in_model_observations(self):
        with preparation_modules() as (prep,_):
            raw = record(legacy_plan_not_in_model_input=True)
            targets,changes = prep.migrate_targets(raw,example())
            self.assertEqual([c['status'] for c in targets['roles'][0][1][2:4]],['unknown']*2)
            self.assertTrue(all(v['reason']=='legacy_primary_plan_not_represented_in_v3_observations' for v in changes))

    def test_identical_input_conflict_is_preserved_without_negative_fill(self):
        with preparation_modules() as (prep,_):
            rows,report = prep.prepare_records([record('a',value=1),record('b',value=0)],config())
            self.assertEqual(len(rows),1)
            self.assertTrue(all(c['status']=='conflict' for c in rows[0]['targets']['roles'][0][1]))
            self.assertEqual(rows[0]['supervision']['source_group_weights'],{})
            self.assertTrue(rows[0]['provenance']['annotation_conflicts'])
            self.assertEqual(report['stats']['merged_rows'],1)

    def test_engine_result_cannot_supply_contextual_truth(self):
        with preparation_modules() as (prep,_):
            raw = record()
            raw['supervision']['kind'] = 'engine_probe'
            with self.assertRaises(ValueError):
                prep.prepare_records([raw],config())

    def test_merged_sources_keep_per_cell_admission_kinds(self):
        with preparation_modules() as (prep,_):
            first,second = record('role'),record('mechanism')
            second['supervision']['kind'] = 'engine_probe'
            second['targets'] = dict(task_labels=[LabelSet('mechanism',('card:1',),
                (('search',LabelCell(1,'known')),)).to_dict()])
            rows,_ = prep.prepare_records([first,second],config())
            self.assertEqual(len(rows),1)
            supervision = rows[0]['supervision']
            self.assertEqual(supervision['kind'],'mixed')
            self.assertEqual(supervision['source_kinds'],['definition_development','engine_probe'])
            role = json.dumps(['legacy:strategic_core',['query:unit']],separators=(',',':'))
            mechanism = json.dumps(['mechanism',['card:1','search']],separators=(',',':'))
            self.assertEqual(supervision['cell_sources'][role][0]['kind'],'definition_development')
            self.assertEqual(supervision['cell_sources'][mechanism][0]['kind'],'engine_probe')

    def test_input_key_ignores_source_and_labels_but_cache_identity_does_not(self):
        with preparation_modules() as (prep,_):
            first,second = record('a',value=1),record('renamed',value=0)
            a,_ = prep.prepare_records([first],config())
            b,_ = prep.prepare_records([second],config())
            self.assertEqual(a[0]['input_key'],b[0]['input_key'])
            self.assertNotEqual(prep.preparation_identity(config(),[first],{}),prep.preparation_identity(config(),[second],{}))
            self.assertEqual(prep.input_key(build_analysis_graph(example())),prep.input_key(build_analysis_graph(replace(example(),context_ref='renamed-context'))))

    def test_prepared_order_is_stable_after_reversing_sources(self):
        with preparation_modules() as (prep,_):
            sources = [record(str(i),inp=example(((1,1),(i+2,1)))) for i in range(5)]
            a,_ = prep.prepare_records(sources,config())
            b,_ = prep.prepare_records(list(reversed(sources)),config())
            self.assertEqual(a,b)

    def test_semantic_cache_ignores_gzip_headers_but_rejects_changed_records(self):
        with preparation_modules() as (prep,_), tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            rows = [{'schema_version':prep.RECORD_VERSION,'payload':1}]
            def shard(mtime,values):
                with (path/'train-00000.jsonl.gz').open('wb') as raw:
                    with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=mtime) as zipped:
                        zipped.write(('\n'.join(json.dumps(v) for v in values)+'\n').encode())
            entry = dict(file='train-00000.jsonl.gz',records=1,semantic_records=digest(rows))
            identity = {'semantic_id':'fixture'}
            prep.write_json(path/'dataset.json',dict(version=prep.VERSION,preparation_identity=identity,
                files=[entry],shards={'train':[entry]},split_counts={'train':1}))
            shard(1,rows)
            prep.validate_cache(path,identity)
            shard(2,rows)
            prep.validate_cache(path,identity)
            shard(2,[{'payload':2}])
            with self.assertRaises(prep.CacheMismatch):
                prep.validate_cache(path,identity)
            with self.assertRaises(prep.CacheMismatch):
                prep.validate_cache(path,{'semantic_id':'changed-labels'})


class FixedMetricTests(unittest.TestCase):
    def test_all_wrong_is_zero_and_all_refused_stays_in_denominator(self):
        wrong = binary_metrics([(LabelCell(1,'known'),0),(LabelCell(0,'known'),1)])
        refused = binary_metrics([(LabelCell(1,'known'),None),(LabelCell(0,'known'),None)])
        self.assertEqual(wrong['f1'],0)
        self.assertEqual(refused['f1'],0)
        self.assertEqual(refused['fn'],1)
        self.assertEqual(refused['overall_accuracy'],0)
        self.assertEqual(refused['coverage'],0)
        self.assertIsNone(refused['brier'])
        self.assertIsNone(binary_metrics([])['f1'])
        self.assertIsNone(binary_metrics([(LabelCell(0,'known'),1)])['f1'])

    def test_fixed_category_matrix_has_unknown_prediction_column(self):
        classes = TASK_DOMAINS['transferability']
        rows = [(LabelCell(c,'known'),None) for c in classes]
        result = categorical_metrics(rows,classes)
        self.assertEqual((len(result['confusion']),len(result['confusion']['open'])),(3,4))
        self.assertEqual(result['f1'],0)
        self.assertIsNone(categorical_metrics(rows[:1],classes)['f1'])
        self.assertFalse(macro_f1_report({'a':{'f1':1}},tasks=('a','b'))['complete'])

    def test_missing_natural_axis_cannot_be_rescued_by_gold_injection(self):
        truth = [dict(members=['card:1','card:2'],allowed_candidate_refs=[])]
        pred = [dict(candidate_ref='gold-injected',members=['card:1','card:2'])]
        result = axis_set_metrics(truth,pred,natural_candidate_ids=[])
        self.assertEqual(result['f1'],0)
        self.assertEqual(result['candidate_recall'],0)
        self.assertEqual(result['excluded_non_natural_predictions'],1)
        self.assertEqual(result['matched_mean_iou'],0)

    def test_axis_matching_uses_global_optimum(self):
        truth = [dict(members=['a','b']),dict(members=['b','c'])]
        pred = [dict(candidate_ref='x',members=['b','c']),dict(candidate_ref='y',members=['a','b'])]
        self.assertEqual(axis_set_metrics(truth,pred,natural_candidate_ids=['x','y'])['matched_mean_iou'],1)

    def test_bootstrap_preserves_whole_source_group(self):
        def statistic(rows):
            self.assertEqual(rows.count('a1'),rows.count('a2'))
            return len(rows)
        result = group_bootstrap({'a':['a1','a2'],'b':['b1']},statistic,repetitions=5)
        self.assertEqual(result['source_groups'],2)
        self.assertEqual(result['defined_repetitions'],5)

    def test_saved_layers_share_truth_and_keep_uncovered_heads(self):
        with preparation_modules() as (prep,assessment):
            raw = record()
            raw['supervision']['partition'] = 'validation'
            rows,_ = prep.prepare_records([raw],config())
            rid = rows[0]['record_id']
            key = assessment.prediction_key('legacy:strategic_core',('query:unit',))
            result = assessment.assess_records(rows,{rid:{'raw':{key:0},'calibrated':{key:1}}},protocol())
            layers = result['partitions']['validation']['layers']
            self.assertEqual(layers['raw']['tasks']['legacy:strategic_core']['f1'],0)
            self.assertEqual(layers['calibrated']['tasks']['legacy:strategic_core']['f1'],1)
            self.assertEqual(layers['applied']['tasks']['legacy:strategic_core']['coverage'],0)
            self.assertFalse(layers['raw']['macro']['complete'])
            self.assertFalse(result['capability_accepted'])

    def test_legacy_comparison_requires_matching_coverage_and_metrics(self):
        with preparation_modules() as (_,assessment):
            summary = assessment.summarize([dict(family='a',labels=[1]*5,prediction=[1]*5)])
            self.assertIsNone(summary['selection_score'])
            self.assertFalse(assessment.comparison(summary,summary)['eligible_to_replace_previous_limited_base'])


if __name__ == '__main__':
    unittest.main()

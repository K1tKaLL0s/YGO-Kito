"""Bounded source/gate/ETA checks. No formal dataset or GPU updates."""
from copy import deepcopy
from collections import Counter
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.multifactor_helpers import task_temporary_directory
from tests.test_multifactor_data_v3 import record as artificial_source,example as artificial_example
from tests.test_multifactor_review_v3 import fixture_run
from training.axis_generic import full18_sources as sources
from training.axis_generic import automatic_v3 as automatic
from training.axis_generic import readiness_v3,timing_v3
from ygo_kito.multifactor.contracts import LabelCell,RoleInput,FactorContractError
from ygo_kito.multifactor.task_queries import LEARNED_TASKS


def reviewed_case(unit):
    codes=set(unit['cards'])|set(sources.NORMALS)|{53129443}
    codes.update(range(900001,900021))
    catalog={c:dict(id=c,type=17 if c in sources.NORMALS else 33) for c in codes}
    case=dict(case_id='engineering-case',main=[[c,1] for c in sorted(codes)],extra=[],period='unknown')
    return case,catalog


def units():
    return sources.read(sources.ROOT/'full18_annotations.json')['units']


class Full18Tests(unittest.TestCase):
    def test_readiness_recognizes_retained_source_ids_after_preparation_and_merge(self):
        row=dict(record_id='record:prepared-hash',provenance=dict(source_record_ids=[
            json.dumps(['consumed_axis_references','legacy-case:a']),
            json.dumps(['full18_reviewed_context','full18:a:gamma_response:support'])]))
        self.assertTrue(readiness_v3.reviewed_source(row))
        row['provenance']['source_record_ids']=row['provenance']['source_record_ids'][:1]
        self.assertFalse(readiness_v3.reviewed_source(row))

    def test_missing_annotations_remain_omitted_and_normal_budget_is_observable(self):
        unit=units()[0];case,catalog=reviewed_case(unit)
        row=sources.source_record(case,unit,'support',catalog,0)
        role=next(v for v in row['targets']['task_labels'] if v['task']=='function_role')
        self.assertNotIn('extender',role['cells'])
        example=RoleInput.from_dict(row['observations']['input'])
        self.assertEqual(example.context.get('normal_summon_headroom').value,0)
        self.assertEqual(example.analysis_context.public_resources[0].quantity,0)
        self.assertEqual(row['supervision']['kind'],'weak_context_annotation')
        self.assertTrue(row['provenance']['previously_consumed'])
        self.assertFalse(row['provenance']['final_eval_eligible'])

    def test_possible_alternative_material_is_not_an_automatic_negative_member(self):
        for name in ('black_luster_ritual','tenyi_bounce'):
            unit=next(u for u in units() if u['id']==name);case,catalog=reviewed_case(unit)
            row=sources.source_record(case,unit,'main',catalog,1)
            members=[v['cells']['member']['value'] for v in row['targets']['task_labels'] if v['task']=='axis_membership']
            self.assertEqual(members,[1]*len(unit['cards']))

    def test_competing_normal_allocation_changes_only_contextual_compatibility(self):
        unit=next(u for u in units() if u['id']=='tourguide_link');case,catalog=reviewed_case(unit)
        a=sources.source_record(case,unit,'support',catalog,0)
        b=sources.source_record(case,unit,'support',catalog,1)
        def target(row,task):return next(v for v in row['targets']['task_labels'] if v['task']==task)
        self.assertEqual(target(a,'receiver_compatibility')['cells']['compatibility']['value'],'conflict')
        self.assertEqual(target(b,'receiver_compatibility')['cells']['compatibility']['value'],'compatible')
        self.assertEqual(target(a,'transferability'),target(b,'transferability'))
        self.assertEqual(target(a,'axis_origin'),target(b,'axis_origin'))

    def test_copy_preferences_use_actual_equal_slot_configurations(self):
        unit=units()[0];case,catalog=reviewed_case(unit)
        rows=list(sources.preference_records(case,catalog))
        self.assertEqual([r['targets']['task_labels'][0]['cells']['preference']['value'] for r in rows],['right','left','equal'])
        for row in rows:
            left=RoleInput.from_dict(row['observations']['input']);right=RoleInput.from_dict(row['comparison']['right']['input'])
            self.assertEqual(sum(n for c,n in left.deck.main),sum(n for c,n in right.deck.main))
            self.assertEqual(left.context,right.context)
            operation=row['comparison']['operation']
            actual=Counter(dict(left.deck.main));actual[operation['remove']['card_id']]-=1;actual[operation['add']['card_id']]+=1
            self.assertEqual({c:n for c,n in actual.items() if n},dict(right.deck.main))

    def test_label_stratification_keeps_all_related_rows_together(self):
        rows=[]
        for g in range(10):
            for value in (0,1):
                cards=((1,1),)+tuple((100*g+i+2,1) for i in range(5))
                row=artificial_source(f'g{g}:{value}',inp=artificial_example(cards),value=value,case_id='case:'+str(g))
                rows.append(row)
        required={('legacy:large_axis','value','0'),('legacy:large_axis','value','1')}
        with patch.object(sources,'required_classes',return_value=required):partitions=sources.freeze_partitions(rows)
        for g in range(10):self.assertEqual(rows[2*g]['supervision']['partition'],rows[2*g+1]['supervision']['partition'])
        groups=[set(partitions[k]) for k in ('training_groups','selection_groups','calibration_groups','retrospective_groups')]
        for i,a in enumerate(groups):
            self.assertTrue(a)
            for b in groups[i+1:]:self.assertFalse(a&b)
        # The prepared source reservations must survive the actual preparation
        # policy. No second random split is applied on top of frozen metadata.
        prepared,_=sources.preparation.prepare_records(rows,dict(seed=17,label_protocol='axis-generic-label-v3-m4',
            split=dict(train=1.,dev=0.,test=0.,require_three=False)))
        actual={fold:{r['provenance']['leakage_group'] for r in prepared if r['supervision']['partition']==fold}
                for fold in ('train','validation','retrospective_test')}
        self.assertEqual(actual['train'],set(partitions['training_groups']))
        self.assertEqual(actual['validation'],set(partitions['selection_groups'])|set(partitions['calibration_groups']))
        self.assertEqual(actual['retrospective_test'],set(partitions['retrospective_groups']))

    def test_full_readiness_rejects_fixture_sources_before_model_construction(self):
        with task_temporary_directory() as temp:
            root=Path(temp);config,manifest=fixture_run(root)
            evidence=root/'evidence';evidence.mkdir()
            def write(name,value):(evidence/name).write_text(json.dumps(value),encoding='utf-8')
            write('full18-evidence.json',dict(annotation_method='explicit test only',units={},
                cards={str(c):dict(type=17,desc='explicit artificial normal') for c in sources.NORMALS}))
            write('full18-protocol.json',dict(human_gold=False,engine_executed=False))
            write('source-partitions.json',{})
            config['selection_tasks']=list(LEARNED_TASKS);config['calibration_groups']=[]
            from ygo_kito.multifactor.training import RoleTrainer
            with patch.object(RoleTrainer,'__init__',side_effect=AssertionError('no model')):
                with self.assertRaisesRegex(FactorContractError,'engineering data'):
                    readiness_v3.check(config,manifest,{},evidence)

    def test_full_readiness_rejects_unverified_quote(self):
        with task_temporary_directory() as temp:
            root=Path(temp)
            evidence=dict(annotation_method='explicit test only',cards={'1':dict(desc='actual')},units={'u':dict(quotes=[[1,'invented']])})
            for name,value in [('full18-evidence.json',evidence),('full18-protocol.json',dict(human_gold=False,engine_executed=False)),('source-partitions.json',{})]:
                (root/name).write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaisesRegex(FactorContractError,'quote missing'):
                readiness_v3.check(dict(selection_tasks=list(LEARNED_TASKS)),{}, {},root)

    def test_estimate_accounts_for_batches_validation_io_and_postprocess(self):
        config=dict(effective_batch_size=64,batch_size=32,epochs=20,patience=4)
        manifest=dict(split_counts=dict(train=256))
        measurement=dict(train_batch_seconds=2.,development_epoch_seconds=10.,training_io_epoch_seconds=3.,postprocess_seconds=30.,binding={'dataset':'test'})
        initial=timing_v3.forecast(config,manifest,measurement)
        self.assertEqual(initial['remaining_seconds'],450.)
        self.assertEqual(initial['possible_early_stop_remaining_seconds'],135.)
        partial=timing_v3.forecast(config,manifest,measurement,next_batch=2)
        self.assertEqual(partial['remaining_seconds'],446.)
        done=timing_v3.forecast(config,manifest,measurement,completed_epoch=20)
        self.assertEqual(done['remaining_seconds'],30.)
        self.assertEqual(done['timezone'],'Asia/Hong_Kong')

    def test_timing_cache_binding_is_checked_before_cuda_or_updates(self):
        with task_temporary_directory() as temp:
            root=Path(temp);recipe,manifest=fixture_run(root)
            folder=root/'timing';folder.mkdir()
            (folder/'measurement.json').write_text(json.dumps(dict(identity={},recovery_equal=True)),encoding='utf-8')
            with self.assertRaisesRegex(FactorContractError,'measurement differs'):
                timing_v3.measure(recipe,manifest,folder,lambda *a,**k:None)

    def test_abstract_focus_does_not_invent_a_different_literal_goal(self):
        values=sources.objective('interfere','support',1,('synchro',))
        self.assertIsNone(values.get('objective_destroy').value)
        self.assertEqual(values.get('objective_synchro').value,1.)
        protected=sources.objective('protect','main',1)
        self.assertIsNone(protected.get('objective_negate').value)

    def test_new_portability_is_not_broadcast_to_legacy_generic_utility(self):
        for unit in (next(u for u in units() if u['id']=='two_normal_materials'),next(u for u in units() if u['id']=='invoked_named_recursion')):
            case,catalog=reviewed_case(unit)
            row=sources.source_record(case,unit,'main',catalog,1)
            self.assertEqual(row['targets']['roles'][0][1][4]['status'],'unknown')

    def test_excluding_a_mandatory_member_is_not_a_closed_portability_label(self):
        unit=units()[0];case,catalog=reviewed_case(unit)
        complete=sources.source_record(case,unit,'support',catalog,1)
        fragment=sources.explicit_incomplete_query(complete,unit)
        self.assertEqual(complete['targets']['roles'][0][1][4]['value'],1)
        self.assertEqual(fragment['targets']['roles'][0][1][4]['value'],0)
        self.assertEqual(fragment['targets']['task_labels'],[])
        self.assertNotIn(unit['exclude_required_member'],dict(RoleInput.from_dict(fragment['observations']['input']).unit_definition.members))

    def test_mechanism_truth_is_bound_to_real_card_nodes_without_unreviewed_negatives(self):
        unit=deepcopy(units()[0]);unit['mechanism_by_card']={'38814750':['negate_activation']}
        case,catalog=reviewed_case(unit);row=sources.source_record(case,unit,'main',catalog,1)
        labels=[v for v in row['targets']['task_labels'] if v['task']=='mechanism']
        self.assertTrue(all(v['subject'][0].startswith('card:') for v in labels))
        gamma=next(v for v in labels if v['subject']==['card:38814750'])
        self.assertEqual(gamma['cells']['negate_activation']['value'],1)
        self.assertNotIn('draw',gamma['cells'])

    def test_opaque_or_indistinguishable_primary_scope_does_not_force_a_role(self):
        unit=next(u for u in units() if u['id']=='invoked_fusion_bridge');case,catalog=reviewed_case(unit)
        case['objective_tags']=['fusion']
        row=sources.source_record(case,unit,'support',catalog,1)
        self.assertEqual(row['targets']['roles'][0][1][2]['status'],'unknown')
        position=next(v for v in row['targets']['task_labels'] if v['task']=='axis_position')
        self.assertEqual(position['cells']['position']['status'],'unknown')

    def test_omitting_a_variant_does_not_break_its_known_transitive_lineage(self):
        a=artificial_source('a',inp=artificial_example(tuple((i,1) for i in range(1,7))),case_id='a')
        b=artificial_source('b',inp=artificial_example(tuple((i,1) for i in range(101,107))),case_id='b')
        sources.carry_lineage([a,b],{'a':'historical-shared','b':'historical-shared'})
        grouping=sources.build_leakage_groups([r for r,_ in sources.preparation._source_stubs([a,b])])
        self.assertEqual(len(grouping['groups']),1)


if __name__=='__main__':unittest.main()

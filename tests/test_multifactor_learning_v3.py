"""M5 regression SOURCES. Do not collect/run without user authorization."""
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import gzip
import importlib
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

import torch

from ygo_kito.multifactor import (AnalysisContext, AnalysisGraph, DeckSpec, Factors, FunctionSeed,
    GraphNode, LabelCell, LabelSet, RoleInput, UnitSpec, build_analysis_graph)
from ygo_kito.multifactor.contracts import FactorContractError, GRAPH_VERSION, ROLES, TASK_DOMAINS, digest
from ygo_kito.multifactor.network import NetworkConfig, RoleNetwork, encode_batch
from ygo_kito.multifactor.training import RoleTrainer, Supervision, Targets
from ygo_kito.multifactor.graph_training import compile_records
from ygo_kito.multifactor.task_queries import (LEARNED_TASKS, iter_queries, observation_view,
                                            query_domain, query_key, validate_query)
from tests.multifactor_helpers import task_temporary_directory

PROTOCOL = 'axis-generic-label-v3-m4'


def config(**values):
    return NetworkConfig(**dict(dict(hidden_dim=16,message_rounds=2,seed=19,feature_schema=GRAPH_VERSION),**values))


def binding(name='fixture'):
    return {key:digest((name,key)) for key in ('dataset','split','calibration','recipe')}


def build(size=3):
    deck = DeckSpec(tuple((i,2 if i==1 else 1) for i in range(1,size+1)),(),()) if size<=60 else DeckSpec(
        tuple((i,1) for i in range(1,61)),tuple((i,1) for i in range(61,min(size,75)+1)),tuple((i,1) for i in range(76,size+1)))
    example = RoleInput('frozen-goal',Factors('context'),(),analysis_mode='deck_analysis',
        analysis_context=AnalysisContext(),deck=deck,
        unit_definition=UnitSpec('focal',((1,1),(2,1)),'function:search'))
    seed = FunctionSeed('observed-search',(('card:1',1),('card:2',1)),('search',))
    return build_analysis_graph(example,function_seeds=(seed,))


def record(labels=(), *, roles=None, confidence=1.0, kind='definition_development', status='known', name='r'):
    observed = build()
    sets = tuple(LabelSet(task,tuple(subject),((coordinate,LabelCell(value if status=='known' else None,status,confidence)),))
                 for task,subject,coordinate,value in labels)
    targets = Targets(roles=() if roles is None else (('query:unit',tuple(LabelCell.from_legacy(v) for v in roles)),),task_labels=sets).to_dict()
    result = dict(schema_version='axis-training-record-v3',record_id=name,input_key=digest(observed.graph.to_dict()),
        observations=observed.to_dict()['observations'],targets=targets,
        supervision=dict(kind=kind,source_kinds=[kind],partition='train',trainable=True,label_protocol=PROTOCOL,
            label_protocol_sha256=digest(PROTOCOL),cell_sources={},source_group_weights={}),
        provenance=dict(leakage_group='fixture-source',source_record_ids=[name]))
    counts = Counter()
    for task,subject,coordinate,cell in Targets.from_dict(targets).graph_cells():
        if cell.known:
            counts[task] += 1
            result['supervision']['cell_sources'][query_key(task,subject,coordinate)] = [dict(kind=kind,source_record_id=name,confidence=confidence)]
    result['supervision']['source_group_weights'] = {task:1/n for task,n in counts.items()}
    return result


def trainer(**kwargs):
    return RoleTrainer(config(),binding=binding(),label_protocol_sha256=digest(PROTOCOL),**kwargs)


def with_comparison(row):
    row=deepcopy(row)
    left,_,_=observation_view(row)
    right=replace(left,deck=DeckSpec(((1,2),(2,1),(4,1)),(),()))
    build_right=build_analysis_graph(right,function_seeds=(FunctionSeed('observed-search',(('card:1',1),('card:2',1)),('search',)),))
    row["comparison"]=dict(right=build_right.to_dict()["observations"],left_key="query:unit",right_key="query:unit",
        operation=dict(add=dict(card_id=4,section="main",quantity=1),remove=dict(card_id=3,section="main",quantity=1),kind="replacement"))
    return row


@contextmanager
def runner_module():
    root = Path(__file__).resolve().parents[1]/'training'/'axis_generic'
    # Restore the training aliases only. Removing newly imported Torch modules
    # would leave their native operator registrations alive and reload them.
    names=("train_v3","runtime","assessment","prepare_v3","workflow_v3","environment_v3","legacy_import")
    previous={name:sys.modules.get(name) for name in names}
    with patch.object(sys,'path',[str(root)]+sys.path):
        try:
            yield importlib.import_module('train_v3')
        finally:
            for name,module in previous.items():
                if module is None:
                    sys.modules.pop(name,None)
                else:
                    sys.modules[name]=module


class GraphEncodingTests(unittest.TestCase):
    def test_large_graph_has_all_cards_and_three_sections(self):
        observed = build(90)
        tensors = encode_batch((observed,),config=config())
        self.assertGreater(len(tensors['nodes']),64)
        self.assertEqual(len(tensors['indices'][0]),len(observed.graph.nodes))
        self.assertTrue(all('section:'+s in tensors['indices'][0] for s in ('main','extra','side')))

    def test_labels_and_source_ids_do_not_enter_graph_tensors(self):
        a = record([('mechanism',('card:1',),'search',1)])
        b = deepcopy(a)
        b['targets'] = Targets().to_dict()
        b['record_id'] = 'renamed'
        b['provenance'] = {'leakage_group':'other'}
        one,two = [encode_batch((r,),config=config()) for r in (a,b)]
        for key,value in one.items():
            if isinstance(value,torch.Tensor):
                torch.testing.assert_close(value,two[key],rtol=0,atol=0)

    def test_opaque_context_name_is_not_a_numeric_feature(self):
        a = build()
        b = replace(a,input=replace(a.input,context_ref='another opaque name'))
        one,two = [encode_batch((v,),config=config()) for v in (a,b)]
        torch.testing.assert_close(one['nodes'],two['nodes'],rtol=0,atol=0)
        torch.testing.assert_close(one['context'],two['context'],rtol=0,atol=0)

    def test_permutation_equivariance_with_global_edge_addresses(self):
        a = build()
        b = replace(a,graph=AnalysisGraph(tuple(reversed(a.graph.nodes)),tuple(reversed(a.graph.edges))))
        model = RoleNetwork(config())
        scores = []
        for observed in (a,b):
            encoded = encode_batch((observed,),config=config())
            scores.append(model.score_queries(model(encoded),encoded,[(0,'legacy:large_axis',('query:unit',),'value')])[0])
        torch.testing.assert_close(*scores,rtol=3e-5,atol=3e-6)

    def test_other_batch_members_do_not_change_valid_scores(self):
        model = RoleNetwork(config())
        one = encode_batch((build(),),config=config())
        two = encode_batch((build(),build(9)),config=config())
        query = [(0,'mechanism',('card:1',),'search')]
        torch.testing.assert_close(model.score_queries(model(one),one,query)[0],model.score_queries(model(two),two,query)[0],rtol=3e-5,atol=3e-6)

    def test_edge_and_node_chunks_do_not_drop_cross_block_edges(self):
        small,large = config(graph_block_size=2),config(graph_block_size=1024)
        a,b = RoleNetwork(small),RoleNetwork(large)
        b.load_state_dict(a.state_dict(),strict=True)
        encoded = encode_batch((build(),),config=small)
        query = [(0,'mechanism',('card:1',),'search')]
        torch.testing.assert_close(a.score_queries(a(encoded),encoded,query)[0],b.score_queries(b(encoded),encoded,query)[0],rtol=3e-5,atol=3e-6)

    def test_stream_and_route_switches_are_independent(self):
        self.assertEqual(NetworkConfig.v3().hidden_dim,64)
        for stream in ('single','dual'):
            for route in (False,True):
                cfg = config(stream_mode=stream,use_route_features=route)
                model = RoleNetwork(cfg)
                self.assertEqual(model.graph_network.route_projection is not None,route)
                self.assertEqual(model(encode_batch((build(),),config=cfg))['node'].shape[-1],16)

    def test_explicit_state_nodes_cannot_change_structural_stream(self):
        observed = build()
        state = GraphNode('opaque-state','condition',Factors('group'),attributes=(('scope_state',1),('quantity',1)))
        first = replace(observed,graph=AnalysisGraph(observed.graph.nodes+(state,),observed.graph.edges))
        changed = replace(state,attributes=(('scope_state',1),('quantity',100)))
        second = replace(observed,graph=AnalysisGraph(observed.graph.nodes+(changed,),observed.graph.edges))
        model = RoleNetwork(config())
        a,b = [encode_batch((v,),config=config()) for v in (first,second)]
        torch.testing.assert_close(model(a)['structural_node'],model(b)['structural_node'],rtol=0,atol=0)

    def test_membership_can_query_outside_candidate_seed(self):
        observed = build()
        domain = query_domain(*observation_view(observed))
        axis = domain['axes'][0]
        self.assertNotIn('card:3',dict(observed.candidates.candidates[0].members))
        validate_query(domain,'axis_membership',(axis,'card:3'),'member')
        self.assertIn(('axis_membership',(axis,'card:3'),'member'),list(iter_queries(domain,'axis_membership')))
        with runner_module() as runner:
            assessment = importlib.import_module('assessment')
            protocol = runner.read(runner.ROOT/'ASSESSMENT_PROTOCOL.v3.json')
            protocol['bootstrap']['repetitions'] = 0
            row = record(name='eval')
            row['supervision'].update(partition='validation',trainable=False)
            row['provenance']['axis_truth'] = [dict(members=['card:1','card:3'],allowed_candidate_refs=[axis])]
            predictions = {'eval':{'axes':{'raw':[dict(candidate_ref=axis,members=['card:1','card:3'])]}}}
            report = assessment.assess_records([row],predictions,protocol)
            self.assertEqual(report['partitions']['validation']['layers']['raw']['axes']['source_macro_iou'],1)

    def test_training_injection_never_changes_encoder_or_natural_eval_domain(self):
        observed = build()
        source = observed.candidates.candidates[0]
        injected = replace(source,members=(('card:1',1),('card:3',1)))
        row = record([('axis_membership',(injected.candidate_id,'card:3'),'member',1)])
        row['supervision']['training_queries'] = [dict(source_candidate_ref=source.candidate_id,members=[['card:1',1],['card:3',1]])]
        normal = encode_batch((row,),config=config())
        training = encode_batch((row,),config=config(),training=True)
        torch.testing.assert_close(normal['nodes'],training['nodes'],rtol=0,atol=0)
        self.assertNotIn(injected.candidate_id,normal['domains'][0]['axes'])
        self.assertIn(injected.candidate_id,training['domains'][0]['axes'])
        self.assertFalse(trainer().train_supervised((row,))['skipped'])

    def test_missing_natural_axis_stays_a_known_miss(self):
        row = record([('axis_membership',('gold-axis-not-recalled','card:3'),'member',1)])
        result = trainer().train_supervised((row,))
        self.assertTrue(result['skipped'])
        self.assertEqual(result['unrepresented_candidate_cells'],1)
        self.assertEqual(row['targets']['task_labels'][0]['cells']['member']['status'],'known')

    def test_directed_relation_queries_preserve_argument_order(self):
        observed = build()
        model = RoleNetwork(config())
        batch = encode_batch((observed,),config=config())
        queries = [(0,'pair_relation',pair,'support') for pair in (('query:unit','card:1'),('card:1','query:unit'))]
        scores = model.score_queries(model(batch),batch,queries)
        self.assertFalse(torch.equal(scores[0],scores[1]))

    def test_graph_budget_refuses_instead_of_truncating(self):
        with self.assertRaises(FactorContractError):
            encode_batch((build(),),config=config(graph_node_budget=2))
        with self.assertRaises(FactorContractError):
            RoleNetwork(config())(encode_batch((build(),),config=None))


class MaskedLearningTests(unittest.TestCase):
    def test_v16_carrier_and_enhancer_are_independent_positive_cells(self):
        subject = ("query:unit", "function:search")
        row = record([("contribution", subject, "carrier", 1)])
        labels = LabelSet("contribution", subject,
                          (("carrier", LabelCell(1, "known")), ("enhancer", LabelCell(1, "known"))))
        row["targets"] = replace(Targets.from_dict(row["targets"]), task_labels=(labels,)).to_dict()
        row["supervision"]["cell_sources"][query_key("contribution", subject, "enhancer")] = deepcopy(
            row["supervision"]["cell_sources"][query_key("contribution", subject, "carrier")])
        row["supervision"]["source_group_weights"]["contribution"] = .5
        target = Targets.from_dict(row["targets"])
        self.assertEqual(target.to_dict(), row["targets"])
        self.assertEqual(len(target.task_labels), 1)
        self.assertEqual({(task, refs, coordinate, cell.value) for task, refs, coordinate, cell
                          in target.graph_cells() if cell.known},
                         {("contribution", subject, "carrier", 1), ("contribution", subject, "enhancer", 1)})
        t = trainer()
        compiled, _ = compile_records(t, [row])
        self.assertEqual({value["coordinate"] for value in compiled}, {"carrier", "enhancer"})
        self.assertEqual(len(compiled), 2)
        self.assertTrue(all(value["cell"].known and value["cell"].value == 1 for value in compiled))
        head = t.model.graph_network.heads["contribution"]
        with torch.no_grad():
            head.weight.zero_()
            head.bias.zero_()
        gradients = []
        hook = head.bias.register_hook(lambda gradient: gradients.append(gradient.detach().clone()))
        try:
            result = t.train_supervised((row,))
        finally:
            hook.remove()
        self.assertFalse(result["skipped"])
        self.assertEqual(set(result["component_losses"]), {"contribution"})
        self.assertAlmostEqual(result["component_losses"]["contribution"], .6931471805599453, places=6)
        self.assertEqual(len(gradients), 1)
        torch.testing.assert_close(gradients[0], torch.full_like(gradients[0], -.25), rtol=0, atol=1e-7)
        self.assertTrue(torch.all(head.bias.detach() > 0).item())
        self.assertEqual(t.steps, 1)
        self.assertEqual(t.updates["contribution"]["definition_development"], 1)
        self.assertEqual(sum(t.updates[task]["definition_development"] for task in LEARNED_TASKS), 1)

    def test_all_learned_heads_have_independent_loss_and_counts(self):
        axis = build().candidates.candidates[0].candidate_id
        labels = [('mechanism',('card:1',),'search',1),('axis_membership',(axis,'card:3'),'member',0),
            ('axis_function',(axis,),'search',1),('function_role',('query:unit','function:search'),'starter',1),
            ('contribution',('query:unit','function:search'),'carrier',1),
            ('axis_position',(axis,),'position','main'),('axis_origin',(axis,),'origin','mixed'),
            ('transferability',('query:unit','function:search'),'portability','conditional'),
            ('receiver_compatibility',('query:unit',),'compatibility','compatible'),
            ('pair_relation',('query:unit','card:3'),'support',1),('copy_preference',('query:unit','query:unit'),'preference','left')]
        row = with_comparison(record(labels,roles=[1,0,1,0,1]))
        target = Targets.from_dict(row['targets'])
        row['targets'] = replace(target,compatibility=(('query:unit',LabelCell(1,'known')),),pairs=(('query:unit','card:3',LabelCell(0,'known')),)).to_dict()
        for task,subject,coordinate,cell in Targets.from_dict(row['targets']).graph_cells():
            row['supervision']['cell_sources'].setdefault(query_key(task,subject,coordinate),[dict(kind='definition_development',source_record_id='r',confidence=1)])
        t = trainer()
        result = t.train_supervised((row,))
        self.assertFalse(result['skipped'])
        self.assertEqual(set(result['component_losses']),set(LEARNED_TASKS))
        self.assertTrue(all(t.updates[task]['definition_development']==1 for task in LEARNED_TASKS))

    def test_unknown_conflict_and_not_applicable_never_forward_or_step(self):
        for status in ('unknown','conflict','not_applicable'):
            t = trainer()
            row = record([('mechanism',('card:1',),'search',None)],status=status)
            with patch.object(t.model,'forward',side_effect=AssertionError('must not forward')):
                result = t.train_supervised((row,))
            self.assertTrue(result['skipped'])
            self.assertEqual(t.steps,0)
            self.assertFalse(t.optimizer.state)

    def test_zero_confidence_never_forwards(self):
        t = trainer()
        row = record([('mechanism',('card:1',),'search',1)],confidence=0)
        with patch.object(t.model,'forward',side_effect=AssertionError('must not forward')):
            self.assertTrue(t.train_supervised((row,))['skipped'])

    def test_weak_evidence_scales_numerator_without_canceling(self):
        scores = []
        for confidence in (1,.25):
            t = trainer()
            row = record([('mechanism',('card:1',),'search',1)],confidence=confidence)
            scores.append(t.train_supervised((row,))['loss'])
        self.assertAlmostEqual(scores[1],scores[0]*.25,places=6)

    def test_unsupervised_head_parameters_and_counters_stay_unchanged(self):
        t = trainer()
        original = deepcopy(t.model.graph_network.heads['axis_origin'].state_dict())
        t.train_supervised((record([('mechanism',('card:1',),'search',1)]),))
        for key,value in t.model.graph_network.heads['axis_origin'].state_dict().items():
            torch.testing.assert_close(value,original[key],rtol=0,atol=0)
        self.assertEqual(t.head_status('axis_origin'),'untrained')

    def test_source_group_weights_are_retained_separately_from_evidence(self):
        row = record([('mechanism',('card:1',),'search',1)],confidence=.2)
        row['supervision']['source_group_weights']['mechanism'] = .01
        compiled,_ = compile_records(trainer(),[row])
        self.assertEqual(compiled[0]['base'],.01)
        self.assertEqual(compiled[0]['evidence'],.2)

    def test_heldout_wrong_protocol_and_bad_coordinate_reject_before_step(self):
        cases = []
        heldout = record([('mechanism',('card:1',),'search',1)])
        heldout['supervision']['partition'] = 'validation'
        cases.append(heldout)
        wrong = record([('mechanism',('card:1',),'search',1)])
        wrong['supervision']['label_protocol_sha256'] = digest('wrong')
        cases.append(wrong)
        cases.append(record([('axis_function',('query:unit',),'search',1)]))
        for row in cases:
            t = trainer()
            with self.assertRaises(FactorContractError):
                t.train_supervised((row,))
            self.assertEqual(t.steps,0)

    def test_mixed_record_uses_per_cell_sources(self):
        row = record([('mechanism',('card:1',),'search',1)],roles=[None,None,1,None,None])
        row['supervision']['kind'] = 'mixed'
        row['supervision']['source_kinds'] = ['definition_development','engine_probe']
        row['supervision']['cell_sources'][query_key('mechanism',('card:1',),'search')][0]['kind'] = 'engine_probe'
        t = trainer()
        t.train_supervised((row,))
        self.assertEqual(t.updates['mechanism']['engine_probe'],1)
        self.assertEqual(t.updates['legacy:strategic_core']['definition_development'],1)
        bad = deepcopy(row)
        bad['supervision']['cell_sources'][query_key('legacy:strategic_core',('query:unit',),'value')][0]['kind'] = 'engine_probe'
        with self.assertRaises(FactorContractError):
            trainer().train_supervised((bad,))

    def test_deterministic_readiness_and_environment_are_not_neural_counts(self):
        t = trainer()
        row = record([('state_readiness',('query:unit',),'ready','blocked')])
        self.assertTrue(t.train_supervised((row,))['skipped'])
        self.assertEqual(t.head_status('state_readiness'),'deterministic_only')
        self.assertEqual(t.head_status('environment_value'),'disabled')
        with self.assertRaises(FactorContractError):
            t.enable_lora(engineering_mode=True)

    def test_preference_requires_goal_operation_and_train_source(self):
        t = trainer()
        source = Supervision('definition_development','explicit preference',scope='candidate',label_protocol_sha256=digest(PROTOCOL))
        with self.assertRaises(FactorContractError):
            t.train_preference(build(),build(),left_key='query:unit',right_key='query:unit',preferred_left=1,source=source)
        pair=with_comparison(record())
        result = t.train_preference(build(),pair["comparison"]["right"],left_key='query:unit',right_key='query:unit',preferred_left=.5,
            source=source,comparison_operation=pair["comparison"]["operation"])
        self.assertFalse(result['skipped'])
        self.assertEqual(t.updates['copy_preference']['definition_development'],1)

    def test_only_explicit_same_definition_consistency_is_admitted(self):
        left = record([('transferability',('query:unit','function:search'),'portability','conditional')],name='left')
        right = record(name='right')
        t = trainer()
        pair = dict(left=0,right=1,task='transferability',subject=['query:unit','function:search'],
                    coordinate='portability',scope='unit_definition',evidence_ref='reviewed invariant',confidence=.5)
        result = t.train_supervised((left,right),consistency=(pair,))
        self.assertIn('consistency',result['component_losses'])
        pair['scope'] = 'receiver_role'
        with self.assertRaises(FactorContractError):
            trainer().train_supervised((left,right),consistency=(pair,))


class RecoveryTests(unittest.TestCase):
    def test_resume_next_update_and_rng_equal_continuous_run(self):
        row = record([('mechanism',('card:1',),'search',1)])
        a = trainer()
        a.train_supervised((row,))
        a.sampler_state.update(epoch=2,next_batch=3)
        with task_temporary_directory() as tmp:
            path = Path(tmp)/'saved.pt'
            a.save(path)
            expected_python,expected_torch = random.random(),torch.rand(3)
            a.train_supervised((row,))
            expected = deepcopy(a.model.state_dict())
            b = RoleTrainer.load(path,expected_config=config(),expected_binding=binding(),expected_label_protocol_sha256=digest(PROTOCOL))
            self.assertEqual(random.random(),expected_python)
            torch.testing.assert_close(torch.rand(3),expected_torch,rtol=0,atol=0)
            self.assertEqual(b.sampler_state['next_batch'],3)
            b.train_supervised((row,))
            for key,value in expected.items():
                torch.testing.assert_close(value,b.model.state_dict()[key],rtol=0,atol=0)
            self.assertEqual(a.updates,b.updates)

    def test_resume_rejects_data_architecture_and_missing_bindings(self):
        with task_temporary_directory() as tmp:
            path = Path(tmp)/'saved.pt'
            trainer().save(path)
            for kwargs in (dict(expected_config=config(),expected_binding=binding('new')),
                           dict(expected_config=config(stream_mode='single'),expected_binding=binding()),{}):
                with self.assertRaises(FactorContractError):
                    RoleTrainer.load(path,expected_label_protocol_sha256=digest(PROTOCOL),**kwargs)

    def test_warm_start_copies_only_shared_encoder_and_resets_heads(self):
        with task_temporary_directory() as tmp:
            path = Path(tmp)/'saved.pt'
            a = trainer()
            a.train_supervised((record([('mechanism',('card:1',),'search',1)]),))
            a.save(path)
            b = RoleTrainer.warm_start(path,config=config(seed=21),binding=binding('new'),label_protocol_sha256=digest('new-label'))
            self.assertEqual(b.steps,0)
            self.assertFalse(b.optimizer.state)
            self.assertTrue(all(b.head_status(t)=='untrained' for t in LEARNED_TASKS))
            torch.testing.assert_close(a.model.graph_network.node_encoder[0].weight,b.model.graph_network.node_encoder[0].weight,rtol=0,atol=0)
            self.assertFalse(torch.equal(a.model.graph_network.heads['mechanism'].weight,b.model.graph_network.heads['mechanism'].weight))
            self.assertTrue(all('heads.' not in key for key in b.warm_start_report['copied']))

    def test_old_weight_file_is_never_replaced(self):
        with task_temporary_directory() as tmp:
            path = Path(tmp)/'existing.pt'
            path.write_bytes(b'preserve original bytes')
            with self.assertRaises(FactorContractError):
                trainer().save(path)
            self.assertEqual(path.read_bytes(),b'preserve original bytes')

    def test_checkpoint_publish_preserves_a_concurrent_file(self):
        from ygo_kito.multifactor import graph_training
        with task_temporary_directory() as tmp:
            path = Path(tmp)/'concurrent.pt'
            t = trainer()
            original_cursor = t.data_cursor
            operation = 'rename' if graph_training.os.name=='nt' else 'link'
            publish = getattr(graph_training.os,operation)

            def concurrent_publish(source,destination):
                Path(destination).write_bytes(b'concurrent writer bytes')
                return publish(source,destination)

            with patch.object(graph_training.os,operation,side_effect=concurrent_publish) as called:
                with self.assertRaises(FileExistsError):
                    t.save(path,data_cursor='unpublished-cursor')
            called.assert_called_once()
            self.assertEqual(path.read_bytes(),b'concurrent writer bytes')
            self.assertEqual(t.data_cursor,original_cursor)
            self.assertEqual(set(Path(tmp).iterdir()),{path})

    def test_adam_shape_corruption_is_rejected(self):
        with task_temporary_directory() as tmp:
            t = trainer()
            t.train_supervised((record([('mechanism',('card:1',),'search',1)]),))
            path = Path(tmp)/'saved.pt'
            t.save(path)
            payload = torch.load(path,weights_only=True)
            next(iter(payload['optimizer']['state'].values()))['exp_avg'] = torch.zeros(1)
            broken = Path(tmp)/'broken.pt'
            torch.save(payload,broken)
            with self.assertRaises(FactorContractError):
                RoleTrainer.load(broken,expected_config=config(),expected_binding=binding(),expected_label_protocol_sha256=digest(PROTOCOL))


class RunnerTests(unittest.TestCase):
    def test_batch_cursor_replays_same_remaining_records_without_final_reads(self):
        with runner_module() as runner,task_temporary_directory() as tmp:
            root = Path(tmp)
            rows = [record(name=str(i)) for i in range(5)]
            with gzip.open(root/'train.gz','wt',encoding='utf-8') as stream:
                stream.write('\n'.join(json.dumps(r) for r in rows)+'\n')
            manifest = dict(shards={'train':[dict(file='train.gz',records=5,semantic_records=digest(rows))],
                                   'test':[dict(file='must-not-open.gz')]})
            whole = list(runner.batches(root,manifest,'train',2,seed=8))
            resumed = list(runner.batches(root,manifest,'train',2,seed=8,skip=1))
            self.assertEqual(whole[1:],resumed)
            with self.assertRaises(FactorContractError):
                list(runner.batches(root,manifest,'test'))

    def test_paused_configuration_stops_before_directory_or_device_actions(self):
        with runner_module() as runner,patch.object(runner,'load_manifest',side_effect=AssertionError('must not read data')):
            with self.assertRaises(FactorContractError):
                runner.main_config({'formal_training':False})

    def test_incomplete_development_coverage_has_no_selection_score(self):
        with runner_module() as runner:
            report = {'partitions':{'validation':{'layers':{'raw':{'tasks':{'mechanism':
                dict(complete_class_coverage=False,source_macro={'f1':1})}}}}}}
            self.assertIsNone(runner.selection_score(report,['mechanism']))

    def test_global_class_coverage_does_not_require_every_source_to_have_every_class(self):
        with runner_module() as runner:
            report = {'partitions':{'validation':{'layers':{'raw':{'tasks':{'transferability':
                dict(complete_class_coverage=True,source_macro={'f1':None,'overall_accuracy':.75})}}}}}}
            self.assertEqual(runner.selection_score(report,['transferability']),.75)


if __name__=='__main__':
    unittest.main()

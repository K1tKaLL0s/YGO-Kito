"""Bounded artificial training controls; no real data or formal recipe."""
from copy import deepcopy
from dataclasses import asdict
import gzip
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import torch

from tests.multifactor_helpers import task_temporary_directory
from tests.test_multifactor_learning_v3 import config, binding, record, runner_module, PROTOCOL
from ygo_kito.multifactor.contracts import FactorContractError, digest
from ygo_kito.multifactor.training import RoleTrainer


def make(**kwargs):
    architecture = kwargs.pop('architecture',config())
    return RoleTrainer(architecture,binding=binding(),label_protocol_sha256=digest(PROTOCOL),**kwargs)


class TrainingControlTests(unittest.TestCase):
    def test_accumulation_matches_full_source_balanced_update(self):
        rows = [record([('mechanism',('card:1',),'search',y)],name=str(i),confidence=c)
                for i,(y,c) in enumerate(((1,1.),(0,.2),(1,.7)))]
        rows[-1]['provenance']['leakage_group']='second-source'
        a,b = make(),make()
        one = a.train_supervised(rows)
        two = b.train_supervised(rows,micro_batch_size=1)
        self.assertEqual(two['micro_batches'],3)
        self.assertAlmostEqual(one['loss'],two['loss'],6)
        self.assertEqual(a.updates,b.updates)
        self.assertEqual(a.data_digest,b.data_digest)
        for x,y in zip(a.model.parameters(),b.model.parameters()):
            torch.testing.assert_close(x,y,atol=2e-6,rtol=2e-5)

    def test_adamw_dropout_resume_next_update_is_identical(self):
        architecture=config(dropout=.1)
        a=make(architecture=architecture,optimizer_config=dict(name='adamw',weight_decay=.0001))
        rows=[record([('mechanism',('card:1',),'search',1)])]
        a.train_supervised(rows,micro_batch_size=1)
        with task_temporary_directory() as root:
            path=Path(root)/'base.pt'
            a.save(path)
            a.train_supervised(rows,micro_batch_size=1)
            b=RoleTrainer.load(path,expected_config=architecture,expected_binding=binding(),expected_label_protocol_sha256=digest(PROTOCOL))
            b.train_supervised(rows,micro_batch_size=1)
            for x,y in zip(a.model.parameters(),b.model.parameters()):
                torch.testing.assert_close(x,y,atol=0,rtol=0)
            with self.assertRaises(FactorContractError):
                RoleTrainer.load(path,expected_config=architecture,expected_binding=binding(),expected_label_protocol_sha256=digest(PROTOCOL),expected_optimizer_config=dict(name='adam',weight_decay=0.))

    def test_micro_batches_respect_graph_budget_without_dropping_rows(self):
        row=record([('mechanism',('card:1',),'search',1)])
        n=len(row['observations']['graph']['nodes'])
        a=make(architecture=config(graph_node_budget=n))
        result=a.train_supervised([row,deepcopy(row)],micro_batch_size=2)
        self.assertEqual(result['micro_batches'],2)
        self.assertEqual(a.steps,1)

    def test_unknown_and_invalid_record_do_not_update(self):
        a=make()
        self.assertTrue(a.train_supervised([record()],micro_batch_size=1)['skipped'])
        good=record([('mechanism',('card:1',),'search',1)])
        bad=deepcopy(good); bad['supervision']['partition']='test'
        with patch.object(a.optimizer,'step',side_effect=AssertionError('must validate first')):
            with self.assertRaises(FactorContractError):
                a.train_supervised([good,bad],micro_batch_size=1)
        self.assertEqual(a.steps,0)

    def test_real_runner_fixture_early_stop_and_completed_resume(self):
        with task_temporary_directory() as temp,runner_module() as runner:
            root=Path(temp); data=root/'data'; data.mkdir()
            manifest=dict(preparation_identity=dict(semantic_id=digest('fixture'),semantic_config=dict(split={})),split_version='fixture',grouping=dict(groups=['train','validation']),shards={})
            for fold in ('train','validation'):
                rows=[]
                for i in range(2):
                    row=record([('mechanism',('card:1',),'search',i)],name=fold+str(i),kind='engineering_fixture')
                    row['supervision'].update(partition=fold,trainable=fold=='train')
                    row['provenance']['leakage_group']=fold
                    rows.append(row)
                path=data/(fold+'.gz')
                with gzip.open(path,'wt',encoding='utf-8') as stream:
                    stream.write(''.join(json.dumps(r)+'\n' for r in rows))
                manifest['shards'][fold]=[dict(file=path.name,records=2,semantic_records=digest(rows))]
            recipe=dict(network=asdict(config()),device='cpu',execution_mode='engineering_fixture',engineering_max_records=4,
                formal_training=False,automatic_lora=False,core_course_resumed=False,dataset_dir=str(data),run_dir=str(root/'run'),
                epochs=3,patience=1,minimum_improvement=1.,batch_size=1,effective_batch_size=2,save_every_batches=5,
                seed=17,learning_rate=.001,load_mode='fresh',label_protocol=PROTOCOL,
                assessment_protocol='ASSESSMENT_PROTOCOL.v3.json',selection_tasks=['mechanism'])
            result=runner.fit(recipe,root/'run',manifest,lambda *args,**kwargs:None)
            self.assertEqual(result['sampler']['epoch'],2)
            self.assertEqual(result['updates'],2)
            self.assertTrue(result['sampler']['finished'])
            self.assertFalse(result['capability_accepted'])
            recipe['load_mode']='resume'
            resumed=runner.fit(recipe,root/'run',manifest,lambda *args,**kwargs:None)
            self.assertTrue(resumed['resumed_completed'])
            self.assertEqual(resumed['updates'],2)

    def test_paused_and_unbounded_engineering_recipe_refuse(self):
        with runner_module() as runner:
            with self.assertRaises(FactorContractError):
                runner.main_config(dict(formal_training=False))
            with self.assertRaises(FactorContractError):
                runner.validate_execution(dict(formal_training=False,execution_mode='engineering_fixture',device='cuda:0',automatic_lora=False,core_course_resumed=False))

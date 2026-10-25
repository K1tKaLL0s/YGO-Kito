"""Pure goal/chain contracts; synthetic messages are not engine evidence."""
import copy,json,unittest
from pathlib import Path
from ygo_kito.build_contracts import BuildTask
from ygo_kito.build_semantics import route_task
from ygo_kito.route_search import resolved_chain_cards
from ygo_kito.validation import ContractError

ROOT=Path(__file__).resolve().parents[1]


class CombinedGoalContracts(unittest.TestCase):
    def test_required_effect_objectives_preserve_strict_public_scope(self):
        raw=json.loads((ROOT/'configs/build-combined-native-v4.json').read_text());task=BuildTask.from_dict(raw)
        child=route_task(task)
        self.assertEqual(child.schema_version,3);self.assertEqual(child.goal['card_id'],78156759)
        self.assertEqual(child.environment['versions']['card_pool'],'native-extra-material-v2')
        self.assertEqual(task.environment['versions']['card_pool'],'native-private-knowledge-v5')
        for mutation in ('no-route','unknown-card','repeat','unhashable','hidden-goal','prewritten-route','no-opening-minimum'):
            d=copy.deepcopy(raw)
            if mutation=='no-route':d['goal'].pop('route_goal')
            elif mutation=='unknown-card':d['goal']['required_activations']=[999999999]
            elif mutation=='repeat':d['goal']['required_activations']=[14878871,14878871]
            elif mutation=='unhashable':d['goal']['required_activations']=[[14878871]]
            elif mutation=='hidden-goal':d['goal']['route_goal']['opponent_hand']=[1]
            elif mutation=='prewritten-route':d['goal']['route_goal']['route']=[{'operation':'special_summon','card_ids':[78156759]}]
            else:d['requirements']=[r for r in d['requirements'] if r['card_id']!=14878871]
            with self.subTest(mutation=mutation),self.assertRaises(ContractError):BuildTask.from_dict(d)

    def test_nonnegated_processed_link_is_separate_from_activation_and_final_benefit(self):
        start={'kind':70,'public_card':100,'player':0,'link':1}
        self.assertEqual(resolved_chain_cards([start,{'kind':71,'link':1}]),set())
        self.assertEqual(resolved_chain_cards([start,{'kind':73,'link':1}]),{100})
        for blocked in (75,76):
            self.assertEqual(resolved_chain_cards([start,{'kind':blocked,'link':1},{'kind':73,'link':1}]),set())
        self.assertEqual(resolved_chain_cards([dict(start,player=1),{'kind':73,'link':1}]),set())
        self.assertEqual(resolved_chain_cards([start,{'kind':74},{'kind':73,'link':1}]),set())

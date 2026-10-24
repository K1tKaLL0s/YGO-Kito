"""Actual CPU updates and composition; synthetic examples do not prove skill."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import torch

from ygo_kito.build_contracts import BuildTask, digest
from ygo_kito.build_training import BuildTrainer, BuildTrainingConfig
from ygo_kito.construction_binding import CatalogBindingAdapter, CardTagAssessment
from ygo_kito.construction_controller import ConstructionController
from ygo_kito.construction_fill import existing_goal_verifier
from ygo_kito.construction_logic import ConstructionLogic, ConstructionSession, LogicTag
from ygo_kito.construction_model import LogicCodec, LogicFeatureEncoder, LogicModelAdapter, rule_graph_candidates
from ygo_kito.coordinator import Coordinator
from ygo_kito.coordinator_model import CoordinatorTrainer
from ygo_kito.coord_contracts import FeedbackPolicy
from ygo_kito.duel_model import parameter_digest
from ygo_kito.validation import ContractError
from tests.test_construction_logic import fixture_assets, fixture_classifier, fixture_session

TRAINING_EVIDENCE=[]


def graph_context(session, role="build_goal"):
    return {"request":session.request,"task":session.task.to_dict(),"goal_sha256":session.goal_sha256,
            "logic":session.logic.to_dict() if session.logic else None,"feedback":list(session.feedback),"role":role}


class ConstructionModelTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.task,self.assets=fixture_assets()
        self.builder=BuildTrainer(self.task,self.assets,BuildTrainingConfig())
        self.codec=LogicCodec((LogicTag("effect","送墓"),LogicTag("effect","回收")))
        self.adapter=LogicModelAdapter.from_builder(self.builder,self.codec)
        self.session=fixture_session("堆墓",self.task)

    def test_real_candidate_generation_model_selection_and_codec_roundtrip(self):
        context=graph_context(self.session)
        candidates=rule_graph_candidates(context,self.codec)
        self.assertGreaterEqual(len(candidates),2)
        for g in candidates:
            self.assertEqual(self.codec.decode(self.codec.encode(g)),g)
        proposal=self.adapter.propose(context)
        self.session.submit_logic(self.codec.decode(self.codec.encode(ConstructionLogic.from_dict(proposal['logic']))),
            role="build_goal",reason=proposal["reason"])
        evidence=self.adapter.last_selection["build_goal"]
        self.assertEqual(evidence["selected_index"],max(range(len(evidence["scores"])),key=lambda i:evidence["scores"][i]))
        self.assertIs(self.adapter.models["build_goal"],self.builder.models["build_goal"])
        self.assertIs(self.adapter.optimizers["build_optimizer"],self.builder.optimizers["build_optimizer"])
        before=self.session.goal_sha256
        self.session.record_feedback("fill","need an alternative connection")
        context=graph_context(self.session,"build_optimizer")
        proposal=self.adapter.propose(context)
        self.session.submit_logic(ConstructionLogic.from_dict(proposal["logic"]),role="build_optimizer",reason=proposal["reason"])
        self.assertEqual(self.session.logic.revision,1)
        self.assertEqual(self.session.goal_sha256,before)

    def test_actual_role_parameter_updates_loss_and_checkpoint_continue(self):
        for role in ("build_goal","build_optimizer"):
            context=graph_context(self.session,role)
            candidates=rule_graph_candidates(context,self.codec)
            before_other=parameter_digest(self.adapter.models["build_optimizer" if role=="build_goal" else "build_goal"])
            first=self.adapter.train_preference(context,candidates,len(candidates)-1,source="synthetic_code_path_only")
            self.assertNotEqual(first["before_sha256"],first["after_sha256"])
            self.assertEqual(before_other,parameter_digest(self.adapter.models["build_optimizer" if role=="build_goal" else "build_goal"]))
            for _ in range(3):last=self.adapter.train_preference(context,candidates,len(candidates)-1,source="synthetic_code_path_only")
            self.assertLess(last["loss"],first["loss"])
            TRAINING_EVIDENCE.append({"role":role,"first":first,"fourth":last,"source":"synthetic_code_path_only"})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"graph.weights"; self.adapter.save(path)
            restored=LogicModelAdapter.from_builder(BuildTrainer(self.task,self.assets,BuildTrainingConfig()),self.codec)
            restored.load(path)
            for role in ("build_goal","build_optimizer"):
                context=graph_context(self.session,role);candidates=rule_graph_candidates(context,self.codec)
                self.assertEqual(self.adapter.scores(context,candidates),restored.scores(context,candidates))
                a=self.adapter.train_preference(context,candidates,0,source="synthetic_code_path_only")
                b=restored.train_preference(context,candidates,0,source="synthetic_code_path_only")
                self.assertEqual(a["after_sha256"],b["after_sha256"])
            mismatch=LogicModelAdapter.from_builder(BuildTrainer(self.task,self.assets,BuildTrainingConfig()),LogicCodec((LogicTag("effect","别的目标"),)))
            with self.assertRaisesRegex(ContractError,"differs"):mismatch.load(path)

    def test_unknown_tags_and_silent_goal_changes_are_rejected(self):
        context=graph_context(self.session)
        candidates=rule_graph_candidates(context,self.codec)
        context["request"]="silently changed goal"
        with self.assertRaisesRegex(ContractError,"task"):self.adapter.scores(context,candidates)
        with self.assertRaises(ContractError):self.codec.encode(replace(candidates[0],nodes=(replace(candidates[0].nodes[0],tags=(LogicTag("effect","unseen"),)),)))

    def test_default_untrained_session_abstains_without_rule_fallback(self):
        session=ConstructionSession("植物族堆墓",self.task)
        self.assertEqual(session.classification.kind,"ambiguous")
        self.assertIn("untrained_classifier",session.classification.reasons)

    def test_entry_identity_is_encoded_and_optimizer_roles_cannot_be_swapped(self):
        from tests.test_construction_logic import example_graph
        graph=example_graph()
        codec=LogicCodec(tuple(t for n in graph.nodes for t in n.tags),tuple(e.kind for e in graph.connectors))
        encoder=LogicFeatureEncoder(codec,192)
        changed=replace(graph,entry_nodes=("grave",))
        a=encoder.batch(graph_context(self.session),[graph]);b=encoder.batch(graph_context(self.session),[changed])
        self.assertFalse(torch.equal(a["numbers"],b["numbers"]))
        swapped={"build_goal":self.builder.optimizers["build_optimizer"],"build_optimizer":self.builder.optimizers["build_goal"]}
        with self.assertRaisesRegex(ContractError,"role parameters"):
            LogicModelAdapter(self.task,self.builder.models,self.builder.encoder,self.codec,optimizers=swapped)

    def test_failed_second_role_load_keeps_all_active_models_and_optimizers(self):
        context=graph_context(self.session)
        self.adapter.train_preference(context,rule_graph_candidates(context,self.codec),0,source="synthetic_code_path_only")
        with tempfile.TemporaryDirectory() as folder:
            good=Path(folder)/"good.weights";bad=Path(folder)/"bad.weights";self.adapter.save(good)
            state=torch.load(good,weights_only=True);state["model_hashes"]["build_optimizer"]="0"*64
            torch.save(state,bad)
            recipient=LogicModelAdapter.from_builder(BuildTrainer(self.task,self.assets,BuildTrainingConfig()),self.codec)
            before={r:parameter_digest(m) for r,m in recipient.models.items()}
            with self.assertRaisesRegex(ContractError,"checksum"):recipient.load(bad)
            self.assertEqual(before,{r:parameter_digest(m) for r,m in recipient.models.items()})
            self.assertEqual(recipient.updates,{"build_goal":0,"build_optimizer":0})

    def test_runtime_codec_cannot_silently_replace_required_features(self):
        context=graph_context(self.session)
        candidates=rule_graph_candidates(context,self.codec)
        self.codec.tags=(LogicTag("effect","silently changed"),)
        with self.assertRaisesRegex(ContractError,"vocabulary changed"):
            self.adapter.scores(context,candidates)

    def test_concrete_binding_covers_requested_tags_across_active_branches(self):
        self.assets.receipt={"resources":{"cards":"a"*64}}
        tags=(LogicTag("effect","甲"),LogicTag("effect","乙"),LogicTag("effect","丙"))
        codec=LogicCodec(tags)
        graph=rule_graph_candidates(graph_context(self.session),codec)[-1]
        records=tuple(CardTagAssessment(1,t,"satisfied","a"*64,digest(self.assets.rows[1]["desc"]),"Synthetic card text",
            "synthetic-review","Only code path") for t in tags)
        binder=CatalogBindingAdapter(self.assets,assessments=records)
        from ygo_kito.build_pipeline import goal_candidates
        deck=goal_candidates(self.task,self.assets)[0]
        result=binder.bind(graph,self.task,deck,required_tags=tags)
        self.assertIsNotNone(result.proposal)
        active={b.node_id for b in result.proposal.bindings}
        self.assertTrue(set(tags)<={t for n in graph.nodes if n.node_id in active for t in n.tags})


class ConcreteControllerTests(unittest.TestCase):
    def test_actual_graph_models_binding_old_coordinator_and_count_goal_without_native(self):
        torch.set_num_threads(1)
        task,assets=fixture_assets()
        from ygo_kito.build_pipeline import goal_candidates
        base=goal_candidates(task,assets)[0]
        raw=task.to_dict();raw["schema_version"]=4
        raw["goal"]={"kind":"deck_constraints","constraints":[{"id":"normal","zones":["main"],
            "predicate":{"field":"type_all","value":17},"minimum":40,"maximum":40}],"preferences":[]}
        raw["environment"]["versions"]["card_pool"]="native-private-knowledge-v5"
        task=BuildTask.from_dict(raw)
        assets.receipt={"resources":{"cards":"a"*64}}
        tag=LogicTag("effect","送墓")
        assessments=tuple(CardTagAssessment(c,tag,"satisfied","a"*64,digest(row["desc"]),"Synthetic card text",
            "explicit-synthetic-annotation","Only checks the code path") for c,row in assets.rows.items())
        binder=CatalogBindingAdapter(assets,assessments=assessments)
        builder=BuildTrainer(task,assets,BuildTrainingConfig())
        graph_adapter=LogicModelAdapter.from_builder(builder,LogicCodec((tag,)))
        session=ConstructionSession("堆墓",task,classifier=fixture_classifier())
        # Start from an existing legal list; old bounded edits do not need scipy.
        with tempfile.TemporaryDirectory() as folder:
            host=Coordinator(Path(folder)/"coord.sqlite3",FeedbackPolicy(),role="coordinator",source="real_engine",assets=assets,create=True)
            controller=ConstructionController(graph_adapter,binder,CoordinatorTrainer(),host=host)
            result=controller.run(session,base=base,verifier=existing_goal_verifier,candidate_id="graph-candidate")
            self.assertEqual(result["status"],"task_checked_candidate")
            self.assertEqual(result["handoff"]["status"],"submitted_existing_coordinator")
            self.assertEqual(result["handoff"]["candidate"]["validation"]["status"],"constraints_satisfied")
            self.assertFalse(result["graph_execution_verified"])
            self.assertEqual(result["graph_model_selections"]["build_goal"]["selection"],"existing_BuildRanker")
            self.assertTrue(any(e["event"]=="route_decision" and e["advisory"] for e in host.history()))
            self.assertEqual([p["role"] for p in result["phases"]],["build_goal","build_optimizer"])

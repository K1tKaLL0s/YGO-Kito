"""Failure atomicity and output provenance; simulated status is not learned skill."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

import torch

from ygo_kito.multifactor import FactorContractError
from ygo_kito.multifactor.adapters import AdapterConfig, base_binding
from ygo_kito.multifactor.network import NetworkConfig, encode_batch
from ygo_kito.multifactor.scoring import Candidate, CandidateScorer
from ygo_kito.multifactor.training import OUTPUT_TASKS, RoleTrainer, Supervision, Targets
from tests.multifactor_helpers import synthetic_example, task_temporary_directory


def assert_tree_equal(case, left, right):
    if isinstance(left, torch.Tensor):
        case.assertTrue(torch.equal(left, right))
    elif isinstance(left, dict):
        case.assertEqual(set(left), set(right))
        for key in left:
            assert_tree_equal(case, left[key], right[key])
    elif isinstance(left, (tuple, list)):
        case.assertEqual(type(left), type(right))
        case.assertEqual(len(left), len(right))
        for a, b in zip(left, right):
            assert_tree_equal(case, a, b)
    else:
        case.assertEqual(left, right)


def snapshot(trainer, example):
    bank = trainer.lora
    with torch.inference_mode():
        prediction = trainer.model(encode_batch((example,)))
    return dict(model=deepcopy(trainer.model.state_dict()), optimizer=deepcopy(trainer.optimizer.state_dict()),
                grad_flags=[p.requires_grad for p in trainer.model.parameters()], model_training=trainer.model.training,
                hooks={name: tuple(module._forward_hooks) for name, module in trainer.model.named_modules()},
                bank_id=None if bank is None else id(bank), active=None if bank is None else bank.active,
                entries={} if bank is None else {name: dict(identity=id(entry), weights=deepcopy(entry.deltas.state_dict()),
                    optimizer=deepcopy(entry.optimizer.state_dict()), updates=deepcopy(entry.updates), steps=entry.steps,
                    data_digest=entry.data_digest, data_cursor=entry.data_cursor,
                    gradients=[None if p.grad is None else p.grad.clone() for p in entry.deltas.parameters()])
                    for name, entry in bank.entries.items()},
                updates=deepcopy(trainer.updates), steps=trainer.steps, data_digest=trainer.data_digest, cursor=trainer.data_cursor,
                rng=torch.get_rng_state().clone(), prediction=deepcopy(prediction))


class AdapterLoadTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        self.example = synthetic_example()
        self.labels = Targets(roles=(("package", (None, None, None, None, 1)),))
        self.source = Supervision("engineering_fixture", "actual bounded Adam steps; no real-label training or quality claim")
        self.directory = Path(self.enterContext(task_temporary_directory()))
        self.path = self.directory / "incoming.pt"
        self.incoming = self.fresh()
        self.incoming.enable_lora(engineering_mode=True)
        self.incoming.create_adapter("incoming", AdapterConfig(rank=2, alpha=2))
        self.update(self.incoming)
        self.update(self.incoming)
        self.incoming.save_adapter(self.path, "incoming", data_cursor="engineering:2")

    def fresh(self):
        return RoleTrainer(NetworkConfig(hidden_dim=16))

    def update(self, trainer):
        return trainer.train_supervised((self.example,), (self.labels,), (self.source,))

    def target(self, existing):
        trainer = self.fresh()
        # An unrelated host hook and mixed fresh flags must also survive failure.
        trainer.model.role_head.register_forward_hook(lambda module, inputs, output: None)
        if existing:
            trainer.enable_lora(engineering_mode=True)
            trainer.create_adapter("previous", AdapterConfig(rank=2, seed=141))
            self.update(trainer)
        else:
            for i, parameter in enumerate(trainer.model.parameters()):
                parameter.requires_grad_(i % 3 != 0)
        return trainer

    def failure_preserves_state(self, *, existing, phase, late=False):
        trainer = self.target(existing)
        before = snapshot(trainer, self.example)
        if not late:
            value = torch.load(self.path, weights_only=True)
            if phase == "weights":
                value["weights"] = {}
            else:
                key = next(iter(value["optimizer"]["state"]))
                value["optimizer"]["state"][key]["exp_avg"] = torch.zeros(1)
            path = self.directory / (phase + "-invalid.pt")
            torch.save(value, path)
            with self.assertRaises((ValueError, RuntimeError)):
                trainer.load_adapter(path)
        else:
            owner = torch.nn.ModuleDict if phase == "weights" else torch.optim.Adam
            original = owner.load_state_dict
            def partial_then_fail(instance, state, *args, **kwargs):
                original(instance, state, *args, **kwargs)
                raise RuntimeError(phase + " failure after complete detached restore")
            with patch.object(owner, "load_state_dict", partial_then_fail):
                with self.assertRaisesRegex(RuntimeError, "detached restore"):
                    trainer.load_adapter(self.path)
        assert_tree_equal(self, before, snapshot(trainer, self.example))

    def test_invalid_weights_preserve_fresh_model(self):
        self.failure_preserves_state(existing=False, phase="weights")

    def test_invalid_weights_preserve_existing_active_adapter(self):
        self.failure_preserves_state(existing=True, phase="weights")

    def test_invalid_adam_moments_preserve_fresh_model(self):
        self.failure_preserves_state(existing=False, phase="adam")

    def test_invalid_adam_moments_preserve_existing_active_adapter(self):
        self.failure_preserves_state(existing=True, phase="adam")

    def test_late_weight_restore_failure_preserves_fresh_model(self):
        self.failure_preserves_state(existing=False, phase="weights", late=True)

    def test_late_weight_restore_failure_preserves_existing_active_adapter(self):
        self.failure_preserves_state(existing=True, phase="weights", late=True)

    def test_late_adam_restore_failure_preserves_fresh_model(self):
        self.failure_preserves_state(existing=False, phase="adam", late=True)

    def test_late_adam_restore_failure_preserves_existing_active_adapter(self):
        self.failure_preserves_state(existing=True, phase="adam", late=True)

    def test_hook_install_failure_rolls_back_new_bank_and_grad_flags(self):
        trainer = self.target(False)
        before = snapshot(trainer, self.example)
        with patch.object(trainer.model.role_head, "register_forward_hook", side_effect=RuntimeError("hook install failure")):
            with self.assertRaisesRegex(RuntimeError, "hook install failure"):
                trainer.load_adapter(self.path)
        assert_tree_equal(self, before, snapshot(trainer, self.example))

    def test_missing_nonempty_adam_and_wrong_settings_are_rejected_atomically(self):
        for kind in ("missing_state", "wrong_lr"):
            with self.subTest(kind=kind):
                trainer = self.target(True)
                before = snapshot(trainer, self.example)
                value = torch.load(self.path, weights_only=True)
                if kind == "missing_state":
                    value["optimizer"]["state"] = {}
                else:
                    value["optimizer"]["param_groups"][0]["lr"] = 0.05
                path = self.directory / (kind + ".pt")
                torch.save(value, path)
                with self.assertRaises(FactorContractError):
                    trainer.load_adapter(path)
                assert_tree_equal(self, before, snapshot(trainer, self.example))

    def test_nonempty_adam_restores_and_next_actual_engineering_update_matches(self):
        payload = torch.load(self.path, weights_only=True)
        self.assertTrue(payload["optimizer"]["state"])
        self.assertTrue(any(float(state["exp_avg"].abs().sum()) > 0 for state in payload["optimizer"]["state"].values()))
        target = self.fresh()
        target.load_adapter(self.path)
        left, right = self.incoming.lora.entries["incoming"], target.lora.entries["incoming"]
        assert_tree_equal(self, left.optimizer.state_dict(), right.optimizer.state_dict())
        self.assertEqual(right.data_cursor, "engineering:2")
        self.assertEqual(self.update(self.incoming), self.update(target))
        assert_tree_equal(self, left.deltas.state_dict(), right.deltas.state_dict())
        assert_tree_equal(self, left.optimizer.state_dict(), right.optimizer.state_dict())
        self.assertEqual(left.data_digest, right.data_digest)
        self.assertEqual(base_binding(self.incoming), base_binding(target))

    def test_normal_checkpoint_with_development_provenance_cannot_mutate_fresh_or_existing_bank(self):
        value = torch.load(self.path, weights_only=True)
        value["engineering_mode"] = False
        for counts in value["updates"].values():
            counts["definition_development"] = counts["engineering_fixture"]
            counts["engineering_fixture"] = 0
        path = self.directory / "development-marked-normal.pt"
        torch.save(value, path)
        for existing in (False, True):
            with self.subTest(existing=existing):
                target = self.fresh()
                # Admission/status control only; no real supervised base is claimed.
                with patch.object(target, "_base_head_status", return_value="trained_uncalibrated"):
                    if existing:
                        target.enable_lora()
                        target.create_adapter("previous", AdapterConfig(rank=2, seed=141))
                    before = snapshot(target, self.example)
                    with self.assertRaisesRegex(FactorContractError, "normal adapter checkpoint contains"):
                        target.load_adapter(path)
                    assert_tree_equal(self, before, snapshot(target, self.example))


class AdapterPublicStateTests(unittest.TestCase):
    """Base status and real counters are mocked solely to test output controls."""

    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        self.example = synthetic_example()
        self.trainer = RoleTrainer(NetworkConfig(hidden_dim=16))
        self.enterContext(patch.object(self.trainer, "_base_head_status", return_value="trained_uncalibrated"))
        self.trainer.enable_lora()
        self.trainer.create_adapter("active")
        self.candidate = Candidate("control", self.example, "package", "simulated base-status control",
                                   legality="pass", legality_ref="synthetic legal control only")

    def output(self):
        return CandidateScorer(self.trainer).score_candidates((self.candidate,), explain=False)[0]

    def assert_null(self, row):
        self.assertTrue(all(value is None for value in row["role_probabilities"].values()))
        self.assertIsNone(row["compatibility_probability"])
        self.assertIsNone(row["advisory_score"])

    def test_active_untrained_adapter_does_not_inherit_base_output_status(self):
        row = self.output()
        self.assert_null(row)
        self.assertTrue(all(state == "untrained" for state in row["role_dimension_status"].values()))
        self.assertEqual(row["adaptation"]["inference_source"], "adapter")
        self.assertTrue(all(value == "trained_uncalibrated" for value in row["adaptation"]["base_head_status"].values()))

    def test_disabled_adapter_preserves_valid_base_inference_status(self):
        self.trainer.activate_adapter(None)
        row = self.output()
        self.assertTrue(all(isinstance(value, float) for value in row["role_probabilities"].values()))
        self.assertIsInstance(row["advisory_score"], float)
        self.assertEqual(row["adaptation"]["inference_source"], "base")

    def test_normal_mode_rejects_engineering_and_definition_sources_before_update(self):
        labels = Targets(roles=(("package", (None, None, None, None, 1)),))
        for kind in ("engineering_fixture", "definition_development"):
            before = snapshot(self.trainer, self.example)
            with self.assertRaisesRegex(FactorContractError, "normal adapter"):
                self.trainer.train_supervised((self.example,), (labels,), (Supervision(kind, "source rejection control"),))
            with self.assertRaisesRegex(FactorContractError, "normal adapter"):
                self.trainer.train_preference(self.example, self.example, left_key="package", right_key="package", preferred_left=1,
                                              source=Supervision(kind, "source rejection control", scope="candidate"))
            assert_tree_equal(self, before, snapshot(self.trainer, self.example))

    def test_development_contamination_stays_diagnostic_and_disabling_recovers_base(self):
        # Simulated legacy/mixed provenance; no optimizer step or real data.
        entry = self.trainer.lora.entries["active"]
        for head in OUTPUT_TASKS:
            entry.updates[head]["human_feedback"] = 1
        entry.updates["utility"]["definition_development"] = 1
        entry.steps = 2
        self.assert_null(self.output())
        self.trainer.activate_adapter(None)
        self.assertIsInstance(self.output()["advisory_score"], float)

    def test_only_individually_supervised_adapter_outputs_become_eligible(self):
        # Counter fixtures test masks; they are not trained/quality evidence.
        entry = self.trainer.lora.entries["active"]
        for head in ("role", "role:generic_utility", "utility"):
            entry.updates[head]["human_feedback"] = 1
        entry.steps = 1
        row = self.output()
        self.assertIsInstance(row["role_probabilities"]["generic_utility"], float)
        self.assertTrue(all(row["role_probabilities"][role] is None for role in row["role_probabilities"] if role != "generic_utility"))
        self.assertIsNone(row["compatibility_probability"])
        self.assertIsInstance(row["advisory_score"], float)


if __name__ == "__main__":
    unittest.main()

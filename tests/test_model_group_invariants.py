"""Cross-role invariants the four-model group relies on, checked without the core.

The group workflow in ``model_group`` assumes four independently owned role
models, a stable parameter digest used as a policy/base identity, and checkpoints
that survive a save/load cycle.  Those are properties of the model code itself,
so they are checkable with synthetic tensors and no rule core, no cards database
and no duel.  Nothing here measures playing strength, learning quality or
calibration, and a pass is not evidence that any role is trained.
"""

from pathlib import Path
import tempfile
import unittest

try:
    import torch
except ModuleNotFoundError as error:
    if error.name != "torch":
        raise
    torch = None

if torch is not None:
    from ygo_kito.build_model import BuildModelConfig, BuildRanker
    from ygo_kito.coordinator_model import CoordinatorModelConfig, CoordinatorNetwork
    from ygo_kito.duel_model import DuelActorCritic, DuelModelConfig, parameter_digest
    from ygo_kito.validation import ContractError

ROLES = ("duel", "build_goal", "build_optimizer", "coordinator")


def duel_batch(rows=2, length=5, actions=3):
    return {"tokens": torch.zeros(rows, length, 7, dtype=torch.long),
            "numbers": torch.zeros(rows, length, 4, dtype=torch.float32),
            "state": torch.zeros(rows, 14, dtype=torch.float32),
            "actions": torch.zeros(rows, actions, 7, dtype=torch.long),
            "action_numbers": torch.zeros(rows, actions, 8, dtype=torch.float32),
            "pointers": torch.zeros(rows, actions, length, dtype=torch.float32),
            "context_mask": torch.ones(rows, length, dtype=torch.bool),
            "action_mask": torch.ones(rows, actions, dtype=torch.bool)}


def build_batch(rows=2, length=4):
    return {"tokens": torch.zeros(rows, length, 4, dtype=torch.long),
            "numbers": torch.zeros(rows, length, 10, dtype=torch.float32),
            "state": torch.zeros(rows, 6, dtype=torch.float32),
            "mask": torch.ones(rows, length, dtype=torch.bool)}


@unittest.skipIf(torch is None, "optional CPU PyTorch unavailable; model tests not passed")
class ModelGroupInvariantTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        torch.manual_seed(20261024)

    def build_roles(self):
        """Four role models on one vocabulary, as the group workflow constructs them."""
        vocabulary = 64
        shared = BuildModelConfig()
        return {"duel": DuelActorCritic(DuelModelConfig(), vocabulary),
                "build_goal": BuildRanker(shared, vocabulary, annotation_count=8),
                "build_optimizer": BuildRanker(shared, vocabulary, annotation_count=8),
                "coordinator": CoordinatorNetwork(CoordinatorModelConfig())}

    def test_roles_share_no_trainable_storage(self):
        # model_group refuses a group whose roles alias each other's parameters;
        # this checks the constructors really do keep them apart.
        models = self.build_roles()
        self.assertEqual(set(models), set(ROLES))
        storage = {role: {p.data_ptr() for p in model.parameters() if p.numel()}
                   for role, model in models.items()}
        for i, first in enumerate(ROLES):
            for second in ROLES[i + 1:]:
                with self.subTest(first=first, second=second):
                    self.assertFalse(storage[first] & storage[second],
                                     "distinct roles must not share parameter storage")

    def test_parameter_digest_is_stable_and_detects_a_single_element_change(self):
        model = DuelActorCritic(DuelModelConfig(), 64)
        digest = parameter_digest(model)
        self.assertEqual(digest, parameter_digest(model), "digest must be reproducible")
        self.assertEqual(len(digest), 64)
        with torch.no_grad():
            first = next(model.parameters())
            first.view(-1)[0] += 1e-3
        self.assertNotEqual(digest, parameter_digest(model),
                            "a policy identity digest that ignores a weight change is useless")

    def test_each_role_round_trips_through_a_state_dict_on_disk(self):
        models = self.build_roles()
        def fresh(role):
            """A blank model of the same class, built the same way as the group does."""
            if role == "duel":
                return DuelActorCritic(DuelModelConfig(), 64)
            if role == "coordinator":
                return CoordinatorNetwork(CoordinatorModelConfig())
            return BuildRanker(BuildModelConfig(), 64, annotation_count=8)
        with tempfile.TemporaryDirectory() as folder:
            for role, model in models.items():
                with self.subTest(role=role):
                    before = parameter_digest(model)
                    path = Path(folder) / f"{role}.pt"
                    with path.open("wb") as handle:
                        torch.save({"model": model.state_dict()}, handle)
                    with path.open("rb") as handle:
                        state = torch.load(handle, map_location="cpu", weights_only=True)
                    reloaded = fresh(role)
                    reloaded.load_state_dict(state["model"], strict=True)
                    self.assertEqual(parameter_digest(reloaded), before)

    def test_a_roles_gradient_does_not_reach_another_role(self):
        models = self.build_roles()
        for model in models.values():
            model.zero_grad(set_to_none=True)
        logits, values = models["duel"](duel_batch())
        (logits.sum() + values.sum()).backward()
        self.assertTrue(any(p.grad is not None for p in models["duel"].parameters()))
        for role in ROLES[1:]:
            with self.subTest(role=role):
                self.assertTrue(all(p.grad is None for p in models[role].parameters()),
                                "training one role must not populate another's gradients")

    def test_duel_actor_is_deterministic_in_eval_and_masks_padding_to_zero(self):
        model = DuelActorCritic(DuelModelConfig(), 64).eval()
        batch = duel_batch(actions=4)
        batch["action_mask"][:, 3] = False
        with torch.no_grad():
            first_logits, first_values = model(batch)
            second_logits, second_values = model(batch)
        self.assertTrue(torch.equal(first_logits, second_logits), "eval forward must be repeatable")
        self.assertTrue(torch.equal(first_values, second_values))
        probabilities = first_logits.softmax(-1)
        self.assertTrue(torch.equal(probabilities[~batch["action_mask"]], torch.zeros(2)))
        self.assertTrue(torch.allclose(probabilities.sum(-1), torch.ones(2)))
        self.assertTrue(torch.isfinite(first_values).all())

    def test_duel_actor_refuses_a_row_with_no_legal_action(self):
        model = DuelActorCritic(DuelModelConfig(), 64).eval()
        batch = duel_batch()
        batch["action_mask"][0] = False
        with self.assertRaisesRegex(ContractError, "legal action"):
            model(batch)

    def test_building_ranker_scores_one_value_per_candidate(self):
        model = BuildRanker(BuildModelConfig(), 64, annotation_count=8).eval()
        with torch.no_grad():
            scores = model(build_batch(rows=3))
        self.assertEqual(tuple(scores.shape), (3,))
        self.assertTrue(torch.isfinite(scores).all())

    def test_coordinator_emits_a_route_distribution_and_a_bounded_forecast(self):
        model = CoordinatorNetwork(CoordinatorModelConfig()).eval()
        with torch.no_grad():
            route_logits, forecast = model(torch.zeros(4, 14))
        self.assertEqual(tuple(route_logits.shape), (4, route_logits.shape[1]))
        self.assertTrue(torch.isfinite(route_logits).all())
        self.assertEqual(tuple(forecast.shape), (4,))
        self.assertTrue(bool(((forecast >= 0) & (forecast <= 1)).all()),
                        "the forecast head is sigmoid bounded and must stay a probability")

    def test_coordinator_refuses_malformed_aggregate_features(self):
        model = CoordinatorNetwork(CoordinatorModelConfig())
        for values in (torch.zeros(4, 13), torch.zeros(4, 15), torch.zeros(14),
                       torch.tensor([[float("nan")] * 14])):
            with self.subTest(shape=tuple(values.shape)), self.assertRaises(ContractError):
                model(values)


@unittest.skipIf(torch is None, "optional CPU PyTorch unavailable; model tests not passed")
class RoleIndependenceIsNotAccidentalTests(unittest.TestCase):
    """Guard the claim, not just the current instance of it."""

    def test_two_instances_of_one_role_class_do_not_share_storage(self):
        torch.set_num_threads(1)
        torch.manual_seed(7)
        first, second = DuelActorCritic(DuelModelConfig(), 32), DuelActorCritic(DuelModelConfig(), 32)
        self.assertNotEqual(parameter_digest(first), parameter_digest(second),
                            "seeded construction must still produce independent weights")
        self.assertFalse({p.data_ptr() for p in first.parameters()} &
                         {p.data_ptr() for p in second.parameters()})


if __name__ == "__main__":
    unittest.main()

"""Synthetic contract fixtures only. No real duel, card pool or banlist."""


def card(card_id=1):
    return {
        "card_id": card_id,
        "names": {"zh": f"测试卡{card_id}", "ja": f"テスト{card_id}", "en": f"Test Card {card_id}"},
        "aliases": ["shared test alias", "O'Brien fixture"],
        "card_type": "test-only",
        "effect_texts": {"zh": "仅作接口夹具，没有实现或宣称真实卡片效果。"},
        "source": {"reference": "test-only:fixture", "version": "1"},
    }


def annotation(layer="fact", annotation_id="tag-1"):
    return {
        "annotation_id": annotation_id, "card_id": 1,
        "dimension": "effect", "layer": layer, "tags": ["送墓", "特召"],
        "condition": "test-only condition; not a verified card effect",
        "source": {"reference": "test-only:fixture", "version": "1"},
    }


def dataset():
    return {"schema_version": 1, "cards": [card()], "annotations": [annotation()]}


def request():
    return {
        "schema_version": 1,
        "context": {"run_id": "test-run", "seed": 7, "models": [], "versions": {
            key: "test-only/not-a-real-lock" for key in ("core", "scripts", "cards", "protocol", "card_pool", "banlist")
        }},
        "duel_id": "test-duel", "decision_id": "test-window-1",
        "observation": {
            "observer": 0, "turn_player": 0, "turn": 1, "phase": "main1",
            "life_points": [8000, 8000], "hand_counts": [1, 1], "deck_counts": [39, 39],
            "cards": [
                {"ref": "own-hand-1", "owner": 0, "controller": 0, "zone": "hand", "visibility": "observer", "card_id": 1},
                {"ref": "opponent-set-1", "owner": 1, "controller": 1, "zone": "spell_trap", "visibility": "hidden", "card_id": None},
            ],
            "public_history": [{"event_id": "public-1", "kind": "phase", "card_ids": []}],
        },
        "actions": [
            {"action_id": "choice-1", "kind": "select", "card_refs": ["opponent-set-1"]},
            {"action_id": "choice-pass", "kind": "pass", "card_refs": []},
        ],
    }


def selection():
    return {"run_id": "test-run", "duel_id": "test-duel", "decision_id": "test-window-1", "action_id": "choice-1"}

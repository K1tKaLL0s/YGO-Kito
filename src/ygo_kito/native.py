"""Pinned YGOPro normal-monster adapter. Unsupported messages fail closed.

Complete games are restricted to the explicit normal pool; no general effects or PC client.
Native response bytes and all-information engine messages stay inside the adapter.
"""

import ctypes as C
from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import random
import sqlite3
import struct
import threading
from uuid import uuid4

from .contracts import ActionSelection, CardView, DecisionRequest, LegalAction, Observation, PublicEvent, RunContext, SearchChoice, Versions, validate_selection
from .engine import EngineUnavailable
from .native_assets import LOCK_PATH, verify_resources
from .native_protocol import NativeError, Reader, decode_prompt, decode_deck_choices
from .native_response_guard import build_response_buffer
from .validation import ContractError, integer

_ACTIVE = threading.Lock()  # The upstream callback registry is process-global.


class CardData(C.Structure):
    _fields_ = [("code", C.c_uint32), ("alias", C.c_uint32), ("setcode", C.c_uint16 * 16),
                *[(key, C.c_uint32) for key in ("type", "level", "attribute", "race")],
                ("attack", C.c_int32), ("defense", C.c_int32),
                *[(key, C.c_uint32) for key in ("lscale", "rscale", "link_marker", "rule_code")]]


def banlist_limits(path: Path, section="2026.10") -> dict[int, int]:
    active, found, limits = False, False, {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("!"):
            active = line[1:].strip() == section
            found |= active
        elif active and line and line[0].isdigit():
            code, limit, *_ = line.split()
            limits[int(code)] = int(limit)
    if not found:
        raise NativeError("locked banlist section missing")
    return limits


class NativeNormalEngine:
    def __init__(self, root: Path, *, seed=7, scenario="normal", legacy_request_ids=False, deck_profile=None, selection_key=None):
        integer(seed, "seed", 0, 2**32 - 8)
        if scenario not in ("normal", "effects-counter", "search-trigger", "search-condition", "count-reset", "count-shared", "search-lock", "lock-control", "effect-duel"):
            raise ContractError("unsupported scoped native scenario")
        if (scenario == "effect-duel") != (deck_profile is not None):
            raise ContractError("effect duel requires an explicit deck profile")
        if legacy_request_ids and scenario != "normal":
            raise ContractError("legacy requests are reserved for old normal replay")
        self.scenario, self._legacy_ids = scenario, legacy_request_ids
        self.general_actions = scenario == "effect-duel"
        if self.general_actions:
            from .deck_profile import validate_profile
            validate_profile(deck_profile)
        self.extended_actions = self.general_actions and deck_profile.get("schema_version") == 2
        self.modern_actions = self.general_actions and deck_profile.get("adapter_revision") in (3,4,5)
        self.private_actions = self.general_actions and deck_profile.get("adapter_revision") in (4,5)
        self.knowledge_actions = self.general_actions and deck_profile.get("adapter_revision") == 5
        self._private_reveals=[[],[]]
        self._private_reveal_counters=[0,0]
        self._private_revealed_slots=[{},{}]
        self._public_materials={}
        if selection_key is not None and not self.private_actions:
            raise ContractError("private selection replay key requires revision 4")
        if selection_key is not None:
            try:
                if not isinstance(selection_key,str) or len(selection_key)!=32 or len(bytes.fromhex(selection_key))!=16:
                    raise ValueError()
            except ValueError as exc:raise ContractError("invalid private selection replay key") from exc
        self._selection_seed = (selection_key or uuid4().hex) if self.private_actions else None
        self._public_history = []
        self._public_declarations = {}
        self._known_owners, self._overlay_owners = {}, {}
        self._observer_windows = [0, 0]
        self.root = root.resolve()
        self.receipt = verify_resources(self.root)
        self.sources = self.root / "engine-src"
        self.lock = json.loads(LOCK_PATH.read_text())
        self.closed, self.handle, self.pending = False, None, None
        self.window, self.turn, self.turn_player, self.phase = 0, 0, 0, "draw"
        self.messages, self.callback_errors, self.loaded_scripts = [], [], set()
        self.events, self.outcome, self.life_points = [], None, [8000, 8000]
        self._revealed_hand = [{}, {}]
        self._confirmation_pause = False
        self._buffers, self._responses = {}, {}
        if not _ACTIVE.acquire(blocking=False):
            raise EngineUnavailable("only one native smoke engine per process is supported")
        try:
            self.lib = C.CDLL(str(self.root / "engine-build/libocgcore.so"))
            self._bind()
            with sqlite3.connect((self.sources / "database/locales/zh-CN/cards.cdb").as_uri() + "?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                self._rows = {row["id"]: dict(row) for row in db.execute("SELECT * FROM datas")}
            limits = self._deck_limits()
            # Explicit custom pool, not a claimed 2022/2026 release-date curriculum.
            self.deck = tuple(code for code, row in sorted(self._rows.items())
                              if row["type"] == 17 and row["alias"] == 0 and row["ot"] & 1
                              and code < 100000000 and 1 <= row["level"] <= 4 and limits.get(code, 3) >= 1)[:40]
            self._allowed_pool = set(self.deck)
            self.player_decks = (self.deck, self.deck)
            if scenario == "effects-counter":
                self._allowed_pool.update((43898403, 77414722, 5318639))
                self.player_decks = (self.deck[:38] + (77414722, 5318639), self.deck[:39] + (43898403,))
            elif scenario == "search-trigger":
                self._allowed_pool.update((26202165, 53129443, 83764718))
                self.player_decks = (self.deck[:36] + (26202165, 53129443, 53129443, 83764718), self.deck)
            elif scenario == "search-condition":
                self._allowed_pool.update((26202165, 81439173))
                self.player_decks = (self.deck[:38] + (26202165, 81439173), self.deck)
            elif scenario in ("count-reset", "count-shared"):
                self._allowed_pool.update((26202165, 53129443, 43422537))
                extra = 53129443 if scenario == "count-reset" else 43422537
                self.player_decks = (self.deck[:36] + (26202165, 26202165, 53129443, extra), self.deck)
            elif scenario == "search-lock":
                self._allowed_pool.update((26202165, 53129443, 43422537, 45812361))
                self.player_decks = (self.deck[:36] + (26202165, 53129443, 43422537, 45812361), self.deck)
            elif scenario == "lock-control":
                self._allowed_pool.add(45812361)
                self.player_decks = (self.deck[:39] + (45812361,), self.deck)
            elif scenario == "effect-duel":
                from .deck_profile import validate_profile
                self.player_decks = validate_profile(deck_profile)
                self._allowed_pool = set().union(*self.player_decks)
            self.player_extras = ((), ())
            self.player_sides = ((), ())
            if self.general_actions and "sides" in deck_profile:
                self.player_sides = tuple(tuple(d) for d in deck_profile["sides"])
            if self.extended_actions:
                self.player_extras = tuple(tuple(d) for d in deck_profile["extras"])
                self._allowed_pool.update(code for d in self.player_extras for code in d)
            if self.extended_actions or any(self.player_sides):
                from .deck_profile import validate_deck_parts
                self._allowed_pool.update(code for d in self.player_sides for code in d)
                for player in (0, 1):
                    validate_deck_parts({"main": list(self.player_decks[player]), "extra": list(self.player_extras[player]),
                                         "side": list(self.player_sides[player])}, self._rows, limits)
            else:
                for deck in self.player_decks:
                    self.validate_deck(deck)
            self._install_callbacks()
            seeds = (C.c_uint32 * 8)(*(seed + i for i in range(8)))
            self.handle = self.lib.create_duel_v2(seeds)
            if not self.handle:
                raise NativeError("native create_duel_v2 failed")
            self._check_callbacks()
            for player in (0, 1):
                self.lib.set_player_info(self.handle, player, 8000, 5, 1)
                # The host supplies initial deck order; start_duel does not shuffle it.
                # Keep this deal RNG private and separate from the core's effect RNG.
                order = list(self.player_decks[player])
                random.Random(seed * 2 + player).shuffle(order)
                for code in order:
                    self.lib.new_card(self.handle, code, player, player, 1, 0, 8)
                for code in self.player_extras[player]:
                    self.lib.new_card(self.handle, code, player, player, 64, 0, 8)
            self._check_callbacks()
            hashes = self.receipt["resources"]
            self.context = RunContext(f"native-{uuid4().hex}", Versions(self.lock["sources"]["core"]["commit"],
                hashes["scripts"], hashes["cards"], hashes["client_protocol"],
                "native-private-knowledge-v5" if self.knowledge_actions else "native-private-selection-v4" if self.private_actions else "native-protocol-history-v3" if self.modern_actions else "native-extra-material-v2" if self.extended_actions else self.lock["card_pool"]["id"] if scenario == "normal" else f"native-{scenario}-v1", "2026.10:" + hashes["banlist"]), None)
            self.lib.start_duel(self.handle, 5 << 16)  # Master Rule 2020, no TEST/SIMPLE_AI mode.
        except BaseException:
            self.close()
            raise

    def _bind(self):
        if C.sizeof(CardData) != 80:
            raise NativeError("card_data ABI size mismatch")
        self._script_type = C.CFUNCTYPE(C.c_void_p, C.c_char_p, C.POINTER(C.c_int))
        self._card_type = C.CFUNCTYPE(C.c_uint32, C.c_uint32, C.POINTER(CardData))
        self._log_type = C.CFUNCTYPE(C.c_uint32, C.c_void_p, C.c_uint32)
        signatures = {
            "set_script_reader": ([self._script_type], None), "set_card_reader": ([self._card_type], None),
            "set_message_handler": ([self._log_type], None), "create_duel_v2": ([C.POINTER(C.c_uint32)], C.c_void_p),
            "set_player_info": ([C.c_void_p, C.c_int32, C.c_int32, C.c_int32, C.c_int32], None),
            "new_card": ([C.c_void_p, C.c_uint32, *([C.c_uint8] * 5)], None),
            "start_duel": ([C.c_void_p, C.c_uint32], None), "end_duel": ([C.c_void_p], None),
            "process": ([C.c_void_p], C.c_uint32), "get_message": ([C.c_void_p, C.c_void_p], C.c_int32),
            "set_responsei": ([C.c_void_p, C.c_int32], None), "set_responseb": ([C.c_void_p, C.c_void_p], None),
            "query_field_count": ([C.c_void_p, C.c_uint8, C.c_uint8], C.c_int32),
            "query_card": ([C.c_void_p, C.c_uint8, C.c_uint8, C.c_uint8, C.c_uint32, C.c_void_p, C.c_int32], C.c_int32),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, result

    def _deck_limits(self):
        """Host period adapters may select a separately checked historical section."""
        return banlist_limits(self.sources / "client/lflist.conf")

    def validate_deck(self, deck):
        from .deck_profile import validate_main_deck
        limits = self._deck_limits()
        validate_main_deck(deck, self._rows, limits, allowed=self._allowed_pool, strict_40=not self.general_actions)

    def _install_callbacks(self):
        def script_reader(name, length):
            try:
                script_root = (self.sources / "scripts").resolve()
                relative = name.decode().removeprefix("./").removeprefix("script/")
                path = (script_root / relative).resolve()
                if not path.is_relative_to(script_root) or path.suffix != ".lua":
                    raise NativeError("script path outside pinned source")
                content = path.read_bytes()
                buffer = C.create_string_buffer(content)
                self._buffers[relative] = buffer
                self.loaded_scripts.add(relative)
                length[0] = len(content)
                return C.addressof(buffer)
            except Exception:
                self.callback_errors.append("script source missing or invalid")
                length[0] = 0
                return None

        def card_reader(code, target):
            row = self._rows.get(code)
            if row is None:
                self.callback_errors.append("card absent from pinned database")
                return 0
            data = target.contents
            data.code, data.alias = code, row["alias"]
            packed = row["setcode"] % (1 << 64)
            for index in range(16):
                data.setcode[index] = (packed >> (index * 16)) & 0xffff if index < 4 else 0
            data.type, data.level, data.attribute, data.race = row["type"], row["level"] & 0xff, row["attribute"], row["race"]
            data.attack, data.defense = row["atk"], row["def"]
            data.lscale, data.rscale = (row["level"] >> 24) & 0xff, (row["level"] >> 16) & 0xff
            data.link_marker = row["def"] if row["type"] & 0x4000000 else 0
            return 0

        def log_handler(_duel, _kind):
            self.callback_errors.append("native Lua/core diagnostic; smoke aborted")
            return 0

        self._callbacks = (self._script_type(script_reader), self._card_type(card_reader), self._log_type(log_handler))
        self.lib.set_script_reader(self._callbacks[0])
        self.lib.set_card_reader(self._callbacks[1])
        self.lib.set_message_handler(self._callbacks[2])

    def _check_callbacks(self):
        if self.callback_errors:
            raise NativeError(self.callback_errors[0])

    def _query(self, player, location, sequence, flags):
        if location == 1:
            raise NativeError("deck contents/order must not be queried for policy projection")
        buffer = (C.c_uint8 * 1024)()
        length = self.lib.query_card(self.handle, player, location, sequence, flags, buffer, 0)
        if length <= 4:
            return None
        if length > len(buffer):
            raise NativeError("native query exceeded buffer")
        reader = Reader(bytes(buffer[:length]))
        if reader.u32() != length or reader.u32() != flags:
            raise NativeError("unexpected native query schema")
        code = reader.u32() if flags & 1 else None
        position = reader.take(4)[3] if flags & 2 else None
        return code, position

    def _count(self, player, location):
        return self.lib.query_field_count(self.handle, player, location)

    def _visible_data(self, player, location, sequence, combat=False):
        if location not in ((2, 4, 8, 16, 32, 64) if self.extended_actions else (2, 4, 8, 16)):
            raise NativeError("unsupported visible card query")
        flags = 0x40001 | (0x300 if combat else 0)
        buffer = (C.c_uint8 * 64)()
        length = self.lib.query_card(self.handle, player, location, sequence, flags, buffer, 0)
        if not 8 <= length <= len(buffer):
            raise NativeError("invalid visible query length")
        reader = Reader(bytes(buffer[:length]))
        if reader.u32() != length or reader.u32() != flags:
            raise NativeError("invalid visible query schema")
        code = reader.u32()
        attack, defense = (struct.unpack("<ii", reader.take(8))) if combat else (None, None)
        owner = reader.u32()
        if reader.offset != length or owner not in (0, 1):
            raise NativeError("invalid visible card owner/schema")
        if self.extended_actions:
            self._known_owners[(player, location, sequence)] = owner
        return code, owner, attack, defense

    def _observation(self, observer):
        cards = []
        for sequence in range(self._count(observer, 2)):
            code, _ = self._query(observer, 2, sequence, 1)
            owner = self._visible_data(observer, 2, sequence)[1] if self.general_actions else observer
            cards.append(CardView(f"p{observer}.hand.{sequence}", owner, observer, "hand", "observer", code))
        opponent = 1 - observer
        revealed = dict(self._revealed_hand[opponent])
        if self.modern_actions:
            # PUBLIC hand status can persist independently of ConfirmCards.
            # Position-only query first; identities are queried only after a
            # public faceup status or an explicit broadcast confirmation.
            for sequence in range(self._count(opponent, 2)):
                value = self._query(opponent,2,sequence,2)
                if value is not None and value[1]&5:
                    revealed[sequence] = self._visible_data(opponent,2,sequence)[0]
        for sequence, code in sorted(revealed.items()):
            owner = self._visible_data(opponent,2,sequence)[1] if self.modern_actions else opponent
            cards.append(CardView(f"p{opponent}.hand.{sequence}", owner, opponent, "hand", "public", code))
        for player in (0, 1):
            for location, zone, count in ((4, "monster", 7), (8, "spell_trap", 8), (16, "graveyard", self._count(player, 16))):
                for sequence in range(count):
                    position = self._query(player, location, sequence, 2)
                    if position is None:
                        continue
                    public = location == 16 or bool(position[1] & 5) or self.modern_actions and bool(position[1]&0x80)
                    visible = player == observer or public
                    code = self._query(player, location, sequence, 1)[0] if visible else None
                    owner, attack, defense = player, None, None
                    if self.general_actions:
                        owner = None
                        if visible:
                            code, owner, attack, defense = self._visible_data(player, location, sequence, public and location == 4)
                    cards.append(CardView(f"p{player}.{zone}.{sequence}", owner, player, zone,
                                          "public" if public else "observer" if visible else "hidden", code,
                                          (position[1]&15 if self.modern_actions else position[1]) if self.general_actions and location in (4, 8) else None, attack, defense))
        if self.extended_actions:
            from .extra_observation import extend
            cards = extend(self, observer, cards)
        history = ()
        if self.scenario != "normal" and not self.modern_actions:
            history = tuple(PublicEvent(f"public-{i}", e["event"], tuple(e["card_ids"])) for i, e in enumerate(public_event_projection(self.events, extended=self.general_actions)))
        if self.modern_actions:
            history = tuple(self._public_history)
        return Observation(observer, self.turn_player, self.turn, self.phase, tuple(self.life_points),
                           tuple(self._count(p, 2) for p in (0, 1)), tuple(self._count(p, 1) for p in (0, 1)), tuple(cards), history)

    def _prompt(self, kind, reader):
        if self.general_actions:
            if self.extended_actions and reader.offset + int(kind == 23) >= len(reader.data):
                raise NativeError("truncated native prompt player")
            player = reader.data[reader.offset + int(kind == 23)] if self.extended_actions else None
            if self.extended_actions and player not in (0, 1):
                raise NativeError("invalid native prompt player")
            observation = self._observation(player) if self.extended_actions else None
            if self.extended_actions:
                from .extra_observation import resolve
                decoded = decode_prompt(kind, reader, allow_sum=True, allow_advanced=self.modern_actions,
                                        catalog=self._rows if self.modern_actions else None,
                                        selection_observation=observation if self.private_actions else None,
                                        selection_seed=(self._selection_seed,player,self._observer_windows[player]) if self.private_actions else None,
                                        known_slots=self._private_revealed_slots[player] if self.knowledge_actions else None,
                                        ref_resolver=lambda *args: resolve(self, *args))
            else:
                decoded = decode_prompt(kind, reader)
            self.window += 1
            self._observer_windows[decoded.player] += 1
            self._responses = {f"choice-{i}": o.response for i, o in enumerate(decoded.options)}
            actions = tuple(LegalAction(f"choice-{i}", o.kind, o.refs, o.value, o.details) for i, o in enumerate(decoded.options))
            self.pending = DecisionRequest(self.context, "native-effect-duel", f"p{decoded.player}-window-{self._observer_windows[decoded.player]}",
                observation or self._observation(decoded.player), actions, search_choices=decoded.search_choices, prompt=decoded.info,
                sum_selection=decoded.sum_selection, selection_choices=decoded.selection_choices,
                private_reveals=tuple(self._private_reveals[decoded.player]) if self.knowledge_actions else ())
            self.pending_kind = kind
            return self.pending
        player = reader.u8()
        options = []
        search_choices = ()
        if kind == 10:
            if reader.u8():
                raise NativeError("battle activation outside normal-monster scope")
            for index in range(reader.u8()):
                reader.u32()
                owner, location, sequence, _direct = reader.u8(), reader.u8(), reader.u8(), reader.u8()
                if location != 4:
                    raise NativeError("attack candidate outside monster zone")
                options.append(("attack", (f"p{owner}.monster.{sequence}",), None, (index << 16) | 1))
            for value in (2, 3):
                if reader.u8():
                    options.append(("pass", (), value, value))
        elif kind == 11:
            for mode, action_kind in enumerate(("summon", "special_summon", "position", "set", "set", "activate")):
                for index in range(reader.u8()):
                    reader.u32()  # Card identity is queried via the player's legal view instead.
                    owner, location, sequence = reader.u8(), reader.u8(), reader.u8()
                    if mode == 5:
                        reader.u32()
                    zone = {2: "hand", 4: "monster", 8: "spell_trap", 16: "graveyard"}.get(location)
                    if zone is None:
                        raise NativeError("candidate zone outside native smoke scope")
                    options.append((action_kind, (f"p{owner}.{zone}.{sequence}",), None, (index << 16) | mode))
            for value in (6, 7, 8):
                if reader.u8():
                    options.append(("pass" if value < 8 else "select", (), value, value))
        elif kind == 12:
            reader.take(8)
            description = reader.u32()
            options = [("yes", (), description, 1), ("no", (), description, 0)]
        elif kind == 13:
            reader.u32()  # Public yes/no description, e.g. direct attack/replay.
            options = [("yes", (), None, 1), ("no", (), None, 0)]
        elif kind == 15:
            cancelable, minimum, maximum, count = reader.u8(), reader.u8(), reader.u8(), reader.u8()
            refs, candidates = [], []
            for _ in range(count):
                code = reader.u32()
                owner, location, sequence, _subsequence = reader.u8(), reader.u8(), reader.u8(), reader.u8()
                candidates.append((code, owner, location, sequence))
            if any(c[2] == 1 for c in candidates):
                search_choices, options = decode_deck_choices(player, minimum, maximum, candidates)
            else:
                for code, owner, location, sequence in candidates:
                    zone = {2: "hand", 4: "monster", 8: "spell_trap", 16: "graveyard"}.get(location)
                    if zone is None or (location == 2 and owner != player):
                        raise NativeError("selection outside supported visible zones")
                    refs.append(f"p{owner}.{zone}.{sequence}")
                if count > 10:
                    raise NativeError("selection exceeds bounded combination scope")
                for size in range(minimum, maximum + 1):
                    for indices in combinations(range(count), size):
                        options.append(("select", tuple(refs[i] for i in indices), size, bytes((size, *indices))))
            if cancelable:
                options.append(("pass", (), None, -1))
        elif kind == 16:
            count, _special = reader.u8(), reader.u8()
            reader.take(8)  # Both public timing hints.
            if count and self.scenario == "normal":
                raise NativeError("effect chains outside native smoke scope")
            forced = False
            for index in range(count):
                _flag, required = reader.u8(), reader.u8()
                reader.u32()
                owner, location, sequence, _position = reader.u8(), reader.u8(), reader.u8(), reader.u8()
                description = reader.u32()
                zone = {2: "hand", 4: "monster", 8: "spell_trap", 16: "graveyard"}.get(location)
                if zone is None or owner != player:
                    raise NativeError("chain candidate outside supported own visible zones")
                options.append(("activate", (f"p{owner}.{zone}.{sequence}",), description, index))
                forced |= bool(required)
            if not forced:
                options.append(("pass", (), None, -1))
        elif kind == 18:
            count, forbidden = reader.u8(), reader.u32()
            if count not in (0, 1):
                raise NativeError("multi-place selection outside native smoke scope")
            for relative in (0, 1):
                owner = player if relative == 0 else 1 - player
                for location, shift in ((4, 0), (8, 8)):
                    for sequence in range(7 if location == 4 else 8):
                        if not forbidden & (1 << (sequence + shift + 16 * relative)):
                            options.append(("select", (), sequence, bytes((owner, location, sequence))))
            if count == 0:
                options.append(("pass", (), None, bytes((player, 0, 0))))
        elif kind == 19:
            reader.u32()
            positions = reader.u8()
            options = [("position", (), position, position) for position in (1, 2, 4, 8) if positions & position]
        self.window += 1
        self._responses = {f"choice-{index}": response for index, (*_, response) in enumerate(options)}
        actions = tuple(LegalAction(f"choice-{i}", action_kind, refs, value) for i, (action_kind, refs, value, _) in enumerate(options))
        self._observer_windows[player] += 1
        window_id = f"window-{self.window}" if self._legacy_ids else f"p{player}-window-{self._observer_windows[player]}"
        self.pending = DecisionRequest(self.context, "native-smoke-duel", window_id, self._observation(player), actions, search_choices=search_choices)
        self.pending_kind = kind
        return self.pending

    def next_decision(self):
        if self.closed:
            raise NativeError("native engine is closed")
        if self.outcome is not None:
            return None
        if self.pending is not None:
            return self.pending
        for _ in range(256):
            result = self.lib.process(self.handle)
            self._check_callbacks()
            buffer = (C.c_uint8 * 65536)()
            length = self.lib.get_message(self.handle, buffer)
            if length < 0 or length > len(buffer):
                raise NativeError("native message exceeded buffer")
            reader = Reader(bytes(buffer[:length]))
            while reader.offset < len(reader.data):
                kind = reader.u8()
                self.messages.append(kind)  # Message IDs only, never raw hidden-state payloads.
                event = {"kind": kind}
                self.events.append(event)
                if kind == 1:
                    raise NativeError("real engine rejected response (MSG_RETRY)")
                if kind in (10, 11, 12, 13, 15, 16, 18, 19) or (self.general_actions and kind in (14, 20, 26)) or (self.extended_actions and kind == 23) or (self.modern_actions and kind in (22,24,25,132,140,141,142,143)):
                    request = self._prompt(kind, reader)
                    event.update(player=request.observation.observer, choices=len(request.actions))
                    if reader.offset != len(reader.data):
                        raise NativeError("unexpected bytes after native prompt")
                    return request
                if self.modern_actions:
                    from .public_history import consume
                    consume(self,kind,reader,event)
                    if self.outcome is not None:
                        if reader.offset != len(reader.data):
                            raise NativeError("unexpected bytes after terminal result")
                        return None
                    continue
                if kind == 2:
                    reader.take(6)
                elif kind == 40:
                    self.turn_player = reader.u8()
                    self.turn += 1
                    event.update(player=self.turn_player, turn=self.turn)
                elif kind == 41:
                    phase = reader.u16()
                    phases = {1: "draw", 2: "standby", 4: "main1", 8: "battle", 16: "battle", 32: "battle", 64: "battle", 128: "battle", 0x100: "main2", 0x200: "end"}
                    if phase not in phases:
                        raise NativeError("unknown native phase")
                    self.phase = phases[phase]
                    event["phase"] = self.phase
                elif kind in (32,):
                    reader.take(1)
                elif kind in (33, 90):
                    event["player"], event["count"] = reader.u8(), reader.u8()
                    self._revealed_hand[event["player"]].clear()
                    if self.extended_actions and kind == 33:
                        from .extra_observation import shuffled_hand
                        shuffled_hand(self, event["player"])
                    reader.take(event["count"] * 4)  # Discard identities, including opponent draws.
                elif kind == 50:
                    code = reader.u32()
                    previous, current = reader.take(4), reader.take(4)
                    if self.extended_actions:
                        from .extra_observation import moved
                        moved(self, previous, current)
                    reason = reader.u32()
                    if previous[1] == 2:
                        self._revealed_hand[previous[0]].clear()
                    if current[1] == 2:
                        self._revealed_hand[current[0]].clear()
                    event.update(from_zone=previous[1], to_zone=current[1], player=current[0])
                    if self.scenario != "normal":
                        event["reason"] = reason
                        if current[1] == 16 or (current[1] in (4, 8) and current[3] & 5):
                            event["public_card"] = code
                        elif self.extended_actions and current[1] in (32, 64) and current[3] & 5:
                            event["public_card"] = code
                elif kind in (60, 62) or (self.general_actions and kind == 64):
                    code, slot = reader.u32(), reader.take(4)
                    if not self.general_actions or slot[3] & 5:
                        event["public_summoning_card"] = code
                    event["player"] = slot[0]
                    if self.general_actions:
                        event.update(zone=slot[1], slot=slot[2], position=slot[3])
                elif kind in (61, 63) or (self.general_actions and kind == 65):
                    pass
                elif kind == 5:
                    self.outcome = {"winner": reader.u8(), "reason_code": reader.u8()}
                    event.update(self.outcome)
                    if reader.offset != len(reader.data):
                        raise NativeError("unexpected bytes after terminal result")
                    return None
                elif kind in (91, 92, 94, 100):
                    player, amount = reader.u8(), reader.u32()
                    if player not in (0, 1):
                        raise NativeError("invalid LP event player")
                    self.life_points[player] = (amount if kind == 94 else self.life_points[player] + amount if kind == 92 else max(0, self.life_points[player] - amount))
                    event.update(player=player, amount=amount, lp=self.life_points[player])
                elif kind == 53 and self.general_actions:
                    code = reader.u32()
                    owner, zone, sequence, previous, current = reader.take(5)
                    event.update(player=owner, zone=zone, slot=sequence, previous_position=previous, position=current)
                    if (previous | current) & 5:
                        event["public_card"] = code
                elif kind in (101, 102) and self.general_actions:
                    event["counter_type"] = reader.u16()
                    event["player"], event["zone"], event["slot"] = reader.u8(), reader.u8(), reader.u8()
                    event["count"] = reader.u16()
                elif kind in (53, 160):
                    reader.take(9)
                elif kind == 54:
                    reader.take(8)
                elif kind == 110:
                    attacker, defender = reader.take(4), reader.take(4)
                    event.update(attacker_player=attacker[0], attacker_zone=attacker[1], attacker_slot=attacker[2],
                                 defender_player=defender[0], defender_zone=defender[1], defender_slot=defender[2])
                elif kind == 111:
                    data = reader.take(26)
                    event.update(attacker_player=data[0], defender_player=data[13],
                                 attacker_atk=struct.unpack_from("<i", data, 4)[0], defender_atk=struct.unpack_from("<i", data, 17)[0])
                elif kind in (112, 113, 114):
                    pass
                elif kind == 70 and self.scenario != "normal":
                    code = reader.u32()
                    reader.take(4)
                    owner, zone, sequence = reader.u8(), reader.u8(), reader.u8()
                    description, link = reader.u32(), reader.u8()
                    event.update(public_card=code, player=owner, zone=zone, slot=sequence, description=description, link=link)
                elif kind in (71, 72, 73, 75, 76) and self.scenario != "normal":
                    event["link"] = reader.u8()
                elif kind == 74 and self.scenario != "normal":
                    pass
                elif kind == 83 and self.scenario != "normal":
                    event["targets"] = [list(reader.take(4)[:3]) for _ in range(reader.u8())]
                elif kind == 31 and self.scenario != "normal":
                    self._confirmation_pause = True
                    event["viewer"] = reader.u8()
                    reader.u8()  # skip_panel, as fixed core/libduel.cpp emits it.
                    revealed = []
                    for _ in range(reader.u8()):
                        code, owner, zone, sequence = reader.u32(), reader.u8(), reader.u8(), reader.u8()
                        if code == 0 or owner not in (0, 1) or zone != 2:
                            raise NativeError("confirmation outside scoped hand reveal")
                        self._revealed_hand[owner][sequence] = code
                        revealed.append(code)
                    event["public_cards"] = revealed
                else:
                    raise NativeError(f"unsupported native message {kind}; full duel not implemented")
            if result & 0x30000000:
                if self.modern_actions and length and result & 0x10000000 and not result & 0x20000000:
                    # The pinned processor flushes non-decision buffers (e.g.
                    # declaration result hints) under WAITING too. Every byte
                    # was decoded above; advance only after nonempty output.
                    self._confirmation_pause = False
                    continue
                if result & 0x10000000 and not result & 0x20000000 and self._confirmation_pause:
                    self._confirmation_pause = False
                    continue  # Fixed core PROCESSOR_WAIT removes itself; confirmation has no response.
                raise NativeError("native engine ended/waited without a supported prompt")
        raise NativeError("native message budget exhausted")

    def submit(self, selection):
        if self.closed or self.outcome is not None or self.pending is None:
            raise ContractError("no active native decision window")
        action = validate_selection(self.pending, selection)
        response = self._responses[action.action_id]
        if self.modern_actions and self.pending_kind in (140,141,142,143):
            hint = {140:6,141:7,142:8,143:9}[self.pending_kind]
            self._public_declarations[(hint,self.pending.observation.observer)] = action.value
        self.pending = None
        self._responses = {}
        if isinstance(response, bytes):
            # The pinned core reads a fixed 256-byte record from this pointer
            # regardless of how short the encoded selection is; the guard owns
            # both sizes so no call site has to. Kept alive across the call.
            buffer = build_response_buffer(response)
            self.lib.set_responseb(self.handle, buffer)
        else:
            self.lib.set_responsei(self.handle, response)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.handle:
            self.lib.end_duel(self.handle)
            self.handle = None
        _ACTIVE.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


NativeSmokeEngine = NativeNormalEngine  # M2a compatibility alias.


def public_event_projection(events, *, extended=False):
    """Whitelist public facts; discard private prompts/counts and their global indices."""
    names = {5: "result", 31: "reveal", 40: "phase", 41: "phase", 50: "move", 60: "summon", 62: "summon", 70: "activate"}
    if extended:
        names.update({53: "move", 64: "summon", 110: "attack"})
    return [{"event": names[e["kind"]], "card_ids": e.get("public_cards", [e.get("public_card", e.get("public_summoning_card"))]
             if e.get("public_card", e.get("public_summoning_card")) else [])}
            for e in events if e["kind"] in names]


def run_native_smoke(root: Path, seed=7) -> dict:
    with NativeSmokeEngine(root, seed=seed) as engine:
        first = engine.next_decision()
        action = next((a for a in first.actions if a.kind == "summon"), None)
        if action is None:
            raise NativeError("real engine supplied no normal summon")
        request = first
        for step in range(8):
            engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
            request = engine.next_decision()
            if 61 in engine.messages:
                if engine._count(0, 4) != 1 or engine._count(0, 2) != first.observation.hand_counts[0] - 1:
                    raise NativeError("real summon event did not match queried field/hand")
                return {"ok": True, "engine": "real-ygopro-core", "scope": "one-normal-summon", "full_duel_supported": False,
                        "seed": seed, "core_commit": engine.lock["sources"]["core"]["commit"],
                        "resources": engine.receipt["resources"], "card_pool": list(engine.deck), "banlist": "community-2026.10",
                        "message_ids": engine.messages, "response_count": step + 1, "summoned": 1,
                        "own_hand_before": first.observation.hand_counts[0], "own_hand_after": engine._count(0, 2),
                        "loaded_scripts": sorted(engine.loaded_scripts), "callback_errors": len(engine.callback_errors)}
            action = request.actions[0]
        raise NativeError("normal summon did not finish within smoke response budget")

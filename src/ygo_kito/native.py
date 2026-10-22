"""Pinned YGOPro core smoke adapter. Unsupported messages fail closed.

This implements one normal summon, not full duels/effects/replays or a PC client.
Native response bytes and all-information engine messages stay inside the adapter.
"""

import ctypes as C
from collections import Counter
import json
from pathlib import Path
import sqlite3
import struct
import threading

from .contracts import ActionSelection, CardView, DecisionRequest, LegalAction, Observation, RunContext, Versions, validate_selection
from .engine import EngineUnavailable
from .native_assets import LOCK_PATH, verify_resources
from .validation import ContractError, integer

_ACTIVE = threading.Lock()  # The upstream callback registry is process-global.


class NativeError(RuntimeError):
    pass


class CardData(C.Structure):
    _fields_ = [("code", C.c_uint32), ("alias", C.c_uint32), ("setcode", C.c_uint16 * 16),
                *[(key, C.c_uint32) for key in ("type", "level", "attribute", "race")],
                ("attack", C.c_int32), ("defense", C.c_int32),
                *[(key, C.c_uint32) for key in ("lscale", "rscale", "link_marker", "rule_code")]]


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, count):
        end = self.offset + count
        if end > len(self.data):
            raise NativeError("truncated native message")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]


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


class NativeSmokeEngine:
    def __init__(self, root: Path, *, seed=7):
        integer(seed, "seed", 0, 2**32 - 8)
        self.root = root.resolve()
        self.receipt = verify_resources(self.root)
        self.sources = self.root / "engine-src"
        self.lock = json.loads(LOCK_PATH.read_text())
        self.closed, self.handle, self.pending = False, None, None
        self.window, self.turn, self.turn_player, self.phase = 0, 0, 0, "draw"
        self.messages, self.callback_errors, self.loaded_scripts = [], [], set()
        self._buffers, self._responses = {}, {}
        if not _ACTIVE.acquire(blocking=False):
            raise EngineUnavailable("only one native smoke engine per process is supported")
        try:
            self.lib = C.CDLL(str(self.root / "engine-build/libocgcore.so"))
            self._bind()
            with sqlite3.connect((self.sources / "database/locales/zh-CN/cards.cdb").as_uri() + "?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                self._rows = {row["id"]: dict(row) for row in db.execute("SELECT * FROM datas")}
            limits = banlist_limits(self.sources / "client/lflist.conf")
            # Explicit custom pool, not a claimed 2022/2026 release-date curriculum.
            self.deck = tuple(code for code, row in sorted(self._rows.items())
                              if row["type"] == 17 and row["alias"] == 0 and row["ot"] & 1
                              and code < 100000000 and 1 <= row["level"] <= 4 and limits.get(code, 3) >= 1)[:40]
            self.validate_deck(self.deck)
            self._install_callbacks()
            seeds = (C.c_uint32 * 8)(*(seed + i for i in range(8)))
            self.handle = self.lib.create_duel_v2(seeds)
            if not self.handle:
                raise NativeError("native create_duel_v2 failed")
            self._check_callbacks()
            for player in (0, 1):
                self.lib.set_player_info(self.handle, player, 8000, 5, 1)
                for code in self.deck:
                    self.lib.new_card(self.handle, code, player, player, 1, 0, 8)
            self._check_callbacks()
            hashes = self.receipt["resources"]
            self.context = RunContext("native-smoke", Versions(self.lock["sources"]["core"]["commit"],
                hashes["scripts"], hashes["cards"], hashes["client_protocol"],
                self.lock["card_pool"]["id"], "2026.10:" + hashes["banlist"]), None)
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

    def validate_deck(self, deck):
        limits = banlist_limits(self.sources / "client/lflist.conf")
        if len(deck) != 40:
            raise ContractError("native smoke requires a 40-card main deck")
        for code, count in Counter(deck).items():
            row = self._rows.get(code)
            if not row or code not in self.deck or count > limits.get(row["alias"] or code, 3):
                raise ContractError("deck violates explicit smoke pool or locked banlist")

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

    def _observation(self, observer):
        cards = []
        for sequence in range(self._count(observer, 2)):
            code, _ = self._query(observer, 2, sequence, 1)
            cards.append(CardView(f"p{observer}.hand.{sequence}", observer, observer, "hand", "observer", code))
        for player in (0, 1):
            for sequence in range(7):
                position = self._query(player, 4, sequence, 2)
                if position is None:
                    continue
                visible = player == observer or position[1] & 5
                code = self._query(player, 4, sequence, 1)[0] if visible else None
                cards.append(CardView(f"p{player}.monster.{sequence}", player, player, "monster",
                                      "public" if position[1] & 5 else "observer" if visible else "hidden", code))
        return Observation(observer, self.turn_player, self.turn, self.phase, (8000, 8000),
                           tuple(self._count(p, 2) for p in (0, 1)), tuple(self._count(p, 1) for p in (0, 1)), tuple(cards))

    def _prompt(self, kind, reader):
        player = reader.u8()
        options = []
        if kind == 11:
            for mode, action_kind in enumerate(("summon", "special_summon", "position", "set", "set", "activate")):
                for index in range(reader.u8()):
                    reader.u32()  # Card identity is queried via the player's legal view instead.
                    owner, location, sequence = reader.u8(), reader.u8(), reader.u8()
                    if mode == 5:
                        reader.u32()
                    zone = {2: "hand", 4: "monster"}.get(location)
                    if zone is None:
                        raise NativeError("candidate zone outside native smoke scope")
                    options.append((action_kind, (f"p{owner}.{zone}.{sequence}",), None, (index << 16) | mode))
            for value in (6, 7, 8):
                if reader.u8():
                    options.append(("pass" if value < 8 else "select", (), value, value))
        elif kind == 16:
            count, _special = reader.u8(), reader.u8()
            reader.take(8)  # Both public timing hints.
            if count:
                raise NativeError("effect chains outside native smoke scope")
            options = [("pass", (), None, -1)]
        elif kind == 18:
            count, forbidden = reader.u8(), reader.u32()
            if count != 1:
                raise NativeError("multi-place selection outside native smoke scope")
            for relative in (0, 1):
                owner = player if relative == 0 else 1 - player
                for location, shift in ((4, 0), (8, 8)):
                    for sequence in range(7 if location == 4 else 8):
                        if not forbidden & (1 << (sequence + shift + 16 * relative)):
                            options.append(("select", (), sequence, bytes((owner, location, sequence))))
        elif kind == 19:
            reader.u32()
            positions = reader.u8()
            options = [("position", (), position, position) for position in (1, 2, 4, 8) if positions & position]
        self.window += 1
        self._responses = {f"choice-{index}": response for index, (*_, response) in enumerate(options)}
        actions = tuple(LegalAction(f"choice-{i}", action_kind, refs, value) for i, (action_kind, refs, value, _) in enumerate(options))
        self.pending = DecisionRequest(self.context, "native-smoke-duel", f"window-{self.window}", self._observation(player), actions)
        return self.pending

    def next_decision(self):
        if self.closed:
            raise NativeError("native engine is closed")
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
                if kind == 1:
                    raise NativeError("real engine rejected response (MSG_RETRY)")
                if kind in (11, 16, 18, 19):
                    request = self._prompt(kind, reader)
                    if reader.offset != len(reader.data):
                        raise NativeError("unexpected bytes after native prompt")
                    return request
                if kind == 2:
                    reader.take(6)
                elif kind == 40:
                    self.turn_player = reader.u8()
                    self.turn += 1
                elif kind == 41:
                    phase = reader.u16()
                    phases = {1: "draw", 2: "standby", 4: "main1", 8: "battle", 16: "battle", 32: "battle", 64: "battle", 128: "battle", 0x100: "main2", 0x200: "end"}
                    if phase not in phases:
                        raise NativeError("unknown native phase")
                    self.phase = phases[phase]
                elif kind in (32,):
                    reader.take(1)
                elif kind in (33, 90):
                    reader.u8()
                    reader.take(reader.u8() * 4)  # Discard all identities, including opponent draws.
                elif kind == 50:
                    reader.take(16)
                elif kind == 60:
                    reader.take(8)
                elif kind == 61:
                    pass
                else:
                    raise NativeError(f"unsupported native message {kind}; full duel not implemented")
            if result & 0x30000000:
                raise NativeError("native engine ended/waited without a supported prompt")
        raise NativeError("native message budget exhausted")

    def submit(self, selection):
        if self.closed or self.pending is None:
            raise ContractError("no active native decision window")
        action = validate_selection(self.pending, selection)
        response = self._responses[action.action_id]
        self.pending = None
        self._responses = {}
        if isinstance(response, bytes):
            buffer = (C.c_uint8 * 64)()
            buffer[:len(response)] = response
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

"""Read the exact Lua registration used by each chain in a construction replay."""

from contextlib import contextmanager
import ctypes as C
from functools import cached_property, partial
from hashlib import sha256
from io import StringIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from .build_contracts import digest
from .native_registrations import RULE_DECLARATION_HEADER, _read_effect, _read_row


_SOURCE = RULE_DECLARATION_HEADER.with_name("construction_rule_trace.cpp")
_GUARDS = _SOURCE.with_name("construction_rule_guards.h")
_PHASES = (70, 71, 72, 73)


class NativeRuleTraceError(RuntimeError):
    pass


def _decode(raw, lua):
    handle = StringIO(raw)
    links, moves, targets, guards, calls, deck_order = {}, {}, {}, [], {}, set()
    while handle.tell() < len(raw):
        start = handle.tell()
        tag = handle.readline().split("\t", 1)[0]
        handle.seek(start)
        if tag == "link":
            (index, kind, link, card, seat, issuer, zone, slot, event, replaced, chain_id,
             entity, owner, stock) = map(int, _read_row(handle, tag, 14))
            if kind not in _PHASES or link < 1 or seat not in (0, 1) or replaced not in (0, 1) or index in links:
                raise ValueError("invalid rule trace chain link")
            links[index] = dict(kind=kind, link=link, card=card, seat=seat, issuer=issuer, zone=zone, slot=slot,
                event=event, replaced=bool(replaced), chain_id=chain_id, entity=entity, owner=owner, stock=stock,
                declaration=_read_effect(handle, lua))
        elif tag == "move":
            index, *placement, reason, card, chain_id, summon_type, call, stage, entity, owner, stock = map(
                int, _read_row(handle, tag, 18))
            if index in moves:
                raise ValueError("duplicate rule trace movement")
            moves[index] = dict(origin=placement[:4], destination=placement[4:], reason=reason, card=card,
                                chain_id=chain_id, summon_type=summon_type, entity=entity, owner=owner, stock=stock,
                                call=call, stage=stage)
        elif tag == "target":
            index, *location, card, entity, owner, stock = map(int, _read_row(handle, tag, 9))
            targets.setdefault(index, []).append(dict(location=location, card=card, entity=entity, owner=owner, stock=stock))
        elif tag == "deck-order":
            index, = map(int, _read_row(handle, tag, 1))
            if index in deck_order:
                raise ValueError("duplicate native deck order notice")
            deck_order.add(index)
        elif tag == "guard":
            *state, role, result = _read_row(handle, tag, 10)
            index, entity, card, seat, turn, phase, zone, position = map(int, state)
            if role not in ("condition", "cost", "target") or result not in ("0", "1") or seat not in (0, 1):
                raise ValueError("invalid native eligibility check")
            guards.append(dict(index=index, entity=entity, card=card, seat=seat, turn=turn, phase=phase,
                zone=zone, position=position, role=role, passed=result == "1", declaration=_read_effect(handle, lua)))
        elif tag == "operation":
            index, chain, identity, stage, method = _read_row(handle, tag, 5)
            key = int(identity)
            if key in calls:
                raise ValueError("duplicate native operation invocation")
            calls[key] = dict(index=int(index), chain_id=int(chain), stage=int(stage), method=method)
        else:
            raise ValueError("invalid row in the rule trace")
    return links, moves, targets, guards, calls, deck_order


def align_rule_trace(events, links, moves, targets, guards=(), calls=None, deck_order=()):
    """Verify captured identities against the message at the same replay index."""
    captured = {}
    unaligned = set()
    verified_moves = {}
    calls = calls or {}
    for i, event in enumerate(events):
        kind = event["kind"]
        if kind == 50:
            motion = moves.get(i)
            if motion and (event["from_zone"], event["to_zone"], event["player"], event["reason"]) == (
                    motion["origin"][1], motion["destination"][1], motion["destination"][0], motion["reason"]
                    ) and event.get("public_card", motion["card"]) == motion["card"]:
                call = calls.get(motion.get("call"))
                if call and call["chain_id"] == motion["chain_id"] and call["stage"] == motion["stage"] and call["index"] <= i:
                    verified_moves[str(i)] = dict(motion, operation=call)
                else:
                    verified_moves[str(i)] = {k: v for k, v in motion.items() if k not in ("call", "stage")}
            continue
        if kind not in _PHASES:
            continue
        row = links.get(i)
        if (not row or (kind, event["link"]) != (row["kind"], row["link"]) or kind == 70 and (
            event["public_card"], event["zone"], event["slot"], event["description"]
        ) != (row["card"], row["zone"], row["slot"], row["declaration"]["description"])):
            unaligned.add(kind)
            continue
        captured[str(i)] = dict(row, targets=targets.get(i, [])) if kind == 71 else row
    return dict(observations=captured, moves=verified_moves, unaligned_phases=sorted(unaligned),
                deck_order_notices=sorted(i for i in deck_order if 0 <= i < len(events)
                    and events[i]["kind"] == 50 and events[i]["from_zone"] == events[i]["to_zone"] == 1
                    and events[i]["reason"] == 0x40 and not events[i].get("public_card")),
                guards=[row for row in guards if 0 <= row["index"] <= len(events)],
                calls={str(key): row for key, row in calls.items() if 0 <= row["index"] <= len(events)})


class NativeRuleTraceSource:
    """Load a read-only observer built against the active period's exact core."""

    def __init__(self, assets):
        self.assets = assets
        self.path = assets.workspace / "construction-native-rule-traces"
        self.core = (assets.root / "engine-build/libocgcore.so").resolve()
        self.sources = {path.name: path.read_bytes() for path in (_SOURCE, RULE_DECLARATION_HEADER, _GUARDS)}
        self.binding = dict(sources={name: sha256(data).hexdigest() for name, data in self.sources.items()},
                            core=assets.receipt["resources"]["library"])

    @cached_property
    def library(self):
        library = self.path / (digest((self.binding, str(self.core))) + ".so")
        try:
            if not library.is_file():
                sources = self.assets.root / "engine-src"
                self.path.mkdir(parents=True, exist_ok=True)
                with TemporaryDirectory(dir=self.path, prefix="rule-observer-") as scratch:
                    directory = Path(scratch)
                    staged = directory / library.name
                    for filename, source in self.sources.items():
                        (directory / filename).write_bytes(source)
                    subprocess.run(["g++", "-std=c++17", "-O2", "-shared", "-fPIC",
                                    "-I", sources / "core", "-I", sources / "lua", directory / _SOURCE.name,
                                    self.core, f"-Wl,-rpath,{self.core.parent}", "-o", staged],
                                   capture_output=True, text=True, check=True, timeout=60)
                    staged.replace(library)
            opened = C.CDLL(str(library))
        except subprocess.CalledProcessError as error:
            raise NativeRuleTraceError(f"locked rule observer failed to compile: {error.stderr.strip()}") from error
        except (OSError, subprocess.TimeoutExpired) as error:
            raise NativeRuleTraceError(f"locked rule observer unavailable: {error}") from error
        opened.ygo_rule_trace_start.argtypes = [C.c_void_p, C.c_uint8]
        opened.ygo_rule_trace_start.restype = C.c_void_p
        opened.ygo_rule_trace_process.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
        opened.ygo_rule_trace_process.restype = C.c_uint32
        opened.ygo_rule_trace_message.argtypes = [C.c_void_p, C.c_size_t, C.c_size_t]
        opened.ygo_rule_trace_message.restype = None
        opened.ygo_rule_trace_read.argtypes = [C.c_void_p]
        opened.ygo_rule_trace_read.restype = C.c_char_p
        opened.ygo_rule_trace_guard_status.argtypes = [C.c_void_p]
        opened.ygo_rule_trace_guard_status.restype = C.c_uint8
        opened.ygo_rule_trace_end.argtypes = [C.c_void_p]
        opened.ygo_rule_trace_end.restype = None
        return opened

    @contextmanager
    def observe(self, engine, *, seat=0):
        if not engine.modern_actions:
            yield lambda _: dict(observations={}, error="rule_trace_needs_period_message_decoder")
            return
        try:
            library = self.library
        except NativeRuleTraceError as error:
            diagnostic = str(error)
            yield lambda _: dict(observations={}, error=diagnostic)
            return
        trace = library.ygo_rule_trace_start(engine.handle, seat)
        if not trace:
            yield lambda _: dict(observations={}, error="native_rule_trace_allocation_failed")
            return
        original = engine.lib.process
        try:
            engine.lib.process = lambda duel: library.ygo_rule_trace_process(duel, trace, len(engine.events))
            engine._construction_rule_message = partial(library.ygo_rule_trace_message, trace)
            yield partial(self._read, library, trace)
        finally:
            del engine._construction_rule_message
            engine.lib.process = original
            library.ygo_rule_trace_end(trace)

    def _read(self, library, trace, events):
        raw = library.ygo_rule_trace_read(trace)
        if raw is None:
            return dict(observations={}, error="native_chain_snapshot_inconsistent")
        try:
            result = align_rule_trace(events, *_decode(raw.decode("utf-8"), self.assets.effect_lua_source))
            if state := library.ygo_rule_trace_guard_status(trace):
                result["guard_error"] = "lua_hook_in_use" if state == 1 else "native_guard_observer_failed"
            return result
        except ValueError as error:
            return dict(observations={}, error=str(error))

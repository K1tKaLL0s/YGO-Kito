"""Read the exact Lua registration used by each chain in a construction replay."""

from contextlib import contextmanager
import ctypes as C
from functools import cached_property, partial
from io import StringIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from .build_contracts import digest
from .native_assets import digest as file_digest
from .native_registrations import RULE_DECLARATION_HEADER, _read_effect, _read_row


_SOURCE = RULE_DECLARATION_HEADER.with_name("construction_rule_trace.cpp")
_PHASES = (70, 71, 72, 73)


class NativeRuleTraceError(RuntimeError):
    pass


def _decode(raw, lua):
    handle = StringIO(raw)
    links, moves, targets = {}, {}, {}
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
            index, *placement, reason, card, chain_id, summon_type, entity, owner, stock = map(
                int, _read_row(handle, tag, 16))
            if index in moves:
                raise ValueError("duplicate rule trace movement")
            moves[index] = dict(origin=placement[:4], destination=placement[4:], reason=reason, card=card,
                                chain_id=chain_id, summon_type=summon_type, entity=entity, owner=owner, stock=stock)
        elif tag == "target":
            index, *location, card, entity, owner, stock = map(int, _read_row(handle, tag, 9))
            targets.setdefault(index, []).append(dict(location=location, card=card, entity=entity, owner=owner, stock=stock))
        else:
            raise ValueError("invalid row in the rule trace")
    return links, moves, targets


def align_rule_trace(events, links, moves, targets):
    """Verify captured identities against the message at the same replay index."""
    captured = {}
    unaligned = set()
    verified_moves = {}
    for i, event in enumerate(events):
        kind = event["kind"]
        if kind == 50:
            motion = moves.get(i)
            if motion and (event["from_zone"], event["to_zone"], event["player"], event["reason"]) == (
                    motion["origin"][1], motion["destination"][1], motion["destination"][0], motion["reason"]
                    ) and event.get("public_card", motion["card"]) == motion["card"]:
                verified_moves[str(i)] = motion
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
    return dict(observations=captured, moves=verified_moves, unaligned_phases=sorted(unaligned))


class NativeRuleTraceSource:
    """Load a read-only observer built against the active period's exact core."""

    def __init__(self, assets):
        self.assets = assets
        self.path = assets.workspace / "construction-native-rule-traces"
        self.core = (assets.root / "engine-build/libocgcore.so").resolve()
        self.binding = dict(source=file_digest(_SOURCE), declaration=file_digest(RULE_DECLARATION_HEADER),
                            core=assets.receipt["resources"]["library"])

    @cached_property
    def library(self):
        library = self.path / (digest((self.binding, str(self.core))) + ".so")
        try:
            if not library.is_file():
                sources = self.assets.root / "engine-src"
                self.path.mkdir(parents=True, exist_ok=True)
                with TemporaryDirectory(dir=self.path, prefix="rule-observer-") as scratch:
                    staged = Path(scratch) / library.name
                    subprocess.run(["g++", "-std=c++17", "-O2", "-shared", "-fPIC",
                                    "-I", sources / "core", "-I", sources / "lua", _SOURCE,
                                    self.core, f"-Wl,-rpath,{self.core.parent}", "-o", staged],
                                   capture_output=True, text=True, check=True, timeout=60)
                    staged.replace(library)
            opened = C.CDLL(str(library))
        except subprocess.CalledProcessError as error:
            raise NativeRuleTraceError(f"locked rule observer failed to compile: {error.stderr.strip()}") from error
        except (OSError, subprocess.TimeoutExpired) as error:
            raise NativeRuleTraceError(f"locked rule observer unavailable: {error}") from error
        opened.ygo_rule_trace_start.argtypes = [C.c_void_p]
        opened.ygo_rule_trace_start.restype = C.c_void_p
        opened.ygo_rule_trace_process.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
        opened.ygo_rule_trace_process.restype = C.c_uint32
        opened.ygo_rule_trace_read.argtypes = [C.c_void_p]
        opened.ygo_rule_trace_read.restype = C.c_char_p
        opened.ygo_rule_trace_end.argtypes = [C.c_void_p]
        opened.ygo_rule_trace_end.restype = None
        return opened

    @contextmanager
    def observe(self, engine):
        try:
            library = self.library
        except NativeRuleTraceError as error:
            diagnostic = str(error)
            yield lambda _: dict(observations={}, error=diagnostic)
            return
        trace = library.ygo_rule_trace_start(engine.handle)
        if not trace:
            yield lambda _: dict(observations={}, error="native_rule_trace_allocation_failed")
            return
        original = engine.lib.process
        try:
            engine.lib.process = lambda duel: library.ygo_rule_trace_process(duel, trace, len(engine.events))
            yield partial(self._read, library, trace)
        finally:
            engine.lib.process = original
            library.ygo_rule_trace_end(trace)

    def _read(self, library, trace, events):
        raw = library.ygo_rule_trace_read(trace)
        if raw is None:
            return dict(observations={}, error="native_chain_snapshot_inconsistent")
        try:
            return align_rule_trace(events, *_decode(raw.decode("utf-8"), self.assets.effect_lua_source))
        except ValueError as error:
            return dict(observations={}, error=str(error))

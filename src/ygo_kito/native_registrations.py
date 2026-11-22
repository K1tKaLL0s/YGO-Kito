"""Read declarations and configuration resource checks from the locked core."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import subprocess
from tempfile import TemporaryDirectory

from .build_contracts import digest
from .card_identity import native_card_identity
from .construction_checkpoint import write_json
from .engine import EngineUnavailable
from .native_assets import digest as file_digest, verify_resources


_PROBE = Path(__file__).with_name("resources") / "rules/construction_rule_registrations.cpp"
RULE_DECLARATION_HEADER = _PROBE.with_name("construction_rule_effect.h")
_FUSION_STOCK = _PROBE.with_name("construction_fusion_stock.lua")
_SUMMON_STOCK = _PROBE.with_name("construction_summon_stock.lua")
_CALLBACK_ROLES = ("condition", "cost", "target", "operation", "value")


class NativeRegistryError(RuntimeError):
    pass


def _card_data(assets):
    database = assets.root / "engine-src/database/locales/zh-CN/cards.cdb"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for row in connection.execute("SELECT * FROM datas ORDER BY id"):
            code, alias = row["id"], row["alias"] or row["id"]
            printed, name = assets.native_code_overrides.get(code, (alias, alias))
            level = row["level"]
            link = row["def"] if row["type"] & 0x4000000 else 0
            yield (code, printed if printed != code else 0, row["setcode"] % (1 << 64),
                   row["type"], level & 255, row["attribute"], row["race"], row["atk"], row["def"],
                   (level >> 24) & 255, (level >> 16) & 255, link, name if name != printed else 0)


def _read_row(handle, expected, fields):
    kind, *values = handle.readline().rstrip("\n").split("\t")
    if kind != expected or len(values) != fields:
        raise ValueError(f"invalid {expected} row from the locked core")
    return values


def _read_effect(handle, lua):
    scope, kind, event, area, desc, category, limit, maximum, persistent, *values = _read_row(handle, "registration", 24)
    if scope not in ("card", "field"):
        raise ValueError("invalid registration scope from the locked core")
    callbacks = {}
    for offset, role in enumerate(_CALLBACK_ROLES):
        source, first, last = values[3 * offset:3 * offset + 3]
        if source == "-":
            continue
        name = source.removeprefix("@").removeprefix("./script/").removeprefix("script/")
        callback = dict(file=name, lines=[int(first), int(last)])
        if checksum := lua.script_checksum(name):
            callback["sha256"] = checksum
        callbacks[role] = callback
    return dict(scope=scope, type=int(kind), event=int(event), range=int(area), description=int(desc),
                category=int(category), count_code=int(limit), count_maximum=int(maximum),
                count_persistent=bool(int(persistent)), callbacks=callbacks)


def _read_cards(assets, raw, codes):
    lua = assets.effect_lua_source
    cards = {}
    with raw.open(encoding="utf-8") as handle:
        for code in codes:
            current, printed, name, warnings, registrations = map(int, _read_row(handle, "card", 5))
            if current != code or (printed, name) != native_card_identity(assets.rows, code):
                raise ValueError(f"initialized script identity disagrees with the card catalog for {code}")
            if min(warnings, registrations) < 0:
                raise ValueError("invalid diagnostic or registration count")
            diagnostics = [_read_row(handle, "diagnostic", 1)[0] for _ in range(warnings)]
            native = []
            for _ in range(registrations):
                reg = _read_effect(handle, lua)
                flag0, flag1, raw_labels = _read_row(handle, "meta", 3)
                reg["property"] = int(flag0)
                reg["property2"] = int(flag1)
                reg["labels"] = [] if raw_labels == "-" else [int(v) for v in raw_labels.split(",")]
                native.append(reg)
            cards[str(code)] = dict(printed_code=printed, rule_name=name, diagnostics=diagnostics, native=native)
        if handle.readline():
            raise ValueError("unexpected cards in the locked core output")
    return cards


def _cached_probe_executable(output, sources, library, compiler):
    executable_dir = output / "bin"
    executable_dir.mkdir(parents=True, exist_ok=True)
    build_key = digest(dict(
        probe=file_digest(_PROBE),
        header=file_digest(RULE_DECLARATION_HEADER),
        library=file_digest(library),
        compiler=compiler,
    ))
    target = executable_dir / f"registrations-{build_key}"
    if not target.exists():
        with TemporaryDirectory(dir=executable_dir, prefix="registration-build-") as scratch:
            staged = Path(scratch) / "registrations"
            subprocess.run(
                [compiler, "-std=c++17", "-O2", "-I", sources / "core", "-I", sources / "lua",
                 _PROBE, library, f"-Wl,-rpath,{library.parent}", "-o", staged],
                capture_output=True, text=True, check=True, timeout=60,
            )
            try:
                staged.replace(target)
            except OSError:
                if not target.exists():
                    raise
    return target


def _cached_card_table(output, assets):
    tables_dir = output / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    table_key = digest(dict(cards=assets.receipt["resources"]["cards"], overrides=assets.native_code_overrides))
    target = tables_dir / f"card-data-{table_key}.tsv"
    if not target.exists():
        with TemporaryDirectory(dir=tables_dir, prefix="registration-table-") as scratch:
            staged = Path(scratch) / "card-data.tsv"
            with staged.open("w", encoding="utf-8") as handle:
                for row in _card_data(assets):
                    handle.write(" ".join(map(str, row)) + "\n")
            try:
                staged.replace(target)
            except OSError:
                if not target.exists():
                    raise
    return target


@contextmanager
def _rule_probe(assets, output, request, *, compiler="g++", raw=None, arguments=()):
    sources = assets.root / "engine-src"
    library = assets.root / "engine-build/libocgcore.so"
    try:
        if verify_resources(assets.root) != assets.receipt:
            raise NativeRegistryError("locked registration assets changed after binding")
        output.mkdir(parents=True, exist_ok=True)
        executable = _cached_probe_executable(output, sources, library, compiler)
        table = _cached_card_table(output, assets)
        with TemporaryDirectory(dir=output, prefix="registration-run-") as scratch:
            path = raw if raw is not None else Path(scratch) / "registrations.tsv"
            with path.open("w", encoding="utf-8") as handle:
                subprocess.run([executable, sources / "scripts", table, *arguments],
                               input=request, stdout=handle, stderr=subprocess.PIPE,
                               text=True, check=True, timeout=180)
            yield path
    except subprocess.CalledProcessError as error:
        raise NativeRegistryError(f"locked registration probe exited {error.returncode}: {error.stderr.strip()}") from error
    except (OSError, ValueError, EngineUnavailable, sqlite3.Error, subprocess.TimeoutExpired) as error:
        raise NativeRegistryError(f"locked registration probe failed: {error}") from error


def collect_native_registrations(assets, codes, output, *, compiler="g++", raw=None):
    """Initialize the selected cards in isolated core sessions with no duel actions."""
    with _rule_probe(assets, output, "\n".join(map(str, codes)), compiler=compiler, raw=raw) as path:
        return _read_cards(assets, path, codes)


def _read_fusion_stock(handle, main, extra, requests):
    stock = [("main", code) for code in main] + [("extra", code) for code in extra]
    assignments = {}
    for effect_key, (code, _, _) in requests.items():
        heading, status, *outcomes = handle.readline().rstrip("\n").split("\t")
        if heading != "stock" or status not in ("inventory_present", "missing", "unknown"):
            raise ValueError("invalid locked fusion stock response")
        options = []
        for outcome in outcomes:
            target, *material = outcome.split(",")
            target = int(target)
            pairs = [tuple(map(int, assignment.split(":"))) for assignment in material]
            positions = [copy for copy, _ in pairs]
            if (not len(main) < target <= len(stock) or not positions
                    or any(not 1 <= copy <= len(stock) for copy in positions)
                    or len({target, *positions}) != 1 + len(positions)):
                raise ValueError("invalid physical fusion assignment")
            options.append(dict(target=stock[target - 1][1], material_quantity=len(positions),
                materials=[dict(copy=copy, section=stock[copy - 1][0], card_id=stock[copy - 1][1], location=location)
                           for copy, location in sorted(pairs)], target_copy=target))
        if bool(options) != (status == "inventory_present"):
            raise ValueError("fusion stock status disagrees with its assignment")
        assignments[effect_key] = dict(status=status, options=sorted(options, key=lambda row: row["target_copy"]),
            source_card_id=code, shortfall=int(status == "missing"), uncovered_targets=[],
            actual_duel_state_required=False)
    return assignments


def _copy_entry(stock, copy):
    if not 1 <= copy <= len(stock):
        raise ValueError(f"invalid physical copy index: {copy}")
    section, code = stock[copy - 1]
    return dict(copy=copy, section=section, card_id=code)


def _read_summon_stock(handle, main, extra, fusion_requests, ritual_requests):
    stock = [("main", code) for code in main] + [("extra", code) for code in extra]
    fusion_keys = list(fusion_requests.keys())
    fusion = _read_fusion_stock(handle, main, extra, fusion_requests) if fusion_requests else {}
    ritual_keys = list(ritual_requests.keys())
    ritual_options = {key: [] for key in ritual_keys}
    contact_fusion, xyz, synchro, link, pendulum = [], [], [], [], []
    monster_rules, inherent_ss = {}, {}

    for raw in handle:
        line = raw.rstrip("\n")
        if line == "end":
            break
        parts = line.split("\t")
        tag = parts[0]
        if tag == "monster_rule":
            (copy_s, cannot_ns, nomi, revive_limit, lv, rank, lnk, is_tuner, is_flip,
             is_pend, pend_lv, markers, down_arrows, lscale, rscale) = parts[1:]
            entry = _copy_entry(stock, int(copy_s))
            monster_rules[entry["card_id"]] = dict(
                card_id=entry["card_id"],
                section=entry["section"],
                cannot_normal_summon=bool(int(cannot_ns)),
                nomi_restricted=bool(int(nomi)),
                revive_limit=bool(int(revive_limit)),
                level=int(lv),
                rank=int(rank),
                link_rating=int(lnk),
                is_tuner=bool(int(is_tuner)),
                is_flip=bool(int(is_flip)),
                is_pendulum=bool(int(is_pend)),
                pendulum_level=int(pend_lv),
                link_markers=int(markers),
                downward_arrows=int(down_arrows),
                lscale=int(lscale),
                rscale=int(rscale),
            )
        elif tag == "inherent_ss":
            copy_s, ordinal_s, rng_s, empty_ok, opp_ok = parts[1:]
            entry = _copy_entry(stock, int(copy_s))
            inherent_ss.setdefault(entry["card_id"], []).append(dict(
                proc_index=int(ordinal_s),
                range=int(rng_s),
                holds_empty_board=bool(int(empty_ok)),
                holds_with_opponent_monster=bool(int(opp_ok)),
            ))
        elif tag == "fusion_no_mat":
            qi, target_copy, lp_paid = map(int, parts[1:])
            key = fusion_keys[qi]
            target = _copy_entry(stock, target_copy)
            if target["section"] != "extra":
                raise ValueError("fusion target outside extra deck")
            row = fusion[key]
            existing = {opt["target_copy"] for opt in row["options"]}
            if target_copy not in existing:
                row["options"].append(dict(
                    target=target["card_id"], material_quantity=0, materials=[],
                    target_copy=target_copy, lp_cost=lp_paid, material_free=True,
                ))
            row["status"] = "inventory_present"
            row["shortfall"] = 0
        elif tag == "contact_fusion":
            target_copy, ordinal_s, pairs_s = parts[1:]
            target = _copy_entry(stock, int(target_copy))
            mats = []
            for pair in pairs_s.split(","):
                c_s, loc_s = pair.split(":")
                mats.append(dict(_copy_entry(stock, int(c_s)), location=int(loc_s)))
            contact_fusion.append(dict(
                target=target["card_id"], target_copy=target["copy"],
                proc_index=int(ordinal_s), materials=mats,
            ))
        elif tag == "xyz":
            target_copy, ordinal_s, is_alt, ext_flag, attached_s, mats_s = parts[1:]
            target = _copy_entry(stock, int(target_copy))
            mats = [_copy_entry(stock, int(c)) for c in mats_s.split(",")]
            xyz.append(dict(
                target=target["card_id"], target_copy=target["copy"],
                proc_index=int(ordinal_s), is_alternate_overlay=bool(int(is_alt)),
                requires_external_state=None if ext_flag == "none" else ext_flag,
                attached_count=int(attached_s), materials=mats,
            ))
        elif tag == "synchro":
            target_copy, ordinal_s, tuners_s, mats_s = parts[1:]
            target = _copy_entry(stock, int(target_copy))
            tuners = [_copy_entry(stock, int(c)) for c in tuners_s.split(",") if c]
            mats = [_copy_entry(stock, int(c)) for c in mats_s.split(",")]
            synchro.append(dict(
                target=target["card_id"], target_copy=target["copy"],
                proc_index=int(ordinal_s), tuners=tuners, materials=mats,
            ))
        elif tag == "link":
            target_copy, ordinal_s, rating_s, markers_s, down_s, mask_s, mats_s = parts[1:]
            target = _copy_entry(stock, int(target_copy))
            mats = [_copy_entry(stock, int(c)) for c in mats_s.split(",")]
            link.append(dict(
                target=target["card_id"], target_copy=target["copy"],
                proc_index=int(ordinal_s), link_rating=int(rating_s),
                link_markers=int(markers_s), downward_arrows=int(down_s),
                linked_zone_mask=int(mask_s), materials=mats,
            ))
        elif tag == "pendulum":
            l_copy, r_copy, ls_s, rs_s, hand_s, ex_s, ex_proper_s = parts[1:]
            left = _copy_entry(stock, int(l_copy))
            right = _copy_entry(stock, int(r_copy))
            ls, rs = int(ls_s), int(rs_s)
            hand_t = [_copy_entry(stock, int(c)) for c in hand_s.split(",")] if hand_s != "-" else []
            ex_t = [_copy_entry(stock, int(c)) for c in ex_s.split(",")] if ex_s != "-" else []
            ex_p = [_copy_entry(stock, int(c)) for c in ex_proper_s.split(",")] if ex_proper_s != "-" else []
            pendulum.append(dict(
                left=left["card_id"], left_copy=left["copy"],
                right=right["card_id"], right_copy=right["copy"],
                min_scale=min(ls, rs), max_scale=max(ls, rs),
                hand_targets=hand_t, extra_targets=ex_t, extra_proper_targets=ex_p,
            ))
        elif tag == "ritual":
            qi_s, target_copy, mats_s = parts[1:]
            target = _copy_entry(stock, int(target_copy))
            mats = [_copy_entry(stock, int(c)) for c in mats_s.split(",")]
            key = ritual_keys[int(qi_s)]
            ritual_options[key].append(dict(
                target=target["card_id"], target_copy=target["copy"],
                materials=mats, release_timing="resolution",
            ))
        else:
            raise ValueError(f"unexpected summon stock row: {line}")
    else:
        raise ValueError("incomplete locked summon stock response")
    if handle.readline():
        raise ValueError("unexpected trailing summon stock data")
    for card_id, procs in inherent_ss.items():
        if card_id in monster_rules:
            monster_rules[card_id]["inherent_ss_procs"] = procs
    ritual = {
        key: dict(
            status="inventory_present" if opts else "missing",
            options=opts,
            source_card_id=ritual_requests[key][0],
            shortfall=0 if opts else 1,
        )
        for key, opts in ritual_options.items()
    }
    return dict(
        fusion=fusion, contact_fusion=contact_fusion, xyz=xyz, synchro=synchro,
        link=link, pendulum=pendulum, ritual=ritual, monster_rules=monster_rules,
    )


class NativeRegistrationSource:
    """Reuse initialized declarations across deck inventories with identical assets."""

    def __init__(self, assets):
        self.assets = assets
        self.directory = assets.workspace / "construction-native-registrations"
        self.binding = dict(schema_version=2, probe_sha256=file_digest(_PROBE),
                            declaration_sha256=file_digest(RULE_DECLARATION_HEADER), resources=assets.receipt,
                            card_identities=digest(assets.native_code_overrides), period=assets.period_context)
        self._cards = {}
        self._fusion = {}
        self._summon = {}

    @property
    def stock_binding(self):
        return dict(self.binding, fusion_stock_sha256=file_digest(_FUSION_STOCK),
                    summon_stock_sha256=file_digest(_SUMMON_STOCK))

    def fusion_stock(self, main, extra, requests, *, alternate=False):
        """Ask the registered predicate to allocate distinct copies from the supplied view."""
        main, extra = tuple(sorted(main)), tuple(sorted(extra))
        key = main, extra, tuple(sorted(requests.items())), alternate
        if key not in self._fusion:
            stock = main + extra
            payload = [f"{len(main)} {len(extra)} {len(requests)} {int(alternate)}",
                       " ".join(map(str, stock))]
            payload.extend(f"{stock.index(code) + 1} {ordinal} {location}"
                           for code, ordinal, location in requests.values())
            with _rule_probe(self.assets, self.directory, "\n".join(payload), arguments=(_FUSION_STOCK,)) as path:
                with path.open(encoding="utf-8") as handle:
                    self._fusion[key] = _read_fusion_stock(handle, main, extra, requests)
                    if handle.readline():
                        raise ValueError("unexpected locked fusion stock response")
        return self._fusion[key]

    def summon_stock(self, main, extra, fusion_requests=None, ritual_requests=None, *, alternate=False, duel_rule=5):
        """Evaluate all mainstream summoning procedures via the locked core."""
        main, extra = tuple(sorted(main)), tuple(sorted(extra))
        fusion_requests = dict(sorted((fusion_requests or {}).items()))
        ritual_requests = dict(sorted((ritual_requests or {}).items()))
        key = main, extra, tuple(fusion_requests.items()), tuple(ritual_requests.items()), alternate, duel_rule
        if key not in self._summon:
            disk_binding = dict(
                self.stock_binding,
                main=list(main), extra=list(extra),
                fusion_requests=[[k, list(v)] for k, v in fusion_requests.items()],
                ritual_requests=[[k, list(v)] for k, v in ritual_requests.items()],
                alternate=alternate, duel_rule=duel_rule,
            )
            disk_path = self.directory / ("summon-" + digest(disk_binding) + ".json")
            try:
                cached = json.loads(disk_path.read_text(encoding="utf-8"))
                result = cached["result"]
                result["monster_rules"] = {int(k): v for k, v in result["monster_rules"].items()}
                if cached["binding"] != json.loads(json.dumps(disk_binding)) or cached["result_sha256"] != digest(result):
                    raise ValueError("summon stock receipt differs from its binding")
            except (OSError, KeyError, TypeError, ValueError):
                stock = main + extra
                payload = [
                    f"{duel_rule} {len(main)} {len(extra)} {len(fusion_requests)} {int(alternate)} {len(ritual_requests)}",
                    " ".join(map(str, stock)),
                ]
                payload.extend(f"{stock.index(code) + 1} {ordinal} {location}"
                               for code, ordinal, location in fusion_requests.values())
                payload.extend(f"{stock.index(code) + 1} {ordinal}"
                               for code, ordinal in ritual_requests.values())
                with _rule_probe(self.assets, self.directory, "\n".join(payload),
                                 arguments=("--summon-stock", _SUMMON_STOCK)) as path:
                    with path.open(encoding="utf-8") as handle:
                        result = _read_summon_stock(handle, main, extra, fusion_requests, ritual_requests)
                receipt = dict(binding=disk_binding, result=result, result_sha256=digest(result))
                try:
                    self.directory.mkdir(parents=True, exist_ok=True)
                    with TemporaryDirectory(dir=self.directory, prefix="summon-write-") as scratch:
                        staged = Path(scratch) / disk_path.name
                        write_json(staged, receipt)
                        staged.replace(disk_path)
                except OSError:
                    pass
            self._summon[key] = result
        return self._summon[key]

    def for_cards(self, codes):
        keys = sorted({str(code) for code in codes}, key=int)
        missing = [key for key in keys if key not in self._cards]
        if missing:
            binding = dict(self.binding, cards=keys)
            path = self.directory / (digest(binding) + ".json")
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                cards = cached["registrations"]
                if (cached["binding"] != binding or sorted(cards, key=int) != keys
                        or cached["registrations_sha256"] != digest(cards)):
                    raise ValueError("registration receipt differs from its binding")
            except (OSError, KeyError, TypeError, ValueError):
                captured = collect_native_registrations(self.assets, tuple(map(int, missing)), self.directory)
                cards = {key: (captured if key in captured else self._cards)[key] for key in keys}
                receipt = dict(binding=binding, registrations=cards, registrations_sha256=digest(cards))
                try:
                    self.directory.mkdir(parents=True, exist_ok=True)
                    with TemporaryDirectory(dir=self.directory, prefix="registration-write-") as scratch:
                        staged = Path(scratch) / path.name
                        write_json(staged, receipt)
                        staged.replace(path)
                except OSError:
                    pass
            self._cards.update(cards)
        return {int(key): self._cards[key] for key in keys}

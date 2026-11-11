"""v3-only observation adapter. Runtime and preparation share the same builder."""
from dataclasses import replace
from pathlib import Path
import sqlite3

from ygo_kito.multifactor.contracts import AnalysisContext, CandidateInsert, DeckSpec, FunctionSeed, GRAPH_VERSION, StructureLink, UnitSpec, FactorContractError, Factors, RoleInput, digest
from ygo_kito.multifactor.semantics import build_analysis_graph
from ygo_kito.multifactor.axis_candidates import AxisCandidate


class Features:
    def __init__(self,config):
        if config.get("feature_schema")!=GRAPH_VERSION:
            raise FactorContractError("features_graph accepts only explicit axis-graph-v3 observations")
        self.feature_schema=GRAPH_VERSION
        self.rows={}
        self.digest=config.get("recorded_catalog_sha256", "")
        if config.get("catalog"):
            con=sqlite3.connect(Path(config["catalog"]).resolve().as_uri()+"?mode=ro",uri=True)
            con.row_factory=sqlite3.Row
            try:
                self.rows={r["id"]:dict(r) for r in con.execute("select d.*,t.name,t.desc from datas d join texts t on d.id=t.id order by d.id")}
            finally:
                con.close()

    def make(self,case,main=None,extra=None,*,variant=None,removed=None):
        if self.feature_schema!=GRAPH_VERSION or variant not in (None,"complete"):
            raise FactorContractError("v3 requires actual changed observations, never legacy variant rules")
        return self.make_graph_v3(case,main,extra,removed=removed)

    def make_graph_v3(self, case, main=None, extra=None, *, removed=None):
        """Read the observation whitelist before any legacy plan/label access."""
        mode = case.get("analysis_mode", "deck_analysis")
        if "deck" in case:
            raw = case["deck"]
            deck = raw if isinstance(raw, DeckSpec) else None if raw is None else DeckSpec.from_dict(raw)
        elif any(k in case for k in ("main", "extra", "side")):
            deck = DeckSpec(*(None if case.get(s) is None else tuple(tuple(p) for p in case[s]) for s in ("main", "extra", "side")))
        else:
            deck = None
        if main is not None or extra is not None:
            deck = deck or DeckSpec()
            deck = replace(deck, **{s: tuple(sorted(value.items())) for s, value in (("main", main), ("extra", extra)) if value is not None})
        if removed is not None:
            if deck is None:
                raise FactorContractError("v3 removal requires a real observed deck")
            for section in ("main", "extra", "side"):
                current = getattr(deck, section)
                if current is not None and dict(current).get(removed, 0):
                    stock = dict(current)
                    stock[removed] -= 1
                    deck = replace(deck, **{section: tuple(sorted((c, n) for c, n in stock.items() if n))})
                    break
            else:
                raise FactorContractError("v3 removal names an unavailable copy")
        unit_definition = case.get("unit_definition")
        if unit_definition is not None and not isinstance(unit_definition, UnitSpec):
            unit_definition = UnitSpec.from_dict(unit_definition)
        context = case.get("analysis_context", AnalysisContext())
        if not isinstance(context, AnalysisContext):
            context = AnalysisContext.from_dict(context)
        insertion = case.get("insertion")
        if insertion is not None and not isinstance(insertion, CandidateInsert):
            insertion = CandidateInsert.from_dict(insertion)
        state = case.get("visible_state")
        if state is not None:
            state = tuple(sorted(state.items())) if isinstance(state, dict) else tuple(tuple(v) for v in state)
        example = RoleInput(case.get("context_ref", "axis-v3-observations"), Factors("context"), (), analysis_mode=mode,
                            analysis_context=context, deck=deck, unit_definition=unit_definition,
                            visible_state=state, insertion=insertion)
        return self.graph(example, case)

    def graph(self, base, case, construction=None):
        if base.analysis_mode is None:
            raise FactorContractError("legacy graph generation is retired")
        # The runtime builder never imports this module or the aggregate class.
        structure_links = tuple(v if isinstance(v, StructureLink) else StructureLink.from_dict(v)
                                for v in case.get("structure_links", ()))
        seeds = tuple(v if isinstance(v, FunctionSeed) else FunctionSeed.from_dict(v) for v in case.get("function_seeds", ()))
        from ygo_kito.multifactor.functional_units import FunctionalContract
        contracts = tuple(v if isinstance(v, FunctionalContract) else FunctionalContract.from_dict(v)
                          for v in case.get("functional_contracts", ()))
        return build_analysis_graph(base, card_rows=self.rows, catalog_digest=self.digest,
            structure_links=structure_links, function_seeds=seeds, unit_contracts=contracts,
            source_ref="configured_catalog_facts")

def training_candidate_view(build, injected=()):
    """Training-only positive query support; markers stay outside observations.

    An injected support set must use a function query already present in input
    facts. Its function, conditions, mode and confidence come from that query,
    never from gold metadata. Natural candidate recall is reported separately.
    """
    if not isinstance(injected, tuple) or any(not isinstance(v, AxisCandidate) for v in injected):
        raise FactorContractError("typed injected training candidates required")
    natural = build.candidates.units + build.candidates.candidates
    by_query = {}
    for value in natural:
        by_query.setdefault(value.function_ref, []).append(value)
    observed_refs = {n.ref for n in build.graph.nodes if n.kind == "card"}
    queries = {v.candidate_id: v for v in natural}
    natural_ids = set(queries)
    added = []
    for candidate in injected:
        if any(ref not in observed_refs for ref, _ in candidate.members):
            raise FactorContractError("injected support must refer to observed graph members")
        eligible = by_query.get(candidate.function_ref, ())
        if not eligible:
            raise FactorContractError("injected query function must come from observations")
        # A query can have several printed modes/condition scopes. Caller must
        # identify an existing scope; gold data cannot invent a new one.
        choices = [v for v in eligible if v.mode_choices == candidate.mode_choices and
                   tuple(sorted(digest(c.to_dict()) for c in v.conditions)) == tuple(sorted(digest(c.to_dict()) for c in candidate.conditions))]
        if not choices:
            raise FactorContractError("injected query conditions/mode not present in observations")
        source = choices[0]
        value = replace(candidate, functions=source.functions, conditions=source.conditions,
                        mode_choices=source.mode_choices, confidence=source.confidence,
                        evidence_refs=source.evidence_refs, parent_ids=(), used_links=())
        if value.candidate_id not in queries:
            queries[value.candidate_id] = value
            added.append(value.candidate_id)
    return dict(observations=dict(graph=build.graph.to_dict(), queries=[queries[k].to_dict() for k in sorted(queries)]),
                provenance=dict(natural_query_ids=sorted(natural_ids), injected_query_ids=sorted(added),
                                natural_candidate_overflow=build.candidates.overflow))

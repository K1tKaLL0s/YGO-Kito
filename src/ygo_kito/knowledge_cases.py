"""Real, versioned private-knowledge fixtures, never user decks or learned play."""
import json
from pathlib import Path

from .protocol_cases import run_configured_case
from .validation import ContractError

CASES_PATH=Path(__file__).resolve().parents[2]/'configs/private-knowledge-engineering-v5.json'
REQUIRED={'crescent-private':(26,15),'rescue-confirmed':(15,),'facedown-xyz':(15,),'facedown-destroy':(15,)}


def read_case(name):
    if name not in REQUIRED:raise ContractError('unknown private-knowledge engineering case')
    return json.loads(CASES_PATH.read_text())['cases'][name]


def run_knowledge_case(root,name,**kwargs):
    return run_configured_case(root,name,read_case(name),REQUIRED[name],**kwargs)

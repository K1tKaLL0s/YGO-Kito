"""Frozen engineering-only curricula; no user deck or competitive opponent."""
import json
from pathlib import Path

from .protocol_cases import EngineeringDriver, run_configured_case
from .validation import ContractError

CASES_PATH=Path(__file__).resolve().parents[2]/'configs/private-selection-engineering-v4.json'
REQUIRED={'chosen-blind':(15,),'mixed-teleport':(15,),'control-swap':(15,),
          'flip-summon':(11,),'large-declaration':(142,),'large-packed-sum':(23,)}


def read_case(name):
    if name not in REQUIRED:raise ContractError('unknown private-selection engineering case')
    return json.loads(CASES_PATH.read_text())['cases'][name]


def run_private_case(root,name,**kwargs):
    return run_configured_case(root,name,read_case(name),REQUIRED[name],**kwargs)


def prompt_curriculum(name,profile,catalog):
    if name!='large-declaration':raise ContractError('unsupported controlled prompt curriculum')
    case=read_case(name)
    if profile!=case['profile']:raise ContractError('prompt curriculum profile/version binding differs')
    return EngineeringDriver(case,catalog,'first'),(142,)

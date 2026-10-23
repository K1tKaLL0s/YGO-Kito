"""Exact, trainable hierarchical sampling over ALL offered legal actions.

Neural scoring uses bounded pages; branch probabilities are learned leaf mass
(logsumexp), so path probability equals the global softmax. No rule heuristic,
shortlist, synthetic engine action, or untrained gating network is substituted.
"""
from dataclasses import replace
import math

import torch
from torch.distributions import Categorical
from torch.nn.functional import pad

from .validation import ContractError

POLICY_VERSION='exact-leaf-mass-hierarchy-v1'
MAX_LEAVES=50000


def score_requests(model,encoder,requests):
    if not requests or any(not 0<len(r.actions)<=MAX_LEAVES for r in requests):
        raise ContractError('hierarchical policy requires 1..50000 complete legal actions')
    cap=encoder.config.max_actions
    if all(len(r.actions)<=cap for r in requests):
        return model(encoder.batch(requests))
    rows,values=[],[]
    for req in requests:
        pieces=[];value=None
        for start in range(0,len(req.actions),cap):
            page=replace(req,actions=req.actions[start:start+cap])
            logits,v=model(encoder.batch([page]))
            pieces.append(logits[0]);value=v[0] if value is None else value
        rows.append(torch.cat(pieces));values.append(value)
    size=max(len(r) for r in rows)
    return torch.stack([pad(r,(0,size-len(r)),value=torch.finfo(r.dtype).min) for r in rows]),torch.stack(values)


def sample_index(logits,*,generator,max_actions):
    if logits.ndim!=1 or not 0<len(logits)<=MAX_LEAVES or not torch.isfinite(logits).all():
        raise ContractError('invalid complete hierarchical logits')
    if len(logits)<=max_actions:
        dist=Categorical(logits=logits)
        index=int(torch.multinomial(dist.probs,1,generator=generator))
        return index,{'version':POLICY_VERSION,'leaf_count':len(logits),'path':[],
                      'path_log_prob':float(dist.log_prob(torch.tensor(index)))}
    fanout=min(128,max_actions)
    if fanout<2:raise ContractError('hierarchy requires at least two branches')
    start,end=0,len(logits);path=[];total=logits.new_zeros(())
    while end-start>fanout:
        width=math.ceil((end-start)/fanout)
        groups=[(i,min(i+width,end)) for i in range(start,end,width)]
        branch=Categorical(logits=torch.stack([torch.logsumexp(logits[a:b],dim=0) for a,b in groups]))
        chosen=int(torch.multinomial(branch.probs,1,generator=generator))
        total=total+branch.log_prob(torch.tensor(chosen))
        path.append({'branches':len(groups),'chosen':chosen})
        start,end=groups[chosen]
    leaf=Categorical(logits=logits[start:end])
    chosen=int(torch.multinomial(leaf.probs,1,generator=generator))
    total=total+leaf.log_prob(torch.tensor(chosen));index=start+chosen
    path.append({'branches':end-start,'chosen':chosen})
    exact=Categorical(logits=logits).log_prob(torch.tensor(index))
    if not torch.allclose(total,exact,atol=3e-5,rtol=1e-6):
        raise ContractError('hierarchical path probability diverged from complete leaf distribution')
    return index,{'version':POLICY_VERSION,'leaf_count':len(logits),'path':path,'path_log_prob':float(total.detach())}

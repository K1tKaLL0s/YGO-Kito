"""Future-only declared prerequisite benefits, with no outcome-based metric choice."""
import argparse,hashlib,json,re
from pathlib import Path
import audit_model_auxiliary_v1_1 as base

VERSION='actual-declared-goal-auxiliary-v2'

def prerequisites(task):
    route=task['goal'].get('route_goal',{})
    witness=route.get('fusion_witness',{})
    return tuple((r['card_id'],z) for r in witness.get('effect_assessments',())
                 for z in witness.get('required_source_zones',()))

def benefits(task,events,actor):
    required=set(task['goal'].get('required_chain_resolutions',()))
    requested=set(prerequisites(task));links={};blocked=set();pending={};resolving=None;found=[]
    for index,event in enumerate(events):
        kind=event['kind']
        if kind==70:links[event['link']]=(event['player'],event.get('public_card'),index)
        elif kind==72:resolving=event['link']
        elif kind in (75,76):blocked.add(event['link'])
        elif kind==50 and resolving in links:
            player,card,start=links[resolving]
            if (player==actor and card in required and event.get('player')==actor
                    and (event.get('public_card'),event.get('to_zone')) in requested
                    and event.get('reason',0)&0x40):
                pending.setdefault(resolving,[]).append({'move_event_index':index,'move':event,
                    'resolving_link':resolving,'required_effect_card':card,'chaining_event_index':start})
        elif kind==73:
            if event['link'] not in blocked:
                for row in pending.pop(event['link'],[]):found.append(dict(row,solved_event_index=index))
            if resolving==event['link']:resolving=None
        elif kind==74:links.clear();blocked.clear();pending.clear();resolving=None
    return found,bool(required)

def main():
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--task',type=Path,required=True)
    parser.add_argument('--metric-plan',type=Path,required=True);parser.add_argument('--comparison',type=Path,required=True)
    args,_=parser.parse_known_args();task=base.read(args.task);task=task.get('task',task);plan=base.read(args.metric_plan)
    match=re.fullmatch(r'collaboration-(\d+)',args.comparison.parent.name)
    if (plan['version']!=VERSION or not match or int(match[1])<plan['minimum_complete_formal_matches_before_comparison']):
        raise ValueError('This prerequisite metric is registered for future comparisons from match32, not retroactive selection')
    extra=tuple(name for card,zone in prerequisites(task) for name in
                (f'goal_effect_card_{card}_available_zone_{zone}',f'first_actor_turn_goal_effect_card_{card}_available_zone_{zone}'))
    original=base.evaluate_game
    def evaluate(task,trace,episode,actor):
        result=original(task,trace,episode,actor);rows,attributable=benefits(task,trace['events'],actor)
        cutoff=result.get('first_actor_turn_cutoff_event',len(trace['events'])-1)
        for card,zone in prerequisites(task):
            hits=[r for r in rows if r['move']['public_card']==card and r['move']['to_zone']==zone]
            result['metrics'][f'goal_effect_card_{card}_available_zone_{zone}']=int(bool(hits)) if attributable else None
            result['metrics'][f'first_actor_turn_goal_effect_card_{card}_available_zone_{zone}']=int(any(r['solved_event_index']<=cutoff for r in hits)) if attributable else None
        result['actual_declared_prerequisite_benefits']=rows
        result['activation_or_resolution_without_observed_benefit_is_not_quality']=True
        return result
    base.VERSION=VERSION;base.SOURCE='actual_public_engine_paired_auxiliary_v2';base.METRICS=(*base.METRICS,*extra)
    base.evaluate_game=evaluate;base.main()
if __name__=='__main__':main()

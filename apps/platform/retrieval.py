"""Conservative rules over reviewed events, with explicit uncertainty."""
import re
import uuid
from copy import deepcopy


def merge_segments(segments):
    """Merge transitive same-asset overlaps without losing event references.

    This operates on candidate clips before timeline edits.  The earliest
    selected segment supplies display settings and the merged position.
    Input dictionaries are left untouched.
    """
    merged = []
    for original in segments:
        segment = deepcopy(original)
        # Repeated passes are necessary when extending one component makes
        # another previously separate interval overlap it.
        indices = set()
        while True:
            more = {index for index, prior in enumerate(merged)
                    if index not in indices and prior['asset_id'] == segment['asset_id']
                    and prior['in_ms'] <= segment['out_ms']
                    and segment['in_ms'] <= prior['out_ms']}
            if not more:
                break
            indices.update(more)
            segment['in_ms'] = min(segment['in_ms'], *(merged[i]['in_ms'] for i in more))
            segment['out_ms'] = max(segment['out_ms'], *(merged[i]['out_ms'] for i in more))
        if indices:
            ordered = [merged[i] for i in sorted(indices)] + [segment]
            combined = deepcopy(ordered[0])
            combined['in_ms'], combined['out_ms'] = segment['in_ms'], segment['out_ms']
            combined['event_ids'] = list(dict.fromkeys(event_id for item in ordered for event_id in item.get('event_ids', [])))
            position = min(indices)
            merged = [item for index, item in enumerate(merged) if index not in indices]
            merged.insert(position, combined)
        else:
            segment['event_ids'] = list(dict.fromkeys(segment.get('event_ids', [])))
            merged.append(segment)
    return merged


WORDS = {'展搓':('stroke','hand_technique','net_zhan_cuo'), '收搓':('stroke','hand_technique','net_shou_cuo'),
         '后退小跳':('movement','footwork','backward_small_hop_start'), '交叉步':('movement','footwork','crossover_step'),
         '后退':('movement','direction','backward'), '起跳杀球':('stroke','stroke','jump_smash'),
         '杀球':('stroke','stroke','smash'), '网前':('stroke','stroke','net_shot'), '扑球':('stroke','stroke','net_kill'),
         '弓步':('movement','footwork','lunge')}


def parse_rules(text, player_id=None):
    if any(word in text for word in ('不要','排除','不含','不是','不做','非','除了')):
        raise ValueError('规则解析暂不支持否定或排除语义，请编辑QuerySpec或使用LLM后复核')
    steps = []
    for phrase in re.split(r'随后|然后|接着|再|→|，|,', text):
        labels, kind = {}, None
        for word, (k,key,value) in WORDS.items():
            if word in phrase and key not in labels:
                if kind is not None and kind != k:
                    raise ValueError('同一短语包含击球和移动，请用“随后”拆成明确步骤或编辑QuerySpec关系')
                labels[key], kind = value, kind or k
        if labels:
            steps.append({'step_id':f's{len(steps)+1}', 'kind':kind, 'labels':labels})
    if not steps:
        raise ValueError('没有识别到明确动作，请编辑结构化条件；当前支持网前、杀球、展搓/收搓、后退小跳等词。')
    return {'schema_version':'1.0','query_id':str(uuid.uuid4()),'text':text,'player_id':player_id or None,
            'scope':{},'steps':steps,'relations':[{'from_step':a['step_id'],'to_step':b['step_id'],'relation':'before',
              'max_gap_ms':10000,'same_player':True,'same_rally':True} for a,b in zip(steps,steps[1:])], 'include_uncertain':False}


def search(query, events, assets):
    assets_by_id = {a['asset_id']:a for a in assets}
    scope = query.get('scope',{})
    filtered = []
    for event in events:
        a = assets_by_id.get(event['asset_id'])
        if not a or event['review_status'] == 'rejected':
            continue
        if not query['include_uncertain'] and event['review_status'] != 'confirmed':
            continue
        if query.get('player_id') and event.get('player_id') != query['player_id']:
            continue
        if any(scope.get(key) and value not in scope[key] for key,value in (
                ('asset_ids',a['asset_id']),('match_ids',a['match_id']),('library_ids',a.get('library_id')),('source_types',a['source_type']))):
            continue
        filtered.append(event)
    filtered.sort(key=lambda e:(e['asset_id'],e['start_ms'],e['end_ms'],e['event_id']))
    choices = []
    for step in query['steps']:
        matches = []
        for event in filtered:
            if step.get('kind') and event['kind'] != step['kind']:
                continue
            missing = []
            for key,value in step['labels'].items():
                actual = event['labels'].get(key)
                if actual == value:
                    continue
                if actual in (None,'unknown') and query['include_uncertain']:
                    missing.append(f"{step['step_id']}.{key}={value}")
                else:
                    break
            else:
                matches.append((event,missing))
        choices.append(matches)
    results = []

    def compatible(selected):
        by_step = {s['step_id']:item[0] for s,item in zip(query['steps'],selected)}
        if len({e['event_id'] for e in by_step.values()}) != len(by_step):
            return False
        if len({e['asset_id'] for e in by_step.values()}) > 1:
            return False
        for rel in query['relations']:
            a,b = by_step.get(rel['from_step']),by_step.get(rel['to_step'])
            if a is None or b is None:
                continue
            if rel.get('same_player') and (not a.get('player_id') or a['player_id'] != b.get('player_id')):
                return False
            if rel.get('same_rally') and (not a.get('rally_id') or a['rally_id'] != b.get('rally_id')):
                return False
            gap = max(0,b['start_ms']-a['end_ms'],a['start_ms']-b['end_ms'])
            if rel['relation'] == 'before' and a['end_ms'] > b['start_ms']:
                return False
            if rel['relation'] == 'overlaps' and max(a['start_ms'],b['start_ms']) >= min(a['end_ms'],b['end_ms']):
                return False
            if rel.get('max_gap_ms') is not None and gap > rel['max_gap_ms']:
                return False
        return True

    def visit(selected):
        if len(results) >= 500:
            return
        if len(selected) < len(choices):
            for item in choices[len(selected)]:
                if compatible(selected+[item]):
                    visit(selected+[item])
            return
        matched = [x[0] for x in selected]
        missing = [m for x in selected for m in x[1]]
        uncertainty = [e.get('unknown_reason') or '尚未确认或可见性不足' for e in matched if e.get('unknown_reason') or e['review_status'] != 'confirmed' or e['visibility'] == 'insufficient']
        if any(e.get('reviewer_type')=='agent' for e in matched):
            uncertainty.append('含Agent审阅记录，尚不能作为人类确认技术真值')
        uncertainty=list(dict.fromkeys(uncertainty))
        if missing:
            uncertainty.append('部分标签未知，不能判定符合或不符合')
        results.append({'schema_version':'1.0','candidate_id':str(uuid.uuid4()),'asset_id':matched[0]['asset_id'],
            'start_ms':min(e['start_ms'] for e in matched),'end_ms':max(e['end_ms'] for e in matched),
            'player_id':matched[0].get('player_id'), 'event_ids':[e['event_id'] for e in matched],
            'matched_conditions':[s for s in query['steps'] if not any(m.startswith(s['step_id']+'.') for m in missing)],
            'missing_conditions':missing,'uncertainty_reasons':uncertainty,'rank_score':1/(1+len(missing)+len(uncertainty)),
            'review_status':'unreviewed','evidence':[{'type':'source_interval','event_id':e['event_id'],'asset_id':e['asset_id'],'start_ms':e['start_ms'],'end_ms':e['end_ms']} for e in matched]})
    if choices and all(choices):
        visit([])
    return sorted(results,key=lambda c:-c['rank_score'])

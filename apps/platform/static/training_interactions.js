(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TrainingInteractions = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const copy = value => JSON.parse(JSON.stringify(value));
  const roles = ['self', 'opponent', 'partner', 'opponent_partner'];
  const pending = actor => ({status: 'pending', reviewer_type: actor, reviewer: 'local-' + actor, note: ''});
  function ms(value, duration, endpoint = false) {
    if (!Number.isInteger(value) || value < 0 || (endpoint ? value > duration : value >= duration)) throw new Error('时间必须是原片范围内的整数毫秒');
  }
  function validateTiming(records, duration) {
    const live = records.filter(r => !r.deleted), byId = new Map(live.map(r => [r.record_id, r]));
    for (const r of live) {
      if (['rally', 'segment'].includes(r.kind)) {
        ms(r.start_ms, duration); ms(r.end_ms, duration, true);
        if (r.end_ms <= r.start_ms) throw new Error('区间结束必须晚于开始');
      } else ms(r.at_ms, duration, r.kind === 'dead_ball');
      if (r.uncertainty_start_ms != null || r.uncertainty_end_ms != null) {
        ms(r.uncertainty_start_ms, duration, true); ms(r.uncertainty_end_ms, duration, true);
        if (!(r.uncertainty_start_ms <= r.at_ms && r.at_ms <= r.uncertainty_end_ms)) throw new Error('修改后的时刻超出了不确定范围，请先调整范围');
      }
      if (r.rally_id) {
        const rally = byId.get(r.rally_id);
        if (!rally || rally.kind !== 'rally') throw new Error('关联回合不存在');
        const start = r.at_ms ?? r.start_ms, end = r.at_ms ?? r.end_ms;
        if (start < rally.start_ms || end > rally.end_ms || (r.at_ms != null && r.kind !== 'dead_ball' && start >= rally.end_ms)) throw new Error('此修改会超出回合，或裁掉已关联的记录');
        if (r.kind === 'dead_ball' && r.at_ms !== rally.end_ms) throw new Error('死球时刻须与关联回合终点一致');
      }
      if (r.kind === 'rally' && r.dead_ball_id) {
        const dead = byId.get(r.dead_ball_id);
        if (!dead || dead.kind !== 'dead_ball' || dead.rally_id !== r.record_id || dead.at_ms !== r.end_ms) throw new Error('独立死球标记与回合不一致');
      }
      for (const e of r.evidence || []) if (e.type === 'image_region') {
        ms(e.at_ms, duration);
        if (r.at_ms != null ? e.at_ms !== r.at_ms : (e.at_ms < r.start_ms || e.at_ms >= r.end_ms)) throw new Error('画面区域仍绑定原取证时刻；请先处理该区域再移动时间边界');
      }
    }
    return records;
  }
  function retimeRecords(bundle, recordId, patch, actor) {
    const records = copy(bundle.records), record = records.find(r => r.record_id === recordId && !r.deleted);
    if (!record) throw new Error('记录已切换或被删除');
    const interval = ['rally', 'segment'].includes(record.kind), keys = Object.keys(patch);
    if (!keys.length || keys.some(k => !(interval ? ['start_ms', 'end_ms'] : ['at_ms']).includes(k))) throw new Error('不支持的时间修改');
    Object.assign(record, patch); record.review = pending(actor);
    if (record.kind === 'rally' && record.dead_ball_id) {
      const dead = records.find(r => r.record_id === record.dead_ball_id && !r.deleted);
      if (!dead) throw new Error('回合死球记录缺失');
      dead.at_ms = record.end_ms; dead.review = pending(actor);
    }
    if (record.kind === 'dead_ball' && record.rally_id) {
      const rally = records.find(r => r.record_id === record.rally_id && !r.deleted);
      if (!rally) throw new Error('关联回合缺失');
      rally.end_ms = record.at_ms; rally.review = pending(actor);
    }
    return validateTiming(records, bundle.asset.duration_ms);
  }
  function subjectPerson(record, role) { return record.state?.[role]?.person_id || (role === 'self' ? record.person_id : null) || null; }
  function validateSubjects(record, people) {
    const resolved = roles.map(role => {
      const id = subjectPerson(record, role), person = people.find(p => p.person_id === id);
      const team = record.state?.[role]?.team_id || (role === 'self' ? record.team_id : null) || person?.team_id || null;
      if (id && !person) throw new Error('主体人物尚未登记');
      if (id && team && person.team_id !== team) throw new Error('角色人物与登记队伍不一致');
      return {role, id, team, side: ['self','partner'].includes(role) ? 'near' : 'far'};
    });
    for (let i = 0; i < resolved.length; i++) for (let j = i + 1; j < resolved.length; j++) {
      const a = resolved[i], b = resolved[j];
      if (a.id && a.id === b.id) throw new Error('同一人物不能同时占用本人、对手或搭档等多个角色');
      if (a.team && b.team && ((a.side === b.side) !== (a.team === b.team))) throw new Error('双方或搭档的已知队伍关系不一致');
    }
  }
  function assignSubject(record, people, subject) {
    const role = subject.subject_role || 'self', id = subject.subject_person_id || null;
    if (!roles.includes(role)) throw new Error('未知判断角色');
    const person = id ? people.find(p => p.person_id === id) : null;
    if (id && !person) throw new Error('请先手动登记主体人物');
    const existing = subjectPerson(record, role);
    if (existing && id !== existing) throw new Error('投放人物与记录该角色不一致，请选择一致的主体或新建记录');
    if (!existing && id && record.judgements?.some(j => (j.subject_role || 'self') === role)) throw new Error('该角色已有身份未知判断，请先在表单明确人物后再投放');
    if (role === 'self') { record.person_id = id; record.team_id = person?.team_id || null; }
    if (role !== 'self' || record.state?.self) {
      record.state ||= {};
      record.state[role] = {...(record.state[role] || {position: null, missing_reasons: []}), person_id: id, team_id: person?.team_id || null};
    }
    validateSubjects(record, people);
    return {role, id};
  }
  function addLabel(bundle, taxonomy, labelId, target, subject, actor, makeId) {
    const label = taxonomy.labels.find(l => l.label_id === labelId && l.selectable !== false);
    if (!label) throw new Error('只能投放当前词表的可选标签，目录分组不能作为标签');
    const result = copy(bundle), duration = bundle.asset.duration_ms;
    let record = result.records.find(r => r.record_id === target.record_id && !r.deleted);
    if (target.record_id && !record) throw new Error('投放目标已删除或不存在');
    if (!record) {
      ms(target.at_ms, duration);
      const kind = label.kinds.includes('segment') ? 'segment' : label.kinds.includes('state') ? 'state' : label.kinds.includes('contact') ? 'contact' : null;
      if (!kind) throw new Error('此标签需要先创建对应类型的记录');
      const rally = result.records.find(r => !r.deleted && r.kind === 'rally' && r.start_ms <= target.at_ms && target.at_ms < r.end_ms);
      record = {record_id: makeId(), project_id: bundle.project_id, asset_id: bundle.asset.asset_id, kind,
        person_id: null, team_id: null, rally_id: rally?.record_id || null, judgements: [], visibility: 'unknown', unknown_reasons: [],
        review: pending(actor), revision: 1, previous_revision: null, deleted: false,
        provenance: {ui: 'training-workbench', title: label.name + ' · 拖入待审'}, evidence: []};
      if (kind === 'segment') {
        record.start_ms = target.at_ms; record.end_ms = Math.min(target.at_ms + 1000, rally?.end_ms || duration);
        record.segment_type = label.dimension === 'footwork' ? 'footwork' : /pattern|tactic|interpretation/.test(label.dimension) ? 'tactic' : 'stroke';
      } else { record.at_ms = target.at_ms; if (kind === 'state') record.state = {}; }
      result.records.push(record);
    }
    if (!label.kinds.includes(record.kind)) throw new Error('此标签不适用于该记录类型，请拖到时间线空白处或合适记录');
    const {role, id} = assignSubject(record, result.people, subject);
    const duplicate = record.judgements.some(j => j.label_id === labelId && (j.subject_role || 'self') === role && (j.subject_person_id || subjectPerson(record, role)) === id);
    if (duplicate) return {bundle, record_id: record.record_id, added: false};
    record.judgements.push({label_id: labelId, value: 'unknown', reason: '拖入候选，尚未判断是否存在', subject_role: role, subject_person_id: id, mapping_status: 'manual'});
    record.review = pending(actor);
    validateTiming(result.records, duration);
    return {bundle: result, record_id: record.record_id, added: true};
  }
  return {validateTiming, retimeRecords, addLabel, assignSubject, validateSubjects};
});

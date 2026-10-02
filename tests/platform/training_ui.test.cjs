const test = require('node:test');
const assert = require('node:assert/strict');
const ui = require('../../apps/platform/static/training.js');

test('time validation preserves original milliseconds and rejects invalid bounds', () => {
  assert.equal(ui.sourceMs(1000.4, 3000), 1000);
  assert.equal(ui.formatTime(62543), '01:02.543');
  for (const value of [-1, 3001, Infinity, 'bad']) assert.throws(() => ui.sourceMs(value, 3000), /原片时间/);
});
test('image-normalized points use actual letterboxed image, excluding borders', () => {
  const rect = {left: 100, top: 50, width: 400, height: 400};
  assert.equal(ui.imagePoint(200, 60, rect, 1920, 1080), null);
  assert.deepEqual(ui.imagePoint(300, 250, rect, 1920, 1080), {x: .5, y: .5});
  assert.deepEqual(ui.imagePoint(100, 137.5, rect, 1920, 1080), {x: 0, y: 0});
  assert.equal(ui.imagePoint(300, 250, rect, 0, 0), null);
});
test('annotation shortcuts never steal typing, input arrows, composition or native button space', () => {
  for (const tagName of ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'A']) for (const key of ['r', 'ArrowLeft', ' ', 's']) {
    assert.equal(ui.shortcut({target: {tagName}, key, ctrlKey: key === 's'}), null);
  }
  assert.equal(ui.shortcut({target: {isContentEditable: true}, key: 'c'}), null);
  assert.equal(ui.shortcut({target: {}, key: 'c', isComposing: true}), null);
  assert.equal(ui.shortcut({target: {}, key: 'C'}), 'contact');
  assert.equal(ui.shortcut({target: {}, key: 's', metaKey: true}), 'save');
});
test('HTTP 409 retains structured error for conflict recovery instead of success', async () => {
  const request = ui.makeRequest(async () => ({ok: false, status: 409, json: async () => ({detail: 'revision conflict'})}));
  await assert.rejects(request('/projects/p/bundles/a', 'PUT', {}), error => error.status === 409 && /conflict/.test(error.message));
});

const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return {promise, resolve, reject}; };
function fixture(options = {}) {
  const calls = [], project = {project_id: 'project-1', name: '测试项目', revision: 1, taxonomy_version: 'fixture'};
  const assets = ['asset-a', 'asset-b'].map(asset_id => ({asset_id, duration_ms: 3000, title: asset_id, sha256: asset_id, media_url: '/media/' + asset_id}));
  const seed = id => ({format: 'badmintontv.training.annotations.v1', schema_version: '1.0', project_id: project.project_id, asset: assets.find(a => a.asset_id === id), revision: 0, people: [], records: []});
  const request = async (path, method = 'GET', body) => {
    calls.push({path, method, body: body && ui.clone(body)});
    const custom = options.respond?.(path, method, body); if (custom !== undefined) return custom;
    if (path === '/projects') return [project];
    if (path === '/catalog') return {assets};
    if (path === '/assets') return assets;
    if (path === '/projects/project-1') return {project, assets, actor_type: options.actor || 'agent', splits: [], taxonomy: {labels: []}};
    if (path.endsWith('/snapshots')) return method === 'POST' ? {snapshot_id: 'snap-1'} : [];
    if (path.includes('/source-frames')) return {source_frames: [{source_frame_index: 0, source_pts: 0, source_pts_ms: 0, source_end_ms: 1000}], total: 3};
    if (path.includes('/bundles/')) return method === 'PUT' ? {...body.bundle, revision: body.expected_revision + 1} : seed(path.split('/').at(-1));
    throw new Error('Unexpected ' + path);
  };
  const controller = ui.createController({request, confirm: options.confirm || (() => true)});
  return {controller, calls, seed, assets, project};
}
async function open(f) { await f.controller.boot(); await f.controller.openProject('project-1'); await f.controller.openAsset('asset-a'); return f.controller; }

test('slow A response cannot replace selected B or make a later save target A', async () => {
  const late = deferred(); let slow = true;
  const f = fixture({respond: (path, method) => path.endsWith('/bundles/asset-a') && method === 'GET' && slow ? late.promise : undefined});
  const c = f.controller; await c.boot(); await c.openProject('project-1');
  const a = c.openAsset('asset-a'); await c.openAsset('asset-b');
  slow = false; late.resolve(f.seed('asset-a')); await a;
  assert.equal(c.state.asset.asset_id, 'asset-b'); assert.equal(c.state.bundle.asset.asset_id, 'asset-b');
  c.newRecord('contact', 1000); await c.save();
  assert.equal(f.calls.filter(call => call.method === 'PUT').at(-1).path, '/projects/project-1/bundles/asset-b');
});
test('409 keeps all local labels and coordinates, refuses silent revision adoption', async () => {
  const f = fixture({respond: (path, method) => method === 'PUT' ? Promise.reject(Object.assign(new Error('conflict'), {status: 409})) : undefined});
  const c = await open(f); c.newRecord('contact', 1234);
  c.modifyRecord(r => { r.judgements = [{label_id: 'footwork', value: 'unknown', reason: '脚部遮挡'}]; r.state = {opponent: {position: {coordinate_system: 'image_normalized', x: .2, y: .7, source: 'agent'}}}; });
  const draft = ui.clone(c.state.bundle);
  await assert.rejects(c.save(), /conflict/);
  assert.deepEqual(c.state.bundle, draft); assert.equal(c.state.saved.revision, 0);
  assert.equal(c.state.conflict, true); assert.equal(c.state.dirty, true); assert.equal(c.state.saving, false);
});
test('unsaved guard rejects asset/project navigation and does not start requests', async () => {
  const f = fixture({confirm: () => false}), c = await open(f); c.newRecord('contact', 1000);
  const before = f.calls.length;
  assert.equal(await c.openAsset('asset-b'), false); assert.equal(await c.openProject('project-2'), false);
  assert.equal(c.discard(), false); assert.equal(f.calls.length, before); assert.equal(c.state.asset.asset_id, 'asset-a');
});
test('first save uses CAS zero with a contract-valid revision one body', async () => {
  const f = fixture(), c = await open(f); c.newRecord('contact', 1000); await c.save();
  const put = f.calls.find(call => call.method === 'PUT'); assert.equal(put.body.expected_revision, 0); assert.equal(put.body.bundle.revision, 1);
  assert.equal(c.state.saved.revision, 1); assert.equal(c.state.dirty, false);
});
test('rally end creates a distinct dead-ball point in the same atomic bundle', async () => {
  const f = fixture(), c = await open(f), rally = c.newRecord('rally', 500);
  c.finishRally(2200); await c.save();
  const records = f.calls.find(call => call.method === 'PUT').body.bundle.records;
  const dead = records.find(r => r.kind === 'dead_ball');
  assert.equal(records.length, 2); assert.equal(dead.at_ms, 2200); assert.equal(dead.rally_id, rally.record_id);
  assert.equal(records[0].dead_ball_id, dead.record_id); assert.equal(records[0].end_ms, 2200);
  assert.notEqual(dead.record_id, rally.record_id); assert.equal(dead.start_ms, undefined);
});
test('agent cannot confirm human truth and ordinary edits invalidate previous review', async () => {
  const f = fixture(), c = await open(f); c.newRecord('contact', 1000);
  assert.throws(() => c.review('confirmed'), /不是 human/);
  c.record().review = {status: 'confirmed', reviewer_type: 'human', reviewer: 'old-reviewer'};
  c.modifyRecord(r => { r.at_ms = 1100; });
  assert.equal(c.record().review.status, 'pending'); assert.equal(c.record().review.reviewer_type, 'agent');
  await c.save(); assert.equal(f.calls.find(call => call.method === 'PUT').body.bundle.records[0].review.reviewer_type, 'agent');
});
test('editing while save awaits retains newer draft, next CAS uses successful saved revision', async () => {
  const pending = deferred(); let first = true;
  const f = fixture({respond: (path, method, body) => { if (method === 'PUT' && first) { first = false; return pending.promise; } }});
  const c = await open(f); c.newRecord('contact', 1000); const saving = c.save();
  c.modifyRecord(r => { r.at_ms = 1200; }); const firstPut = f.calls.find(call => call.method === 'PUT');
  pending.resolve({...firstPut.body.bundle, revision: 1}); await saving;
  assert.equal(c.record().at_ms, 1200); assert.equal(c.state.dirty, true); assert.equal(c.state.saved.records[0].at_ms, 1000);
  await c.save(); assert.equal(f.calls.filter(call => call.method === 'PUT')[1].body.expected_revision, 1);
});
test('late save response never replaces another asset bundle', async () => {
  const pending = deferred(); const f = fixture({respond: (path, method) => method === 'PUT' ? pending.promise : undefined});
  const c = await open(f); c.newRecord('contact', 1000); const saving = c.save();
  const put = f.calls.find(call => call.method === 'PUT'); await c.openAsset('asset-b');
  pending.resolve({...put.body.bundle, revision: 1}); await saving;
  assert.equal(c.state.bundle.asset.asset_id, 'asset-b'); assert.equal(c.state.bundle.revision, 0); assert.equal(c.state.dirty, false);
});
test('VFR step uses returned PTS instead of frame divided by fps', async () => {
  const f = fixture({respond: path => path.includes('at_ms=1000') ? {source_frames: [
    {source_frame_index: 30, source_pts: 90000, source_pts_ms: 1000},
    {source_frame_index: 31, source_pts: 96003, source_pts_ms: 1066.7}], total: 80} : undefined});
  const c = await open(f); const next = await c.step(1000, 1);
  assert.equal(next.source_frame_index, 31); assert.equal(next.source_pts_ms, 1066.7); assert.equal(next.exact, true);
  c.state.frames = null; assert.deepEqual(await c.step(1000, 1), {source_pts_ms: 1040, exact: false});
});
test('repeated fractional-PTS navigation uses source ordinal pages and never sends float at_ms', async () => {
  const f = fixture({respond: path => path.includes('offset_frame=32') ? {source_frames: [{source_frame_index: 32, source_pts: 102000, source_pts_ms: 1133.333}], total: 80} : undefined});
  const c = await open(f);
  const next = await c.step(1067, 1, {source_frame_index: 31, source_pts: 96003, source_pts_ms: 1066.7});
  assert.equal(next.source_frame_index, 32); assert.equal(next.source_pts_ms, 1133.333);
  assert.ok(f.calls.at(-1).path.includes('offset_frame=32')); assert.equal(f.calls.some(call => /at_ms=\d+\./.test(call.path)), false);
});
test('snapshot does not run when dirty bundle save conflicts', async () => {
  const f = fixture({respond: (path, method) => method === 'PUT' ? Promise.reject(Object.assign(new Error('conflict'), {status: 409})) : undefined});
  const c = await open(f); c.newRecord('contact', 1000); await assert.rejects(c.snapshot(), /conflict/);
  assert.equal(f.calls.some(call => call.path.endsWith('/snapshots') && call.method === 'POST'), false);
});
test('split drafts survive annotation rerenders and 409 without advancing project revision', async () => {
  const f = fixture({confirm: () => false, respond: (path, method) => path.endsWith('/splits') && method === 'PUT' ? Promise.reject(Object.assign(new Error('split conflict'), {status: 409})) : undefined});
  const c = await open(f); c.editSplit('match-1', 'test'); c.newRecord('contact', 1000);
  await c.refreshProject();
  assert.deepEqual(c.state.splitDraft, [{group_id: 'match-1', split: 'test'}]);
  await assert.rejects(c.saveSplits(ui.clone(c.state.splitDraft)), /split conflict/);
  assert.equal(c.state.splitDirty, true); assert.equal(c.state.project.revision, 1);
  assert.equal(await c.openProject('another-project'), false);
});
test('confirmed cascade delete retains rally and dead-ball tombstones', async () => {
  const f = fixture(), c = await open(f); c.newRecord('rally', 500); c.finishRally(2000);
  assert.throws(() => c.removeRecord(), /确认关联删除/); c.removeRecord(true);
  assert.equal(c.state.bundle.records.length, 2); assert.ok(c.state.bundle.records.every(r => r.deleted && r.review.reviewer_type === 'agent'));
});

class Element extends EventTarget {
  constructor(tagName = 'DIV') { super(); Object.assign(this, {tagName: tagName.toUpperCase(), value: '', textContent: '', children: [], dataset: {}, style: {}, hidden: false, disabled: false, classList: {toggle() {}}, currentTime: 0, paused: true, videoWidth: 1920, videoHeight: 1080}); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; this.textContent = ''; }
  get options() { return this.children; }
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
  closest() { return null; }
  querySelectorAll(selector) { return this.children.flatMap(child => [...(selector === 'select[data-group-id]' && child.tagName === 'SELECT' && child.dataset.groupId ? [child] : []), ...child.querySelectorAll(selector)]); }
  getBoundingClientRect() { return {left: 0, top: 0, width: 640, height: 360}; }
  pause() { this.paused = true; }
  play() { this.paused = false; return Promise.resolve(); }
  load() {}
  scrollIntoView() {}
}
const tick = () => new Promise(resolve => setImmediate(resolve));
test('mounted UI matches template, hides directory labels, and keeps four subjects separate', async () => {
  const fs = require('node:fs'), path = require('node:path');
  const html = fs.readFileSync(path.join(__dirname, '../../apps/platform/templates/training.html'), 'utf8');
  const elements = new Map([...html.matchAll(/<([a-z]+)[^>]*\bid="([^"]+)"[^>]*>/g)].map(match => [match[2], new Element(match[1])]));
  elements.get('label-subject-role').value = 'self';
  const doc = new EventTarget(); doc.getElementById = id => { assert.ok(elements.has(id), 'Missing template ID ' + id); return elements.get(id); }; doc.createElement = tag => new Element(tag);
  const f = fixture(); const taxonomy = {labels: [
    {label_id: 'directory', name: '动作目录', description: '只供导航', dimension: 'stroke', kinds: ['contact'], selectable: false},
    {label_id: 'stroke', name: '网前球', parent_id: 'directory', description: '测试定义：球在网前处理。\n所需证据：触球前后画面。\n易混项：挑球与扑球。', dimension: 'stroke', kinds: ['contact'], selectable: true} ]};
  const project = {project: f.project, assets: f.assets, taxonomy, actor_type: 'agent', splits: []};
  const win = new EventTarget(); Object.assign(win, {confirm: () => true, setTimeout, fetch: async url => ({ok: true, json: async () => {
    const p = url.replace('/api/v1/training', '');
    if (p === '/projects') return [f.project]; if (p === '/catalog') return {assets: []}; if (p === '/assets') return [];
    if (p === '/projects/project-1') return project; if (p.endsWith('/snapshots')) return [];
    if (p.includes('/bundles/')) return f.seed('asset-a'); if (p.includes('/source-frames')) return {source_frames: [], total: 3};
    throw Error(p);
  }})});
  const c = ui.mount(doc, win); await tick(); await c.openProject('project-1'); await c.openAsset('asset-a'); c.newRecord('contact', 1000);
  const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);
  assert.equal(descendants(elements.get('taxonomy-labels')).find(node => node.tagName === 'SUMMARY').textContent, '击球 · 2 项');
  let definition = descendants(elements.get('taxonomy-labels')).find(node => node.className === 'label-definition');
  assert.equal(definition.tagName, 'DETAILS'); assert.equal(definition.open, false, 'full guidance starts collapsed');
  assert.equal(definition.children[0].tagName, 'SUMMARY'); assert.equal(definition.children[0].textContent, '定义与判断依据');
  assert.equal(definition.children.find(node => node.className === 'definition').textContent, taxonomy.labels[1].description, 'full definition/evidence/confusion text remains verbatim');
  const labelRow = descendants(elements.get('taxonomy-labels')).find(node => node.className === 'label-row');
  assert.equal(descendants(labelRow).find(node => node.tagName === 'LABEL').textContent, '网前球', 'default label uses short name');
  assert.equal(descendants(labelRow).some(node => node.className === 'definition'), false);
  definition.open = true; assert.equal(definition.open, true, 'native details can be expanded without mutating annotations');
  assert.equal(c.record().judgements.length, 0);
  for (const query of ['触球前后画面', '挑球与扑球']) {
    elements.get('label-filter').value = query; elements.get('label-filter').dispatchEvent(new Event('input')); await tick();
    assert.equal(descendants(elements.get('taxonomy-labels')).filter(node => node.tagName === 'SELECT').length, 1, 'search still matches collapsed evidence/confusion text');
    definition = descendants(elements.get('taxonomy-labels')).find(node => node.className === 'label-definition');
    assert.equal(definition.open, false); assert.equal(definition.children.find(node => node.className === 'definition').textContent, taxonomy.labels[1].description);
  }
  elements.get('label-filter').value = ''; elements.get('label-filter').dispatchEvent(new Event('input')); await tick();
  c.edit(bundle => bundle.people.push({person_id: 'person-a', display_name: '匿名 A', identity_status: 'unconfirmed'}));
  const identity = descendants(elements.get('participant-list')).find(node => node.tagName === 'SELECT');
  assert.equal(identity.options.find(option => option.value === 'confirmed').disabled, true, 'agent may not confirm participant identity');
  let selects = descendants(elements.get('taxonomy-labels')).filter(node => node.tagName === 'SELECT');
  assert.equal(selects.length, 1, 'directory must not offer judgement control');
  selects[0].value = 'present'; selects[0].dispatchEvent(new Event('change')); await tick();
  elements.get('label-subject-role').value = 'opponent_partner'; elements.get('label-subject-role').dispatchEvent(new Event('change')); await tick();
  selects = descendants(elements.get('taxonomy-labels')).filter(node => node.tagName === 'SELECT');
  selects[0].value = 'unknown'; selects[0].dispatchEvent(new Event('change')); await tick();
  assert.equal(c.record().judgements.length, 2);
  assert.deepEqual(c.record().judgements.map(j => j.subject_role), ['self', 'opponent_partner']);
  assert.ok(c.record().state.opponent_partner); assert.equal(c.record().judgements[1].value, 'unknown');
  const unknownItem = descendants(elements.get('taxonomy-labels')).find(node => node.className === 'label-item');
  assert.ok(unknownItem.children.some(node => node.tagName === 'INPUT' && node.placeholder.includes('必填')), 'missing reason remains visible outside collapsed definition');
  assert.equal(c.record().evidence.length, 0, 'label changes must not fabricate evidence');
  elements.get('add-time-evidence').dispatchEvent(new Event('click')); await tick();
  assert.equal(c.record().evidence[0].type, 'source_time'); assert.equal(c.record().evidence[0].observation_source, 'agent');
  c.record().provenance.revision_audit = {actor_type: 'agent', reviewer: 'saved-agent'};
  c.record().review = {status: 'pending', reviewer_type: null, reviewer: null}; c.notify();
  assert.ok(descendants(elements.get('record-list')).some(node => node.className === 'review' && node.textContent === '待审核 · 来源 agent'));
  assert.match(elements.get('review-provenance').textContent, /记录来源：agent \/ saved-agent/);
  assert.match(elements.get('review-provenance').textContent, /审核状态：待审核；审核人：未记录 \/ 未记录/);
  c.record().provenance.revision_audit = {actor_type: 'human', reviewer: 'last-editor'}; c.notify();
  assert.equal(elements.get('record-review').value, 'pending', 'human edit provenance must not grant confirmed review');
  assert.ok(descendants(elements.get('record-list')).some(node => node.className === 'review' && node.textContent === '待审核 · 来源 human'));
  delete c.record().provenance.revision_audit;
  c.record().review = {status: 'pending', reviewer_type: 'agent', reviewer: 'legacy-agent'}; c.notify();
  assert.match(elements.get('review-provenance').textContent, /记录来源：agent \/ legacy-agent/);
  const formEvent = new Event('submit', {cancelable: true}); elements.get('annotation-form').dispatchEvent(formEvent);
  assert.equal(formEvent.defaultPrevented, true, 'native submit must be stopped before async save'); await tick();
  c.state.snapshots = [{snapshot_id: 'blocked-snapshot', created_at: '2026-10-02T00:00:00Z', project: f.project, content_sha256: 'a'.repeat(64),
    quality_summary: {record_count: 2, eligible_judgement_count: 0, excluded_judgement_count: 2, trainable: false, blockers: ['independent_match_group_unconfirmed']}}];
  c.notify();
  let downloads = descendants(elements.get('snapshot-list')).filter(node => node.tagName === 'A');
  assert.equal(downloads.length, 2); assert.ok(downloads.every(link => link.href.includes('view=audit')));
  assert.ok(descendants(elements.get('snapshot-list')).some(node => node['aria-disabled'] === 'true' && !node.href && node.textContent.includes('先完成质量审核')));
  assert.ok(descendants(elements.get('snapshot-summary')).some(node => node.textContent === '原片所属的独立比赛组尚未确认'));
  c.state.snapshots[0].quality_summary = {...c.state.snapshots[0].quality_summary, trainable: true, blockers: []}; c.notify();
  downloads = descendants(elements.get('snapshot-list')).filter(node => node.tagName === 'A');
  assert.equal(downloads.length, 3); assert.equal(downloads.filter(link => link.href.includes('view=training')).length, 1);
});

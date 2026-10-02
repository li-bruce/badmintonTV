const test = require('node:test');
const assert = require('node:assert/strict');
const regions = require('../../apps/platform/static/training_regions.js');

test('image coordinates subtract horizontal and vertical letterbox and reject nonfinite input', () => {
  const square = {left: 100, top: 50, width: 400, height: 400};
  assert.deepEqual(regions.contentRect(square, 1920, 1080), {left: 100, top: 137.5, width: 400, height: 225});
  assert.deepEqual(regions.imagePoint(300, 250, square, 1920, 1080), {x: .5, y: .5});
  assert.deepEqual(regions.imagePoint(100, 137.5, square, 1920, 1080), {x: 0, y: 0});
  assert.equal(regions.imagePoint(300, 137.49, square, 1920, 1080), null);
  assert.equal(regions.imagePoint(499, 250, square, 1080, 1920), null);
  for (const value of [NaN, Infinity, -Infinity, '200', null, true]) {
    assert.equal(regions.imagePoint(value, 200, square, 1920, 1080), null);
    assert.equal(regions.imagePoint(200, value, square, 1920, 1080), null);
    assert.equal(regions.contentRect(square, value, 1080), null);
  }
  assert.equal(regions.contentRect({...square, left: NaN}, 1920, 1080), null);
  assert.equal(regions.contentRect(square, 0, 0), null);
});
test('geometry rejects crossings, adjacent overlap, duplicates, degeneracy and limits while allowing concave polygons', () => {
  const p = (...values) => values.map(([x, y]) => ({x, y}));
  assert.deepEqual(regions.validatePoints('rectangle', p([.8, .9], [.2, .1])), p([.2, .1], [.8, .9]));
  const concave = p([.1, .1], [.9, .1], [.4, .4], [.9, .9], [.1, .9]);
  assert.deepEqual(regions.validatePoints('polygon', concave), concave);
  for (const points of [p([0, 0], [1, 1], [0, 1], [1, 0]), p([0, 0], [1, 0], [.5, 0], [.5, 1]), p([0, 0], [.5, .5], [1, 1]), p([0, 0], [1, 0], [0, 0]), p([0, 0], [1, 0]), p([0, 0], [1, 0], [0, Infinity]), p([0, 0], [1, 0], [0, -1]), p([0, 0], [1, 0], [true, 1])]) assert.throws(() => regions.validatePoints('polygon', points));
  assert.throws(() => regions.validatePoints('rectangle', p([.2, .1], [.2, .9])));
  assert.throws(() => regions.validatePoints('polygon', Array.from({length: 65}, (_, i) => ({x: .5 + .4 * Math.cos(i * 2 * Math.PI / 65), y: .5 + .4 * Math.sin(i * 2 * Math.PI / 65)}))));
});
test('record time binding preserves point equality and half-open source/interval bounds', () => {
  assert.equal(regions.recordContains({at_ms: 1000}, 1000, 3000), true);
  assert.equal(regions.recordContains({at_ms: 1000}, 1001, 3000), false);
  assert.equal(regions.recordContains({at_ms: 3000}, 3000, 3000), false);
  assert.equal(regions.recordContains({start_ms: 1000, end_ms: 2000}, 1999, 3000), true);
  assert.equal(regions.recordContains({start_ms: 1000, end_ms: 2000}, 2000, 3000), false);
  assert.equal(regions.recordContains({start_ms: 1000, end_ms: 2000}, 1000.1, 3000), false);
});

// Small event/DOM fixture: real mounted handlers, no browser, video decoder or fake media assertions.
class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.listeners = {}; this.disabled = false;
    this.classes = new Set(); this.classList = {toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name), remove: name => this.classes.delete(name)};
    this.rect = {left: 100, top: 50, width: 400, height: 400}; this.paused = true; this.seeking = false; this.readyState = 2;
    this.videoWidth = 1920; this.videoHeight = 1080; this.currentTime = 1; this.captures = new Set();
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  emit(name, properties = {}) {
    const event = {target: this, button: 0, pointerId: 1, preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }, ...properties};
    for (const fn of this.listeners[name] || []) fn(event); return event;
  }
  getBoundingClientRect() { return this.rect; }
  pause() { this.paused = true; }
  focus() { this.focused = true; }
  setPointerCapture(id) { this.captures.add(id); }
  hasPointerCapture(id) { return this.captures.has(id); }
  releasePointerCapture(id) { this.captures.delete(id); }
}
const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);
function fixture({afterChange} = {}) {
  const doc = new Element(), win = new Element(), stage = new Element(), player = new Element('video'), container = new Element();
  doc.createElement = tag => new Element(tag); doc.createElementNS = (_ns, tag) => new Element(tag);
  const record = {record_id: 'record-a', project_id: 'project-a', asset_id: 'asset-a', at_ms: 1000, person_id: 'person-a',
    evidence: [{type: 'source_time', asset_id: 'asset-a', at_ms: 1000, observation_source: 'human'}]};
  const state = {epoch: 1, actorType: 'agent', selectedId: record.record_id, project: {project_id: 'project-a'},
    asset: {asset_id: 'asset-a', duration_ms: 3000, sha256: 'a'.repeat(64)}, bundle: {asset: {asset_id: 'asset-a'}, people: [{person_id: 'person-a', display_name: '球员 A'}], records: [record]}};
  const calls = [], errors = [], seeks = []; let subject = {subject_role: 'self', subject_person_id: 'person-a'}, begins = 0;
  const getRecord = () => state.bundle.records.find(r => r.record_id === state.selectedId);
  const app = regions.mount({doc, win, stage, player, container, getState: () => state, getRecord, getTime: () => player.currentTime * 1000,
    getSubject: () => subject, onBegin: () => { begins++; }, onChange: evidence => { calls.push(structuredClone(evidence)); getRecord().evidence = evidence; afterChange?.(state, app); },
    onError: error => errors.push(error.message), onSeek: ms => { seeks.push(ms); player.currentTime = ms / 1000; player.seeking = true; player.emit('seeking'); }});
  const svg = stage.children[0];
  const actions = name => descendants(container).filter(n => n.getAttribute('data-region-action') === name);
  const click = (name, index = 0) => { const button = actions(name)[index]; assert.ok(button, name); if (!button.disabled) button.emit('click'); };
  const pointer = (type, x, y, target = svg, extra = {}) => svg.emit(type, {clientX: 100 + x * 400, clientY: 137.5 + y * 225, target, ...extra});
  const drawRect = () => { click('rectangle'); pointer('pointerdown', .1, .2); pointer('pointermove', .4, .6); pointer('pointerup', .4, .6); };
  const latest = () => record.evidence.filter(e => e.type === 'image_region').at(-1);
  const shape = () => svg.children.find(n => n.getAttribute('data-region-id') && n.tagName === 'POLYGON');
  return {doc, win, stage, player, container, record, state, app, calls, errors, seeks, svg, actions, click, pointer, drawRect, latest, shape, getRecord,
    setSubject: value => { subject = value; }, begins: () => begins};
}
test('rectangle writes once on release with frame/subject/actor bindings and preserves ordinary evidence', () => {
  const f = fixture(), old = structuredClone(f.record.evidence[0]); f.click('rectangle');
  f.pointer('pointerdown', .1, .2); f.pointer('pointermove', .4, .6);
  assert.equal(f.calls.length, 0); assert.equal(f.record.evidence.length, 1);
  f.pointer('pointerup', .4, .6);
  assert.equal(f.calls.length, 1); assert.deepEqual(f.record.evidence[0], old); assert.equal(f.begins(), 1);
  assert.deepEqual({...f.latest(), evidence_id: 'generated'}, {type: 'image_region', schema_version: '1.0', evidence_id: 'generated',
    record_id: 'record-a', asset_id: 'asset-a', at_ms: 1000, coordinate_system: 'image_normalized', shape: 'rectangle', points: [{x: .1, y: .2}, {x: .4, y: .6}],
    subject_role: 'self', subject_person_id: 'person-a', observation_source: 'agent', precision: 'browser_time'});
});
test('Escape, pointercancel, outside drag and zero-area release never publish a draft', () => {
  for (const abort of ['escape', 'cancel', 'pointercancel', 'outside', 'zero']) {
    const f = fixture(); f.click('rectangle'); f.pointer('pointerdown', .1, .2);
    if (abort === 'escape') assert.equal(f.doc.emit('keydown', {key: 'Escape'}).defaultPrevented, true);
    if (abort === 'cancel') f.click('cancel');
    if (abort === 'pointercancel') f.svg.emit('pointercancel');
    if (abort === 'outside') f.pointer('pointermove', .4, -1);
    f.pointer('pointerup', abort === 'zero' ? .1 : .4, .6);
    assert.equal(f.calls.length, 0, abort); assert.equal(f.record.evidence.length, 1, abort);
  }
});
test('black borders and nonfinite pointer positions cannot start or finish drawing', () => {
  for (const event of [{clientX: 200, clientY: 100}, {clientX: NaN, clientY: 200}, {clientX: 200, clientY: Infinity}]) {
    const f = fixture(); f.click('rectangle'); f.svg.emit('pointerdown', event); f.pointer('pointerup', .4, .6);
    assert.equal(f.calls.length, 0); assert.ok(f.errors.length);
  }
});
test('polygon Enter/button completion uses vertices; self-intersection rejects the whole draft', () => {
  for (const finish of ['key', 'button']) {
    const f = fixture(); f.click('polygon'); for (const [x, y] of [[.1, .1], [.8, .1], [.6, .6], [.1, .9]]) f.pointer('pointerdown', x, y);
    assert.equal(f.calls.length, 0);
    if (finish === 'key') f.doc.emit('keydown', {key: 'Enter'}); else f.click('finish');
    assert.equal(f.calls.length, 1); assert.equal(f.latest().shape, 'polygon'); assert.equal(f.latest().points.length, 4);
  }
  const f = fixture(); f.click('polygon'); for (const [x, y] of [[.1, .1], [.9, .9], [.1, .9], [.9, .1]]) f.pointer('pointerdown', x, y);
  f.click('finish'); assert.equal(f.calls.length, 0); assert.match(f.errors.at(-1), /自交/);
});
test('typing Enter and composition do not complete polygons', () => {
  const f = fixture(); f.click('polygon'); for (const [x, y] of [[.1, .1], [.8, .1], [.1, .9]]) f.pointer('pointerdown', x, y);
  assert.equal(f.svg.focused, true, 'drawing takes focus away from toolbar so Enter finishes instead of restarting');
  f.doc.emit('keydown', {key: 'Enter', target: new Element('input')}); f.doc.emit('keydown', {key: 'Enter', isComposing: true});
  assert.equal(f.calls.length, 0); f.app.cancel(); assert.equal(f.calls.length, 0);
});
test('move and rectangle corner adjustment preserve id/time and cancel does not mutate the saved region', () => {
  const f = fixture(); f.drawRect(); const original = structuredClone(f.latest()), id = original.evidence_id;
  f.pointer('pointerdown', .2, .3, f.shape()); f.pointer('pointermove', .3, .4); assert.deepEqual(f.latest(), original);
  f.doc.emit('keydown', {key: 'Escape'}); f.pointer('pointerup', .3, .4); assert.deepEqual(f.latest(), original);
  f.pointer('pointerdown', .2, .3, f.shape()); f.pointer('pointermove', .3, .4); f.pointer('pointerup', .3, .4);
  assert.equal(f.latest().evidence_id, id); assert.equal(f.latest().at_ms, 1000); assert.deepEqual(f.latest().points, [{x: .2, y: .3}, {x: .5, y: .7}]);
  const handle = f.svg.children.find(n => n.getAttribute('data-region-handle') === '0');
  f.pointer('pointerdown', .2, .3, handle); f.pointer('pointerup', .15, .25);
  assert.deepEqual(f.latest().points, [{x: .15, y: .25}, {x: .5, y: .7}]); assert.equal(f.calls.length, 3);
  f.click('delete'); assert.equal(f.record.evidence.length, 1); assert.equal(f.record.evidence[0].type, 'source_time');
});
test('polygon vertex edits validate geometry; editing existing human evidence uses current agent source', () => {
  const f = fixture(); f.state.actorType = 'human'; f.click('polygon'); for (const [x, y] of [[.1, .1], [.8, .1], [.1, .9]]) f.pointer('pointerdown', x, y);
  f.click('finish'); const id = f.latest().evidence_id; assert.equal(f.latest().observation_source, 'human');
  f.state.actorType = 'agent'; f.app.render();
  const handle = f.svg.children.find(n => n.getAttribute('data-region-handle') === '1');
  f.pointer('pointerdown', .8, .1, handle); f.pointer('pointerup', .9, .2);
  assert.equal(f.latest().evidence_id, id); assert.equal(f.latest().observation_source, 'agent'); assert.deepEqual(f.latest().points[1], {x: .9, y: .2});
});
test('simple selection is a no-op even for legacy non-six-decimal coordinates', () => {
  const f = fixture(); f.drawRect(); f.latest().points = [{x: 1/3, y: .1}, {x: .8, y: .9}]; f.latest().observation_source = 'human'; f.app.render();
  const original = structuredClone(f.latest()); f.pointer('pointerdown', .4, .3, f.shape()); f.pointer('pointerup', .4, .3);
  assert.equal(f.calls.length, 1); assert.deepEqual(f.latest(), original);
});
test('moving out of the image cancels without clamping or partial persistence', () => {
  const f = fixture(); f.drawRect(); const original = structuredClone(f.latest());
  f.pointer('pointerdown', .2, .3, f.shape()); f.pointer('pointermove', 0, .3); f.pointer('pointerup', 0, .3);
  assert.equal(f.calls.length, 1); assert.deepEqual(f.latest(), original);
});
for (const change of ['record', 'epoch', 'asset', 'project', 'evidence', 'time', 'actor', 'record-range']) {
  test(`stale ${change} during a drag cannot write either old or new selected record`, () => {
    const f = fixture(); f.drawRect(); const old = structuredClone(f.record.evidence); f.pointer('pointerdown', .2, .3, f.shape());
    if (change === 'record') { f.state.bundle.records.push({...structuredClone(f.record), record_id: 'record-b', evidence: []}); f.state.selectedId = 'record-b'; }
    if (change === 'epoch') f.state.epoch++;
    if (change === 'asset') f.state.asset.sha256 = 'b'.repeat(64);
    if (change === 'project') f.state.project.project_id = 'project-b';
    if (change === 'evidence') f.record.evidence.push({type: 'note', text: 'Concurrent edit'});
    if (change === 'time') f.player.currentTime = 1.001;
    if (change === 'actor') f.state.actorType = 'human';
    if (change === 'record-range') f.record.at_ms = 1001;
    f.pointer('pointerup', .3, .4);
    assert.equal(f.calls.length, 1); assert.deepEqual(f.record.evidence.slice(0, 2), old);
    if (change === 'record') assert.deepEqual(f.getRecord().evidence, []);
  });
}
test('off-time evidence is not overlaid and locating waits for seeked before enabling drawing', () => {
  const f = fixture(); f.drawRect(); f.player.currentTime = 1.1; f.app.updateTime(1100);
  assert.equal(f.svg.children.length, 0); assert.match(f.actions('select')[0].textContent, /其它时刻/);
  f.click('rectangle'); assert.equal(f.calls.length, 1); assert.match(f.errors.at(-1), /先定位/);
  f.click('locate'); assert.deepEqual(f.seeks, [1000]); assert.equal(f.actions('rectangle')[0].disabled, true);
  f.pointer('pointerdown', .1, .2); f.pointer('pointerup', .4, .6); assert.equal(f.calls.length, 1);
  f.player.seeking = false; f.player.emit('seeked'); assert.equal(f.actions('rectangle')[0].disabled, false);
  f.drawRect(); assert.equal(f.calls.length, 2); assert.equal(f.latest().precision, 'browser_time');
});
test('playback and in-flight seeks cancel drafts and unknown people fail without evidence', () => {
  const f = fixture(); f.click('polygon'); f.pointer('pointerdown', .1, .1);
  f.player.paused = false; f.player.emit('play'); f.click('finish'); assert.equal(f.calls.length, 0);
  f.player.pause(); f.click('rectangle'); f.pointer('pointerdown', .1, .1); f.player.seeking = true; f.player.emit('seeking'); f.pointer('pointerup', .5, .5); assert.equal(f.calls.length, 0);
  f.player.seeking = false; f.player.emit('seeked'); f.setSubject({subject_role: 'opponent', subject_person_id: 'not-in-project'}); f.click('rectangle'); assert.match(f.errors.at(-1), /不属于/); assert.equal(f.calls.length, 0);
});
test('lost capture, window blur, and resize cancel unpublished drags', () => {
  for (const signal of ['capture', 'blur', 'resize']) {
    const f = fixture(); f.click('rectangle'); f.pointer('pointerdown', .1, .2); f.pointer('pointermove', .4, .6);
    if (signal === 'capture') f.svg.emit('lostpointercapture'); else f.win.emit(signal);
    f.pointer('pointerup', .4, .6); assert.equal(f.calls.length, 0, signal);
  }
});
test('switching asset during a pending seek does not leave the new asset tools permanently disabled', () => {
  const f = fixture(); f.player.currentTime = 1.2; f.click('locate'); assert.equal(f.actions('rectangle')[0].disabled, true);
  f.state.epoch++; f.state.asset.sha256 = 'b'.repeat(64); f.player.seeking = false; f.player.currentTime = 1;
  f.app.render(); assert.equal(f.actions('rectangle')[0].disabled, false); f.drawRect(); assert.equal(f.calls.length, 1);
});
test('synchronous callback cloning records and rerendering preserves selected evidence and handles', () => {
  const f = fixture({afterChange: (state, app) => {
    state.bundle.records = structuredClone(state.bundle.records);
    state.bundle.records[0].review = {status: 'pending', reviewer_type: state.actorType};
    app.render(); app.updateTime(1000);
  }});
  f.drawRect(); const current = f.getRecord(), region = current.evidence.find(e => e.type === 'image_region');
  assert.notEqual(current, f.record); assert.equal(f.calls.length, 1);
  assert.equal(f.actions('delete')[0].disabled, false); assert.equal(f.svg.children.filter(n => n.getAttribute('data-region-handle') !== null).length, 4);
  f.pointer('pointerdown', .2, .3, f.shape()); f.pointer('pointerup', .3, .4);
  assert.equal(f.calls.length, 2); assert.equal(f.getRecord().evidence[1].evidence_id, region.evidence_id);
  assert.deepEqual(f.getRecord().evidence[1].points, [{x: .2, y: .3}, {x: .5, y: .7}]);
});
test('loaded metadata alone cannot draw; first decoded data refreshes the tools without extra seeking', () => {
  const f = fixture(); f.player.readyState = 1; f.player.emit('loadedmetadata'); assert.equal(f.actions('rectangle')[0].disabled, true);
  f.player.readyState = 2; f.player.emit('loadeddata'); assert.equal(f.actions('rectangle')[0].disabled, false);
  f.drawRect(); assert.equal(f.calls.length, 1);
});

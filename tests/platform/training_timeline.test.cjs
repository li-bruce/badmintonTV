const test = require('node:test');
const assert = require('node:assert/strict');
const timeline = require('../../apps/platform/static/training_timeline.js');

class Element extends EventTarget {
  constructor(tag, doc) {
    super(); this.tagName = tag.toUpperCase(); this.doc = doc; this.children = []; this.dataset = {}; this.style = {}; this.attributes = {};
    this.className = ''; this.textContent = ''; this.captures = new Set(); this.hidden = false;
    this.classList = {
      add: name => { if (!this.className.split(' ').includes(name)) this.className += ' ' + name; },
      remove: name => { this.className = this.className.split(' ').filter(item => item !== name).join(' '); },
      toggle: (name, enabled) => { if (enabled) this.classList.add(name); else this.classList.remove(name); },
      contains: name => this.className.split(' ').includes(name),
    };
  }
  append(...nodes) { for (const node of nodes) { node.parentNode = this; this.children.push(node); } }
  replaceChildren(...nodes) { for (const node of this.children) node.parentNode = null; this.children = []; this.append(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getBoundingClientRect() { let root = this; while (root.parentNode) root = root.parentNode; return {left: 0, top: 0, width: root.tagName === 'MAIN' ? 1000 : 0, height: 100}; }
  focus() { this.doc.activeElement = this; }
  setPointerCapture(id) { this.captures.add(id); }
  releasePointerCapture(id) { this.captures.delete(id); this.dispatchEvent(event('lostpointercapture', {pointerId: id})); }
  hasPointerCapture(id) { return this.captures.has(id); }
  closest(selector) { if (selector === '.btv-timeline-record' && this.classList.contains('btv-timeline-record')) return this; return this.parentNode?.closest(selector) || null; }
}
const all = node => node.children.flatMap(child => [child, ...all(child)]);
const tick = () => new Promise(resolve => setImmediate(resolve));
function event(type, values = {}) { const e = new Event(type, {cancelable: true}); for (const [name, value] of Object.entries(values)) Object.defineProperty(e, name, {value}); return e; }
function setup(records = [{record_id: 'segment', kind: 'segment', segment_type: 'footwork', start_ms: 2000, end_ms: 4000, revision: 1}], options = {}) {
  const doc = {activeElement: null}; doc.createElement = tag => new Element(tag, doc);
  const win = new EventTarget(), container = new Element('main', doc);
  const state = {epoch: 1, project: {project_id: 'project-a'}, asset: {asset_id: 'asset-a', sha256: 'a', duration_ms: 10000},
    selectedId: null, taxonomy: {labels: [{label_id: 'footwork.step', name: '并步', dimension: 'footwork'}, {label_id: 'group', selectable: false}]},
    bundle: {revision: 1, records: structuredClone(records)}};
  const edits = [], errors = [], seeks = [], drops = []; let current = 0, instance;
  const seek = ms => { seeks.push(ms); if (options.seekOnSelect) { current = ms; instance?.updateTime(ms); } };
  instance = timeline.mount({doc, win, container, getState: () => state, getTime: () => current,
    onSelect: id => { state.selectedId = id; instance?.render(); if (options.seekOnSelect) seek(state.bundle.records.find(r => r.record_id === id).start_ms); if (options.cancelOnSelect) instance?.cancel(); }, onSeek: seek,
    onEdit: (id, patch) => { if (state.rejectEdit) throw new Error(state.rejectEdit); edits.push({id, patch}); Object.assign(state.bundle.records.find(r => r.record_id === id), patch); instance.render(); },
    onDropLabel: (id, target) => drops.push({id, target}), onError: error => errors.push(error.message)});
  const block = id => all(container).find(node => node.dataset.recordId === id);
  const control = name => all(container).find(node => node.tagName === 'BUTTON' && node.textContent === name);
  const pointer = (target, type, x, values = {}) => target.dispatchEvent(event(type, {pointerId: 7, button: 0, clientX: x, ...values}));
  return {doc, win, container, state, edits, errors, seeks, drops, instance, block, control, pointer, setTime: ms => { current = ms; }};
}

test('overlapping intervals and close points occupy separate selectable subrows', () => {
  const records = [
    {record_id: 'a', kind: 'segment', start_ms: 100, end_ms: 200},
    {record_id: 'b', kind: 'segment', start_ms: 150, end_ms: 300},
    {record_id: 'c', kind: 'segment', start_ms: 300, end_ms: 400},
    {record_id: 'd', kind: 'contact', at_ms: 500}, {record_id: 'e', kind: 'contact', at_ms: 505},
    {record_id: 'gone', kind: 'contact', at_ms: 500, deleted: true},
  ];
  const tracks = timeline.layoutTracks(records, {start: 0, end: 1000}, 30);
  const stroke = tracks.find(t => t.key === 'stroke'), points = tracks.find(t => t.key === 'point');
  assert.equal(stroke.lanes, 2); assert.equal(stroke.items[0].lane, stroke.items[2].lane); assert.equal(points.lanes, 2); assert.equal(points.items.length, 2);
});
test('whole interval drag previews without mutation, retains capture across render, commits one ms patch', async () => {
  const f = setup(), original = f.block('segment');
  f.pointer(original, 'pointerdown', 200);
  assert.equal(f.block('segment'), original); assert.equal(original.hasPointerCapture(7), true);
  f.pointer(f.win, 'pointermove', 300); f.instance.render();
  assert.equal(f.state.bundle.records[0].start_ms, 2000); assert.equal(original.dataset.startMs, '3000'); assert.equal(f.block('segment'), original);
  f.pointer(f.win, 'pointerup', 300); await tick();
  assert.deepEqual(f.edits, [{id: 'segment', patch: {start_ms: 3000, end_ms: 5000}}]); assert.equal(original.hasPointerCapture(7), false);
});

test('click selection survives synchronous notify render and seek, then exits preview before rally focus', async () => {
  const f = setup([{record_id: 'rally', kind: 'rally', start_ms: 3000, end_ms: 5000}], {seekOnSelect: true});
  const original = f.block('rally'), status = all(f.container).find(node => node.classList.contains('btv-timeline-status'));
  f.pointer(original, 'pointerdown', 400);
  assert.equal(f.block('rally'), original, 'synchronous selection render keeps the captured node');
  assert.equal(original.hasPointerCapture(7), true); assert.deepEqual(f.seeks, [3000]);
  f.pointer(f.win, 'pointerup', 400);
  assert.equal(original.hasPointerCapture(7), false); assert.equal(f.edits.length, 0);
  assert.doesNotMatch(status.textContent, /拖动预览中|松手/);
  f.control('当前回合').dispatchEvent(new Event('click'));
  f.win.dispatchEvent(event('keydown', {key: 'Escape'}));
  assert.doesNotMatch(status.textContent, /拖动预览中|松手/);
  const next = f.block('rally'); f.pointer(next, 'pointerdown', 400); f.pointer(f.win, 'pointerup', 450); await tick();
  assert.equal(f.edits.length, 1, 'a later real drag still commits exactly once');
});

test('synchronous selection cancellation cannot be overwritten by a stale begin preview message', () => {
  const f = setup(undefined, {cancelOnSelect: true}); const original = f.block('segment');
  f.pointer(original, 'pointerdown', 200); f.pointer(f.win, 'pointerup', 300);
  const status = all(f.container).find(node => node.classList.contains('btv-timeline-status'));
  assert.equal(original.hasPointerCapture(7), false); assert.equal(f.edits.length, 0);
  assert.match(status.textContent, /已取消/); assert.doesNotMatch(status.textContent, /拖动预览中/);
});

test('label drop freezes its attached lane coordinate before cancelling a pointer draft and redrawing', async () => {
  const f = setup(), original = f.block('segment');
  f.pointer(original, 'pointerdown', 200); f.pointer(f.win, 'pointermove', 250);
  original.dispatchEvent(event('drop', {clientX: 350, dataTransfer: {types: [timeline.LABEL_MIME], getData: () => 'footwork.step'}})); await tick();
  assert.equal(original.hasPointerCapture(7), false); assert.equal(f.edits.length, 0);
  assert.deepEqual(f.errors, []); assert.deepEqual(f.drops, [{id: 'footwork.step', target: {at_ms: 3500, record_id: 'segment'}}]);
  f.pointer(f.win, 'pointerup', 300); assert.equal(f.edits.length, 0);
});
test('right boundary adjusts only end, left crossing and source overflow refuse instead of clamping', async () => {
  const f = setup(); let node = f.block('segment'), handle = node.children.find(child => child.dataset.editMode === 'end');
  f.pointer(handle, 'pointerdown', 400); f.pointer(f.win, 'pointerup', 450); await tick();
  assert.deepEqual(f.edits[0].patch, {start_ms: 2000, end_ms: 4500});
  node = f.block('segment'); handle = node.children.find(child => child.dataset.editMode === 'start');
  f.pointer(handle, 'pointerdown', 200); f.pointer(f.win, 'pointermove', 500);
  assert.equal(node.dataset.startMs, '5000'); assert.equal(node.classList.contains('is-invalid'), true);
  f.pointer(f.win, 'pointerup', 500); await tick(); assert.equal(f.edits.length, 1); assert.match(f.errors.at(-1), /区间必须/);
  node = f.block('segment'); f.pointer(node, 'pointerdown', 200); f.pointer(f.win, 'pointerup', -100); await tick();
  assert.equal(f.edits.length, 1); assert.equal(f.state.bundle.records[0].start_ms, 2000);
});
for (const cancellation of ['Escape', 'pointercancel', 'external', 'blur']) test(cancellation + ' cancels in-flight drag without a state edit', () => {
  const f = setup(); f.pointer(f.block('segment'), 'pointerdown', 200); f.pointer(f.win, 'pointermove', 300);
  if (cancellation === 'Escape') f.win.dispatchEvent(event('keydown', {key: 'Escape'}));
  else if (cancellation === 'pointercancel') f.pointer(f.win, 'pointercancel', 300);
  else if (cancellation === 'blur') f.win.dispatchEvent(new Event('blur'));
  else f.instance.cancel();
  f.pointer(f.win, 'pointerup', 300); assert.equal(f.edits.length, 0); assert.equal(f.state.bundle.records[0].start_ms, 2000);
});
test('late pointerup after source switch or concurrent record edit cannot overwrite new data', () => {
  const f = setup(); f.pointer(f.block('segment'), 'pointerdown', 200);
  f.state.epoch++; f.state.asset.asset_id = 'asset-b'; f.instance.render(); f.pointer(f.win, 'pointerup', 300);
  assert.equal(f.edits.length, 0);
  f.pointer(f.block('segment'), 'pointerdown', 200); f.state.bundle.records[0].start_ms = 2300; f.pointer(f.win, 'pointerup', 300);
  assert.equal(f.edits.length, 0); assert.equal(f.state.bundle.records[0].start_ms, 2300); assert.match(f.errors.at(-1), /已变化/);
});
test('point dragging and keyboard time steps preserve point shape and keyboard focus', async () => {
  const f = setup([{record_id: 'point', kind: 'contact', at_ms: 2500, revision: 1}]);
  f.pointer(f.block('point'), 'pointerdown', 250); f.pointer(f.win, 'pointerup', 260); await tick();
  assert.deepEqual(f.edits[0].patch, {at_ms: 2600});
  let node = f.block('point'); node.focus(); node.dispatchEvent(event('keydown', {key: 'ArrowRight'})); await tick();
  assert.equal(f.state.bundle.records[0].at_ms, 2610); assert.equal(f.doc.activeElement, f.block('point'));
  f.doc.activeElement.dispatchEvent(event('keydown', {key: 'ArrowLeft', shiftKey: true})); await tick(); assert.equal(f.state.bundle.records[0].at_ms, 2510);
  f.doc.activeElement.dispatchEvent(event('keydown', {key: 'ArrowRight', altKey: true})); await tick(); assert.equal(f.state.bundle.records[0].at_ms, 2511);
  f.doc.activeElement.dispatchEvent(event('keydown', {key: 'ArrowRight', isComposing: true})); await tick(); assert.equal(f.edits.length, 4);
  f.doc.activeElement.dispatchEvent(event('keydown', {key: 'ArrowRight', target: new Element('input', f.doc)})); await tick(); assert.equal(f.edits.length, 4, 'input arrows never edit timeline');
});
test('interval colour dots retain independent leaf label dimensions and exclude taxonomy folders', () => {
  const f = setup(); f.state.taxonomy.labels.push({label_id: 'stroke.net', name: '网前球', dimension: 'stroke'});
  f.state.bundle.records[0].judgements = [{label_id: 'footwork.step', value: 'unknown', subject_role: 'opponent'}, {label_id: 'stroke.net', value: 'present'}, {label_id: 'group', value: 'present'}]; f.instance.render();
  const dots = all(f.block('segment')).filter(node => node.tagName === 'I');
  assert.equal(dots.length, 2); assert.notEqual(dots[0].style.background, dots[1].style.background); assert.equal(dots[0].title, '并步 · 对手 · 未知');
});
test('authoritative edit rejection restores original timing and reports the actual dependency error', async () => {
  const f = setup(); f.state.rejectEdit = '区域取证时刻将越出区间，修改已拒绝';
  f.pointer(f.block('segment'), 'pointerdown', 200); f.pointer(f.win, 'pointerup', 300); await tick();
  assert.equal(f.edits.length, 0); assert.equal(f.state.bundle.records[0].start_ms, 2000);
  assert.equal(f.block('segment').dataset.startMs, '2000'); assert.equal(f.errors.at(-1), f.state.rejectEdit);
  const status = all(f.container).find(node => node.classList.contains('btv-timeline-status')); assert.equal(status.textContent, f.state.rejectEdit);
});
test('rally boundaries reject lost children but allow atomic linked dead-ball adjustment', () => {
  const rally = {record_id: 'rally', kind: 'rally', start_ms: 1000, end_ms: 9000, dead_ball_id: 'dead'};
  const records = [rally, {record_id: 'contact', kind: 'contact', at_ms: 2000, rally_id: 'rally'}, {record_id: 'dead', kind: 'dead_ball', at_ms: 9000, rally_id: 'rally'}];
  assert.equal(timeline.validateEdit(rally, {start_ms: 1000, end_ms: 8000}, records, 10000), null);
  assert.match(timeline.validateEdit(rally, {start_ms: 2500, end_ms: 9000}, records, 10000), /切掉/);
  assert.match(timeline.validateEdit(records[1], {at_ms: 9000}, records, 10000), /所属回合/);
  assert.match(timeline.validateEdit(records[2], {at_ms: 8000}, records, 10000), /回合右边界/);
});
test('label drops use explicit MIME and source coordinate, with record id only on a record', async () => {
  const f = setup(); const dataTransfer = {types: [timeline.LABEL_MIME], getData: () => 'footwork.step'};
  let node = f.block('segment'); node.dispatchEvent(event('drop', {clientX: 350, dataTransfer})); await tick();
  const lane = all(f.container).find(item => item.dataset.track === 'stroke');
  lane.dispatchEvent(event('drop', {clientX: 550, dataTransfer})); await tick();
  assert.deepEqual(f.drops, [{id: 'footwork.step', target: {at_ms: 3500, record_id: 'segment'}}, {id: 'footwork.step', target: {at_ms: 5500}}]);
  lane.dispatchEvent(event('drop', {clientX: 550, dataTransfer: {types: ['text/plain'], getData: () => 'footwork.step'}}));
  lane.dispatchEvent(event('drop', {clientX: 550, dataTransfer: {types: [timeline.LABEL_MIME], getData: () => 'group'}}));
  await tick(); assert.equal(f.drops.length, 2); assert.match(f.errors.at(-1), /可选标签/);
});

for (const targetKind of ['record', 'lane']) test('label dragenter accepts a quick entry onto ' + targetKind + ' before any dragover', async () => {
  const f = setup(), target = targetKind === 'record' ? f.block('segment') : all(f.container).find(node => node.dataset.track === 'stroke');
  const dataTransfer = {types: [timeline.LABEL_MIME], getData: () => 'footwork.step', dropEffect: 'none'};
  const enter = event('dragenter', {clientX: 350, dataTransfer});
  target.dispatchEvent(enter);
  assert.equal(enter.defaultPrevented, true, 'the target accepts the initial entry without waiting for dragover');
  assert.equal(dataTransfer.dropEffect, 'copy');
  target.dispatchEvent(event('drop', {clientX: 350, dataTransfer})); await tick();
  assert.deepEqual(f.drops, [{id: 'footwork.step', target: {at_ms: 3500, ...(targetKind === 'record' ? {record_id: 'segment'} : {})}}]);
  const unsupported = {types: ['text/plain'], getData: () => 'footwork.step', dropEffect: 'none'};
  const otherEnter = event('dragenter', {clientX: 350, dataTransfer: unsupported});
  target.dispatchEvent(otherEnter); target.dispatchEvent(event('drop', {clientX: 350, dataTransfer: unsupported}));
  assert.equal(otherEnter.defaultPrevented, false); assert.equal(unsupported.dropEffect, 'none'); assert.equal(f.drops.length, 1);
});
test('whole view, rally focus, zoom and playhead report original source milliseconds', () => {
  const f = setup([{record_id: 'rally', kind: 'rally', start_ms: 3000, end_ms: 5000}]);
  f.state.selectedId = 'rally'; f.control('当前回合').dispatchEvent(new Event('click'));
  let range = all(f.container).find(node => node.className === 'btv-timeline-range');
  assert.match(range.textContent, /00:02.880 — 00:05.120/);
  f.setTime(4000); f.instance.updateTime(4000); assert.match(range.textContent, /当前 00:04.000/);
  f.control('＋ 放大').dispatchEvent(new Event('click')); assert.match(range.textContent, /00:03.440 — 00:04.560/);
  f.control('全片').dispatchEvent(new Event('click')); assert.match(range.textContent, /00:00.000 — 00:10.000/);
  const lane = all(f.container).find(node => node.dataset.track === 'stroke'); lane.dispatchEvent(event('click', {clientX: 123}));
  assert.deepEqual(f.seeks, [1230]);
});
test('ticks remain finite and bounded for a 100ms zoom or long original video', () => {
  for (const view of [{start: 1000, end: 1100}, {start: 0, end: 14_400_000}]) {
    const ticks = timeline.ticks(view); assert.ok(ticks.length > 1 && ticks.length < 20); assert.ok(ticks.every(value => Number.isInteger(value) && value >= view.start && value <= view.end));
  }
});

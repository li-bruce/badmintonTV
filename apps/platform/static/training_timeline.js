/* Native, source-millisecond annotation timeline. This module never mutates the bundle. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TrainingTimeline = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const LABEL_MIME = 'application/x-btv-label';
  const TRACKS = [['rally', '回合'], ['stroke', '动作'], ['footwork', '步法'], ['tactic', '战术'], ['point', '触球 / 死球'], ['state', '态势']];
  const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
  const point = record => ['contact', 'dead_ball', 'state'].includes(record.kind);
  const start = record => point(record) ? record.at_ms : record.start_ms;
  const end = record => point(record) ? record.at_ms : record.end_ms;
  const sourceKey = state => [state.epoch, state.project?.project_id || state.bundle?.project_id, state.asset?.asset_id || state.bundle?.asset?.asset_id, state.asset?.sha256 || state.bundle?.asset?.sha256].join('|');
  const fingerprint = record => JSON.stringify([record?.record_id, record?.revision, record?.deleted, record?.kind, record?.start_ms, record?.end_ms, record?.at_ms, record?.rally_id, record?.dead_ball_id]);
  function timeText(ms) {
    const value = Math.max(0, Math.round(ms));
    return `${String(Math.floor(value / 60000)).padStart(2, '0')}:${String(Math.floor(value / 1000) % 60).padStart(2, '0')}.${String(value % 1000).padStart(3, '0')}`;
  }
  function movePatch(record, mode, delta) {
    delta = Math.round(delta);
    if (point(record)) return {at_ms: record.at_ms + delta};
    return {start_ms: record.start_ms + (mode === 'end' ? 0 : delta), end_ms: record.end_ms + (mode === 'start' ? 0 : delta)};
  }
  function validateEdit(record, patch, records, duration) {
    const next = {...record, ...patch};
    if (!Number.isFinite(duration) || duration <= 0) return '原片时长不可用';
    if (point(record)) {
      if (!Number.isInteger(next.at_ms) || next.at_ms < 0 || (record.kind === 'dead_ball' ? next.at_ms > duration : next.at_ms >= duration)) return '点位必须在原片范围内；只有死球点可位于原片终点';
    } else if (!Number.isInteger(next.start_ms) || !Number.isInteger(next.end_ms) || next.start_ms < 0 || next.end_ms > duration || next.start_ms >= next.end_ms) return '区间必须满足 0 ≤ 开始 < 结束 ≤ 原片时长';
    const live = records.filter(item => !item.deleted);
    if (record.rally_id) {
      const rally = live.find(item => item.record_id === record.rally_id && item.kind === 'rally');
      if (!rally) return '关联回合不存在，请先修正表单关系';
      if (start(next) < rally.start_ms || end(next) > rally.end_ms || (point(next) && next.kind !== 'dead_ball' && next.at_ms >= rally.end_ms)) return '标注必须保留在所属回合内';
      if (rally.dead_ball_id === record.record_id && next.at_ms !== rally.end_ms) return '此死球点是回合终点，请拖动回合右边界一同调整';
    }
    if (record.kind === 'rally') {
      for (const child of live.filter(item => item.rally_id === record.record_id && item.record_id !== record.dead_ball_id)) {
        if (start(child) < next.start_ms || end(child) > next.end_ms || (point(child) && child.kind !== 'dead_ball' && child.at_ms >= next.end_ms)) return '新回合边界会切掉已有标注，已拒绝修改';
      }
    }
    return null;
  }
  function trackOf(record) {
    if (record.kind === 'rally') return 'rally';
    if (record.kind === 'state') return 'state';
    if (point(record)) return 'point';
    return ['footwork', 'tactic'].includes(record.segment_type) ? record.segment_type : 'stroke';
  }
  function layoutTracks(records, view, gapMs) {
    return TRACKS.map(([key, name]) => {
      const laneEnds = [], items = [];
      for (const record of records.filter(r => !r.deleted && trackOf(r) === key && end(r) >= view.start && start(r) <= view.end).sort((a, b) => start(a) - start(b) || end(a) - end(b) || a.record_id.localeCompare(b.record_id))) {
        const left = Math.max(view.start, start(record)) - (point(record) ? gapMs / 2 : 0);
        const right = Math.max(Math.min(view.end, end(record)) + (point(record) ? gapMs / 2 : 0), left + gapMs);
        let lane = laneEnds.findIndex(value => value <= left);
        if (lane < 0) lane = laneEnds.length;
        laneEnds[lane] = right; items.push({record, lane});
      }
      return {key, name, lanes: Math.max(1, laneEnds.length), items};
    });
  }
  function ticks(view) {
    const desired = Math.max(1, (view.end - view.start) / 6), scale = 10 ** Math.floor(Math.log10(desired));
    const step = [1, 2, 5, 10].map(n => n * scale).find(n => n >= desired);
    const values = [];
    for (let value = Math.ceil(view.start / step) * step; value <= view.end && values.length < 20; value += step) values.push(Math.round(value));
    return values;
  }
  function mount({doc, win, container, getState, getTime, onSelect, onSeek, onEdit, onDropLabel, onError}) {
    let view = {start: 0, end: 1}, key = null, drag = null, busy = false, current = 0;
    let lanes = [], nodes = new Map(), focusNodes = new Map();
    const el = (tag, text, className) => { const node = doc.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; };
    const root = el('section', undefined, 'btv-timeline'); root.setAttribute('aria-label', '原片可视标注时间线');
    const toolbar = el('div', undefined, 'btv-timeline-toolbar'), heading = el('strong', '源时间线');
    const range = el('output', undefined, 'btv-timeline-range'); range.setAttribute('aria-live', 'polite');
    const scroll = el('div', undefined, 'btv-timeline-scroll'), body = el('div', undefined, 'btv-timeline-body'); scroll.append(body);
    const status = el('p', '拖动区间或边界调整原片毫秒；松手后只更新草稿。', 'btv-timeline-status'); status.setAttribute('role', 'status');
    const help = el('p', '块或手柄聚焦后 ← / → 微调 10 ms；Shift 为 100 ms，Alt 为 1 ms。Escape 取消拖动。色点代表不同标签维度。仍可在右侧表单精确填写，以上不是逐帧操作。', 'btv-timeline-help');
    toolbar.append(heading); root.append(toolbar, range, scroll, status, help); container.append(root);
    const report = error => { const value = error instanceof Error ? error : new Error(String(error)); status.textContent = value.message; status.classList.add('is-error'); onError?.(value); };
    const say = text => { status.textContent = text; status.classList.remove('is-error'); };
    const call = (fn, ...args) => { try { return Promise.resolve(fn?.(...args)).catch(report); } catch (error) { report(error); return Promise.resolve(); } };
    const stateRecords = () => getState().bundle?.records || [];
    const duration = () => getState().asset?.duration_ms || getState().bundle?.asset?.duration_ms || 0;
    const find = id => stateRecords().find(record => record.record_id === id && !record.deleted);
    const selected = () => find(getState().selectedId);
    const button = (text, fn) => { const node = el('button', text); node.type = 'button'; node.addEventListener('click', () => { cancel(); fn(); }); toolbar.append(node); return node; };
    function setView(from, to) {
      const total = duration(); if (!(total > 0)) return;
      const span = clamp(to - from, Math.min(100, total), total), left = clamp(from, 0, total - span);
      view = {start: Math.round(left), end: Math.round(left + span)}; render();
    }
    const whole = button('全片', () => setView(0, duration()));
    const focus = button('当前回合', () => {
      const record = selected();
      const rally = record?.kind === 'rally' ? record : find(record?.rally_id);
      if (!rally || rally.kind !== 'rally') { report('请先选择回合或关联到回合的标注'); return; }
      const margin = Math.max(100, (rally.end_ms - rally.start_ms) * .06);
      setView(rally.start_ms - margin, rally.end_ms + margin);
    });
    function zoom(factor) {
      const position = Number(getTime?.()), anchor = Number.isFinite(position) && position >= view.start && position <= view.end ? position : (view.start + view.end) / 2;
      const span = (view.end - view.start) * factor; setView(anchor - span / 2, anchor + span / 2);
    }
    const plus = button('＋ 放大', () => zoom(.5)), minus = button('－ 缩小', () => zoom(2));
    const left = button('← 范围', () => { const shift = (view.end - view.start) * .6; setView(view.start - shift, view.end - shift); });
    const right = button('范围 →', () => { const shift = (view.end - view.start) * .6; setView(view.start + shift, view.end + shift); });
    function position(node, record) {
      const span = view.end - view.start, from = clamp((start(record) - view.start) / span, 0, 1), to = clamp((end(record) - view.start) / span, 0, 1);
      node.style.left = `${from * 100}%`;
      node.style.width = point(record) ? '20px' : `${Math.max(0, to - from) * 100}%`;
      node.dataset.startMs = String(start(record)); node.dataset.endMs = String(end(record));
    }
    function timeAt(event, lane) {
      const rect = lane.getBoundingClientRect(); if (!(rect.width > 0)) throw new Error('时间线尚无可用显示宽度');
      return Math.round(clamp(view.start + (event.clientX - rect.left) / rect.width * (view.end - view.start), 0, duration()));
    }
    function supportedDrop(event) { return Array.from(event.dataTransfer?.types || []).includes(LABEL_MIME); }
    function drop(event, lane, recordId) {
      if (!supportedDrop(event)) return;
      event.preventDefault(); event.stopPropagation();
      const labelId = event.dataTransfer.getData(LABEL_MIME);
      const label = getState().taxonomy?.labels?.find(item => item.label_id === labelId && item.selectable !== false);
      if (!label || !labelId || labelId.length > 512) { report('请从当前项目标签库拖入可选标签'); return; }
      if (recordId && !find(recordId)) { report('目标记录已变化，请重新投放'); return; }
      try {
        // Cancelling a pointer draft can synchronously replace this lane.
        const target = {at_ms: timeAt(event, lane), ...(recordId ? {record_id: recordId} : {})};
        cancel(); call(onDropLabel, labelId, target);
      } catch (error) { report(error); }
    }
    function dropEvents(node, lane, recordId) {
      node.addEventListener('dragover', event => { if (supportedDrop(event)) { event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = 'copy'; } });
      node.addEventListener('drop', event => drop(event, lane, recordId));
    }
    function draftFromEvent(event) {
      const delta = Math.round((event.clientX - drag.x) / drag.width * (drag.view.end - drag.view.start));
      return movePatch(drag.original, drag.mode, delta);
    }
    function unchanged(active) {
      return active.key === sourceKey(getState()) && active.bundleRevision === getState().bundle?.revision && fingerprint(find(active.id)) === active.fingerprint;
    }
    function release(active) { try { if (active.capture.hasPointerCapture?.(active.pointerId)) active.capture.releasePointerCapture(active.pointerId); } catch (_) {} }
    function cancel() {
      if (!drag) return;
      const active = drag; drag = null; release(active); say('已取消拖动，标注未改写。'); render();
    }
    function begin(event, record, mode, node, lane) {
      if (busy || drag || event.button !== 0 || !getState().bundle) return;
      const rect = lane.getBoundingClientRect(); if (!(rect.width > 0)) return;
      event.preventDefault(); event.stopPropagation();
      drag = {id: record.record_id, original: {...record}, fingerprint: fingerprint(record), key: sourceKey(getState()), bundleRevision: getState().bundle.revision,
        mode, node, capture: event.currentTarget || node, pointerId: event.pointerId, x: event.clientX, width: rect.width, view: {...view}};
      drag.capture.focus?.({preventScroll: true});
      try { drag.capture.setPointerCapture?.(event.pointerId); } catch (_) {}
      node.classList.add('is-dragging');
      // Selection may synchronously render, seek, or cancel the active gesture.
      say('拖动预览中；松手提交草稿，Escape 取消。'); call(onSelect, record.record_id);
    }
    function move(event) {
      if (!drag || event.pointerId !== drag.pointerId) return;
      event.preventDefault();
      if (!unchanged(drag)) { cancel(); report('源视频或记录已变化，拖动已取消'); return; }
      const patch = draftFromEvent(event), draft = {...drag.original, ...patch};
      const invalid = validateEdit(drag.original, patch, stateRecords(), duration());
      drag.patch = patch; drag.invalid = invalid; position(drag.node, draft); drag.node.classList.toggle('is-invalid', Boolean(invalid));
      say(invalid ? `无效预览：${invalid}；松手不会改写。` : `${timeText(start(draft))}${point(draft) ? '' : ' — ' + timeText(end(draft))} · 松手更新草稿`);
    }
    function commit(record, patch, activeKey) {
      const invalid = validateEdit(record, patch, stateRecords(), duration());
      if (invalid) { report(invalid); render(); return; }
      busy = true;
      let result;
      try { result = onEdit(record.record_id, patch); } catch (error) { busy = false; report(error); render(); return; }
      Promise.resolve(result).then(() => { if (activeKey === sourceKey(getState())) say('时间已更新到草稿；请保存标注包。'); }, report).finally(() => { busy = false; render(); });
    }
    function finish(event) {
      if (!drag || event.pointerId !== drag.pointerId) return;
      event.preventDefault();
      const active = drag, validContext = unchanged(active), patch = draftFromEvent(event), moved = Math.abs(event.clientX - active.x) >= 3;
      drag = null; release(active);
      if (!validContext) { report('源视频或记录已变化，拖动已取消'); render(); return; }
      if (!moved || Object.keys(patch).every(field => patch[field] === active.original[field])) {
        say('已选中标注；时间未改写。'); render(); call(onSeek, start(active.original)); return;
      }
      commit(active.original, patch, active.key);
    }
    function keyEdit(event, record, mode) {
      if (event.defaultPrevented || event.isComposing || event.ctrlKey || event.metaKey || event.target?.isContentEditable || /^(INPUT|SELECT|TEXTAREA)$/.test(event.target?.tagName || '')) return;
      if (!['ArrowLeft', 'ArrowRight', 'Enter'].includes(event.key)) return;
      event.preventDefault(); event.stopPropagation();
      if (busy || drag) return;
      if (event.key === 'Enter') { call(onSelect, record.record_id); call(onSeek, start(record)); return; }
      const currentRecord = find(record.record_id); if (!currentRecord) return;
      const delta = (event.key === 'ArrowLeft' ? -1 : 1) * (event.altKey ? 1 : event.shiftKey ? 100 : 10);
      call(onSelect, currentRecord.record_id); commit(currentRecord, movePatch(currentRecord, mode, delta), sourceKey(getState()));
    }
    function makeBlock(record, lane, laneIndex, labels) {
      const node = el('div', undefined, `btv-timeline-record ${point(record) ? 'is-point' : 'is-interval'} kind-${record.kind}`);
      node.dataset.recordId = record.record_id; node.tabIndex = 0; node.setAttribute('role', 'button');
      node.dataset.editMode = 'move'; focusNodes.set(record.record_id + ':move', node);
      const title = record.provenance?.title || ({rally: '回合', contact: '触球', dead_ball: '死球', state: '态势'}[record.kind] || ({footwork: '步法', tactic: '战术'}[record.segment_type] || '动作'));
      const caption = `${title} ${timeText(start(record))}${point(record) ? '' : ' — ' + timeText(end(record))}`;
      node.title = caption; node.setAttribute('aria-label', caption + '；左右键微调时间'); node.style.top = `${laneIndex * 34 + 6}px`;
      const name = el('span', point(record) ? (record.kind === 'dead_ball' ? '◆' : '●') : title, 'btv-timeline-name'); node.append(name);
      const judgements = (record.judgements || []).filter(j => j.value !== 'unlabeled' && labels.get(j.label_id)?.selectable !== false);
      if (judgements.length && !point(record)) {
        const axes = el('span', undefined, 'btv-timeline-axes');
        for (const judgement of judgements.slice(0, 5)) {
          const label = labels.get(judgement.label_id), dimension = label?.dimension || judgement.label_id;
          const hue = [...dimension].reduce((sum, char) => (sum * 31 + char.charCodeAt(0)) % 360, 0);
          const role = {self: '本人', opponent: '对手', partner: '搭档', opponent_partner: '对方搭档'}[judgement.subject_role || 'self'];
          const value = {present: '存在', absent: '不存在', unknown: '未知', unobservable: '看不清', not_applicable: '不适用'}[judgement.value] || judgement.value;
          const dot = el('i'); dot.style.background = `hsl(${hue} 60% 72%)`; dot.title = `${label?.name || judgement.label_id} · ${role} · ${value}`; axes.append(dot);
        }
        if (judgements.length > 5) axes.append(el('small', '+' + (judgements.length - 5))); node.append(axes);
      }
      if (!point(record)) for (const mode of ['start', 'end']) {
        const handle = el('span', mode === 'start' ? '‹' : '›', 'btv-timeline-handle handle-' + mode); handle.tabIndex = 0; handle.setAttribute('role', 'button');
        handle.setAttribute('aria-label', `${title}${mode === 'start' ? '开始' : '结束'}边界，可拖动或用左右键微调`);
        handle.dataset.editMode = mode; focusNodes.set(record.record_id + ':' + mode, handle);
        handle.hidden = mode === 'start' ? record.start_ms < view.start : record.end_ms > view.end;
        handle.addEventListener('pointerdown', event => begin(event, record, mode, node, lane)); handle.addEventListener('keydown', event => keyEdit(event, record, mode)); node.append(handle);
      }
      node.addEventListener('pointerdown', event => begin(event, record, 'move', node, lane));
      node.addEventListener('keydown', event => keyEdit(event, record, 'move')); dropEvents(node, lane, record.record_id);
      node.addEventListener('lostpointercapture', event => { if (drag && event.pointerId === drag.pointerId) cancel(); });
      position(node, record); node.classList.toggle('is-selected', record.record_id === getState().selectedId); nodes.set(record.record_id, node); return node;
    }
    function updateTime(ms) {
      if (Number.isFinite(ms)) current = ms;
      for (const lane of lanes) {
        const cursor = lane.cursor; cursor.hidden = current < view.start || current > view.end;
        cursor.style.left = `${clamp((current - view.start) / (view.end - view.start), 0, 1) * 100}%`;
        cursor.setAttribute('aria-label', '当前位置 ' + timeText(current));
      }
      range.textContent = `${timeText(view.start)} — ${timeText(view.end)} / 原片 ${timeText(duration())} · 当前 ${timeText(current)}`;
    }
    function render() {
      const state = getState(), total = duration(), nextKey = sourceKey(state);
      if (drag && unchanged(drag)) { for (const [id, node] of nodes) node.classList.toggle('is-selected', id === state.selectedId); updateTime(Number(getTime?.())); return; }
      if (drag) { const active = drag; drag = null; release(active); say('记录或源视频变化，拖动已取消。'); }
      if (key !== nextKey) { key = nextKey; view = {start: 0, end: Math.max(1, total)}; }
      for (const control of [whole, focus, plus, minus, left, right]) control.disabled = !state.bundle || total <= 0;
      const focused = doc.activeElement, focusedRecord = focused?.closest?.('.btv-timeline-record');
      const focusKey = focusedRecord ? focusedRecord.dataset.recordId + ':' + (focused.dataset.editMode || 'move') : null;
      body.replaceChildren(); lanes = []; nodes = new Map(); focusNodes = new Map();
      if (!state.bundle || total <= 0) { body.append(el('p', '选择视频后显示原片时间线。', 'btv-timeline-empty')); updateTime(0); return; }
      const ruler = el('div', undefined, 'btv-timeline-track btv-timeline-ruler'); ruler.append(el('span', '原片时间', 'btv-timeline-track-name'));
      const rulerLane = el('div', undefined, 'btv-timeline-lane');
      for (const value of ticks(view)) { const tick = el('span', timeText(value), 'btv-timeline-tick'); tick.style.left = `${(value - view.start) / (view.end - view.start) * 100}%`; if (value === view.start) tick.style.transform = 'none'; else if (value === view.end) tick.style.transform = 'translateX(-100%)'; rulerLane.append(tick); }
      ruler.append(rulerLane); body.append(ruler);
      const rect = rulerLane.getBoundingClientRect(), width = rect.width || 600;
      const layout = layoutTracks(stateRecords(), view, (view.end - view.start) * 46 / width);
      const labels = new Map((state.taxonomy?.labels || []).map(label => [label.label_id, label]));
      for (const track of layout) {
        const row = el('div', undefined, 'btv-timeline-track'); row.append(el('span', `${track.name} (${track.items.length})`, 'btv-timeline-track-name'));
        const lane = el('div', undefined, 'btv-timeline-lane'); lane.style.height = `${track.lanes * 34 + 12}px`; lane.dataset.track = track.key;
        lane.addEventListener('click', event => { if (event.target === lane && !drag) { try { call(onSeek, timeAt(event, lane)); } catch (error) { report(error); } } });
        dropEvents(lane, lane);
        for (const item of track.items) lane.append(makeBlock(item.record, lane, item.lane, labels));
        const cursor = el('span', undefined, 'btv-timeline-cursor'); lane.append(cursor); lanes.push({lane, cursor}); row.append(lane); body.append(row);
      }
      if (focusKey) focusNodes.get(focusKey)?.focus?.({preventScroll: true});
      updateTime(Number(getTime?.()));
    }
    win.addEventListener('pointermove', move); win.addEventListener('pointerup', finish);
    win.addEventListener('pointercancel', event => { if (drag && event.pointerId === drag.pointerId) cancel(); });
    win.addEventListener('keydown', event => { if (event.key === 'Escape' && drag) { event.preventDefault(); event.stopPropagation(); cancel(); } });
    win.addEventListener('resize', () => { cancel(); render(); });
    win.addEventListener('blur', cancel);
    render(); return {render, updateTime, cancel};
  }
  return {mount, movePatch, validateEdit, layoutTracks, ticks, timeText, LABEL_MIME};
});

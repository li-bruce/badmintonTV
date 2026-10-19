/* Single-frame image evidence. No tracking or frame-accurate playback claim. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TrainingRegions = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const roles = {self: '本人', opponent: '对手', partner: '搭档', opponent_partner: '对方搭档'};
  const clone = value => JSON.parse(JSON.stringify(value));
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const rounded = value => Number(value.toFixed(6));
  const uid = () => 'region-' + (globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`);
  function contentRect(rect, width, height) {
    if (!rect || ![rect.left, rect.top, rect.width, rect.height, width, height].every(finite) || Math.min(rect.width, rect.height, width, height) <= 0) return null;
    const scale = Math.min(rect.width / width, rect.height / height), w = width * scale, h = height * scale;
    return {left: rect.left + (rect.width - w) / 2, top: rect.top + (rect.height - h) / 2, width: w, height: h};
  }
  function imagePoint(x, y, rect, width, height) {
    const box = contentRect(rect, width, height);
    if (!box || !finite(x) || !finite(y) || x < box.left || y < box.top || x > box.left + box.width || y > box.top + box.height) return null;
    return {x: rounded((x - box.left) / box.width), y: rounded((y - box.top) / box.height)};
  }
  function cross(a, b, c) { return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x); }
  function intersects(a, b, c, d) {
    const ac = cross(a, b, c), ad = cross(a, b, d), ca = cross(c, d, a), cb = cross(c, d, b);
    const on = (a, b, p) => p.x >= Math.min(a.x, b.x) && p.x <= Math.max(a.x, b.x) && p.y >= Math.min(a.y, b.y) && p.y <= Math.max(a.y, b.y);
    return ((ac > 0 && ad < 0 || ac < 0 && ad > 0) && (ca > 0 && cb < 0 || ca < 0 && cb > 0)) ||
      ac === 0 && on(a, b, c) || ad === 0 && on(a, b, d) || ca === 0 && on(c, d, a) || cb === 0 && on(c, d, b);
  }
  function validatePoints(shape, points) {
    if (!Array.isArray(points) || points.some(p => !p || !finite(p.x) || !finite(p.y) || p.x < 0 || p.x > 1 || p.y < 0 || p.y > 1)) throw new Error('圈选坐标必须是图像内的有限数值');
    const n = points.length;
    if (new Set(points.map(p => `${p.x},${p.y}`)).size !== n) throw new Error('圈选顶点不能重复');
    if (shape === 'rectangle') {
      if (n !== 2 || points[0].x === points[1].x || points[0].y === points[1].y) throw new Error('矩形需要两个对角点，宽高不能为零');
      return [{x: Math.min(points[0].x, points[1].x), y: Math.min(points[0].y, points[1].y)}, {x: Math.max(points[0].x, points[1].x), y: Math.max(points[0].y, points[1].y)}];
    }
    if (shape !== 'polygon' || n < 3 || n > 64) throw new Error('多边形需要 3 至 64 个顶点');
    let area = 0;
    for (let i = 0; i < n; i++) {
      const a = points[i], b = points[(i + 1) % n], prev = points[(i + n - 1) % n];
      area += a.x * b.y - b.x * a.y;
      if (cross(prev, a, b) === 0 && (prev.x - a.x) * (b.x - a.x) + (prev.y - a.y) * (b.y - a.y) > 0) throw new Error('多边形相邻边不能重叠');
      for (let j = i + 1; j < n; j++) if (j !== i + 1 && !(i === 0 && j === n - 1) && intersects(a, b, points[j], points[(j + 1) % n])) throw new Error('多边形不能自交或相互接触');
    }
    if (area === 0) throw new Error('多边形面积不能为零');
    return points.map(p => ({x: p.x, y: p.y}));
  }
  function recordContains(record, at, duration) {
    return !!record && Number.isInteger(at) && finite(duration) && at >= 0 && at < duration &&
      (Number.isInteger(record.at_ms) ? at === record.at_ms : Number.isInteger(record.start_ms) && Number.isInteger(record.end_ms) && at >= record.start_ms && at < record.end_ms);
  }
  function corners(points) {
    const [a, b] = points;
    return [{x: a.x, y: a.y}, {x: b.x, y: a.y}, {x: b.x, y: b.y}, {x: a.x, y: b.y}];
  }
  function timeLabel(ms) { return `${(ms / 1000).toFixed(3)} s`; }
  function mount({doc, win, stage, player, container, getState, getRecord, getTime, getSubject, onChange, onError = () => {}, onBegin = () => {}, onSeek}) {
    let draft = null, selected = null, waitingSeek = false, message = '', selectionContext = '';
    const svg = doc.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'training-region-overlay'); svg.setAttribute('aria-label', '当前时刻图像圈选'); svg.setAttribute('tabindex', '0'); stage.append(svg);
    const toolbar = element('div', undefined, 'training-region-toolbar'), status = element('p', '', 'training-region-status');
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const list = element('div', undefined, 'training-region-list');
    const rectangle = button('画矩形', () => begin('rectangle'), 'rectangle');
    const polygon = button('画多边形', () => begin('polygon'), 'polygon');
    const finish = button('完成多边形 · Enter', finishPolygon, 'finish');
    const abort = button('取消 · Esc', cancel, 'cancel');
    const remove = button('删除所选圈选', removeSelected, 'delete');
    const locate = button('定位所选记录', locateRecord, 'locate');
    toolbar.append(rectangle, polygon, finish, abort, remove, locate);
    container.append(element('h3', '当前记录的图像圈选'), toolbar, status, list);
    function element(tag, text, className) {
      const value = doc.createElement(tag); if (text !== undefined) value.textContent = text;
      if (className) value.className = className; return value;
    }
    function button(text, action, name) {
      const value = element('button', text); value.type = 'button'; value.setAttribute('data-region-action', name);
      value.addEventListener('click', () => { try { action(); } catch (error) { fail(error); } }); return value;
    }
    function currentTime() { const value = getTime(); return finite(value) ? Math.round(value) : NaN; }
    function key() {
      const s = getState(), r = getRecord();
      return JSON.stringify([s.epoch, s.project?.project_id, s.asset?.asset_id, s.asset?.sha256, r?.record_id]);
    }
    function fingerprint() {
      const s = getState();
      return JSON.stringify([key(), s.actorType, getRecord()]);
    }
    function recordReady() {
      const s = getState(), r = getRecord();
      return !!(r && !r.deleted && s.bundle && s.asset && r.asset_id === s.asset.asset_id && r.project_id === s.project?.project_id && s.bundle.asset?.asset_id === s.asset.asset_id);
    }
    function mediaReady() { return !waitingSeek && !player.seeking && player.readyState >= 2 && !!contentRect(player.getBoundingClientRect(), player.videoWidth, player.videoHeight); }
    function regions() {
      const r = getRecord();
      return (r?.evidence || []).filter(e => e.type === 'image_region' && e.record_id === r.record_id && e.asset_id === r.asset_id);
    }
    function chosen() { return regions().find(e => e.evidence_id === selected); }
    function compatible(context) { return context === fingerprint(); }
    function activeValid() { return draft && compatible(draft.context) && currentTime() === draft.at && mediaReady() && player.paused; }
    function clearDraft() { draft = null; svg.classList.remove('drawing'); }
    function cancel() { clearDraft(); message = ''; render(); }
    function fail(error) { clearDraft(); message = error.message || String(error); onError(error); render(); }
    function subject() {
      const r = getRecord(), value = getSubject ? getSubject() : {subject_role: 'self', subject_person_id: r.person_id || null};
      if (!value || !Object.hasOwn(roles, value.subject_role)) throw new Error('先选择圈选主体');
      const person = value.subject_person_id || null;
      if (person !== null && (typeof person !== 'string' || !getState().bundle.people?.some(p => p.person_id === person))) throw new Error('圈选主体不属于当前项目人物');
      return {subject_role: value.subject_role, subject_person_id: person};
    }
    function begin(shape) {
      cancel();
      if (!recordReady()) throw new Error('先选择一条有效标注记录');
      if (!mediaReady()) throw new Error('视频尚未完成定位，请等待画面加载后再圈选');
      const at = currentTime(), s = getState(), r = getRecord();
      if (!recordContains(r, at, s.asset.duration_ms)) throw new Error('当前时间不在所选记录内，请先定位记录，再开始圈选');
      if (!['human', 'agent', 'model'].includes(s.actorType)) throw new Error('当前标注来源不支持圈选');
      const selectedSubject = subject(); onBegin(); player.pause(); selected = null;
      draft = {kind: 'create', shape, points: [], context: fingerprint(), at, actor: s.actorType, subject: selectedSubject, pointer: null};
      message = ''; render(); svg.focus?.({preventScroll: true});
    }
    function navigate(at) {
      cancel(); player.pause();
      if (currentTime() === at && !player.seeking) return render();
      const context = key(); waitingSeek = true; message = '定位中；等待画面加载后再点击绘制'; render();
      try {
        const result = onSeek ? onSeek(at) : (player.currentTime = at / 1000);
        if (result?.catch) result.catch(error => { if (context === key()) { waitingSeek = false; fail(error); } });
      } catch (error) { waitingSeek = false; fail(error); }
    }
    function locateRecord() {
      const r = getRecord(); if (!recordReady()) throw new Error('先选择一条标注记录');
      navigate(Number.isInteger(r.at_ms) ? r.at_ms : r.start_ms);
    }
    function commit(points) {
      if (!activeValid()) throw new Error('记录或时间已变化，圈选草稿已取消');
      const old = draft, r = getRecord(), s = getState();
      if (!recordContains(r, old.at, s.asset.duration_ms)) throw new Error('圈选时间已不属于当前记录');
      const value = old.kind === 'edit' ? {...clone(old.original), points: validatePoints(old.shape, points), observation_source: old.actor} : {
        type: 'image_region', schema_version: '1.0', evidence_id: uid(), record_id: r.record_id, asset_id: r.asset_id,
        at_ms: old.at, coordinate_system: 'image_normalized', shape: old.shape, points: validatePoints(old.shape, points),
        ...old.subject, observation_source: old.actor, precision: 'browser_time'
      };
      const evidence = clone(r.evidence || []);
      if (old.kind === 'edit') {
        const index = evidence.findIndex(e => e.type === 'image_region' && e.evidence_id === value.evidence_id);
        if (index < 0) throw new Error('所选圈选已变化，请重新选择'); evidence[index] = value;
      } else {
        while (evidence.some(e => e.evidence_id === value.evidence_id)) value.evidence_id = uid();
        evidence.push(value);
      }
      clearDraft(); selected = value.evidence_id; message = '圈选已加入当前记录，保存记录后持久化'; onChange(evidence); render();
    }
    function finishPolygon() {
      if (!draft || draft.kind !== 'create' || draft.shape !== 'polygon') return;
      commit(draft.points);
    }
    function removeSelected() {
      if (!recordReady() || !chosen()) return;
      const context = fingerprint(), id = selected; clearDraft();
      const evidence = clone(getRecord().evidence || []).filter(e => !(e.type === 'image_region' && e.evidence_id === id));
      if (!compatible(context)) return;
      selected = null; message = '圈选已移除，保存记录后持久化'; onChange(evidence); render();
    }
    function point(event) { return imagePoint(event.clientX, event.clientY, player.getBoundingClientRect(), player.videoWidth, player.videoHeight); }
    function capture(event) { try { svg.setPointerCapture(event.pointerId); } catch (_) { /* Pointer may already have ended. */ } }
    function editedPoints(p) {
      if (draft.handle !== null) {
        if (draft.shape === 'rectangle') return [corners(draft.initialPoints)[(draft.handle + 2) % 4], p];
        return draft.initialPoints.map((v, i) => i === draft.handle ? p : {...v});
      }
      const dx = p.x - draft.start.x, dy = p.y - draft.start.y;
      return draft.initialPoints.map(v => ({x: rounded(v.x + dx), y: rounded(v.y + dy)}));
    }
    function pointerDown(event) {
      if (event.button !== undefined && event.button !== 0 || event.isPrimary === false) return;
      try {
        const p = point(event);
        if (draft?.kind === 'create') {
          event.preventDefault();
          svg.focus?.({preventScroll: true});
          if (!activeValid()) throw new Error('记录或时间已变化，圈选草稿已取消');
          if (!p) throw new Error('不能在视频黑边或图像外圈选');
          if (draft.shape === 'polygon') {
            if (draft.points.length >= 64) throw new Error('多边形最多 64 个顶点');
            draft.points.push(p); render(); return;
          }
          draft.points = [p, p]; draft.start = p; draft.pointer = event.pointerId; capture(event); paint(); return;
        }
        const id = event.target.getAttribute?.('data-region-id');
        const region = regions().find(e => e.evidence_id === id);
        if (!region || region.at_ms !== currentTime() || !recordReady() || !mediaReady() || !p) return;
        event.preventDefault();
        onBegin(); player.pause(); selected = id;
        const initialPoints = validatePoints(region.shape, region.points);
        if (!['human', 'agent', 'model'].includes(getState().actorType)) throw new Error('当前标注来源不支持修改圈选');
        const rawHandle = event.target.getAttribute?.('data-region-handle');
        const handle = rawHandle === null || rawHandle === undefined ? null : Number(rawHandle);
        draft = {kind: 'edit', shape: region.shape, original: clone(region), initialPoints, points: clone(initialPoints), handle,
          start: p, pointer: event.pointerId, at: region.at_ms, actor: getState().actorType, context: fingerprint()};
        capture(event); render();
      } catch (error) { fail(error); }
    }
    function pointerMove(event) {
      if (!draft || draft.pointer !== event.pointerId) return;
      event.preventDefault();
      try {
        if (!activeValid()) throw new Error('记录或时间已变化，圈选草稿已取消');
        const p = point(event); if (!p) throw new Error('拖动超出图像范围，修改已取消');
        const points = draft.kind === 'edit' ? editedPoints(p) : [draft.start, p];
        if (points.some(v => v.x < 0 || v.x > 1 || v.y < 0 || v.y > 1)) throw new Error('圈选超出图像范围，修改已取消');
        draft.points = points; paint();
      } catch (error) { fail(error); }
    }
    function pointerUp(event) {
      if (!draft || draft.pointer !== event.pointerId) return;
      event.preventDefault();
      try {
        const p = point(event); if (!p) throw new Error('拖动超出图像范围，修改已取消');
        const points = draft.kind === 'edit' ? editedPoints(p) : [draft.start, p];
        if (draft.kind === 'edit' && p.x === draft.start.x && p.y === draft.start.y) { clearDraft(); render(); return; }
        commit(points);
      } catch (error) { fail(error); }
      finally { try { if (svg.hasPointerCapture?.(event.pointerId)) svg.releasePointerCapture(event.pointerId); } catch (_) { /* No active pointer. */ } }
    }
    function svgElement(tag, attrs) {
      const value = doc.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) value.setAttribute(k, String(v)); return value;
    }
    function paint() {
      svg.replaceChildren(); svg.classList.toggle('drawing', !!draft);
      const box = contentRect(player.getBoundingClientRect(), player.videoWidth, player.videoHeight), rect = stage.getBoundingClientRect();
      if (!box || !(rect.width > 0 && rect.height > 0) || !recordReady() || waitingSeek || player.seeking) return;
      svg.setAttribute('viewBox', `0 0 ${rect.width} ${rect.height}`);
      const xy = p => ({x: box.left - rect.left + p.x * box.width, y: box.top - rect.top + p.y * box.height});
      function draw(shape, points, id, preview) {
        if (!points.length) return;
        const vertices = shape === 'rectangle' && points.length === 2 ? corners(points) : points;
        const attrs = {points: vertices.map(p => { const v = xy(p); return `${v.x},${v.y}`; }).join(' '),
          class: 'training-region-shape' + (id === selected ? ' selected' : '') + (preview ? ' draft' : '')};
        if (id && !preview) attrs['data-region-id'] = id;
        svg.append(svgElement(shape === 'polygon' && preview && draft?.kind === 'create' ? 'polyline' : 'polygon', attrs));
        if (id === selected && !draft) for (let i = 0; i < vertices.length; i++) {
          const v = xy(vertices[i]); svg.append(svgElement('circle', {cx: v.x, cy: v.y, r: 6, class: 'training-region-handle', 'data-region-id': id, 'data-region-handle': i}));
        }
        if (preview && shape === 'polygon') for (const p of points) {
          const v = xy(p); svg.append(svgElement('circle', {cx: v.x, cy: v.y, r: 3, class: 'training-region-vertex'}));
        }
      }
      for (const region of regions()) if (region.at_ms === currentTime() && !(draft?.kind === 'edit' && region.evidence_id === selected)) {
        try { draw(region.shape, validatePoints(region.shape, region.points), region.evidence_id, false); } catch (_) { /* Invalid legacy data remains preserved, never plotted. */ }
      }
      if (draft) draw(draft.shape, draft.points, null, true);
    }
    function render() {
      const nextKey = key();
      if (selectionContext !== nextKey) { clearDraft(); selected = null; waitingSeek = false; selectionContext = nextKey; message = ''; }
      if (draft && !activeValid()) { clearDraft(); message = '记录、时间或播放状态已变化，圈选草稿已取消'; }
      if (selected && !chosen()) selected = null;
      const valid = recordReady(), at = currentTime(), inside = valid && recordContains(getRecord(), at, getState().asset.duration_ms);
      rectangle.disabled = polygon.disabled = !valid || !mediaReady();
      finish.hidden = !(draft?.kind === 'create' && draft.shape === 'polygon'); finish.disabled = !draft || draft.points.length < 3;
      abort.hidden = !draft; remove.disabled = !chosen() || !!draft; locate.disabled = !valid || waitingSeek;
      rectangle.setAttribute('aria-pressed', String(draft?.shape === 'rectangle')); polygon.setAttribute('aria-pressed', String(draft?.shape === 'polygon'));
      const instruction = draft ? (draft.kind === 'edit' ? '拖动后松开以确认修改；Esc 取消' : draft.shape === 'rectangle' ? '在画面内拖出矩形，松开确认；Esc 取消' : `逐点添加顶点（${draft.points.length}/64），Enter 或按钮完成；Esc 取消`) :
        !valid ? '先选择一条标注记录' : !inside ? '当前时间不在所选记录内，请先定位记录' : '单帧圈选，可拖动调整';
      status.textContent = (message ? message + '。' : '') + instruction + '。';
      list.replaceChildren();
      for (const region of regions()) {
        const visible = region.at_ms === at && !waitingSeek && !player.seeking;
        const person = getState().bundle?.people?.find(p => p.person_id === region.subject_person_id);
        const row = element('div', undefined, 'training-region-row');
        const select = button(`${region.shape === 'rectangle' ? '矩形' : '多边形'} · ${roles[region.subject_role] || '未知主体'}${person ? ' / ' + person.display_name : ''} · ${timeLabel(region.at_ms)}${visible ? '' : '（其它时刻，未叠加）'}`, () => {
          clearDraft(); selected = region.evidence_id; message = visible ? '拖动框内移动，拖动圆点调整顶点' : '此圈选在其它时刻；定位后才能调整'; render();
        }, 'select');
        select.setAttribute('aria-pressed', String(selected === region.evidence_id));
        row.append(select, button('跳到圈选时间', () => { selected = region.evidence_id; navigate(region.at_ms); }, 'seek')); list.append(row);
      }
      paint();
    }
    function updateTime() { render(); }
    svg.addEventListener('pointerdown', pointerDown); svg.addEventListener('pointermove', pointerMove); svg.addEventListener('pointerup', pointerUp);
    svg.addEventListener('pointercancel', cancel);
    svg.addEventListener('lostpointercapture', event => { if (draft?.pointer === event.pointerId) cancel(); });
    doc.addEventListener('keydown', event => {
      if (!draft || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancel(); }
      else if (event.key === 'Enter' && !/^(INPUT|TEXTAREA|SELECT|BUTTON|A)$/.test(event.target?.tagName) && !event.target?.isContentEditable) {
        event.preventDefault(); event.stopPropagation(); try { finishPolygon(); } catch (error) { fail(error); }
      }
    }, true);
    player.addEventListener('seeking', () => { clearDraft(); render(); });
    player.addEventListener('seeked', () => { waitingSeek = false; message = ''; render(); });
    player.addEventListener('play', cancel);
    for (const event of ['loadedmetadata', 'loadeddata', 'canplay']) player.addEventListener(event, render);
    win.addEventListener('resize', () => { if (draft) cancel(); else paint(); });
    win.addEventListener('blur', () => { if (draft) cancel(); });
    render(); return {render, updateTime, cancel};
  }
  return {mount, contentRect, imagePoint, validatePoints, recordContains};
});

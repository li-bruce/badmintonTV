/* Local training workspace. Source milliseconds and server reviewer identity are authoritative. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else { root.TrainingWorkbench = api; if (root.document) api.mount(root.document, root); }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const clone = value => JSON.parse(JSON.stringify(value));
  const uid = prefix => prefix + '-' + (globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`);
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  function recordOrigin(record) {
    const audit = record.provenance?.revision_audit;
    return {actorType: audit?.actor_type || record.review?.reviewer_type || '未记录', reviewer: audit?.reviewer || record.review?.reviewer || '未记录'};
  }
  function sourceMs(value, duration) {
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0 || !Number.isFinite(duration) || number > duration) throw new Error('原片时间必须在视频范围内');
    return Math.round(number);
  }
  function formatTime(ms) {
    if (!Number.isFinite(ms)) return '—';
    const n = Math.max(0, Math.round(ms));
    return `${String(Math.floor(n / 60000)).padStart(2, '0')}:${String(Math.floor(n / 1000) % 60).padStart(2, '0')}.${String(n % 1000).padStart(3, '0')}`;
  }
  function contentRect(rect, width, height) {
    if (!(width > 0 && height > 0 && rect.width > 0 && rect.height > 0)) return null;
    const scale = Math.min(rect.width / width, rect.height / height);
    const w = width * scale, h = height * scale;
    return {left: rect.left + (rect.width - w) / 2, top: rect.top + (rect.height - h) / 2, width: w, height: h};
  }
  function imagePoint(x, y, rect, width, height) {
    const content = contentRect(rect, width, height);
    if (!content || x < content.left || y < content.top || x > content.left + content.width || y > content.top + content.height) return null;
    return {x: Number(((x - content.left) / content.width).toFixed(6)), y: Number(((y - content.top) / content.height).toFixed(6))};
  }
  function shortcut(event) {
    if (event.defaultPrevented || event.isComposing || event.altKey || event.repeat) return null;
    const target = event.target;
    if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT|BUTTON|A)$/.test(target.tagName) || target.closest?.('[contenteditable="true"], [role="textbox"]'))) return null;
    if (event.ctrlKey || event.metaKey) return event.key.toLowerCase() === 's' ? 'save' : null;
    return {' ': 'play', ArrowLeft: 'previous', ArrowRight: 'next', r: 'rally', c: 'contact', a: 'action', f: 'footwork', t: 'tactics', i: 'start', o: 'end'}[event.key.length === 1 ? event.key.toLowerCase() : event.key] || null;
  }
  function makeRequest(fetcher) {
    return async function request(path, method = 'GET', body) {
      const response = await fetcher('/api/v1/training' + path, {method, headers: {'Content-Type': 'application/json'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      let value;
      try { value = await response.json(); } catch (_) { value = {}; }
      if (!response.ok) {
        const detail = value.detail ?? value.error ?? value;
        const error = new Error(typeof detail === 'string' ? detail : detail.message || JSON.stringify(detail));
        error.status = response.status; error.detail = detail; throw error;
      }
      return value;
    };
  }
  function createController({request, confirm = () => true, changed = () => {}}) {
    const state = {projects: [], catalog: [], registered: [], project: null, assets: [], taxonomy: null, actorType: 'agent',
      splits: [], splitDraft: [], splitDirty: false, snapshots: [], asset: null, bundle: null, saved: null, selectedId: null, dirty: false, conflict: false,
      epoch: 0, mutation: 0, saving: false, frames: null, error: null};
    const notify = () => changed(state);
    const allowed = (includeSplits = false) => !(state.dirty || (includeSplits && state.splitDirty)) || confirm('当前有未保存的标注或分组修改。放弃这些修改并继续？');
    const projectPath = id => '/projects/' + encodeURIComponent(id);
    const bundlePath = (project, asset) => projectPath(project) + '/bundles/' + encodeURIComponent(asset);
    function edit(change) {
      if (!state.bundle) return;
      change(state.bundle); state.dirty = true; state.mutation++; notify();
    }
    async function boot() {
      const [projects, catalog, registered] = await Promise.all([request('/projects'), request('/catalog'), request('/assets')]);
      state.projects = projects; state.catalog = catalog.assets; state.registered = registered; notify();
    }
    async function openProject(id) {
      if (!allowed(true)) { notify(); return false; }
      const epoch = ++state.epoch;
      state.asset = state.bundle = state.saved = null; state.dirty = false; state.conflict = false; state.selectedId = null;
      state.project = null; state.assets = []; state.frames = null; state.snapshots = []; state.error = null; state.splitDirty = false; state.splitDraft = []; notify();
      if (!id) return true;
      const detail = await request(projectPath(id));
      if (epoch !== state.epoch) return false;
      state.project = detail.project; state.assets = detail.assets; state.taxonomy = detail.taxonomy;
      state.splits = detail.splits || []; state.splitDraft = clone(state.splits); state.actorType = detail.actor_type || 'agent'; notify();
      const snapshots = await request(projectPath(id) + '/snapshots');
      if (epoch === state.epoch) { state.snapshots = snapshots; notify(); }
      return true;
    }
    async function openAsset(id, force = false) {
      if (!force && !allowed()) { notify(); return false; }
      const asset = state.assets.find(item => item.asset_id === id);
      if (!asset || !state.project) return false;
      const epoch = ++state.epoch, project = state.project.project_id;
      state.asset = asset; state.bundle = state.saved = null; state.selectedId = null; state.frames = null;
      state.dirty = state.conflict = false; state.error = null; notify();
      const bundle = await request(bundlePath(project, id));
      if (epoch !== state.epoch) return false;
      state.bundle = clone(bundle); state.saved = clone(bundle); notify();
      try {
        const frames = await request('/assets/' + encodeURIComponent(id) + '/source-frames?at_ms=0&limit=128');
        if (epoch === state.epoch) { state.frames = frames; notify(); }
      } catch (error) { if (epoch === state.epoch) { state.error = '源 PTS 不可用：' + error.message; notify(); } }
      return true;
    }
    async function refreshProject(epoch = state.epoch) {
      if (!state.project) return;
      const id = state.project.project_id;
      const detail = await request(projectPath(id));
      if (epoch !== state.epoch || state.project?.project_id !== id) return;
      state.project = detail.project; state.assets = detail.assets; state.splits = detail.splits || [];
      if (!state.splitDirty) state.splitDraft = clone(state.splits);
      state.actorType = detail.actor_type || 'agent'; notify();
    }
    async function save() {
      if (state.saving) throw new Error('上次保存尚未完成');
      if (!state.bundle || !state.project || !state.asset) throw new Error('先选择视频');
      const epoch = state.epoch, mutation = state.mutation, payload = clone(state.bundle);
      payload.revision = Math.max(1, payload.revision);
      const path = bundlePath(state.project.project_id, state.asset.asset_id), expected = state.saved.revision;
      state.saving = true; notify();
      try {
        const saved = await request(path, 'PUT', {bundle: payload, expected_revision: expected});
        if (epoch !== state.epoch) return saved;
        state.saved = clone(saved); state.conflict = false;
        if (state.mutation === mutation) { state.bundle = clone(saved); state.dirty = false; }
        else { state.bundle.revision = saved.revision; state.dirty = true; }
        notify(); await refreshProject(epoch); return saved;
      } catch (error) {
        if (epoch === state.epoch && error.status === 409) { state.conflict = true; state.dirty = true; notify(); }
        throw error;
      } finally { state.saving = false; notify(); }
    }
    function discard() {
      if (!allowed()) return false;
      state.bundle = clone(state.saved); state.dirty = false; state.conflict = false; state.mutation++;
      if (!state.bundle?.records?.some(item => item.record_id === state.selectedId)) state.selectedId = null;
      notify(); return true;
    }
    async function createProject(name) {
      if (!name.trim()) throw new Error('请输入项目名称');
      if (!allowed(true)) return false;
      const epoch = state.epoch, mutation = state.mutation;
      const project = await request('/projects', 'POST', {name: name.trim()});
      state.projects = await request('/projects');
      if (epoch !== state.epoch) { notify(); return project; }
      if (mutation === state.mutation) { state.dirty = false; state.splitDirty = false; }
      await openProject(project.project_id); return project;
    }
    async function addAsset(id) {
      if (!state.project) throw new Error('先创建或选择项目');
      const epoch = state.epoch, path = projectPath(state.project.project_id);
      await request(path + '/assets', 'POST', {asset_id: id, expected_revision: state.project.revision});
      await refreshProject(epoch);
    }
    async function saveSplits(splits) {
      if (!state.project) throw new Error('先选择项目');
      const epoch = state.epoch;
      await request(projectPath(state.project.project_id) + '/splits', 'PUT', {expected_revision: state.project.revision, splits});
      if (epoch === state.epoch && JSON.stringify(splits) === JSON.stringify(state.splitDraft)) state.splitDirty = false;
      await refreshProject(epoch);
    }
    function editSplit(group, split) {
      const existing = state.splitDraft.find(item => item.group_id === group);
      if (existing) existing.split = split; else state.splitDraft.push({group_id: group, split});
      state.splitDirty = true; notify();
    }
    async function snapshot() {
      if (!state.project) throw new Error('先选择项目');
      const epoch = state.epoch, id = state.project.project_id;
      if (state.dirty) await save();
      if (epoch !== state.epoch || state.project?.project_id !== id) throw new Error('项目已切换，请重新生成快照');
      if (state.splitDirty) await saveSplits(clone(state.splitDraft));
      if (epoch !== state.epoch || state.project?.project_id !== id) throw new Error('项目已切换，请重新生成快照');
      const result = await request(projectPath(id) + '/snapshots', 'POST', {expected_revision: state.project.revision});
      if (epoch === state.epoch) { state.snapshots.unshift(result); notify(); }
      return result;
    }
    async function step(ms, direction, anchor = null) {
      if (!state.asset) return null;
      const epoch = state.epoch, id = state.asset.asset_id, duration = state.asset.duration_ms;
      if (!state.frames) return {source_pts_ms: clamp(ms + direction * 40, 0, duration), exact: false};
      if (anchor && Number.isInteger(anchor.source_frame_index)) {
        const index = Math.max(0, anchor.source_frame_index + direction);
        const target = await request('/assets/' + encodeURIComponent(id) + '/source-frames?offset_frame=' + index + '&limit=1');
        if (epoch !== state.epoch) return null;
        return target.source_frames[0] ? {...target.source_frames[0], exact: true} : {...anchor, exact: true};
      }
      const page = await request('/assets/' + encodeURIComponent(id) + '/source-frames?at_ms=' + Math.floor(clamp(ms, 0, Math.max(0, duration - 1))) + '&limit=2');
      if (epoch !== state.epoch) return null;
      const current = page.source_frames[0];
      if (!current) throw new Error('此位置没有已验证源帧');
      const index = clamp(current.source_frame_index + direction, 0, page.total - 1);
      let frame = page.source_frames.find(item => item.source_frame_index === index);
      if (!frame) {
        const target = await request('/assets/' + encodeURIComponent(id) + '/source-frames?offset_frame=' + index + '&limit=1');
        if (epoch !== state.epoch) return null;
        frame = target.source_frames[0];
      }
      return frame ? {...frame, exact: true} : null;
    }
    function record() { return state.bundle?.records.find(item => item.record_id === state.selectedId && !item.deleted); }
    function modifyRecord(change, reviewOnly = false) {
      const selected = record(); if (!selected) return;
      edit(() => {
        change(selected);
        if (!reviewOnly) selected.review = {status: 'pending', reviewer_type: state.actorType, reviewer: 'local-' + state.actorType, note: ''};
      });
    }
    function newRecord(type, ms) {
      if (!state.bundle) throw new Error('先选择已加入项目的视频');
      const duration = state.asset.duration_ms, at = sourceMs(ms, duration);
      if (at >= duration && type !== 'dead_ball') throw new Error('该标记必须早于原片结束');
      const kind = ['action', 'footwork', 'tactics'].includes(type) ? 'segment' : type;
      const current = record();
      const rally = current?.kind === 'rally' ? current : state.bundle.records.find(item => item.record_id === current?.rally_id && !item.deleted);
      const value = {record_id: uid('record'), project_id: state.project.project_id, asset_id: state.asset.asset_id, kind,
        person_id: null, team_id: null, rally_id: kind === 'rally' ? null : (rally && at >= rally.start_ms && at < rally.end_ms ? rally.record_id : null),
        judgements: [], visibility: 'unknown', unknown_reasons: [], review: {status: 'draft', reviewer_type: state.actorType, reviewer: 'local-' + state.actorType},
        revision: 1, previous_revision: null, deleted: false, provenance: {ui: 'training-workbench', title: ''}, evidence: []};
      if (['rally', 'segment'].includes(kind)) { value.start_ms = at; value.end_ms = Math.min(duration, at + 1000); }
      else value.at_ms = at;
      if (kind === 'segment') value.segment_type = {action: 'stroke', footwork: 'footwork', tactics: 'tactic'}[type];
      if (kind === 'state') value.state = {self: null, opponent: null, partner: null, missing_reasons: []};
      state.selectedId = value.record_id; edit(bundle => bundle.records.push(value)); return value;
    }
    function finishRally(ms) {
      const selected = record();
      const rally = selected?.kind === 'rally' ? selected : state.bundle?.records.find(item => item.record_id === selected?.rally_id && !item.deleted);
      if (!rally) throw new Error('先选择需要结束的回合，或该回合内的一条记录');
      const at = sourceMs(ms, state.asset.duration_ms);
      if (at <= rally.start_ms) throw new Error('死球时刻必须晚于回合起点');
      edit(bundle => {
        let dead = bundle.records.find(item => item.record_id === rally.dead_ball_id && !item.deleted);
        if (!dead) {
          dead = {record_id: uid('record'), project_id: state.project.project_id, asset_id: state.asset.asset_id, kind: 'dead_ball', at_ms: at,
            rally_id: rally.record_id, judgements: [], visibility: 'unknown', unknown_reasons: [], revision: 1, previous_revision: null,
            deleted: false, provenance: {ui: 'training-workbench'}, review: {status: 'draft', reviewer_type: state.actorType, reviewer: 'local-' + state.actorType}};
          bundle.records.push(dead);
        }
        dead.at_ms = at; rally.end_ms = at; rally.dead_ball_id = dead.record_id;
        for (const item of [rally, dead]) item.review = {status: 'pending', reviewer_type: state.actorType, reviewer: 'local-' + state.actorType};
      });
    }
    function review(status) {
      if (status === 'confirmed' && state.actorType !== 'human') throw new Error('服务器当前来源不是 human，不能确认人工真值');
      modifyRecord(item => { item.review = {status, reviewer_type: state.actorType, reviewer: 'local-' + state.actorType}; }, true);
    }
    function removeRecord(cascade = false) {
      const selected = record(); if (!selected) return;
      const related = state.bundle.records.filter(item => !item.deleted && (item.rally_id === selected.record_id || item.dead_ball_id === selected.record_id));
      if (related.length && !cascade) throw new Error('这条记录仍有关联标注，请先确认关联删除');
      edit(() => {
        for (const item of [selected, ...(selected.kind === 'rally' ? related : [])]) {
          item.deleted = true; item.review = {status: 'pending', reviewer_type: state.actorType, reviewer: 'local-' + state.actorType};
        }
        if (selected.kind === 'dead_ball') for (const item of related) {
          item.dead_ball_id = null; item.review = {status: 'pending', reviewer_type: state.actorType, reviewer: 'local-' + state.actorType};
        }
      }); state.selectedId = null; notify();
    }
    return {state, boot, edit, openProject, openAsset, refreshProject, save, discard, createProject, addAsset, saveSplits, editSplit, snapshot, step, notify, record, modifyRecord, newRecord, finishRally, review, removeRecord};
  }
  function mount(doc, win) {
    const $ = id => doc.getElementById(id), player = $('training-player');
    const request = makeRequest(win.fetch.bind(win));
    let inEdit = false, loadedAsset = null, frameAnchor = null, pickRole = null, stepSerial = 0;
    const registrations = new Map();
    function el(tag, text, className) { const node = doc.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
    function message(text = '', error = false) { $('notice').textContent = text; $('notice').hidden = !text; $('notice').classList.toggle('error', error); }
    function run(action) { return Promise.resolve().then(action).catch(error => { message(error.message || String(error), true); }); }
    const ctl = createController({request, confirm: text => win.confirm(text), changed: render});
    const s = ctl.state;
    const types = {rally: '回合', contact: '触球点', dead_ball: '死球点', action: '动作区间', footwork: '步法区间', tactics: '战术区间', state: '态势点'};
    const reviews = {draft: '草稿', pending: '待审核', confirmed: '人工确认', rejected: '已拒绝'};
    const judgments = {unlabeled: '未标', present: '存在', absent: '不存在', unknown: '未知', unobservable: '看不清', not_applicable: '不适用'};
    const visibility = {unknown: '未知', clear: '清楚', partial: '部分可见', unobservable: '看不清'};
    const identities = {unknown: '身份未知', unconfirmed: '名称待确认', confirmed: '身份已核对'};
    const roles = {self: '本人', opponent: '对手', partner: '搭档', opponent_partner: '对方搭档'};
    const dimensions = {stroke: '击球', hand_technique: '手法', footwork: '步法', ball: '球路', shuttle: '羽毛球与球路', state: '态势', player_state: '人物态势', tactic: '战术', singles_pattern: '单打多拍模式', doubles_pattern: '双打配合模式', interpretation: '解释与意图', outcome: '结果与评估'};
    const typeOf = record => record.kind === 'segment' ? ({stroke: 'action', footwork: 'footwork', tactic: 'tactics'}[record.segment_type] || 'action') : record.kind;
    const activeRecords = () => (s.bundle?.records || []).filter(record => !record.deleted);
    const timeOf = record => record.at_ms ?? record.start_ms;
    const now = () => sourceMs(Math.max(0, player.currentTime || 0) * 1000, s.asset?.duration_ms || 0);
    function options(select, items, value, placeholder) {
      select.replaceChildren();
      if (placeholder !== undefined) { const option = el('option', placeholder); option.value = ''; select.append(option); }
      for (const [key, name] of items) { const option = el('option', name); option.value = key; select.append(option); }
      select.value = value ?? '';
    }
    function button(text, handler, className = 'quiet compact') { const node = el('button', text, className); node.type = 'button'; node.addEventListener('click', () => run(handler)); return node; }
    function teamName(person) { return person.provenance?.team_name || (person.team_id ? '已登记队伍' : '队伍未知'); }
    function teams() { return [...new Map((s.bundle?.people || []).filter(p => p.team_id).map(p => [p.team_id, teamName(p)])).entries()]; }
    function listButton(title, meta, action, active = false) {
      const node = button('', action, 'list-item' + (active ? ' active' : '')); node.append(el('strong', title), el('small', meta)); return node;
    }
    function editRecord(change) { inEdit = true; try { ctl.modifyRecord(change); } finally { inEdit = false; } }
    function field(id, value) { $(id).value = value ?? ''; }
    function updateTime() {
      $('source-time').textContent = '原片 ' + formatTime((player.currentTime || 0) * 1000);
      if (frameAnchor) $('frame-evidence').textContent = `源帧 ${frameAnchor.source_frame_index} · PTS ${frameAnchor.source_pts} · ${frameAnchor.source_pts_ms.toFixed(3)} ms（定位锚点，浏览器画面未逐帧核实）`;
      else $('frame-evidence').textContent = '浏览器时间定位；未进行精确源帧核查';
    }
    function seek(ms, anchor = null) {
      if (!s.asset) return;
      const value = sourceMs(ms, s.asset.duration_ms);
      player.pause(); frameAnchor = anchor; player.currentTime = value / 1000; field('seek-ms', value); updateTime();
    }
    async function step(direction) {
      const serial = ++stepSerial;
      const target = await ctl.step(now(), direction, frameAnchor);
      if (!target || serial !== stepSerial) return;
      seek(target.source_pts_ms, target.exact ? target : null);
    }
    function markers() {
      $('coordinate-markers').replaceChildren();
      const record = ctl.record(); if (!record?.state) return;
      const stage = $('video-stage').getBoundingClientRect();
      const content = contentRect(stage, player.videoWidth, player.videoHeight); if (!content) return;
      for (const role of Object.keys(roles)) {
        const point = record.state[role]?.position;
        if (!point || point.coordinate_system !== 'image_normalized') continue;
        const mark = el('div', undefined, 'coordinate-marker');
        mark.style.left = `${content.left - stage.left + point.x * content.width}px`;
        mark.style.top = `${content.top - stage.top + point.y * content.height}px`;
        mark.append(el('span', roles[role])); $('coordinate-markers').append(mark);
      }
    }
    function cancelPick() { pickRole = null; $('coordinate-overlay').hidden = true; $('cancel-position').hidden = true; }
    function render() {
      options($('project-select'), s.projects.map(p => [p.project_id, p.name]), s.project?.project_id, '选择项目');
      $('project-meta').textContent = s.project ? `修订 ${s.project.revision} · 词表 ${s.project.taxonomy_version} · ${s.assets.length} 条视频` : '项目、修订与快照保存在独立训练空间。';
      $('actor-type').textContent = s.actorType === 'human' ? 'Human · 服务器授权真人标注' : `${s.actorType} · 非人工真值来源`;
      $('actor-name').readOnly = true; field('actor-name', 'local-' + s.actorType);
      $('actor-help').textContent = s.actorType === 'human' ? '来源由服务器指定。内容修订会清除旧确认，需另行审核。' : '来源由服务器指定；此会话不能升级为真人审核。';
      for (const option of $('participant-identity').options) if (option.value === 'confirmed') option.disabled = s.actorType !== 'human';
      if (s.actorType !== 'human' && $('participant-identity').value === 'confirmed') $('participant-identity').value = 'unconfirmed';
      $('saved-state').textContent = s.saving ? '正在保存…' : s.dirty ? '有未保存标注' : s.splitDirty ? '有未保存分组' : s.bundle ? `已加载 · 修订 ${s.saved.revision}` : '尚未编辑';
      $('saved-state').classList.toggle('dirty', s.dirty || s.splitDirty);
      $('create-snapshot').disabled = !s.project || s.saving;
      for (const id of ['play-pause', 'step-prev', 'step-next', 'seek-time', 'new-rally', 'finish-rally', 'mark-contact', 'new-action', 'new-footwork', 'new-tactics', 'new-state']) $(id).disabled = !s.bundle;
      $('save-record').disabled = !s.bundle || s.saving;
      $('save-bundle').disabled = !s.bundle || s.saving;
      $('add-participant').disabled = !s.bundle;
      $('conflict-panel').hidden = !s.conflict;
      $('video-list').replaceChildren();
      const filter = $('video-filter').value.trim().toLowerCase();
      for (const asset of s.assets.filter(item => (item.title + ' ' + (item.group_id || '')).toLowerCase().includes(filter))) {
        $('video-list').append(listButton(asset.title || '未命名视频', `${formatTime(asset.duration_ms)} · ${asset.group_status === 'confirmed' ? '比赛组已核验' : '比赛组未确认'}`, () => ctl.openAsset(asset.asset_id), asset.asset_id === s.asset?.asset_id));
      }
      if (!s.assets.length) $('video-list').append(el('p', s.project ? '从下方已登记目录添加视频。' : '先选择或创建项目。', 'empty'));
      renderCatalog();
      const key = s.asset ? `${s.project.project_id}/${s.asset.asset_id}/${s.asset.sha256}` : null;
      if (key !== loadedAsset) {
        loadedAsset = key; cancelPick(); frameAnchor = null; stepSerial++; player.pause();
        if (s.asset?.media_url) player.src = s.asset.media_url; else player.removeAttribute('src');
        player.load(); updateTime();
      }
      $('video-title').textContent = s.asset?.title || '选择一条已登记视频';
      $('video-meta').textContent = s.asset ? `${formatTime(s.asset.duration_ms)} · 训练专用引用 · ${s.asset.width || '—'} × ${s.asset.height || '—'} · 原片只读` : '原片只读引用，不复制视频。';
      $('step-prev').textContent = s.frames ? '← 上一源 PTS' : '← 前移 40 ms';
      $('step-next').textContent = s.frames ? '下一源 PTS →' : '后移 40 ms →';
      $('step-help').textContent = s.frames ? `已核验源 PTS，共 ${s.frames.total} 帧；使用真实时间戳定位，浏览器呈现不声明逐帧精确。` : (s.error || '源 PTS 尚未加载；临时按 40 ms 移动，不用 FPS 推算帧号。');
      renderPeople(); renderRecords(); renderSplits(); renderSnapshots();
      if (!inEdit) renderEditor(); markers();
    }
    function renderCatalog() {
      $('catalog-list').replaceChildren();
      const inProject = new Set(s.assets.map(a => a.asset_id));
      for (const asset of s.catalog) {
        const registered = s.registered.some(item => (item.asset_id || item.asset?.asset_id) === asset.asset_id);
        const status = registrations.get(asset.asset_id);
        const item = listButton(asset.title || '未命名视频', inProject.has(asset.asset_id) ? '已在项目中' : status || (registered ? '已登记 · 点击加入项目' : '点击校验并登记原片'), async () => {
          if (!s.project) throw new Error('先选择或创建项目');
          if (registered) return ctl.addAsset(asset.asset_id);
          const project = s.project.project_id;
          registrations.set(asset.asset_id, '等待原片身份校验…'); renderCatalog();
          try {
            let task = await request('/registrations', 'POST', {asset_id: asset.asset_id});
            const started = Date.now();
            while (['queued', 'running'].includes(task.status)) {
              registrations.set(asset.asset_id, task.status === 'running' ? '正在校验原片；尚未完成' : '等待校验'); renderCatalog();
              await new Promise(resolve => win.setTimeout(resolve, 1500));
              if (Date.now() - started > 900000) throw new Error('登记仍在后台进行，请稍后刷新目录');
              task = await request('/registrations/' + encodeURIComponent(task.registration_id));
            }
            if (task.status !== 'ready') throw new Error(task.error || '原片登记未完成');
            s.registered = await request('/assets');
            if (s.project?.project_id === project) await ctl.addAsset(asset.asset_id);
            message('原片身份校验完成，已登记。');
          } finally { registrations.delete(asset.asset_id); renderCatalog(); }
        });
        item.disabled = !s.project || inProject.has(asset.asset_id) || registrations.has(asset.asset_id); $('catalog-list').append(item);
      }
    }
    function renderPeople() {
      $('participant-list').replaceChildren();
      for (const person of s.bundle?.people || []) {
        const row = el('div', undefined, 'person-row'); row.append(el('strong', person.display_name), el('small', teamName(person), 'muted'));
        const select = el('select'); options(select, Object.entries(identities), person.identity_status); select.setAttribute('aria-label', person.display_name + '身份核查');
        for (const option of select.options) if (option.value === 'confirmed') option.disabled = s.actorType !== 'human';
        select.addEventListener('change', () => run(() => { if (select.value === 'confirmed' && s.actorType !== 'human') throw new Error('当前服务器来源不能新增人工确认身份'); ctl.edit(() => { person.identity_status = select.value; }); })); row.append(select); $('participant-list').append(row);
      }
      if (!s.bundle) $('participant-list').append(el('p', '选择视频后可登记人物。', 'muted'));
    }
    function renderRecords() {
      $('record-list').replaceChildren(); const records = activeRecords();
      $('record-count').textContent = `${records.length} 条 · ${records.filter(r => r.review.status === 'pending').length} 条待审核`;
      const filter = $('record-filter').value;
      for (const record of records.filter(r => !filter || typeOf(r) === filter).sort((a, b) => timeOf(a) - timeOf(b))) {
        const item = button('', () => { s.selectedId = record.record_id; cancelPick(); renderEditor(); renderRecords(); markers(); seek(timeOf(record)); }, 'record-item' + (s.selectedId === record.record_id ? ' active' : ''));
        item.append(el('span', formatTime(timeOf(record)), 'time'), el('span', record.provenance?.title || types[typeOf(record)]), el('span', reviews[record.review.status] + ' · 来源 ' + recordOrigin(record).actorType, 'review'));
        $('record-list').append(item);
      }
      if (!records.length) $('record-list').append(el('p', '在播放器下方标记触球或区间。', 'empty'));
    }
    function renderEditor() {
      const record = ctl.record(); $('annotation-form').hidden = !record; $('editor-empty').hidden = Boolean(record);
      $('editor-title').textContent = record ? (record.provenance?.title || types[typeOf(record)]) : '新建或选择一条标注';
      $('record-revision').textContent = record ? `记录修订 ${record.revision}` : '';
      if (!record) return;
      field('record-kind', typeOf(record)); field('record-title', record.provenance?.title);
      field('record-time', record.at_ms); field('record-start', record.start_ms); field('record-end', record.end_ms);
      field('uncertainty-start', record.uncertainty_start_ms); field('uncertainty-end', record.uncertainty_end_ms);
      const point = ['contact', 'dead_ball', 'state'].includes(record.kind);
      $('point-fields').hidden = !point; $('interval-fields').hidden = point;
      $('record-kind').disabled = true;
      $('time-help').textContent = record.kind === 'rally' ? (record.dead_ball_id ? '终点已关联独立死球标记。' : '当前终点是可编辑范围；请定位死球并点击“回合终点 / 死球”完成回合。') : '区间为 [开始, 结束)，所有时间均为原片毫秒。';
      options($('record-rally'), activeRecords().filter(r => r.kind === 'rally').map(r => [r.record_id, `${r.provenance?.title || '回合'} ${formatTime(r.start_ms)}–${formatTime(r.end_ms)}`]), record.rally_id, '未关联 / 不适用');
      $('record-rally').disabled = record.kind === 'rally';
      options($('record-player'), (s.bundle.people || []).map(p => [p.person_id, p.display_name]), record.person_id, '身份未知');
      options($('record-team'), teams(), record.team_id, '未指定');
      options($('record-visibility'), Object.entries(visibility), record.visibility);
      field('record-reason', (record.unknown_reasons || []).join('；'));
      field('record-notes', record.provenance?.notes || '');
      $('evidence-summary').textContent = record.evidence?.length ? `已添加 ${record.evidence.length} 条源片证据：` + record.evidence.filter(e => e.type === 'source_time').map(e => formatTime(e.at_ms)).join('、') : '尚未添加时间证据。选择标签不会自动伪造证据。';
      options($('record-review'), Object.entries(reviews), record.review.status);
      for (const option of $('record-review').options) if (option.value === 'confirmed') option.disabled = s.actorType !== 'human';
      const origin = recordOrigin(record);
      $('review-provenance').textContent = `记录来源：${origin.actorType} / ${origin.reviewer}。审核状态：${reviews[record.review.status]}；审核人：${record.review.reviewer_type || '未记录'} / ${record.review.reviewer || '未记录'}。当前服务来源：${s.actorType}。编辑来源不等于人工确认；修改内容后需重新审核。`;
      $('delete-record').hidden = false; field('incoming-ball', record.state?.incoming_ball); field('outgoing-ball', record.state?.outgoing_ball);
      const subject = $('label-subject-role').value || 'self';
      options($('label-subject-person'), s.bundle.people.map(p => [p.person_id, p.display_name]), subject === 'self' ? record.person_id : record.state?.[subject]?.person_id, '身份未知');
      renderTaxonomy(record); renderStates(record);
    }
    function renderTaxonomy(record) {
      const container = $('taxonomy-labels'); container.replaceChildren();
      const query = $('label-filter').value.trim().toLowerCase(), labels = s.taxonomy?.labels || [];
      const subject = $('label-subject-role').value || 'self', person = $('label-subject-person').value || null;
      const matchesSubject = j => (j.subject_role || 'self') === subject && (j.subject_person_id || null) === person;
      const byId = new Map(labels.map(item => [item.label_id, item]));
      const pathName = label => { const names = [label.name]; let p = byId.get(label.parent_id); while (p) { names.unshift(p.name); p = byId.get(p.parent_id); } return names.join(' › '); };
      const groups = new Map();
      for (const label of labels.filter(label => label.kinds.includes(record.kind) && (pathName(label) + label.description + label.dimension + (dimensions[label.dimension] || '')).toLowerCase().includes(query))) {
        if (!groups.has(label.dimension)) groups.set(label.dimension, []); groups.get(label.dimension).push(label);
      }
      for (const [dimension, members] of groups) {
        const family = el('details', undefined, 'label-family'); family.open = Boolean(query) || members.some(label => record.judgements.some(j => j.label_id === label.label_id));
        family.append(el('summary', `${dimensions[dimension] || dimension} · ${members.length} 项`));
        for (const label of members) {
          if (label.selectable === false) { family.append(el('p', pathName(label), 'taxonomy-directory')); continue; }
          const judgement = record.judgements.find(j => j.label_id === label.label_id && matchesSubject(j));
          const item = el('div', undefined, 'label-item');
          const row = el('div', undefined, 'label-row'), desc = el('div');
          desc.append(el('label', label.name));
          const select = el('select'); options(select, Object.entries(judgments), judgement?.value || 'unlabeled'); select.setAttribute('aria-label', pathName(label) + '判断');
          select.addEventListener('change', () => { ctl.modifyRecord(r => {
            if (subject !== 'self') { r.state ||= {}; r.state[subject] ||= {person_id: person, position: null, missing_reasons: []}; }
            let j = r.judgements.find(item => item.label_id === label.label_id && matchesSubject(item));
            if (!j) { j = {label_id: label.label_id, value: select.value, subject_role: subject, subject_person_id: person, mapping_status: 'manual'}; r.judgements.push(j); } else j.value = select.value;
          }); }); row.append(desc, select); item.append(row);
          if (judgement && judgement.value !== 'unlabeled') {
            const reason = el('input'); reason.value = judgement.reason || ''; reason.placeholder = ['unknown', 'unobservable', 'absent'].includes(judgement.value) ? '本主体此项判断的具体理由（必填）' : '本主体此项判断的观察理由'; reason.setAttribute('aria-label', roles[subject] + label.name + '理由');
            reason.addEventListener('input', () => editRecord(r => { r.judgements.find(j => j.label_id === label.label_id && matchesSubject(j)).reason = reason.value; })); item.append(reason);
          }
          const definition = el('details', undefined, 'label-definition'); definition.open = false;
          definition.append(el('summary', '定义与判断依据'), el('p', pathName(label), 'taxonomy-path'), el('p', label.description, 'definition'));
          if (label.status === 'provisional') definition.append(el('p', '定义待审核', 'muted'));
          item.append(definition); family.append(item);
        }
        container.append(family);
      }
      if (!groups.size) container.append(el('p', '此类型暂无匹配标签。', 'muted'));
    }
    function renderStates(record) {
      $('state-list').replaceChildren();
      for (const role of Object.keys(roles)) {
        const actor = record.state?.[role]; if (!actor) continue;
        const card = el('div', undefined, 'state-card'), head = el('div', undefined, 'section-heading');
        head.append(el('strong', roles[role]), button('移除', () => { cancelPick(); ctl.modifyRecord(r => { r.state[role] = null; }); })); card.append(head);
        const label = el('label', '人物'), select = el('select');
        options(select, s.bundle.people.map(p => [p.person_id, p.display_name]), actor.person_id, '身份未知');
        select.addEventListener('change', () => ctl.modifyRecord(r => { const person = s.bundle.people.find(p => p.person_id === select.value); r.state[role].person_id = person?.person_id || null; r.state[role].team_id = person?.team_id || null; if (role === 'self') { r.person_id = person?.person_id || null; r.team_id = person?.team_id || null; } for (const j of r.judgements) if ((j.subject_role || 'self') === role) j.subject_person_id = person?.person_id || null; }));
        label.append(select); card.append(label);
        const moveLabel = el('label', '移动观察'), movement = el('input'); movement.value = actor.movement || ''; movement.placeholder = '方向、回位、支撑或未知';
        movement.addEventListener('input', () => editRecord(r => { r.state[role].movement = movement.value || null; })); moveLabel.append(movement); card.append(moveLabel);
        const missing = el('label', '缺失理由'), input = el('input'); input.value = (actor.missing_reasons || []).join('；'); input.placeholder = '例如：远端人物脚部不可见';
        input.addEventListener('input', () => editRecord(r => { r.state[role].missing_reasons = input.value.trim() ? [input.value.trim()] : []; })); missing.append(input); card.append(missing);
        const position = actor.position;
        card.append(el('p', position ? `图像归一坐标 x=${position.x.toFixed(4)}, y=${position.y.toFixed(4)} · ${position.source}` : '图像位置未标；不默认为 (0, 0)', 'state-position'));
        card.append(button('在当前画面点选位置', () => { if (!player.videoWidth) throw new Error('请等待原视频画面加载'); player.pause(); pickRole = role; $('coordinate-overlay').hidden = false; $('cancel-position').hidden = false; $('video-stage').scrollIntoView({block: 'center'}); message(`在视频画面点击${roles[role]}位置；只记录图像归一坐标。`); }));
        if (position) card.append(button('清除位置', () => ctl.modifyRecord(r => { r.state[role].position = null; })));
        $('state-list').append(card);
      }
      $('add-state').disabled = Object.keys(roles).every(role => record.state?.[role]);
    }
    function renderSplits() {
      const current = new Map(s.splitDraft.map(item => [item.group_id, item.split]));
      $('split-list').replaceChildren();
      const groups = new Map(); for (const asset of s.assets) if (asset.group_id) { const values = groups.get(asset.group_id) || []; values.push(asset); groups.set(asset.group_id, values); }
      for (const [group, assets] of groups) {
        const label = el('label', `${group} · ${assets.length} 条视频`), select = el('select'); select.dataset.groupId = group;
        options(select, [['unassigned', '未分配'], ['train', '训练集'], ['validation', '验证集'], ['test', '测试集']], current.get(group) || 'unassigned');
        select.disabled = assets.some(a => a.group_status !== 'confirmed'); label.append(select);
        select.addEventListener('change', () => ctl.editSplit(group, select.value));
        if (select.disabled) label.append(el('span', '比赛组尚未可信确认，不能分配。', 'muted')); $('split-list').append(label);
      }
      if (s.assets.some(a => !a.group_id)) $('split-list').append(el('p', '部分视频没有可信比赛组，暂不能分配。', 'muted'));
    }
    function renderSnapshots() {
      const blockers = {no_human_confirmed_semantically_defined_judgements: '没有语义定义已审核且由真人确认的判断', unassigned_or_unconfirmed_groups: '视频比赛组未分配或未确认', rally_dead_ball_missing: '部分回合缺少独立死球点', independent_match_group_unconfirmed: '原片所属的独立比赛组尚未确认'};
      $('snapshot-list').replaceChildren();
      for (const snapshot of s.snapshots) {
        const box = el('div', undefined, 'list-item'); box.append(el('strong', new Date(snapshot.created_at).toLocaleString('zh-CN')), el('small', `项目修订 ${snapshot.project?.revision ?? '—'} · ${snapshot.content_sha256?.slice(0, 16) || '—'}`));
        const links = el('div', undefined, 'toolbar');
        for (const [view, format, text] of [['audit', 'json', '完整审阅 JSON'], ['audit', 'jsonl', '审阅 JSONL'], ['training', 'jsonl', '训练视图 JSONL']]) {
          if (view === 'training' && snapshot.quality_summary?.trainable !== true) {
            const disabled = el('span', '训练视图暂不可下载：请先完成质量审核。', 'muted'); disabled.setAttribute('aria-disabled', 'true'); links.append(disabled); continue;
          }
          const link = el('a', text); link.href = `/api/v1/training/snapshots/${encodeURIComponent(snapshot.snapshot_id)}/download?view=${view}&format=${format}`; link.setAttribute('download', ''); links.append(link);
        }
        box.append(links); $('snapshot-list').append(box);
      }
      const latest = s.snapshots[0]; $('snapshot-summary').replaceChildren();
      if (!latest) { $('snapshot-summary').textContent = '尚未生成快照'; return; }
      const summary = latest.quality_summary, metrics = el('div', undefined, 'summary-metrics');
      metrics.append(el('span', `${summary.record_count} 条记录`), el('span', `${summary.eligible_judgement_count} 项可纳入训练`), el('span', `${summary.excluded_judgement_count} 项排除 / 待审核`)); $('snapshot-summary').append(metrics);
      $('snapshot-summary').append(el('p', summary.trainable ? '当前快照满足合同中的训练准入条件。' : '快照已保存；训练条件仍有阻塞。'));
      const list = el('ul', undefined, 'snapshot-blockers'); for (const reason of summary.blockers) list.append(el('li', blockers[reason] || reason)); $('snapshot-summary').append(list);
    }
    function bind(id, event, action) { $(id).addEventListener(event, e => { if (event === 'submit') e.preventDefault(); run(() => action(e)); }); }
    bind('create-project', 'click', () => ctl.createProject($('project-name').value));
    bind('project-select', 'change', () => ctl.openProject($('project-select').value));
    bind('refresh-videos', 'click', async () => { await ctl.boot(); await ctl.refreshProject(); });
    bind('video-filter', 'input', render); bind('record-filter', 'change', renderRecords);
    bind('reload-records', 'click', () => s.asset && ctl.openAsset(s.asset.asset_id));
    bind('reload-conflict', 'click', () => s.asset && ctl.openAsset(s.asset.asset_id));
    bind('discard-record', 'click', () => ctl.discard());
    bind('delete-record', 'click', () => {
      const record = ctl.record(); if (!record) return;
      const count = activeRecords().filter(r => r.rally_id === record.record_id).length;
      const detail = record.kind === 'rally' ? `此回合和关联的 ${count} 条记录将一起删除。` : record.kind === 'dead_ball' ? '删除死球标记后，关联回合会恢复为终点证据缺失。' : '';
      if (win.confirm(`删除当前记录？${detail}历史修订仍保留。`)) ctl.removeRecord(true);
    });
    bind('annotation-form', 'submit', async e => { e.preventDefault(); await ctl.save(); message('标注包已保存，历史修订保留。'); });
    bind('save-bundle', 'click', async () => { await ctl.save(); message('本视频标注包已保存，人物与历史修订保留。'); });
    bind('add-participant', 'click', () => {
      const name = $('participant-name').value.trim(), team = $('participant-team').value.trim();
      if (!name) throw new Error('请输入人物显示名称');
      if (!s.bundle) throw new Error('先选择视频');
      if ($('participant-identity').value === 'confirmed' && s.actorType !== 'human') throw new Error('当前服务器来源不能新增人工确认身份');
      const oldTeam = s.bundle.people.find(p => p.provenance?.team_name === team && p.team_id);
      ctl.edit(bundle => bundle.people.push({person_id: uid('person'), display_name: name, team_id: team ? oldTeam?.team_id || uid('team') : null, identity_status: $('participant-identity').value, provenance: {team_name: team}}));
      field('participant-name', '');
    });
    bind('play-pause', 'click', () => player.paused ? player.play() : player.pause());
    bind('playback-rate', 'change', () => { player.playbackRate = Number($('playback-rate').value); });
    bind('seek-time', 'click', () => seek($('seek-ms').value));
    bind('step-prev', 'click', () => step(-1)); bind('step-next', 'click', () => step(1));
    for (const [id, kind] of [['new-rally', 'rally'], ['mark-contact', 'contact'], ['new-action', 'action'], ['new-footwork', 'footwork'], ['new-tactics', 'tactics'], ['new-state', 'state']]) bind(id, 'click', () => { cancelPick(); ctl.newRecord(kind, now()); });
    bind('finish-rally', 'click', () => ctl.finishRally(now()));
    bind('set-time-now', 'click', () => ctl.modifyRecord(r => { r.at_ms = now(); }));
    bind('set-start-now', 'click', () => ctl.modifyRecord(r => { r.start_ms = now(); }));
    bind('set-end-now', 'click', () => { const r = ctl.record(); if (r?.kind === 'rally') ctl.finishRally(now()); else ctl.modifyRecord(r => { r.end_ms = now(); }); });
    for (const [id, name] of [['record-time', 'at_ms'], ['record-start', 'start_ms'], ['record-end', 'end_ms'], ['uncertainty-start', 'uncertainty_start_ms'], ['uncertainty-end', 'uncertainty_end_ms']]) bind(id, 'input', () => editRecord(r => {
      r[name] = $(id).value === '' ? null : Number($(id).value);
      if (name === 'end_ms' && r.kind === 'rally' && r.dead_ball_id) { const dead = s.bundle.records.find(item => item.record_id === r.dead_ball_id); if (dead) { dead.at_ms = r.end_ms; dead.review = {status: 'pending', reviewer_type: s.actorType, reviewer: 'local-' + s.actorType}; } }
    }));
    bind('record-title', 'input', () => editRecord(r => { r.provenance = {...r.provenance, title: $('record-title').value}; }));
    bind('record-notes', 'input', () => editRecord(r => { r.provenance = {...r.provenance, notes: $('record-notes').value}; }));
    bind('record-reason', 'input', () => editRecord(r => { r.unknown_reasons = $('record-reason').value.trim() ? [$('record-reason').value.trim()] : []; }));
    bind('record-visibility', 'change', () => ctl.modifyRecord(r => { r.visibility = $('record-visibility').value; }));
    bind('record-rally', 'change', () => ctl.modifyRecord(r => { r.rally_id = $('record-rally').value || null; }));
    bind('record-player', 'change', () => ctl.modifyRecord(r => { const p = s.bundle.people.find(p => p.person_id === $('record-player').value); r.person_id = p?.person_id || null; r.team_id = p?.team_id || null; if (r.state?.self) { r.state.self.person_id = r.person_id; r.state.self.team_id = r.team_id; } for (const j of r.judgements) if ((j.subject_role || 'self') === 'self') j.subject_person_id = r.person_id; }));
    bind('record-team', 'change', () => ctl.modifyRecord(r => { r.team_id = $('record-team').value || null; }));
    bind('record-review', 'change', () => ctl.review($('record-review').value));
    bind('label-subject-role', 'change', renderEditor);
    bind('label-subject-person', 'change', () => ctl.modifyRecord(r => {
      const role = $('label-subject-role').value, person = s.bundle.people.find(p => p.person_id === $('label-subject-person').value);
      r.state ||= {}; r.state[role] ||= {position: null, missing_reasons: []};
      r.state[role].person_id = person?.person_id || null; r.state[role].team_id = person?.team_id || null;
      if (role === 'self') { r.person_id = person?.person_id || null; r.team_id = person?.team_id || null; }
      for (const j of r.judgements) if ((j.subject_role || 'self') === role) j.subject_person_id = person?.person_id || null;
    }));
    bind('add-time-evidence', 'click', () => ctl.modifyRecord(r => {
      const item = {type: 'source_time', asset_id: s.asset.asset_id, at_ms: now(), observation_source: s.actorType};
      if (frameAnchor) Object.assign(item, {source_pts: frameAnchor.source_pts, source_frame_index: frameAnchor.source_frame_index, precision: 'pts_seek_anchor_not_verified_display'});
      else item.precision = 'browser_time';
      r.evidence ||= []; r.evidence.push(item);
    }));
    bind('label-filter', 'input', () => { if (ctl.record()) renderTaxonomy(ctl.record()); });
    bind('add-state', 'click', () => ctl.modifyRecord(r => { r.state ||= {}; const role = Object.keys(roles).find(role => !r.state[role]); if (role) r.state[role] = {person_id: role === 'self' ? r.person_id : null, team_id: role === 'self' ? r.team_id : null, position: null, movement: null, missing_reasons: []}; }));
    for (const [id, name] of [['incoming-ball', 'incoming_ball'], ['outgoing-ball', 'outgoing_ball']]) bind(id, 'input', () => editRecord(r => { r.state ||= {}; r.state[name] = $(id).value || null; }));
    bind('cancel-position', 'click', cancelPick);
    bind('coordinate-overlay', 'click', e => {
      if (!pickRole || !ctl.record()?.state?.[pickRole]) return;
      const point = imagePoint(e.clientX, e.clientY, $('video-stage').getBoundingClientRect(), player.videoWidth, player.videoHeight);
      if (!point) throw new Error('请点击实际视频画面，黑边不属于图像坐标');
      const role = pickRole; cancelPick(); ctl.modifyRecord(r => {
        r.state[role].position = {...point, coordinate_system: 'image_normalized', source: s.actorType};
        r.state.provenance ||= {}; r.state.provenance.image_observations ||= {};
        r.state.provenance.image_observations[role] = {at_ms: now(), precision: frameAnchor ? 'pts_seek_anchor_not_verified_display' : 'browser_time'};
      }); message('图像归一坐标及所点画面的原片时间已写入草稿，保存后持久化。');
    });
    bind('save-splits', 'click', async () => { await ctl.saveSplits(clone(s.splitDraft)); message('比赛组划分已保存。'); });
    bind('create-snapshot', 'click', async () => { await ctl.snapshot(); message('不可变快照已生成；请查看训练准入摘要。'); });
    doc.addEventListener('keydown', e => {
      const action = shortcut(e); if (!action || !s.bundle) return;
      e.preventDefault(); run(() => {
        if (action === 'play') return player.paused ? player.play() : player.pause();
        if (action === 'previous' || action === 'next') return step(action === 'previous' ? -1 : 1);
        if (action === 'save') return ctl.save();
        if (action === 'start') return ctl.modifyRecord(r => { if (['rally', 'segment'].includes(r.kind)) r.start_ms = now(); });
        if (action === 'end') { if (ctl.record()?.kind === 'rally') return ctl.finishRally(now()); return ctl.modifyRecord(r => { if (r.kind === 'segment') r.end_ms = now(); }); }
        cancelPick(); return ctl.newRecord(action, now());
      });
    });
    win.addEventListener('beforeunload', e => { if (s.dirty || s.splitDirty) { e.preventDefault(); e.returnValue = ''; } });
    player.addEventListener('timeupdate', () => { if (!player.paused) frameAnchor = null; updateTime(); });
    player.addEventListener('seeking', () => { if (frameAnchor && Math.abs(player.currentTime * 1000 - Math.round(frameAnchor.source_pts_ms)) > .75) frameAnchor = null; updateTime(); });
    player.addEventListener('loadedmetadata', markers); win.addEventListener('resize', markers);
    player.addEventListener('error', () => { if (s.asset) message('浏览器无法播放此原片。原片仍只读保留；请核对编码和媒体访问错误。', true); });
    render(); run(() => ctl.boot());
    return ctl;
  }
  return {clone, sourceMs, formatTime, contentRect, imagePoint, shortcut, makeRequest, createController, mount};
});

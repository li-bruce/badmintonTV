// Pure PTS operations. Tests execute this block without browser bindings.
const PreviewMath = Object.freeze({
  floorIndex(rows, value, key) {
    let lo=0, hi=rows.length;
    while(lo<hi){const mid=(lo+hi)>>>1;if(rows[mid][key]<=value)lo=mid+1;else hi=mid}
    return Math.max(0,lo-1);
  },
  proxyAt(frames, mediaMs) {
    return frames[this.floorIndex(frames,mediaMs,'proxy_pts_ms')]||null;
  },
  coverageAt(frames, sourceMs) {
    if(!frames.length)return null;
    const row=frames[this.floorIndex(frames,sourceMs,'coverage_start_ms')];
    return sourceMs>=row.coverage_start_ms && sourceMs<row.coverage_end_ms ? row : null;
  },
  mediaForSource(frames, sourceMs, durationMs, imageCenter=false) {
    const row=this.coverageAt(frames,sourceMs);
    if(!row)throw Error('源时间不在当前代理覆盖窗口内，请生成对应窗口');
    const next=frames[row.proxy_frame_index+1];
    const end=next?.proxy_pts_ms??durationMs;
    const fraction=imageCenter ? .5 : (sourceMs-row.coverage_start_ms)/(row.coverage_end_ms-row.coverage_start_ms);
    return row.proxy_pts_ms+Math.max(0,Math.min(1,fraction))*(end-row.proxy_pts_ms);
  },
  sourceAtMedia(frames, mediaMs, durationMs) {
    const row=this.proxyAt(frames,mediaMs);if(!row)return null;
    const end=frames[row.proxy_frame_index+1]?.proxy_pts_ms??durationMs;
    const fraction=end>row.proxy_pts_ms?(mediaMs-row.proxy_pts_ms)/(end-row.proxy_pts_ms):0;
    return row.coverage_start_ms+Math.max(0,Math.min(1,fraction))*(row.coverage_end_ms-row.coverage_start_ms);
  },
  marks(row, exactFrame, nativeMs) {
    if(exactFrame)return {start:Math.floor(exactFrame.source_pts_ms),end:Math.ceil(exactFrame.source_end_ms),contact:Math.floor(exactFrame.source_pts_ms)};
    if(row)return {start:Math.floor(row.coverage_start_ms),end:Math.ceil(row.coverage_end_ms),contact:Math.floor(row.source_pts_ms)};
    return {start:Math.round(nativeMs),end:Math.round(nativeMs),contact:Math.round(nativeMs)};
  },
  summary(rows) {
    const valid=rows.filter(r=>r.status==='ok').map(r=>r.elapsed_ms).sort((a,b)=>a-b);
    const n=valid.length;
    return {samples:rows.length,measured:n,failed:rows.filter(r=>r.status==='error').length,
      no_op:rows.filter(r=>r.status==='no_op').length,
      median_ms:n?(n%2?valid[(n-1)/2]:(valid[n/2-1]+valid[n/2])/2):null,
      p95_ms:n?valid[Math.ceil(n*.95)-1]:null};
  }
});
// Browser bindings start here.
const $=id=>document.getElementById(id), state={assets:[],asset:null,event:null,candidates:[],timeline:null};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const json=x=>JSON.stringify(x,null,2), id=p=>p+'-'+crypto.randomUUID();
function notice(text,error=false){$('notice').textContent=text;$('notice').classList.toggle('error',error)}
async function api(path,method='GET',body){const r=await fetch('/api/v1'+path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const x=await r.json();if(!r.ok){const error=new Error(typeof x.detail==='string'?x.detail:json(x.detail));error.status=r.status;throw error}return x}
function action(id,fn){$(id).onclick=async()=>{try{await fn()}catch(e){notice(e.message,true)}}}
function download(name,obj){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([json(obj)],{type:'application/json'}));a.download=name;a.click();URL.revokeObjectURL(a.href)}
function page(name){document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===name));document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active',x.dataset.page===name));$('page-title').textContent=document.querySelector(`[data-page="${name}"]`).textContent.slice(3);if(name==='jobs')loadJobs();if(name==='timeline')loadTimelines().catch(error=>notice(error.message,true))}
document.querySelectorAll('nav button').forEach(x=>x.onclick=()=>page(x.dataset.page));
async function overview(){const w=await api('/workflow');$('stats').innerHTML=[['源视频',w.assets],['标注事件',w.events],['人工确认',w.confirmed_events],['剪辑工程',w.timelines]].map(([k,v])=>`<div class="stat"><span>${k}</span><b>${v}</b></div>`).join('');$('recent-jobs').innerHTML=w.jobs.slice(0,5).map(jobCard).join('')||'<p class="muted">还没有任务。导入原视频后开始探测。</p>';$('recent-jobs').querySelectorAll('button').forEach(b=>b.onclick=()=>page('jobs'))}
async function loadLibraries(){const ls=await api('/libraries'),prior=$('library-select').value;$('library-select').innerHTML=ls.map(x=>`<option value="${esc(x.library_id)}">${esc(x.name)}</option>`).join('');if(ls.some(x=>x.library_id===prior))$('library-select').value=prior}
action('create-library',async()=>{const x=await api('/libraries','POST',{name:$('library-name').value});await loadLibraries();$('library-select').value=x.library_id;notice('资料库已保存')});
action('import-path',async()=>{if(!$('match-id').value)throw Error('请填写比赛或录制会话 ID');const j=await api('/assets/import-path','POST',{library_id:$('library-select').value,relative_path:$('source-path').value,metadata:{match_id:$('match-id').value,title:$('source-path').value.split('/').pop(),source_type:'personal'}});notice('已提交探测任务：'+j.job_id+'。完成后在任务页点击应用结果。');await overview()});
$('manifest-file').onchange=async()=>{$('manifest-json').value=await $('manifest-file').files[0].text()};
action('import-manifest',async()=>{const x=await api('/assets/import','POST',{library_id:$('library-select').value,manifest:JSON.parse($('manifest-json').value)});notice(x.job_id?'大清单已进入后台哈希校验，完成后在任务页应用：'+x.job_id:`清单已入库：${x.imported.length} 条（重复按hash复用）`);await loadAssets();await overview()});
async function loadAssets(){const q=new URLSearchParams();if($('library-select').value)q.set('library_id',$('library-select').value);if($('asset-player').value)q.set('player_id',$('asset-player').value);if($('asset-tag').value)q.set('tag',$('asset-tag').value);state.assets=await api('/assets?'+q);$('assets').innerHTML=state.assets.map(a=>`<div class="card"><b>${esc(a.title)}</b><p>${a.duration_ms/1000}s · ${esc(a.source_type)} · ${esc(a.rights.status)}</p><button class="small" data-asset="${esc(a.asset_id)}">预览与标注</button></div>`).join('')||'<p class="muted">当前没有素材</p>';$('assets').querySelectorAll('[data-asset]').forEach(b=>b.onclick=()=>selectAsset(b.dataset.asset))}
action('refresh-assets',loadAssets);$('library-select').onchange=loadAssets;
const preview={epoch:0,data:null,jobId:null,frames:[],sourceFrames:new Map(),selected:null,presented:null,
  inspectRequest:0,seekRequest:0,intent:0,internalSeek:false,loopSeeking:false,loopGeneration:0,loopCount:0,loopRegion:'',benchmark:false,measurements:[]};
const inspections={active:null,pending:new Set(),queue:Promise.resolve(),cache:new Map()},inspectionTerminal=new Set(['succeeded','failed','blocked','cancelled']);
function currentInspection(token){return inspections.active===token&&!token.obsolete&&token.epoch===preview.epoch&&token.request===preview.inspectRequest&&token.previewData===preview.data}
function serializeInspection(work){const result=inspections.queue.then(work);inspections.queue=result.catch(()=>{});return result}
async function cancelObsoleteInspections(){
  for(const token of inspections.pending){
    if(currentInspection(token)||!token.job)continue;
    if(!inspectionTerminal.has(token.job.status)){
      const cancelled=await api('/jobs/'+encodeURIComponent(token.job.job_id)+'/cancel','POST',{});
      if(!cancelled.cancel_requested&&!inspectionTerminal.has(cancelled.status))throw Error('原图任务未确认取消：'+token.job.job_id);
      token.job=cancelled;
    }
    inspections.pending.delete(token);
  }
}
function invalidateInspection(){
  preview.inspectRequest++;if(inspections.active){inspections.active.obsolete=true;inspections.active=null}
  if(inspections.pending.size)serializeInspection(cancelObsoleteInspections).catch(e=>notice('旧原图任务取消失败，请在任务页检查：'+e.message,true));
}
function assetPath(){if(!state.asset)throw Error('请先选择素材');return '/assets/'+encodeURIComponent(state.asset.asset_id)}
function localMediaURL(value){const u=new URL(value,location.href);if(u.origin!==location.origin)throw Error('预览产物必须来自本机同源接口');return u.href}
async function previewJSON(url,params={}){
  const u=new URL(localMediaURL(url));for(const [k,v] of Object.entries(params))u.searchParams.set(k,v);
  const r=await fetch(u);const body=await r.json();if(!r.ok)throw Error(typeof body.detail==='string'?body.detail:json(body.detail));return body;
}
function mediaDurationMs(){return Number.isFinite($('player').duration)?$('player').duration*1000:0}
function displayedProxy(){return PreviewMath.proxyAt(preview.frames,preview.presented??$('player').currentTime*1000)}
function sourcePosition(){
  if(preview.selected)return preview.selected.source_pts_ms;
  if(preview.data)return PreviewMath.sourceAtMedia(preview.frames,$('player').currentTime*1000,mediaDurationMs());
  return $('player').currentTime*1000;
}
function currentMarks(){const marks=PreviewMath.marks(preview.data?displayedProxy():null,preview.selected,$('player').currentTime*1000);marks.end=Math.min(marks.end,state.asset?.duration_ms??marks.end);return marks}
function clearSourceImage(){invalidateInspection();$('source-frame-image').hidden=true;$('source-frame-status').textContent='仅定位代理；点击原分辨率核查可后台提取所选源帧，长片可能耗时';$('source-frame-meta').textContent=''}
function previewControls(){
  const ready=!!preview.data && preview.frames.length>0 && !preview.benchmark;
  for(const key of ['source-prev','source-next','inspect-source'])$(key).disabled=!ready;
  for(const key of ['seek-benchmark-cold','seek-benchmark-first','seek-benchmark-repeat'])$(key).disabled=!ready;
  $('prepare-preview').disabled=preview.benchmark;
  $('source-seek').disabled=preview.benchmark;
}
function updatePreviewReadout(){
  const row=preview.data?displayedProxy():null;
  if(!row){$('preview-image-mapping').textContent='原片播放 · 当前源时间 '+Math.round($('player').currentTime*1000)+' ms';$('preview-coverage').textContent='生成兼容预览后可读取逐帧PTS映射并核查源帧';return}
  const exact=preview.selected;
  $('preview-image-mapping').textContent=`代理画面 #${row.proxy_frame_index} → 源帧 #${row.source_frame_index} · PTS ${row.source_pts} × ${preview.data.source_time_base} · ${row.source_pts_ms} ms`;
  $('preview-coverage').textContent=`代理区间覆盖源 [${row.coverage_start_ms}, ${row.coverage_end_ms}) ms`+(exact?`；精确选择源帧 #${exact.source_frame_index} [${exact.source_pts_ms}, ${exact.source_end_ms}) ms`:'；开始/结束标记使用覆盖边界，击球标记使用画面源PTS');
  $('preview-image-mapping').dataset.sourceFrame=String(row.source_frame_index);
  $('preview-coverage').dataset.startMs=String(row.coverage_start_ms);$('preview-coverage').dataset.endMs=String(row.coverage_end_ms);
  if(document.activeElement!==$('source-seek-ms'))$('source-seek-ms').value=Math.floor(sourcePosition());
  const thumbs=$('preview-thumbnails').querySelectorAll('[data-source-ms]');
  let active=null;for(const t of thumbs){t.setAttribute('aria-current','false');if(Number(t.dataset.sourceMs)<=sourcePosition())active=t}active?.setAttribute('aria-current','true');
}
async function sourceFrameAt(ms){
  if(!preview.data)throw Error('请先生成兼容预览以读取源帧索引');
  for(const frame of preview.sourceFrames.values())if(frame.source_pts_ms<=ms && ms<frame.source_end_ms)return frame;
  const epoch=preview.epoch,response=await previewJSON(preview.data.source_frames_url,{at_ms:ms,limit:128});
  if(epoch!==preview.epoch)throw Error('已切换素材，停止旧源帧请求');
  for(const frame of response.source_frames)preview.sourceFrames.set(frame.source_frame_index,frame);
  const frame=response.source_frames.find(f=>f.source_pts_ms<=ms && ms<f.source_end_ms);
  if(!frame)throw Error('源时间未命中PTS索引，不能推算帧号');return frame;
}
async function sourceFrameByIndex(index){
  if(!preview.data)throw Error('尚无源帧索引');
  index=Math.max(0,Math.min(preview.data.source_frame_count-1,index));
  if(preview.sourceFrames.has(index))return preview.sourceFrames.get(index);
  const epoch=preview.epoch,response=await previewJSON(preview.data.source_frames_url,{offset_frame:Math.max(0,index-32),limit:128});
  if(epoch!==preview.epoch)throw Error('已切换素材，停止旧源帧请求');
  for(const frame of response.source_frames)preview.sourceFrames.set(frame.source_frame_index,frame);
  const frame=preview.sourceFrames.get(index);if(!frame)throw Error('服务端未返回所需源帧');return frame;
}
function drawThumbnails(){
  const host=$('preview-thumbnails');host.replaceChildren();
  const p=preview.data;if(!p?.thumbnail_url)return;
  for(const thumb of p.thumbs||[]){
    const button=document.createElement('button'),crop=document.createElement('span'),label=document.createElement('span');
    button.type='button';button.dataset.sourceMs=String(thumb.source_pts_ms);button.title=`定位源时间 ${thumb.source_pts_ms} ms`;
    crop.className='thumbnail-crop';crop.style.width=thumb.width+'px';crop.style.height=thumb.height+'px';
    crop.style.backgroundImage=`url(${JSON.stringify(localMediaURL(p.thumbnail_url))})`;crop.style.backgroundPosition=`-${thumb.x}px 0px`;
    label.textContent=(thumb.source_pts_ms/1000).toFixed(3)+' s';button.append(crop,label);
    button.onclick=()=>seekSource(thumb.source_pts_ms).catch(e=>notice(e.message,true));host.append(button);
  }
}
function waitForMedia(){
  const player=$('player');if(player.readyState>=1)return Promise.resolve();
  return new Promise((resolve,reject)=>{const timer=setTimeout(()=>finish(Error('浏览器媒体元数据读取超时')),15000);
    const ready=()=>finish(),error=()=>finish(Error('浏览器不能解码此媒体，请生成兼容预览'));
    function finish(err){clearTimeout(timer);player.removeEventListener('loadedmetadata',ready);player.removeEventListener('error',error);err?reject(err):resolve()}
    player.addEventListener('loadedmetadata',ready);player.addEventListener('error',error);
  });
}
async function refreshPreview(sourceMs=null){
  const epoch=preview.epoch,response=await api(assetPath()+'/preview');if(epoch!==preview.epoch)return;
  $('preview-status').textContent=`预览状态：${response.status}`+(response.job_id?' · '+response.job_id:'');
  if(response.status!=='succeeded'||!response.preview){previewControls();return response}
  const p=response.preview;
  if(p.source_asset_id!==state.asset.asset_id||p.source_sha256!==state.asset.sha256)throw Error('代理与当前原片ID/hash不一致');
  if(preview.data?.frame_map_url===p.frame_map_url&&preview.data?.index_relative_path===p.index_relative_path){if(sourceMs!=null)await seekSource(sourceMs);return response}
  const frames=[];let offset=0,total=Infinity;
  while(offset<total){
    const page=await previewJSON(p.frame_map_url,{offset_frame:offset,limit:1000});if(epoch!==preview.epoch)return;
    if(!page.frames?.length)throw Error('代理帧映射不完整');frames.push(...page.frames);total=page.total;offset=frames.length;
  }
  if(frames.length!==p.proxy_frame_count||frames.some((r,i)=>r.proxy_frame_index!==i||r.coverage_end_ms<=r.coverage_start_ms))throw Error('代理帧索引或覆盖区间无效');
  clearSourceImage();preview.data=p;preview.jobId=response.job_id;preview.frames=frames;preview.sourceFrames.clear();preview.selected=null;preview.presented=null;
  $('player').pause();$('player').src=localMediaURL(p.media_url);$('player').load();
  drawThumbnails();previewControls();
  $('preview-status').textContent=`兼容代理 · ≤${p.max_height}p · 源窗口 ${p.window_start_ms}–${p.window_end_ms} ms · ${p.proxy_frame_count} 帧 · 无音轨`;
  await waitForMedia();if(epoch!==preview.epoch)return;
  const target=sourceMs??p.window_start_ms;
  if(target>=p.window_start_ms && target<p.window_end_ms)await seekSource(target);
  else{updatePreviewReadout();notice('当前代理未覆盖所选源时间，请修改窗口并生成预览')}
  return response;
}
async function selectAsset(id,ms=0){
  clearSourceImage();
  preview.epoch++;preview.intent++;preview.inspectRequest++;preview.seekRequest++;preview.data=null;preview.frames=[];preview.sourceFrames.clear();preview.selected=null;preview.presented=null;preview.internalSeek=false;preview.benchmark=false;
  $('loop-enabled').checked=false;resetLoopCounter();$('source-frame-image').hidden=true;$('source-frame-status').textContent='尚未核查源帧';$('source-frame-meta').textContent='';$('preview-thumbnails').replaceChildren();
  const epoch=preview.epoch;
  const asset=state.assets.find(a=>a.asset_id===id)||(await api('/assets')).find(a=>a.asset_id===id);
  if(epoch!==preview.epoch)return;if(!asset)throw Error('素材不存在');state.asset=asset;
  $('player').pause();$('player').src='/api/v1/assets/'+encodeURIComponent(id)+'/media';$('player').onloadedmetadata=()=>{if(epoch===preview.epoch&&!preview.data)$('player').currentTime=ms/1000};
  $('asset-title').textContent=state.asset.title;$('asset-meta').textContent=`${state.asset.asset_id} · ${state.asset.width}×${state.asset.height} · ${state.asset.duration_ms}ms · ${state.asset.relative_path}`;
  $('preview-start').value=Math.floor(ms);$('preview-end').value=Math.min(state.asset.duration_ms,Math.floor(ms)+120000);$('source-seek-ms').value=ms;previewControls();updatePreviewReadout();
  $('ls-asset').value=id;
  try{const frameMap=await api('/assets/'+id+'/frame-map');if(epoch===preview.epoch)$('ls-map').value=json(frameMap)}catch(e){if(epoch===preview.epoch)$('ls-map').value=''}
  if(epoch!==preview.epoch)return;newEvent();await loadEvents();
  try{await refreshPreview(ms)}catch(e){if(epoch===preview.epoch)$('preview-status').textContent='兼容预览尚不可用：'+e.message}
}
// Wait for both seeked and the frame actually submitted by the browser. A callback
// is observation, not an exact-seek guarantee; mismatches/timeouts remain visible.
async function seekMedia(mediaMs,{requestedSourceMs=null,measure=false}={}){
  await waitForMedia();const player=$('player'),epoch=preview.epoch,request=++preview.seekRequest;
  const expected=preview.data?PreviewMath.proxyAt(preview.frames,mediaMs):null;
  const start=performance.now();preview.internalSeek=true;preview.presented=null;
  const result={requested_source_ms:requestedSourceMs,target_media_ms:mediaMs,expected_proxy_frame:expected?.proxy_frame_index??null,rvfc_supported:typeof player.requestVideoFrameCallback==='function'};
  if(Math.abs(player.currentTime*1000-mediaMs)<.01 && !player.seeking){preview.internalSeek=false;return {...result,status:'no_op',elapsed_ms:performance.now()-start}}
  return new Promise((resolve,reject)=>{
    let seekedAt=null,frameAt=null,metadata=null,callback=null,done=false;
    const timer=setTimeout(()=>finish(Error('寻帧超时：浏览器未提交目标代理帧')),8000);
    function finish(error){
      if(done)return;done=true;clearTimeout(timer);player.removeEventListener('seeked',onSeeked);player.removeEventListener('error',onError);
      if(callback!=null)player.cancelVideoFrameCallback?.(callback);
      if(request===preview.seekRequest)preview.internalSeek=false;
      result.status=error?'error':'ok';result.elapsed_ms=performance.now()-start;result.seeked_ms=seekedAt;result.presented_ms=frameAt;
      result.observed_media_ms=metadata?.mediaTime!=null?metadata.mediaTime*1000:null;
      const actual=result.observed_media_ms==null?null:PreviewMath.proxyAt(preview.frames,result.observed_media_ms+.001);
      result.observed_source_frame=actual?.source_frame_index??null;result.observed_source_pts_ms=actual?.source_pts_ms??null;
      result.source_error_ms=actual&&requestedSourceMs!=null?actual.source_pts_ms-requestedSourceMs:null;
      result.error=error?.message??null;result.frame_observed=!!metadata;
      if(error&&!measure)reject(error);else resolve(result);
    }
    function current(){if(epoch!==preview.epoch||request!==preview.seekRequest){finish(Error('寻帧已被后续操作替代'));return false}return true}
    function maybeFinish(){if(current()&&seekedAt!==null&&(!result.rvfc_supported||frameAt!==null))finish()}
    function onSeeked(){if(!current())return;seekedAt=performance.now()-start;maybeFinish()}
    function onError(){finish(Error('媒体解码或读取失败'))}
    function onFrame(now,meta){
      if(!current())return;
      const actual=PreviewMath.proxyAt(preview.frames,meta.mediaTime*1000+.001);
      if(!expected||actual?.proxy_frame_index===expected.proxy_frame_index){metadata=meta;frameAt=performance.now()-start;preview.presented=meta.mediaTime*1000;maybeFinish()}
      if(!done&&frameAt===null)callback=player.requestVideoFrameCallback(onFrame);
    }
    player.addEventListener('seeked',onSeeked);player.addEventListener('error',onError);
    if(result.rvfc_supported)callback=player.requestVideoFrameCallback(onFrame);
    try{player.currentTime=mediaMs/1000}catch(error){finish(error)}
  });
}
async function seekSource(ms,{inspect=false,measure=false}={}){
  if(!state.asset)throw Error('请先选择素材');
  if(!Number.isFinite(ms)||ms<0||ms>=state.asset.duration_ms)throw Error('定位源时间必须在视频范围内');
  const intent=++preview.intent,epoch=preview.epoch;$('player').pause();clearSourceImage();
  if(!preview.data){await seekMedia(ms);updatePreviewReadout();return}
  const frame=await sourceFrameAt(ms);if(intent!==preview.intent||epoch!==preview.epoch)throw Error('源定位已被后续操作替代');
  const mediaMs=PreviewMath.mediaForSource(preview.frames,frame.source_pts_ms,mediaDurationMs(),true);
  preview.selected=frame;
  const result=await seekMedia(mediaMs,{requestedSourceMs:frame.source_pts_ms,measure});if(epoch!==preview.epoch)return result;
  result.requested_source_frame=frame.source_frame_index;result.requested_source_pts=frame.source_pts;
  result.requested_source_end_ms=frame.source_end_ms;
  result.source_error_frames=result.observed_source_frame==null?null:result.observed_source_frame-frame.source_frame_index;
  result.within_one_source_frame=result.source_error_frames==null?null:Math.abs(result.source_error_frames)<=1;
  updatePreviewReadout();if(inspect)await inspectSourceFrame(frame);return result;
}
async function stepSource(delta){
  if(!preview.data||preview.benchmark)return;
  $('player').pause();clearSourceImage();const row=displayedProxy(),base=preview.selected?.source_frame_index??row?.source_frame_index;
  if(base==null)throw Error('当前画面尚未映射到源帧');
  const intent=++preview.intent,frame=await sourceFrameByIndex(base+delta);if(intent!==preview.intent)return;preview.selected=frame;
  if(PreviewMath.coverageAt(preview.frames,frame.source_pts_ms))await seekSource(frame.source_pts_ms);
  else{updatePreviewReadout();notice('已选择代理窗口外的源帧；点击原分辨率核查可提取原图，播放需生成对应代理窗口')}
}
async function inspectSourceFrame(frame=null){
  if(!preview.data)throw Error('请先生成兼容预览');
  clearSourceImage();$('player').pause();
  const token={epoch:preview.epoch,request:preview.inspectRequest,previewData:preview.data,asset:state.asset,previewJobId:preview.jobId,obsolete:false,job:null};
  inspections.active=token;let cacheKey=null;
  try{
    frame=frame??preview.selected??await sourceFrameByIndex(displayedProxy().source_frame_index);
    if(!currentInspection(token))return;
    preview.selected=frame;updatePreviewReadout();$('source-inspector').open=true;
    $('source-frame-status').textContent=`后台核查源帧 #${frame.source_frame_index}；须校验原片，长片可能从头解码，请稍候…`;
    // The index path includes the successful preview attempt directory. Without
    // this identity no cache entry is reused across a retried preview job.
    if(token.previewData.index_relative_path)cacheKey=json([token.asset.asset_id,token.asset.sha256,frame.source_frame_index,token.previewJobId,token.previewData.index_relative_path]);
    let cached=null;
    const job=await serializeInspection(async()=>{
      await cancelObsoleteInspections();if(!currentInspection(token))return null;
      cached=cacheKey?inspections.cache.get(cacheKey):null;if(cached)return cached;
      inspections.pending.add(token);
      try{token.job=await api('/assets/'+encodeURIComponent(token.asset.asset_id)+'/source-frame','POST',{preview_job_id:token.previewJobId,source_frame_index:frame.source_frame_index})}
      catch(error){inspections.pending.delete(token);throw error}
      if(!currentInspection(token)){await cancelObsoleteInspections();return null}
      return token.job;
    });
    if(!currentInspection(token)||!job)return;
    let current=job;const deadline=performance.now()+120000;
    while(!inspectionTerminal.has(current.status)){
      if(!currentInspection(token))return;
      if(performance.now()>deadline)throw Error('源帧核查超时，已请求取消；请在任务页检查：'+job.job_id);
      await new Promise(resolve=>setTimeout(resolve,500));if(!currentInspection(token))return;
      current=await api('/jobs/'+encodeURIComponent(job.job_id));token.job=current;
      if(currentInspection(token))$('source-frame-status').textContent=`源帧 #${frame.source_frame_index} · ${current.status} · ${job.job_id}`;
    }
    inspections.pending.delete(token);if(!currentInspection(token))return;
    if(current.status!=='succeeded')throw Error('源帧提取'+current.status+'：'+json(current.error));
    const result=current.result?.frame,artifact=current.result?.artifacts?.find(a=>a.kind==='source_frame'&&/\.jpe?g$/i.test(a.relative_path));
    if(!result||!artifact||result.source_asset_id!==token.asset.asset_id||result.source_sha256!==token.asset.sha256||result.source_frame_index!==frame.source_frame_index||String(result.source_pts)!==String(frame.source_pts)||!Number.isFinite(result.source_pts_ms)||Math.abs(result.source_pts_ms-frame.source_pts_ms)>.01)throw Error('源帧产物与请求的原片/帧序号/PTS不一致');
    const img=$('source-frame-image');img.src='/api/v1/jobs/'+encodeURIComponent(job.job_id)+'/artifacts/'+encodeURIComponent(artifact.artifact_id);
    try{await img.decode()}catch(e){if(currentInspection(token))throw Error('原分辨率源帧图像加载失败；可再次点击核查重试');return}
    if(!currentInspection(token))return;
    if(img.naturalWidth!==result.width||img.naturalHeight!==result.height)throw Error('源帧图片尺寸与提取记录不一致');
    if(cacheKey){inspections.cache.delete(cacheKey);inspections.cache.set(cacheKey,current);while(inspections.cache.size>16)inspections.cache.delete(inspections.cache.keys().next().value)}
    img.hidden=false;img.alt=`源帧 #${frame.source_frame_index}，PTS ${frame.source_pts}，原尺寸 ${result.width}×${result.height}`;
    img.dataset.sourceFrame=String(frame.source_frame_index);img.dataset.sourcePts=String(frame.source_pts);img.dataset.sourceMs=String(frame.source_pts_ms);
    $('source-frame-status').textContent=`已加载源帧 #${frame.source_frame_index} · ${result.width}×${result.height} 原尺寸`+(cached?' · 复用本会话已校验结果':'');
    $('source-frame-meta').textContent=`源PTS ${frame.source_pts} × ${token.previewData.source_time_base} · [${frame.source_pts_ms}, ${frame.source_end_ms}) ms · SHA-256 ${result.source_sha256}。像素放大不增加原片细节。`;
    resizeSourceImage();
  }catch(error){if(currentInspection(token)){if(cacheKey)inspections.cache.delete(cacheKey);throw error}}
  finally{token.obsolete=true;if(inspections.active===token)inspections.active=null;if(inspections.pending.has(token))serializeInspection(cancelObsoleteInspections).catch(e=>notice('旧原图任务取消失败，请在任务页检查：'+e.message,true))}
}
function resizeSourceImage(){const img=$('source-frame-image'),zoom=$('source-zoom').value;if(zoom==='fit'){img.style.width='100%';img.style.maxWidth=img.naturalWidth+'px'}else{img.style.width=img.naturalWidth*Number(zoom)+'px';img.style.maxWidth='none'}img.style.height='auto'}
function loopRegion(){return Number($('event-start').value)+':'+Number($('event-end').value)}
function showLoopCount(){
  $('loop-status').textContent=`${$('loop-enabled').checked?'按当前开始/结束循环':'循环未启用'} · 源区间 [${$('event-start').value}, ${$('event-end').value}) ms · 已完成循环 ${preview.loopCount} 次`;
  $('loop-status').dataset.loopCount=String(preview.loopCount);
}
function resetLoopCounter(){
  preview.loopGeneration++;preview.loopCount=0;preview.loopRegion=loopRegion();preview.loopSeeking=false;
  $('loop-status').dataset.lastLoopSourceMs='';showLoopCount();
}
function checkLoop(fromEnded=false){
  if(preview.loopRegion!==loopRegion())resetLoopCounter();
  if(!$('loop-enabled').checked||preview.loopSeeking||preview.internalSeek||($('player').paused&&!fromEnded))return;
  const start=Number($('event-start').value),end=Number($('event-end').value),at=sourcePosition();
  if(!(start>=0&&end>start&&end<=state.asset?.duration_ms)){$('loop-enabled').checked=false;$('loop-status').textContent='循环区间无效';return}
  if(preview.data&&(start<preview.data.window_start_ms||end>preview.data.window_end_ms)){$('loop-enabled').checked=false;$('loop-status').textContent='循环区间超出代理覆盖窗口';return}
  if(fromEnded||at>=end||at<start){
    preview.loopSeeking=true;preview.selected=null;
    const mediaMs=preview.data?PreviewMath.mediaForSource(preview.frames,start,mediaDurationMs()):start;
    // Hold the target frame until seeked and its presentation callback arrive;
    // ongoing playback can pass it before the browser delivers the callback.
    $('player').pause();
    const epoch=preview.epoch,generation=preview.loopGeneration,completedCycle=fromEnded||at>=end;
    const current=()=>epoch===preview.epoch&&generation===preview.loopGeneration&&$('loop-enabled').checked&&preview.loopRegion===loopRegion();
    return seekMedia(mediaMs).then(async()=>{
      if(!current())return;
      const returnedSourceMs=sourcePosition();await $('player').play();
      if(!current())return;
      // Initial positioning before the interval is not a completed loop. Count
      // only a real end→start seek after the browser also resumed playback.
      if(completedCycle){preview.loopCount++;$('loop-status').dataset.lastLoopSourceMs=String(returnedSourceMs);showLoopCount()}
    }).catch(e=>{if(current()){$('loop-enabled').checked=false;showLoopCount();notice(e.message,true)}}).finally(()=>{if(generation===preview.loopGeneration)preview.loopSeeking=false});
  }
}
function previewPlaybackTick(){if(!preview.internalSeek){updatePreviewReadout();checkLoop()}}
$('player').addEventListener('timeupdate',previewPlaybackTick);
$('player').addEventListener('seeking',()=>{if(!preview.internalSeek){preview.intent++;preview.selected=null;preview.presented=null;clearSourceImage();updatePreviewReadout()}});
$('player').addEventListener('play',()=>{preview.selected=null;clearSourceImage();updatePreviewReadout()});
$('player').addEventListener('ended',()=>{if($('loop-enabled').checked)checkLoop(true)});
$('player').addEventListener('error',()=>{if(state.asset)$('preview-status').textContent='浏览器无法播放当前文件；可生成 H.264 兼容预览'});
if(typeof $('player').requestVideoFrameCallback==='function'){
  const observe=(now,metadata)=>{if(!preview.internalSeek){preview.presented=metadata.mediaTime*1000;previewPlaybackTick()}$('player').requestVideoFrameCallback(observe)};
  $('player').requestVideoFrameCallback(observe);
}
function loopClock(){if(!$('player').paused&&$('loop-enabled').checked)checkLoop();requestAnimationFrame(loopClock)}requestAnimationFrame(loopClock);
action('prepare-preview',async()=>{
  const start=Number($('preview-start').value),end=Number($('preview-end').value);
  if(!(start>=0&&end>start&&end<=state.asset?.duration_ms&&end-start<=120000))throw Error('代理窗口须在源片内，长度为1–120000 ms');
  const job=await api(assetPath()+'/preview','POST',{start_ms:start,end_ms:end,max_height:Number($('preview-height').value),max_fps:$('preview-fps').value?30:null});
  $('preview-status').textContent='兼容预览已排队：'+job.job_id;notice('后台任务完成后点击刷新预览；可在任务页查看或取消');
});
action('refresh-preview',()=>refreshPreview());action('source-prev',()=>stepSource(-1));action('source-next',()=>stepSource(1));
action('inspect-source',()=>inspectSourceFrame());action('source-seek',()=>seekSource(Number($('source-seek-ms').value)));
$('source-zoom').onchange=resizeSourceImage;
$('loop-enabled').onchange=()=>{resetLoopCounter();checkLoop()};
for(const field of ['event-start','event-end'])$(field).addEventListener('input',resetLoopCounter);
$('preview-workbench').addEventListener('keydown',event=>{
  if(event.target.closest('input,textarea,select,button,summary')||event.altKey||event.ctrlKey||event.metaKey||preview.benchmark)return;
  if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();stepSource(event.key==='ArrowLeft'?-1:1).catch(e=>notice(e.message,true))}
  if(event.code==='Space'){event.preventDefault();const p=$('player');if(p.paused)p.play().catch(e=>notice(e.message,true));else p.pause()}
});
function previewVisibility(){
  const rect=$('player').getBoundingClientRect(),width=window.innerWidth,height=window.innerHeight;
  const visibleWidth=Math.max(0,Math.min(rect.right,width)-Math.max(rect.left,0));
  const visibleHeight=Math.max(0,Math.min(rect.bottom,height)-Math.max(rect.top,0));
  return {document_visibility:document.visibilityState,viewport_width:width,viewport_height:height,
    player_rect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height,top:rect.top,right:rect.right,bottom:rect.bottom,left:rect.left},
    visible_area_fraction:rect.width*rect.height>0?visibleWidth*visibleHeight/(rect.width*rect.height):0};
}
async function benchmarkSeeks(group,reloadMedia=false){
  if(!preview.data||preview.benchmark)throw Error('请先加载兼容预览');
  const epoch=preview.epoch,p=preview.data,run={group,asset_id:state.asset.asset_id,source_sha256:p.source_sha256,preview_job_id:preview.jobId,started_at:new Date().toISOString(),
    timing_scope:reloadMedia?'media_load_plus_seek_and_presentation':'seek_and_presentation',
    cache_control:reloadMedia?'每点重新加载媒体元素，使用唯一HTTP URL（服务端no-store）；媒体元素/HTTP缓存冷；OS文件缓存未清除，不是全系统冷缓存':'复用当前媒体元素，不重载；浏览器及OS文件缓存未清除，HTTP缓存是否复用不作保证',
    fixed_points_ms:Array.from({length:30},(_,i)=>p.window_start_ms+(p.window_end_ms-p.window_start_ms)*i/30),rows:[]};
  preview.benchmark=true;$('loop-enabled').checked=false;previewControls();
  $('player').scrollIntoView({block:'center',behavior:'instant'});run.visibility_at_start=previewVisibility();
  try{
    for(let i=0;i<30;i++){
      if(epoch!==preview.epoch)throw Error('素材已切换，停止计时');
      const ms=run.fixed_points_ms[i],visibility=previewVisibility();
      $('seek-benchmark-status').textContent=`${group} · ${i+1}/30 · 源 ${Math.floor(ms)} ms`;
      let pointStart=null,mediaLoadMs=null;
      try{
        // Resolve the source PTS before timing; the cold measure is load+seek,
        // not legacy index pagination or a fabricated timestamp calculation.
        await sourceFrameAt(ms);if(epoch!==preview.epoch)throw Error('素材已切换，停止计时');
        if(reloadMedia){
          const url=new URL(localMediaURL(p.media_url));url.searchParams.set('_btv_cold_seek',crypto.randomUUID());
          $('player').pause();preview.presented=null;clearSourceImage();pointStart=performance.now();
          $('player').src=url.href;$('player').load();await waitForMedia();mediaLoadMs=performance.now()-pointStart;
          if(epoch!==preview.epoch)throw Error('素材已切换，停止计时');
        }
        const result=await seekSource(ms,{measure:true});
        if(reloadMedia){result.seek_elapsed_ms=result.elapsed_ms;result.media_load_ms=mediaLoadMs;result.elapsed_ms=performance.now()-pointStart;
          result.seeked_from_load_ms=result.seeked_ms==null?null:mediaLoadMs+result.seeked_ms;
          result.presented_from_load_ms=result.presented_ms==null?null:mediaLoadMs+result.presented_ms}
        run.rows.push({point:i+1,visibility,...result});
      }catch(e){run.rows.push({point:i+1,visibility,requested_source_ms:ms,status:'error',elapsed_ms:pointStart==null?null:performance.now()-pointStart,media_load_ms:mediaLoadMs,error:e.message})}
      run.summary=PreviewMath.summary(run.rows);$('seek-benchmark-results').textContent=json(run);
    }
  }finally{
    run.finished_at=new Date().toISOString();run.summary=PreviewMath.summary(run.rows);preview.measurements.push(run);preview.benchmark=false;previewControls();
    $('seek-benchmark-results').textContent=json(preview.measurements);
    $('seek-benchmark-status').textContent=`${group}完成：实测 ${run.summary.measured}/30 · 中位数 ${run.summary.median_ms?.toFixed(1)??'未测'} ms · P95 ${run.summary.p95_ms?.toFixed(1)??'未测'} ms · 失败 ${run.summary.failed}`;
  }
}
action('seek-benchmark-cold',()=>benchmarkSeeks('cold_media_load',true));action('seek-benchmark-first',()=>benchmarkSeeks('first_access'));action('seek-benchmark-repeat',()=>benchmarkSeeks('repeat_access'));
action('seek-benchmark-export',()=>download('preview-seek-measurements.json',preview.measurements));
function newEvent(){state.event=null;$('edit-state').textContent='新标注 · revision 1';$('event-start').value=0;$('event-end').value=Math.min(1000,state.asset?.duration_ms||1000);$('event-contact').value='';resetLoopCounter()}
action('new-event',async()=>newEvent());
['in','out','contact'].forEach((k,i)=>action('mark-'+k,async()=>{if(!state.asset)throw Error('请先选择素材');const marks=currentMarks();$(['event-start','event-end','event-contact'][i]).value=[marks.start,marks.end,marks.contact][i];if(i<2)resetLoopCounter()}));
async function loadEvents(){const events=await api('/events?asset_id='+encodeURIComponent(state.asset.asset_id));$('events').innerHTML=events.map(e=>`<div class="card"><span class="tag">${esc(e.kind)}</span><span class="tag">${esc(e.review_status)}</span><b>${e.start_ms}–${e.end_ms}ms</b><p>${esc(e.player_id||'未知球员')} · ${esc(json(e.labels))} · v${e.revision}</p><button class="small secondary" data-event="${esc(e.event_id)}">定位 / 修改</button></div>`).join('');$('events').querySelectorAll('[data-event]').forEach(b=>b.onclick=()=>{const e=events.find(e=>e.event_id===b.dataset.event);state.event=e;$('event-start').value=e.start_ms;$('event-end').value=e.end_ms;$('event-contact').value=e.contact_ms??'';$('event-player').value=e.player_id??'';$('event-rally').value=e.rally_id??'';$('event-kind').value=e.kind;$('event-visibility').value=e.visibility;$('event-review').value=e.review_status;$('event-labels').value=json(e.labels);$('event-unknown').value=e.unknown_reason??'';$('edit-state').textContent=`编辑 ${e.event_id} · 基于 revision ${e.revision}`;seekSource(e.start_ms).catch(error=>notice(error.message,true))})}
action('save-event',async()=>{if(!state.asset)throw Error('请先选择素材');const revision=state.event?.revision||0,start=Number($('event-start').value),end=Number($('event-end').value);const event={schema_version:'1.0',event_id:state.event?.event_id||id('event'),asset_id:state.asset.asset_id,match_id:state.asset.match_id,rally_id:$('event-rally').value||null,shot_id:null,player_id:$('event-player').value||null,track_id:null,kind:$('event-kind').value,start_ms:start,end_ms:end,contact_ms:$('event-contact').value===''?null:Number($('event-contact').value),labels:JSON.parse($('event-labels').value),visibility:$('event-visibility').value,confidence:null,review_status:$('event-review').value,revision:revision+1,provenance:{source:'manual',model_id:null,model_version:null,run_id:null},evidence:[{type:'source_interval',asset_id:state.asset.asset_id,start_ms:start,end_ms:end}],unknown_reason:$('event-unknown').value||null};state.event=await api('/events','POST',{event,expected_revision:revision,reviewer:$('reviewer').value,reviewer_type:$('reviewer-type').value});$('edit-state').textContent=`已保存 ${state.event.event_id} · revision ${state.event.revision}`;notice('标注已持久保存');await loadEvents();await overview()});
action('export-events',async()=>download('events.v1.json',await api('/events/export'+(state.asset?'?asset_id='+state.asset.asset_id:''))));
action('parse-query',async()=>{$('query-spec').value=json(await api('/queries/parse','POST',{text:$('query-text').value,player_id:$('query-player').value||null,use_llm:$('use-llm').checked}));notice('请检查解析条件，再执行检索')});
action('search-query',async()=>{const x=await api('/queries/search','POST',JSON.parse($('query-spec').value));state.candidates=x.candidates;drawCandidates();notice(`找到 ${x.candidates.length} 条候选；排序分数不是准确率`)});
function drawCandidates(){$('candidates').innerHTML=state.candidates.map(c=>`<div class="card"><b>${esc(c.asset_id)} · ${c.start_ms}–${c.end_ms}ms</b><p>球员 ${esc(c.player_id||'未知')} · ${esc(c.review_status)} · 排序 ${c.rank_score.toFixed(2)}</p><p>缺失：${esc(c.missing_conditions.join('；')||'无')}<br>不确定：${esc(c.uncertainty_reasons.join('；')||'无')}</p><details><summary>查看条件与源证据</summary><pre>${esc(json({matched_conditions:c.matched_conditions,evidence:c.evidence}))}</pre></details><div class="row"><button class="small secondary" data-preview="${c.candidate_id}">回看原片</button><button class="small" data-confirm="${c.candidate_id}">确认选用</button><button class="small secondary" data-reject="${c.candidate_id}">拒绝</button></div></div>`).join('')||'<p class="muted">没有符合条件的候选；可检查标签、球员、回合和审核状态。</p>';$('candidates').querySelectorAll('[data-preview]').forEach(b=>b.onclick=async()=>{const c=state.candidates.find(c=>c.candidate_id===b.dataset.preview);page('library');await selectAsset(c.asset_id,c.start_ms)});['confirm','reject'].forEach(k=>$('candidates').querySelectorAll('[data-'+k+']').forEach(b=>b.onclick=async()=>{try{const c=await api('/candidates/'+b.dataset[k]+'/confirm','POST',{review_status:k==='confirm'?'confirmed':'rejected',reviewer:$('reviewer').value,reviewer_type:$('reviewer-type').value});state.candidates[state.candidates.findIndex(x=>x.candidate_id===c.candidate_id)]=c;drawCandidates()}catch(e){notice(e.message,true)}}))}
action('build-timeline',async()=>{const ids=state.candidates.filter(c=>c.review_status==='confirmed').map(c=>c.candidate_id);if(!ids.length)throw Error('请先确认至少一个候选');state.timeline=await api('/timelines/from-candidates','POST',{candidate_ids:ids,title:'羽毛球技战术集锦',pre_ms:1000,post_ms:1000});page('timeline');drawTimeline();notice('已保存可编辑时间线，重叠片段已合并')});
const renderDrafts=new Map(),defaultSafeArea={x:.06,y:.10,width:.82,height:.78};
const renderOptionFields=['export-preset','export-platform-profile','safe-area-x','safe-area-y','safe-area-width','safe-area-height'];
function outputForPreset(preset){
  if(!['portrait_1080p30','portrait_1080p60'].includes(preset))throw Error('请明确选择 30 / 60 fps 竖屏预设；旧工程输出不会自动转换');
  return {width:1080,height:1920,fps:preset==='portrait_1080p60'?60:30,video_codec:'h264',audio_codec:'aac'};
}
function matchingPreset(output){
  for(const name of ['portrait_1080p30','portrait_1080p60'])if(Object.entries(outputForPreset(name)).every(([key,value])=>output?.[key]===value))return name;
  return null;
}
function renderDraft(timeline=state.timeline){
  if(!timeline)throw Error('先从候选创建时间线');
  if(!renderDrafts.has(timeline.timeline_id))renderDrafts.set(timeline.timeline_id,{timelineId:timeline.timeline_id,revision:null,loaded:false,loading:false,saving:false,dirty:false,conflict:false,loadToken:0,error:null,options:{export_preset:null,safe_area:{...defaultSafeArea},platform_profile:null}});
  return renderDrafts.get(timeline.timeline_id);
}
function drawRenderOptions(){
  if(!state.timeline)return;
  const draft=renderDraft(),options=draft.options,busy=draft.loading||draft.saving;
  $('export-preset').value=options.export_preset??'';$('export-platform-profile').value=options.platform_profile??'';
  for(const name of ['x','y','width','height'])$('safe-area-'+name).value=options.safe_area[name];
  for(const name of renderOptionFields)$(name).disabled=busy||!draft.loaded;
  $('save-timeline').disabled=busy||!draft.loaded;$('render-timeline').disabled=busy||!draft.loaded;$('reload-render-options').disabled=busy;
  const status=$('render-options-status');status.dataset.timelineId=draft.timelineId;status.dataset.revision=draft.revision??'';status.dataset.dirty=String(draft.dirty);status.dataset.conflict=String(draft.conflict);
  if(draft.conflict)status.textContent='时间线已保存；导出设置发生修订冲突。保留了本地修改，尚未提交渲染。请先复制需要保留的设置，再点击重载读取已保存版本。';
  else if(busy)status.textContent=draft.saving?'正在保存时间线与导出设置…':'正在读取导出设置…';
  else if(draft.error)status.textContent='导出设置未保存：'+draft.error;
  else if(!options.export_preset)status.textContent=`当前工程 ${state.timeline.output?.fps??'未知'} fps；未选择竖屏预设。请明确选择 30 / 60 fps 后再保存或导出，原输出暂保持不变。`;
  else status.textContent=`导出设置 revision ${draft.revision??0} · ${draft.dirty?'本地修改未保存':'已加载'}`+(matchingPreset(state.timeline.output)!==options.export_preset?'；工程输出与预设不同，保存将使用所选预设。':'');
}
async function loadRenderOptions(timeline=state.timeline,{force=false}={}){
  const draft=renderDraft(timeline);
  if(!force&&(draft.dirty||draft.saving)){if(state.timeline?.timeline_id===draft.timelineId)drawRenderOptions();return draft}
  const token=++draft.loadToken;draft.loading=true;draft.error=null;
  if(state.timeline?.timeline_id===draft.timelineId)drawRenderOptions();
  try{
    const record=await api('/timelines/'+encodeURIComponent(draft.timelineId)+'/render-options');
    if(token!==draft.loadToken)return draft;
    if(record.timeline_id!==draft.timelineId||!Number.isInteger(record.revision)||!record.options)throw Error('导出设置返回了不匹配的工程或修订');
    draft.revision=record.revision;draft.options={export_preset:record.options.export_preset??null,safe_area:{...(record.options.safe_area??defaultSafeArea)},platform_profile:record.options.platform_profile??null};
    draft.loaded=true;draft.dirty=false;draft.conflict=false;
    if(force&&state.timeline?.timeline_id===draft.timelineId&&draft.options.export_preset){state.timeline.output=outputForPreset(draft.options.export_preset);$('timeline-json').value=json(state.timeline)}
    return draft;
  }catch(error){if(token===draft.loadToken)draft.error=error.message;throw error}
  finally{if(token===draft.loadToken){draft.loading=false;if(state.timeline?.timeline_id===draft.timelineId)drawRenderOptions()}}
}
function optionsFromControls(){
  const safe_area={};for(const name of ['x','y','width','height']){const value=String($('safe-area-'+name).value).trim();safe_area[name]=value===''?NaN:Number(value)}
  return {export_preset:$('export-preset').value||null,safe_area,platform_profile:$('export-platform-profile').value||null};
}
function renderOptionsChanged(){
  if(!state.timeline)return;const draft=renderDraft();if(!draft.loaded||draft.loading||draft.saving)return;
  draft.options=optionsFromControls();draft.dirty=true;draft.error=null;
  if(draft.options.export_preset){state.timeline.output=outputForPreset(draft.options.export_preset);$('timeline-json').value=json(state.timeline)}
  // Keep partially typed number inputs intact while updating the status.
  $('render-options-status').dataset.dirty='true';
  $('render-options-status').textContent=draft.conflict?'修订冲突；本地修改仍保留，请重载已保存版本后重新应用所需修改。':`导出设置 revision ${draft.revision} · 本地修改未保存`;
}
function validateRenderOptions(options,timeline){
  outputForPreset(options.export_preset);
  const area=options.safe_area;
  if(!area||!['x','y','width','height'].every(key=>typeof area[key]==='number'&&Number.isFinite(area[key]))||area.x<0||area.y<0||area.width<=0||area.height<=0||area.x+area.width>1||area.y+area.height>1)throw Error('安全区须为有效比例：x、y ≥ 0，宽、高 > 0，x + 宽、y + 高 ≤ 1');
  if(![null,'youtube_shorts'].includes(options.platform_profile))throw Error('平台规则只支持不附加上限或 YouTube Shorts');
  const duration=(timeline.segments||[]).reduce((sum,segment)=>sum+(Number(segment.out_ms)-Number(segment.in_ms))/Number(segment.speed??1),0);
  if(options.platform_profile==='youtube_shorts'&&(!Number.isFinite(duration)||duration>180000))throw Error('YouTube Shorts 档总输出时长不得超过 180000 ms（含速度换算）');
  return options;
}
async function saveTimelineWithOptions(){
  if(!state.timeline)throw Error('先从候选创建时间线');
  const draft=renderDraft();if(!draft.loaded||draft.loading||draft.saving)throw Error('导出设置尚未准备好');
  if(draft.conflict)throw Error('导出设置存在修订冲突，本地修改已保留；请先重载已保存版本');
  const options=validateRenderOptions(optionsFromControls(),state.timeline),timeline=JSON.parse(JSON.stringify(state.timeline));
  timeline.title=$('timeline-title').value;timeline.output=outputForPreset(options.export_preset);
  draft.options=options;draft.dirty=true;draft.saving=true;draft.error=null;drawRenderOptions();
  let timelineSaved=false;
  try{
    const saved=await api('/timelines','POST',{timeline,reviewer:$('reviewer').value,reviewer_type:$('reviewer-type').value});timelineSaved=true;
    if(state.timeline?.timeline_id===draft.timelineId){state.timeline=saved;$('timeline-json').value=json(saved)}
    const record=await api('/timelines/'+encodeURIComponent(draft.timelineId)+'/render-options','PUT',{expected_revision:draft.revision,options});
    if(record.timeline_id!==draft.timelineId||!Number.isInteger(record.revision))throw Error('导出设置保存响应无有效修订');
    draft.revision=record.revision;draft.options=record.options;draft.dirty=false;
    return saved;
  }catch(error){
    draft.conflict=timelineSaved&&error.status===409;draft.error=(timelineSaved?'时间线已保存；导出设置未保存：':'')+error.message;
    throw Error(draft.conflict?'导出设置修订冲突，本地设置已保留，未提交渲染；请重载已保存版本后处理。':draft.error);
  }finally{draft.saving=false;if(state.timeline?.timeline_id===draft.timelineId)drawRenderOptions()}
}
for(const field of renderOptionFields)$(field).addEventListener(field.startsWith('safe-area-')?'input':'change',renderOptionsChanged);
action('reload-render-options',()=>loadRenderOptions(state.timeline,{force:true}));
async function loadTimelines(){
  const list=await api('/timelines');$('timeline-select').innerHTML=list.map(t=>`<option value="${esc(t.timeline_id)}">${esc(t.title)}</option>`).join('');
  if(state.timeline)$('timeline-select').value=state.timeline.timeline_id;else if(list.length)state.timeline=list[0];
  $('timeline-select').onchange=async()=>{state.timeline=list.find(t=>t.timeline_id===$('timeline-select').value);drawTimeline();try{await loadRenderOptions()}catch(error){notice(error.message,true)}};
  drawTimeline();if(state.timeline)await loadRenderOptions();
}
action('refresh-timelines',loadTimelines);
function drawTimeline(){const t=state.timeline;if(!t)return;drawRenderOptions();$('timeline-title').value=t.title;$('timeline-json').value=json(t);$('segments').innerHTML=t.segments.map((s,i)=>`<div class="segment"><div class="row"><h3>${i+1}. ${esc(s.asset_id)}</h3><button class="small secondary" data-up="${i}">↑</button><button class="small secondary" data-down="${i}">↓</button><button class="small secondary" data-remove="${i}">移除</button><button class="small secondary" data-view="${i}">预览源片</button></div><div class="form-grid"><label>入点 ms<input data-field="in_ms" data-i="${i}" type="number" value="${s.in_ms}"></label><label>出点 ms<input data-field="out_ms" data-i="${i}" type="number" value="${s.out_ms}"></label><label>速度<input data-field="speed" data-i="${i}" type="number" step="0.1" min="0.1" value="${s.speed}"></label><label>片段标题<input data-field="title" data-i="${i}" value="${esc(s.title)}"></label><label>声音<select data-field="audio" data-i="${i}"><option value="source" ${s.audio==='source'?'selected':''}>原声</option><option value="mute" ${s.audio==='mute'?'selected':''}>静音</option></select></label><label>审核<select data-field="review_status" data-i="${i}"><option value="confirmed" ${s.review_status==='confirmed'?'selected':''}>已确认</option><option value="unreviewed" ${s.review_status==='unreviewed'?'selected':''}>待审核</option></select></label></div></div>`).join('');$('segments').querySelectorAll('[data-field]').forEach(el=>el.onchange=()=>{t.segments[Number(el.dataset.i)][el.dataset.field]=['in_ms','out_ms','speed'].includes(el.dataset.field)?Number(el.value):el.value;$('timeline-json').value=json(t)});['up','down','remove','view'].forEach(k=>$('segments').querySelectorAll('[data-'+k+']').forEach(b=>b.onclick=async()=>{const i=Number(b.dataset[k]);if(k==='remove')t.segments.splice(i,1);else if(k==='view'){page('library');await selectAsset(t.segments[i].asset_id,t.segments[i].in_ms);return}else{const j=i+(k==='up'?-1:1);if(j>=0&&j<t.segments.length)[t.segments[i],t.segments[j]]=[t.segments[j],t.segments[i]]}drawTimeline()}))}
action('apply-timeline-json',async()=>{
  state.timeline=JSON.parse($('timeline-json').value);drawTimeline();const draft=renderDraft();
  if(!draft.loaded){try{await loadRenderOptions()}catch(error){
    // Preserve the existing JSON→new-timeline workflow. A missing timeline has
    // no persisted render-options revision; the POST creates it before PUT.
    if(error.status!==404)throw error;draft.loaded=true;draft.revision=0;draft.error=null;
  }}
  draft.options.export_preset=matchingPreset(state.timeline.output);draft.dirty=true;drawRenderOptions();
});
action('save-timeline',async()=>{await saveTimelineWithOptions();notice('时间线与导出设置均已保存')});
action('render-timeline',async()=>{const saved=await saveTimelineWithOptions();const j=await api('/timelines/'+encodeURIComponent(saved.timeline_id)+'/render','POST',{research_preview:$('research-preview').checked});notice('导出已排队：'+j.job_id);page('jobs')});
function jobCard(j){return `<div class="card"><b>${esc(j.operation)}</b> <span class="tag">${esc(j.status)}</span><p>${esc(j.job_id)} · 尝试 ${j.attempt??j.attempts??0} ${j.cancel_requested?'· 请求取消中':''}</p><p>${esc(j.progress?.stage||'')} ${esc(j.progress?.current??'')}${j.progress?.total!=null?'/'+esc(j.progress.total):''} ${esc(j.progress?.unit||'')}</p>${j.error?'<p>'+esc(json(j.error))+'</p>':''}<div class="row"><button class="small secondary" data-log="${j.job_id}">详情 / 日志</button><button class="small secondary" data-cancel="${j.job_id}">取消</button><button class="small secondary" data-retry="${j.job_id}">重试</button>${j.status==='succeeded'?'<button class="small" data-apply="'+j.job_id+'">应用结果</button>':''}</div></div>`}
async function loadJobs(){const jobs=await api('/jobs');$('jobs-list').innerHTML=jobs.map(jobCard).join('')||'<p class="muted">没有任务</p>';['log','cancel','retry','apply'].forEach(k=>$('jobs-list').querySelectorAll('[data-'+k+']').forEach(b=>b.onclick=async()=>{try{const id=b.dataset[k];if(k==='log'){const j=await api('/jobs/'+id),logs=await api('/jobs/'+id+'/logs');$('job-artifacts').replaceChildren();$('job-detail').textContent=json({job:j,logs});const artifacts=j.result?.artifacts||[];for(const a of artifacts){const link=document.createElement('a');link.href='/api/v1/jobs/'+id+'/artifacts/'+a.artifact_id;link.textContent='下载 '+a.kind+' '+a.relative_path;link.style.display='block';$('job-artifacts').append(link);if(a.relative_path.endsWith('.mp4')){const video=document.createElement('video');video.controls=true;video.preload='metadata';video.src=link.href;video.style.maxHeight='520px';$('job-artifacts').append(video)}}}else{const result=await api('/jobs/'+id+'/'+k,'POST',{});$('job-artifacts').replaceChildren();$('job-detail').textContent=json({action:k,result});notice(({cancel:'取消请求',retry:'重试已提交',apply:'结果已应用'})[k]+'：'+(result.job_id||id)+' · '+(result.status||'操作完成'));await loadJobs();if(k==='apply')await loadAssets()}}catch(e){notice(e.message,true)}}));const models=await api('/models');const currentModel=$('run-model-id').value;$('run-model-id').innerHTML=models.map(m=>'<option value="'+esc(m.model_id)+'">'+esc(m.display_name)+' · '+esc(m.status)+'</option>').join('');if(models.some(m=>m.model_id===currentModel))$('run-model-id').value=currentModel;$('models').innerHTML=models.map(m=>`<div class="card"><b>${esc(m.display_name)}</b> <span class="tag">${esc(m.status)}</span><p>${esc(m.version||'尚无版本')} · ${esc((m.capabilities||[]).join(', '))}</p><p>${esc(m.reason||'')}</p><details><summary>参数与能力</summary><pre>${esc(json(m))}</pre></details></div>`).join('')}
action('refresh-jobs',loadJobs);action('import-model',async()=>{await api('/models/import','POST',JSON.parse($('model-json').value));await loadJobs()});
async function loadSettings(){const c=await api('/settings/llm');$('llm-url').value=c.base_url;$('llm-model').value=c.model;$('llm-key').value=c.key_env;$('llm-timeout').value=c.timeout;$('llm-mask').textContent='密钥状态：'+c.key_masked;$('health').textContent=json(await api('/health'));try{$('ls-status').textContent=json(await api('/annotation/label-studio/status'))}catch(e){$('ls-status').textContent='集成适配器尚未启用'}}
action('save-llm',async()=>{await api('/settings/llm','PUT',{provider:'openai-compatible',base_url:$('llm-url').value,model:$('llm-model').value,key_env:$('llm-key').value,timeout:Number($('llm-timeout').value)});await loadSettings();notice('已保存端点配置，未保存明文密钥')});action('test-llm',async()=>{$('llm-status').textContent=json(await api('/settings/llm/test','POST',{}))});
action('save-player',async()=>{await api('/players','POST',{player_id:$('player-id').value||undefined,display_name:$('player-name').value,identity_status:'unconfirmed'});notice('球员已保存，身份待确认')});
action('ls-task',async()=>{const x=await api('/annotation/label-studio/task','POST',{asset_id:$('ls-asset').value,frame_map:JSON.parse($('ls-map').value)});download('labelstudio-task.json',[x]);$('ls-result').textContent='任务 JSON 已导出，可在 Label Studio 中导入并编辑。'});
action('ls-import',async()=>{$('ls-result').textContent=json(await api('/annotation/label-studio/import','POST',{export:JSON.parse($('ls-export').value),frame_map:JSON.parse($('ls-map').value),reviewer:$('reviewer').value,reviewer_type:$('reviewer-type').value}))});
async function boot(){try{await loadLibraries();await Promise.all([overview(),loadAssets(),loadSettings()]);$('connection').textContent='● 控制面已连接'}catch(e){notice(e.message,true);$('connection').textContent='连接异常'}}boot();setInterval(()=>{if($('jobs').classList.contains('active'))loadJobs().catch(()=>{})},5000);

action('run-model',async()=>{const j=await api('/models/'+encodeURIComponent($('run-model-id').value)+'/run','POST',{asset_ids:$('run-model-assets').value.split(',').map(x=>x.trim()).filter(Boolean),parameters:JSON.parse($('run-model-parameters').value)});notice('模型任务已提交：'+j.job_id);await loadJobs()});

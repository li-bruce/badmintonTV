// Dependency-free frontend regressions. Run from repo root:
// node -e "require('vm').runInThisContext(require('fs').readFileSync('tests/platform/preview_ui.test.cjs','utf8'))"
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('apps/platform/static/app.js', 'utf8');
const mathScope = {};
vm.runInNewContext(source.split('// Browser bindings start here.')[0]+'\nthis.math=PreviewMath;',mathScope);
const math=mathScope.math;
// Explicit PTS-derived fixture: 60 fps source represented by 30 fps proxy.
// The image map skips odd frames; coverage remains continuous.
const proxy=[
  {proxy_frame_index:0,proxy_pts_ms:0,source_frame_index:60,source_pts:90000,source_pts_ms:1000,coverage_start_ms:1000,coverage_end_ms:1033.333333},
  {proxy_frame_index:1,proxy_pts_ms:33.333333,source_frame_index:62,source_pts:93000,source_pts_ms:1033.333333,coverage_start_ms:1033.333333,coverage_end_ms:1066.666667},
  {proxy_frame_index:2,proxy_pts_ms:66.666667,source_frame_index:64,source_pts:96000,source_pts_ms:1066.666667,coverage_start_ms:1066.666667,coverage_end_ms:1100}
];
test('60→30 dropped image still has continuous source coverage',()=>{
  assert.equal(math.coverageAt(proxy,1016.666667).source_frame_index,60);
  assert.ok(Math.abs(math.mediaForSource(proxy,1016.666667,100)-16.666667)<.00001);
  assert.deepEqual({...math.marks(proxy[0],null,0)},{start:1000,end:1034,contact:1000});
  assert.equal(math.coverageAt(proxy,1033.333333).source_frame_index,62);
  assert.equal(math.coverageAt(proxy,1100),null);
});
test('exact source selection labels the missing source frame, not its proxy image',()=>{
  const frame={source_frame_index:61,source_pts:91500,source_pts_ms:1016.666667,source_end_ms:1033.333333};
  assert.deepEqual({...math.marks(proxy[0],frame,0)},{start:1016,end:1034,contact:1016});
  assert.equal(math.proxyAt(proxy,math.mediaForSource(proxy,frame.source_pts_ms,100,true)).source_frame_index,60);
});
test('VFR media↔source uses explicit unequal coverage durations and nonzero source origin',()=>{
  const vfr=[
    {proxy_frame_index:0,proxy_pts_ms:0,source_pts_ms:2400,coverage_start_ms:2400,coverage_end_ms:2417},
    {proxy_frame_index:1,proxy_pts_ms:17,source_pts_ms:2417,coverage_start_ms:2417,coverage_end_ms:2490},
    {proxy_frame_index:2,proxy_pts_ms:90,source_pts_ms:2490,coverage_start_ms:2490,coverage_end_ms:2500}
  ];
  for(const value of [2400,2416.8,2417,2475,2499.9])assert.ok(Math.abs(math.sourceAtMedia(vfr,math.mediaForSource(vfr,value,100),100)-value)<1e-8);
  assert.throws(()=>math.mediaForSource(vfr,2399,100),/覆盖窗口/);
  assert.throws(()=>math.mediaForSource(vfr,2500,100),/覆盖窗口/);
});
test('repeated source image does not merge separate proxy coverage',()=>{
  const duplicate=proxy.map(r=>({...r,source_frame_index:60,source_pts_ms:1000}));
  assert.equal(math.coverageAt(duplicate,1080).proxy_frame_index,2);
  assert.equal(math.marks(duplicate[2],null,0).start,1066);
  assert.equal(math.marks(duplicate[2],null,0).contact,1000);
});
test('genuine source gap is rejected; there is no FPS fallback',()=>{
  const gap=proxy.map(r=>({...r}));gap[0].coverage_end_ms=1010;
  assert.throws(()=>math.mediaForSource(gap,1020,100),/覆盖窗口/);
});
test('benchmark summaries exclude failed and no-op seeks, retaining counts',()=>{
  const rows=[1,2,3,4].map(elapsed_ms=>({status:'ok',elapsed_ms}));
  rows.push({status:'error',elapsed_ms:8000},{status:'no_op',elapsed_ms:.1});
  assert.deepEqual({...math.summary(rows)},{samples:6,measured:4,failed:1,no_op:1,median_ms:2.5,p95_ms:4});
  assert.equal(math.summary([]).median_ms,null);
});

class NodeElement extends EventTarget {
  constructor(){super();this.value='';this.textContent='';this.innerHTML='';this.style={};this.dataset={};this.classList={toggle(){},contains(){return false}};this.children=[];this.checked=false;this.disabled=false}
  querySelectorAll(){return []} querySelector(){return null} setAttribute(){} append(...items){this.children.push(...items)} replaceChildren(){this.children=[]} closest(){return null}
  scrollIntoView(){this.scrolled=true} getBoundingClientRect(){return {x:20,y:40,width:280,height:158,left:20,right:300,top:40,bottom:198}}
}
class VideoElement extends NodeElement {
  constructor(){super();this.readyState=1;this.duration=.1;this.paused=true;this.seeking=false;this.time=0;this.callbacks=new Map();this.nextCallback=0;this.autoPresent=true}
  get currentTime(){return this.time}
  set currentTime(value){this.time=value;this.seeking=true;this.dispatchEvent(new Event('seeking'));setTimeout(()=>{this.seeking=false;this.dispatchEvent(new Event('seeked'));if(this.autoPresent)this.present(value)},0)}
  requestVideoFrameCallback(fn){const id=++this.nextCallback;this.callbacks.set(id,fn);return id}
  cancelVideoFrameCallback(id){this.callbacks.delete(id)}
  present(mediaTime){const callbacks=[...this.callbacks.values()];this.callbacks.clear();for(const cb of callbacks)cb(performance.now(),{mediaTime})}
  pause(){this.paused=true} play(){this.paused=false;this.dispatchEvent(new Event('play'));return Promise.resolve()} load(){}
}
function ui(){
  const nodes=new Map(),video=new VideoElement();nodes.set('player',video);
  const element=id=>{if(!nodes.has(id))nodes.set(id,new NodeElement());return nodes.get(id)};
  const scope={URL,URLSearchParams,Blob,Map,Error,performance,setTimeout,clearTimeout,setInterval(){},requestAnimationFrame(){},
    location:{href:'http://127.0.0.1:18082/',origin:'http://127.0.0.1:18082'},
    window:{innerWidth:1000,innerHeight:700},crypto:{randomUUID:()=> 'test'},document:{getElementById:element,querySelectorAll:()=>[],querySelector:()=>({textContent:'05 模型与任务'}),createElement:()=>new NodeElement(),activeElement:null,visibilityState:'visible'},
    fetch:async url=>({ok:true,json:async()=>String(url).endsWith('/workflow')?{jobs:[]}:String(url).endsWith('/settings/llm')?{}:[]})};
  vm.createContext(scope);vm.runInContext(source+'\nthis.ui={preview,state,inspections,selectAsset,seekMedia,seekSource,stepSource,inspectSourceFrame,clearSourceImage,sourceFrameAt,sourceFrameByIndex,currentMarks,updatePreviewReadout,benchmarkSeeks,checkLoop,resetLoopCounter,renderDraft,loadRenderOptions,renderOptionsChanged,validateRenderOptions,saveTimelineWithOptions,drawTimeline,loadJobs};',scope);
  scope.ui.state.asset={asset_id:'source-a',sha256:'hash-a',duration_ms:2000};
  scope.ui.preview.data={source_asset_id:'source-a',source_sha256:'hash-a',source_time_base:'1/90000',source_frame_count:120,source_frames_url:'/source-frames',window_start_ms:1000,window_end_ms:1100};
  scope.ui.preview.frames=proxy;
  return {scope,video,nodes,api:scope.ui};
}
test('seek measurement waits for the submitted target frame as well as seeked',async()=>{
  const {video,api}=ui();video.autoPresent=false;
  let resolved=false;
  const pending=api.seekMedia(50,{requestedSourceMs:1033.333333,measure:true}).then(x=>{resolved=true;return x});
  await new Promise(r=>setTimeout(r,10));assert.equal(resolved,false);
  video.present(.0);await Promise.resolve();assert.equal(resolved,false);
  video.present(.033333333);const result=await pending;
  assert.equal(result.status,'ok');assert.equal(result.frame_observed,true);
  assert.equal(result.observed_source_frame,62);assert.ok(result.elapsed_ms>=result.seeked_ms);assert.ok(result.presented_ms>=0);
});
test('source-frame cache is not contaminated by an old asset response',async()=>{
  const {scope,api}=ui();let complete;
  scope.fetch=()=>new Promise(resolve=>{complete=()=>resolve({ok:true,json:async()=>({source_frames:[{source_frame_index:61,source_pts_ms:1016,source_end_ms:1033}]})})});
  const pending=api.sourceFrameAt(1020);api.preview.epoch++;complete();
  await assert.rejects(pending,/切换素材/);assert.equal(api.preview.sourceFrames.size,0);
});
test('late asset A lookup cannot replace selected B or contaminate its saved event',async()=>{
  const {scope,api,nodes}=ui();await new Promise(resolve=>setTimeout(resolve,0));
  const assetA={asset_id:'asset-a',title:'A',sha256:'a',match_id:'match-a',duration_ms:4000,width:1920,height:1080,relative_path:'data/a.mp4'};
  const assetB={...assetA,asset_id:'asset-b',title:'B',sha256:'b',match_id:'match-b',relative_path:'data/b.mp4'};
  api.state.assets=[assetB];let releaseA,saved;
  scope.fetch=async(path,init={})=>{
    if(path==='/api/v1/assets')return new Promise(resolve=>{releaseA=()=>resolve({ok:true,json:async()=>[assetA,assetB]})});
    let body=[];
    if(path.endsWith('/preview'))body={status:'not_ready'};
    if(path==='/api/v1/events'&&init.method==='POST'){saved=JSON.parse(init.body);body=saved.event}
    if(path==='/api/v1/workflow')body={jobs:[]};
    return {ok:true,json:async()=>body};
  };
  const pendingA=api.selectAsset('asset-a');assert.equal(typeof releaseA,'function');
  await api.selectAsset('asset-b');releaseA();await pendingA;
  assert.equal(api.state.asset.asset_id,'asset-b');assert.equal(nodes.get('asset-title').textContent,'B');
  for(const [key,value] of Object.entries({'event-labels':'{}','event-kind':'stroke','event-visibility':'visible','event-review':'unreviewed','reviewer':'agent-ui-test','reviewer-type':'agent'}))scope.document.getElementById(key).value=value;
  await nodes.get('save-event').onclick();
  assert.equal(saved.event.asset_id,'asset-b');assert.equal(saved.event.match_id,'match-b');assert.equal(saved.event.evidence[0].asset_id,'asset-b');
  assert.equal(saved.expected_revision,0);assert.equal(saved.reviewer_type,'agent');
});
async function eventUI(){
  const context=ui(),{scope,api}=context;await new Promise(resolve=>setTimeout(resolve,0));
  const asset=key=>({asset_id:key,title:key,sha256:'hash-'+key,match_id:'match-'+key,duration_ms:4000,width:1280,height:720});
  api.state.assets=['A','B'].map(asset);
  const event=key=>({event_id:'event-'+key,asset_id:key,match_id:'match-'+key,revision:1,start_ms:20,end_ms:200,kind:'stroke',review_status:'unreviewed',labels:{},visibility:'visible'});
  context.events={A:[event('A')],B:[event('B')]};context.calls=[];context.response=body=>({ok:true,json:async()=>body});
  const list=scope.document.getElementById('events');
  scope.document.getElementById('notice');
  list.querySelectorAll=()=>{context.buttons=[...list.innerHTML.matchAll(/data-event="([^"]+)"/g)].map(match=>{const button=scope.document.createElement('button');button.dataset.event=match[1];return button});return context.buttons};
  scope.fetch=async(path,init={})=>{
    context.calls.push({path,method:init.method||'GET',body:init.body?JSON.parse(init.body):null});
    const intercepted=context.respond?.(path,init);if(intercepted!==undefined)return intercepted;
    if(path.startsWith('/api/v1/events?asset_id='))return context.response(context.events[path.split('=').at(-1)]||[]);
    if(path==='/api/v1/events'&&init.method==='POST')return context.response(JSON.parse(init.body).event);
    return context.response(path.endsWith('/preview')?{status:'not_ready'}:path.endsWith('/workflow')?{jobs:[]}:[]);
  };
  for(const [key,value] of Object.entries({'event-labels':'{}','event-kind':'stroke','event-visibility':'visible','event-review':'unreviewed','reviewer':'agent-ui-test','reviewer-type':'agent'}))scope.document.getElementById(key).value=value;
  return context;
}

test('late event-list A response cannot replace B or start a second B preview refresh',async()=>{
  const context=await eventUI(),{api,nodes,response}=context;let release;
  context.respond=path=>path==='/api/v1/events?asset_id=A'?new Promise(resolve=>{release=()=>resolve(response(context.events.A))}):undefined;
  const pendingA=api.selectAsset('A',500);await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(typeof release,'function');await api.selectAsset('B',1500);
  release();await pendingA;
  assert.equal(api.state.asset.asset_id,'B');assert.deepEqual(context.buttons.map(button=>button.dataset.event),['event-B']);
  assert.equal(context.calls.filter(call=>call.path==='/api/v1/assets/B/preview').length,1);
  assert.doesNotMatch(nodes.get('events').innerHTML,/event-A/);
  await nodes.get('save-event').onclick();
  const saved=context.calls.find(call=>call.method==='POST').body;
  assert.equal(saved.event.asset_id,'B');assert.equal(saved.expected_revision,0);assert.notEqual(saved.event.event_id,'event-A');
});

test('event buttons from an earlier asset epoch remain inert after B or A→B→A selection',async()=>{
  for(const backToA of [false,true]){
    const context=await eventUI(),{api,nodes,video}=context;
    await api.selectAsset('A');const oldButton=context.buttons[0];await api.selectAsset('B');if(backToA)await api.selectAsset('A');
    const before={time:video.currentTime,text:nodes.get('edit-state').textContent,start:nodes.get('event-start').value};
    oldButton.onclick();assert.equal(api.state.event,null);
    assert.equal(video.currentTime,before.time);assert.equal(nodes.get('edit-state').textContent,before.text);assert.equal(nodes.get('event-start').value,before.start);
  }
});

test('late save success or failure cannot alter another asset epoch or refresh its event list',async()=>{
  for(const failure of [false,true])for(const backToA of [false,true]){
    const context=await eventUI(),{api,nodes,response}=context;await api.selectAsset('A');let release;
    context.respond=(path,init)=>path==='/api/v1/events'&&init.method==='POST'?new Promise(resolve=>{
      const submitted=JSON.parse(init.body).event;
      release=()=>resolve(failure?{ok:false,status:409,json:async()=>({detail:'old A conflict'})}:response({...submitted,revision:2}));
    }):undefined;
    const pendingSave=nodes.get('save-event').onclick();assert.equal(typeof release,'function');
    await api.selectAsset('B');if(backToA)await api.selectAsset('A');
    const before={calls:context.calls.length,text:nodes.get('edit-state').textContent,notice:nodes.get('notice').textContent};
    release();await pendingSave;
    assert.equal(context.calls.length,before.calls);assert.equal(api.state.event,null);
    assert.equal(nodes.get('edit-state').textContent,before.text);assert.equal(nodes.get('notice').textContent,before.notice);
    const sent=context.calls.find(call=>call.method==='POST').body.event;assert.equal(sent.asset_id,'A');assert.equal(sent.evidence[0].asset_id,'A');
  }
});

test('selection clears the old event before a slow new frame-map lookup and saving uses revision zero',async()=>{
  const context=await eventUI(),{api,nodes,response}=context;await api.selectAsset('A');context.buttons[0].onclick();
  assert.equal(api.state.event.event_id,'event-A');let release;
  context.respond=path=>path==='/api/v1/assets/B/frame-map'?new Promise(resolve=>{release=()=>resolve(response([]))}):undefined;
  const pending=api.selectAsset('B');assert.equal(typeof release,'function');assert.equal(api.state.event,null);assert.equal(nodes.get('events').innerHTML,'');
  await nodes.get('save-event').onclick();const saved=context.calls.find(call=>call.method==='POST').body;
  assert.equal(saved.event.asset_id,'B');assert.equal(saved.expected_revision,0);assert.notEqual(saved.event.event_id,'event-A');
  release();await pending;
});

test('same-asset switch to a new event draft keeps a late successful save receipt out of the editor',async()=>{
  const context=await eventUI(),{api,nodes,response}=context;await api.selectAsset('A');let release;
  context.respond=(path,init)=>path==='/api/v1/events'&&init.method==='POST'?new Promise(resolve=>{release=()=>resolve(response(JSON.parse(init.body).event))}):undefined;
  const pending=nodes.get('save-event').onclick();await nodes.get('new-event').onclick();
  release();await pending;assert.equal(api.state.event,null);assert.equal(nodes.get('edit-state').textContent,'新标注 · revision 1');
});

test('an event seek waiting for A metadata cannot seek B when metadata later becomes ready',async()=>{
  const context=await eventUI(),{api,nodes,video}=context;await api.selectAsset('A');
  video.readyState=0;context.buttons[0].onclick();await api.selectAsset('B');
  const before={time:video.currentTime,notice:nodes.get('notice').textContent};
  video.readyState=1;video.dispatchEvent(new Event('loadedmetadata'));await new Promise(resolve=>setTimeout(resolve,5));
  assert.equal(api.state.asset.asset_id,'B');assert.equal(video.currentTime,before.time);assert.equal(nodes.get('notice').textContent,before.notice);
});

test('a slower old source seek cannot replace a later intent',async()=>{
  const {scope,api}=ui();let complete;
  scope.fetch=()=>new Promise(resolve=>{complete=()=>resolve({ok:true,json:async()=>({source_frames:[{source_frame_index:61,source_pts_ms:1016,source_end_ms:1033}]})})});
  const pending=api.seekSource(1020);api.preview.intent++;complete();
  await assert.rejects(pending,/后续操作/);assert.equal(api.preview.selected,null);
});
test('source marks remain exact while proxy presents a dropped-frame neighbour',async()=>{
  const {api,nodes}=ui();const frame={source_frame_index:61,source_pts:91500,source_pts_ms:1016.666667,source_end_ms:1033.333333};
  api.preview.sourceFrames.set(61,frame);
  const result=await api.seekSource(frame.source_pts_ms,{measure:true});
  assert.equal(result.status,'ok');assert.equal(result.observed_source_frame,60);
  assert.equal(api.currentMarks().start,1016);assert.equal(api.currentMarks().end,1034);
  assert.match(nodes.get('preview-coverage').textContent,/精确选择源帧 #61/);
});
test('cold group reloads unique media URLs and warm group reuses the same 30 fixed points',async()=>{
  const {scope,video,api}=ui();const urls=[];let serial=0;
  scope.crypto.randomUUID=()=>String(++serial);
  api.preview.data.media_url='/api/v1/assets/a/previews/j/media';
  for(let i=0;i<6;i++)api.preview.sourceFrames.set(60+i,{source_frame_index:60+i,source_pts:90000+i*1500,source_pts_ms:1000+i*100/6,source_end_ms:1000+(i+1)*100/6});
  video.load=function(){urls.push(this.src);this.time=0;this.readyState=0;setTimeout(()=>{this.readyState=1;this.dispatchEvent(new Event('loadedmetadata'))},1)};
  await api.benchmarkSeeks('cold_media_load',true);
  const cold=api.preview.measurements[0];
  assert.equal(urls.length,30);assert.equal(new Set(urls).size,30);assert.equal(cold.rows.length,30);
  assert.equal(video.scrolled,true);assert.equal(cold.visibility_at_start.document_visibility,'visible');
  for(const row of cold.rows){assert.equal(row.visibility.visible_area_fraction,1);assert.ok(row.elapsed_ms>=row.media_load_ms);assert.ok(row.elapsed_ms>=row.seek_elapsed_ms);assert.ok(row.seeked_from_load_ms>=row.media_load_ms)}
  assert.match(cold.cache_control,/OS文件缓存未清除/);
  await api.benchmarkSeeks('repeat_access');
  assert.equal(urls.length,30);assert.deepEqual(api.preview.measurements[1].fixed_points_ms,cold.fixed_points_ms);
});
function loopUI(){
  const context=ui(),{video,nodes,api}=context;
  nodes.get('event-start').value=1000;nodes.get('event-end').value=1060;
  nodes.get('loop-enabled').checked=true;api.resetLoopCounter();video.time=.08;video.paused=false;
  return context;
}
test('loop count waits for completed seek and successful play, then exposes observed source position',async()=>{
  const {video,nodes,api}=loopUI();let resume;
  video.play=()=>new Promise(resolve=>{resume=resolve});
  const pending=api.checkLoop();
  assert.equal(nodes.get('loop-status').dataset.loopCount,'0');
  await new Promise(r=>setTimeout(r,10));assert.equal(typeof resume,'function');
  assert.equal(nodes.get('loop-status').dataset.loopCount,'0');
  resume();await pending;
  assert.equal(nodes.get('loop-status').dataset.loopCount,'1');
  assert.equal(Number(nodes.get('loop-status').dataset.lastLoopSourceMs),1000);
  assert.match(nodes.get('loop-status').textContent,/源区间 \[1000, 1060\).*已完成循环 1 次/);
});
test('loop pauses before seeking so advancing playback cannot skip the awaited target frame',async()=>{
  const {scope,video,nodes,api}=loopUI(),pausedDuringSeek=[];
  scope.setTimeout=(fn,delay)=>setTimeout(fn,delay===8000?40:delay);
  const position=Object.getOwnPropertyDescriptor(VideoElement.prototype,'currentTime'),present=video.present;
  Object.defineProperty(video,'currentTime',{get:position.get,set(value){pausedDuringSeek.push(this.paused);position.set.call(this,value)}});
  // A playing decoder may first submit a later frame after the seek. Holding
  // playback makes the requested frame available to the presentation observer.
  video.present=function(time){present.call(this,this.paused?time:time+.04)};
  for(let count=1;count<=2;count++){
    video.time=.08;video.paused=false;await api.checkLoop();
    assert.equal(nodes.get('loop-status').dataset.loopCount,String(count));
    assert.equal(nodes.get('loop-enabled').checked,true);assert.equal(video.paused,false);
    assert.equal(Number(nodes.get('loop-status').dataset.lastLoopSourceMs),1000);
  }
  assert.deepEqual(pausedDuringSeek,[true,true]);
});
test('failed playback resume does not count a planned loop',async()=>{
  const {video,nodes,api}=loopUI();video.play=()=>Promise.reject(Error('autoplay blocked'));
  await api.checkLoop();
  assert.equal(nodes.get('loop-status').dataset.loopCount,'0');
  assert.equal(nodes.get('loop-status').dataset.lastLoopSourceMs,'');
  assert.equal(nodes.get('loop-enabled').checked,false);
});
test('a completed seek from an old asset or interval cannot increment the new loop counter',async()=>{
  for(const changed of ['asset','interval']){
    const {video,nodes,api}=loopUI();let resume;video.play=()=>new Promise(resolve=>{resume=resolve});
    const pending=api.checkLoop();await new Promise(r=>setTimeout(r,10));
    if(changed==='asset')api.preview.epoch++;else nodes.get('event-end').value=1080;
    api.resetLoopCounter();resume();await pending;
    assert.equal(nodes.get('loop-status').dataset.loopCount,'0');assert.equal(nodes.get('loop-status').dataset.lastLoopSourceMs,'');
  }
});
test('initial interval positioning is not a loop, but ended playback can complete one',async()=>{
  const {video,nodes,api}=loopUI();nodes.get('event-start').value=1020;api.resetLoopCounter();video.time=0;
  await api.checkLoop();assert.equal(nodes.get('loop-status').dataset.loopCount,'0');
  video.time=.1;video.paused=true;
  await api.checkLoop(true);assert.equal(nodes.get('loop-status').dataset.loopCount,'1');
  assert.equal(Number(nodes.get('loop-status').dataset.lastLoopSourceMs),1020);
  video.paused=true;nodes.get('loop-enabled').onchange();
  assert.equal(nodes.get('loop-status').dataset.loopCount,'0');
  nodes.get('event-start').value=1030;nodes.get('event-start').dispatchEvent(new Event('input'));
  assert.match(nodes.get('loop-status').textContent,/源区间 \[1030, 1060\)/);
});
async function renderUI(fps=30){
  const context=ui(),{scope,api,nodes}=context,calls=[];
  const originalFetch=scope.fetch;
  const server={timeline:{schema_version:'1.0',timeline_id:'timeline-a',title:'Render test',segments:[{in_ms:0,out_ms:1000,speed:1}],output:{width:1080,height:1920,fps,video_codec:'h264',audio_codec:'aac'}},
    record:{schema_version:'1.0',timeline_id:'timeline-a',revision:0,options:{export_preset:[30,60].includes(fps)?'portrait_1080p'+fps:null,safe_area:{x:.06,y:.10,width:.82,height:.78},platform_profile:null}}};
  scope.fetch=async(path,init={})=>{
    if(!String(path).startsWith('/api/v1/timelines'))return originalFetch(path,init);
    const method=init.method??'GET',body=init.body?JSON.parse(init.body):null;calls.push({path,method,body});
    const response=(value,status=200)=>({ok:status<400,status,json:async()=>JSON.parse(JSON.stringify(value))});
    if(path==='/api/v1/timelines'&&method==='POST'){server.timeline=body.timeline;return response(server.timeline)}
    if(path.endsWith('/render-options')&&method==='GET')return response(server.record);
    if(path.endsWith('/render-options')&&method==='PUT'){
      if(body.expected_revision!==server.record.revision)return response({detail:'revision conflict'},409);
      server.record={...server.record,revision:server.record.revision+1,options:body.options};return response(server.record);
    }
    if(path.endsWith('/render'))return response({job_id:'render-test-job'});
    return response([server.timeline]);
  };
  api.state.timeline=JSON.parse(JSON.stringify(server.timeline));api.drawTimeline();
  await api.loadRenderOptions();
  scope.document.getElementById('reviewer').value='test-agent';scope.document.getElementById('reviewer-type').value='agent';
  return {...context,calls,server};
}
test('legacy 24/25/50 fps is unchanged until an explicit 30/60 preset updates output and JSON',async()=>{
  for(const fps of [24,25,50]){
    const {api,nodes,calls}=await renderUI(fps);
    assert.equal(api.state.timeline.output.fps,fps);assert.equal(nodes.get('export-preset').value,'');
    await assert.rejects(api.saveTimelineWithOptions(),/明确选择/);assert.equal(calls.filter(c=>c.method!=='GET').length,0);
    nodes.get('export-preset').value='portrait_1080p60';nodes.get('export-preset').dispatchEvent(new Event('change'));
    assert.equal(api.state.timeline.output.fps,60);assert.equal(JSON.parse(nodes.get('timeline-json').value).output.fps,60);
    await api.saveTimelineWithOptions();
    assert.equal(calls.at(-1).body.expected_revision,0);assert.equal(api.renderDraft().revision,1);
  }
});
test('render saves timeline then CAS options before enqueue, and reload restores persisted controls',async()=>{
  const {api,nodes,calls,server}=await renderUI();
  nodes.get('export-preset').value='portrait_1080p60';nodes.get('export-platform-profile').value='youtube_shorts';nodes.get('safe-area-x').value=.08;api.renderOptionsChanged();
  await nodes.get('render-timeline').onclick();
  const writes=calls.filter(c=>c.method!=='GET');
  assert.deepEqual(writes.map(c=>[c.method,c.path]),[['POST','/api/v1/timelines'],['PUT','/api/v1/timelines/timeline-a/render-options'],['POST','/api/v1/timelines/timeline-a/render']]);
  assert.equal(writes[0].body.reviewer_type,'agent');assert.equal(writes[0].body.timeline.output.fps,60);
  assert.equal(server.record.options.platform_profile,'youtube_shorts');assert.equal(server.record.options.safe_area.x,.08);
  nodes.get('safe-area-x').value=.01;api.renderOptionsChanged();await api.loadRenderOptions(api.state.timeline,{force:true});
  assert.equal(nodes.get('safe-area-x').value,.08);assert.equal(nodes.get('render-options-status').dataset.revision,1);
});
test('options conflict retains local values and prior revision, never enqueues or implicitly reloads',async()=>{
  const {api,nodes,calls,server}=await renderUI();
  nodes.get('export-preset').value='portrait_1080p60';nodes.get('safe-area-x').value=.1;api.renderOptionsChanged();server.record.revision=1;
  await nodes.get('render-timeline').onclick();
  assert.equal(calls.filter(c=>c.path.endsWith('/render')).length,0);
  assert.equal(api.renderDraft().revision,0);assert.equal(api.renderDraft().conflict,true);assert.equal(api.renderDraft().dirty,true);
  assert.equal(nodes.get('export-preset').value,'portrait_1080p60');assert.equal(nodes.get('safe-area-x').value,.1);
  const count=calls.length;await api.loadRenderOptions();assert.equal(calls.length,count);
  assert.match(nodes.get('render-options-status').textContent,/保留了本地修改/);
  await assert.rejects(api.saveTimelineWithOptions(),/修订冲突/);assert.equal(calls.length,count);
  await nodes.get('reload-render-options').onclick();
  assert.equal(api.renderDraft().revision,1);assert.equal(nodes.get('export-preset').value,'portrait_1080p30');
  assert.equal(JSON.parse(nodes.get('timeline-json').value).output.fps,30);
});
test('invalid safe areas fail before writes and only Shorts enforces 180000 ms after speed conversion',async()=>{
  const {api,nodes,calls}=await renderUI();
  for(const area of [{x:-.1,y:.1,width:.8,height:.8},{x:.2,y:.1,width:.9,height:.8},{x:.1,y:.1,width:0,height:.8},{x:.1,y:.3,width:.8,height:.8},{x:NaN,y:0,width:1,height:1}]){
    assert.throws(()=>api.validateRenderOptions({export_preset:'portrait_1080p30',safe_area:area,platform_profile:null},api.state.timeline),/安全区/);
  }
  nodes.get('safe-area-width').value=0;await assert.rejects(api.saveTimelineWithOptions(),/安全区/);
  assert.equal(calls.filter(c=>c.method!=='GET').length,0);
  const options={export_preset:'portrait_1080p30',safe_area:{x:0,y:0,width:1,height:1},platform_profile:'youtube_shorts'};
  const timeline={segments:[{in_ms:0,out_ms:360000,speed:2}]};
  assert.equal(api.validateRenderOptions(options,timeline),options);
  timeline.segments[0].out_ms=360001;assert.throws(()=>api.validateRenderOptions(options,timeline),/180000/);
  options.platform_profile=null;assert.equal(api.validateRenderOptions(options,timeline),options);
});
test('applying JSON for an unsaved timeline uses revision zero only after the server confirms 404',async()=>{
  const {scope,api,nodes}=await renderUI();
  const original=scope.fetch;
  scope.fetch=async(path,init)=>path==='/api/v1/timelines/timeline-new/render-options'?{ok:false,status:404,json:async()=>({detail:'不存在的资源'})}:original(path,init);
  nodes.get('timeline-json').value=JSON.stringify({...api.state.timeline,timeline_id:'timeline-new'});
  await nodes.get('apply-timeline-json').onclick();
  assert.equal(api.renderDraft().loaded,true);assert.equal(api.renderDraft().revision,0);
  assert.equal(nodes.get('export-preset').value,'portrait_1080p30');
  assert.equal(api.state.timeline.timeline_id,'timeline-new');
});
test('cancel and retry keep the full job in details and only a short status in the notice',async()=>{
  const {scope,api,nodes}=ui();await new Promise(resolve=>setTimeout(resolve,0));
  const fullJob={job_id:'job-large-payload',status:'cancelled',payload:{assets:[{provenance:{large:'x'.repeat(10000)}}]}};
  const buttons={};for(const operation of ['cancel','retry']){buttons[operation]=new NodeElement();buttons[operation].dataset[operation]=fullJob.job_id}
  scope.document.getElementById('jobs-list').querySelectorAll=selector=>Object.entries(buttons).filter(([operation])=>selector==='[data-'+operation+']').map(([,button])=>button);
  scope.fetch=async path=>({ok:true,json:async()=>path==='/api/v1/jobs'?[fullJob]:path==='/api/v1/models'?[]:{...fullJob,status:path.endsWith('/retry')?'queued':'cancelled'}});
  await api.loadJobs();
  for(const [operation,button] of Object.entries(buttons)){
    await button.onclick();
    assert.ok(nodes.get('notice').textContent.length<150);assert.match(nodes.get('notice').textContent,/job-large-payload/);
    assert.match(nodes.get('notice').textContent,operation==='retry'?/queued/:/cancelled/);
    const detail=JSON.parse(nodes.get('job-detail').textContent);
    assert.equal(detail.action,operation);assert.equal(detail.result.payload.assets[0].provenance.large.length,10000);
  }
});
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
async function exactUI(){
  const context=ui(),{api,scope}=context;await tick();
  api.preview.jobId='preview-1';api.preview.data.index_relative_path='platform/previews/preview-1/attempt-01/index.sqlite3';
  api.state.asset={...api.state.asset,width:1920,height:1080};
  const img=scope.document.getElementById('source-frame-image');img.naturalWidth=1920;img.naturalHeight=1080;img.decode=async()=>{};
  scope.document.getElementById('source-zoom').value='fit';
  const frame=index=>({source_frame_index:index,source_pts:90000+(index-60)*1500,source_pts_ms:1000+(index-60)*100/6,source_end_ms:1000+(index-59)*100/6});
  for(let index=60;index<90;index++)api.preview.sourceFrames.set(index,frame(index));
  const succeeded=(index,jobId='exact-'+index)=>({job_id:jobId,status:'succeeded',result:{frame:{...frame(index),source_asset_id:api.state.asset.asset_id,source_sha256:api.state.asset.sha256,width:1920,height:1080},artifacts:[{artifact_id:'image',kind:'source_frame',relative_path:'platform/'+jobId+'/source.jpg'}]}});
  const response=body=>({ok:true,json:async()=>body});
  scope.setTimeout=(fn,delay)=>setTimeout(fn,delay===500?5:delay);
  return {...context,img,frame,succeeded,response};
}
test('rapid ordinary source steps never enqueue exact-frame jobs, including outside the proxy window',async()=>{
  const {api,scope,frame}=await exactUI();let exactJobs=0;
  scope.fetch=async path=>{if(path.endsWith('/source-frame'))exactJobs++;throw Error('ordinary steps must use cached source index and proxy only')};
  api.preview.selected=frame(60);
  await Promise.all([api.stepSource(1),api.stepSource(1),api.stepSource(1)]);
  for(let i=0;i<8;i++)await api.stepSource(1);
  assert.equal(exactJobs,0);assert.equal(api.inspections.pending.size,0);assert.equal(api.preview.selected.source_frame_index,69);
});
test('validated same-frame image is cached, with source hash and preview attempt isolating reuse',async()=>{
  const {api,scope,nodes,frame,succeeded,response}=await exactUI();let posts=0;
  scope.fetch=async(path,init)=>{assert.ok(path.endsWith('/source-frame'));posts++;return response(succeeded(JSON.parse(init.body).source_frame_index,'exact-'+posts))};
  await api.inspectSourceFrame(frame(61));await api.inspectSourceFrame(frame(61));
  assert.equal(posts,1);assert.match(nodes.get('source-frame-status').textContent,/复用本会话已校验结果/);
  api.preview.data.index_relative_path='platform/previews/preview-1/attempt-02/index.sqlite3';
  await api.inspectSourceFrame(frame(61));assert.equal(posts,2);
  api.state.asset.sha256='hash-replacement';api.preview.data.source_sha256='hash-replacement';
  await api.inspectSourceFrame(frame(61));assert.equal(posts,3);
  api.state.asset.asset_id='different-asset';api.preview.data.source_asset_id='different-asset';
  await api.inspectSourceFrame(frame(61));assert.equal(posts,4);
});
test('successful exact-frame cache is bounded to 16 entries and absent attempt identity disables reuse',async()=>{
  const {api,scope,frame,succeeded,response}=await exactUI();let posts=0;
  scope.fetch=async(path,init)=>{posts++;return response(succeeded(JSON.parse(init.body).source_frame_index,'exact-'+posts))};
  for(let index=60;index<77;index++)await api.inspectSourceFrame(frame(index));
  assert.equal(api.inspections.cache.size,16);await api.inspectSourceFrame(frame(60));assert.equal(posts,18);
  delete api.preview.data.index_relative_path;
  await api.inspectSourceFrame(frame(60));await api.inspectSourceFrame(frame(60));assert.equal(posts,20);
});
test('unverified or undecodable exact results never enter the successful cache',async()=>{
  for(const invalid of ['hash','pts','ms','dimensions','decode']){
    const {api,scope,img,frame,succeeded,response}=await exactUI();const job=succeeded(61);
    if(invalid==='hash')job.result.frame.source_sha256='wrong';
    if(invalid==='pts')job.result.frame.source_pts++;
    if(invalid==='ms')delete job.result.frame.source_pts_ms;
    if(invalid==='dimensions')img.naturalWidth=640;
    if(invalid==='decode')img.decode=async()=>{throw Error('decode failed')};
    scope.fetch=async()=>response(job);
    await assert.rejects(api.inspectSourceFrame(frame(61)),/不一致|加载失败/);
    assert.equal(api.inspections.cache.size,0);assert.equal(img.hidden,true);
  }
});
test('switching asset cancels queued or running exact jobs and ignores their stale polls',async()=>{
  for(const status of ['queued','running']){
    const {api,scope,img,frame,response}=await exactUI(),cancels=[];
    const assetB={asset_id:'asset-b',sha256:'hash-b',duration_ms:4000,title:'B',width:1920,height:1080};api.state.assets=[assetB];
    scope.fetch=async(path,init={})=>{
      if(path.endsWith('/source-frame'))return response({job_id:'pending-'+status,status});
      if(path.endsWith('/cancel')){cancels.push(path);return response({job_id:'pending-'+status,status:status==='queued'?'cancelled':'running',cancel_requested:true})}
      if(path.endsWith('/preview'))return response({status:'not_ready'});
      if(path.startsWith('/api/v1/jobs/'))return response({job_id:'pending-'+status,status});
      return response([]);
    };
    const old=api.inspectSourceFrame(frame(61));await tick();
    await api.selectAsset('asset-b');await api.inspections.queue;await old;
    assert.deepEqual(cancels,['/api/v1/jobs/pending-'+status+'/cancel']);assert.equal(api.inspections.pending.size,0);
    assert.equal(api.state.asset.asset_id,'asset-b');assert.equal(api.inspections.active,null);assert.equal(img.hidden,true);
  }
});
test('a late enqueue response is cancelled after asset switch even before its job id was known',async()=>{
  const {api,scope,img,frame,response}=await exactUI();let release;const cancels=[];
  api.state.assets=[{asset_id:'asset-b',sha256:'b',title:'B',width:1920,height:1080,duration_ms:4000}];
  scope.fetch=async path=>{
    if(path.endsWith('/source-frame'))return new Promise(resolve=>{release=()=>resolve(response({job_id:'late-job',status:'queued'}))});
    if(path.endsWith('/cancel')){cancels.push(path);return response({job_id:'late-job',status:'cancelled',cancel_requested:true})}
    return response(path.endsWith('/preview')?{status:'not_ready'}:[]);
  };
  const old=api.inspectSourceFrame(frame(61));await tick();assert.equal(typeof release,'function');
  await api.selectAsset('asset-b');assert.equal(cancels.length,0);
  release();await old;await api.inspections.queue;
  assert.deepEqual(cancels,['/api/v1/jobs/late-job/cancel']);assert.equal(api.inspections.pending.size,0);assert.equal(img.hidden,true);
});
test('new inspections wait for late enqueue and cancellation acknowledgment; only latest intent starts',async()=>{
  const {api,scope,frame,succeeded,response}=await exactUI();let releasePost,releaseCancel;const created=[],active=new Set();let peak=0;
  scope.fetch=async(path,init)=>{
    if(path.endsWith('/source-frame')){
      const index=JSON.parse(init.body).source_frame_index;created.push(index);active.add(index);peak=Math.max(peak,active.size);
      if(created.length===1)return new Promise(resolve=>{releasePost=()=>resolve(response({job_id:'old-job',status:'queued'}))});
      active.delete(index);return response(succeeded(index));
    }
    if(path.endsWith('/cancel'))return new Promise(resolve=>{releaseCancel=()=>{active.delete(61);resolve(response({job_id:'old-job',status:'cancelled',cancel_requested:true}))}});
    throw Error('unexpected poll');
  };
  const first=api.inspectSourceFrame(frame(61));await tick();
  const second=api.inspectSourceFrame(frame(62)),latest=api.inspectSourceFrame(frame(63));await tick();
  assert.deepEqual(created,[61]);releasePost();await tick();assert.equal(typeof releaseCancel,'function');assert.deepEqual(created,[61]);
  releaseCancel();await Promise.all([first,second,latest]);await api.inspections.queue;
  assert.deepEqual(created,[61,63]);assert.equal(peak,1);assert.equal(api.inspections.pending.size,0);
});
test('failed cancellation blocks new exact enqueue instead of accumulating effective tasks',async()=>{
  const {api,scope,frame,response}=await exactUI();let posts=0,fail=true;
  scope.fetch=async path=>{
    if(path.endsWith('/source-frame')){posts++;return response({job_id:'old-job',status:'running'})}
    if(path.endsWith('/cancel'))return fail?{ok:false,status:503,json:async()=>({detail:'cancel unavailable'})}:response({job_id:'old-job',status:'running',cancel_requested:true});
    return response({job_id:'old-job',status:'running'});
  };
  const first=api.inspectSourceFrame(frame(61));await tick();
  await assert.rejects(api.inspectSourceFrame(frame(62)),/cancel unavailable/);await first;
  assert.equal(posts,1);assert.equal(api.inspections.pending.size,1);
  fail=false;api.clearSourceImage();await api.inspections.queue;assert.equal(api.inspections.pending.size,0);
});
test('a stale poll failure cannot evict a newer verified cache entry for the same frame',async()=>{
  const {api,scope,frame,succeeded,response}=await exactUI();let posts=0,releasePoll,pollStarted;
  const polling=new Promise(resolve=>{pollStarted=resolve});
  scope.fetch=async(path,init)=>{
    if(path.endsWith('/source-frame')){posts++;return response(posts===1?{job_id:'old-job',status:'running'}:succeeded(61,'new-job'))}
    if(path.endsWith('/cancel'))return response({job_id:'old-job',status:'running',cancel_requested:true});
    return new Promise((resolve,reject)=>{releasePoll=()=>reject(Error('late old poll failure'));pollStarted()});
  };
  const old=api.inspectSourceFrame(frame(61));await polling;
  await api.inspectSourceFrame(frame(61));assert.equal(api.inspections.cache.size,1);
  releasePoll();await old;assert.equal(api.inspections.cache.size,1);
  await api.inspectSourceFrame(frame(61));assert.equal(posts,2);
});

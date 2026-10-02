const test = require('node:test');
const assert = require('node:assert/strict');
const ui = require('../../apps/platform/static/training_interactions.js');
const source = require('../../configs/models/taxonomy.v1.json');
const taxonomy = {labels: source.labels.map(l => ({label_id:l.id,name:l.name_zh,dimension:l.domain,selectable:l.node_type==='label',kinds:l.applicability.record_kinds.map(k=>({interval:'segment',contact:'contact',state:'state'}[k]))}))};
const bundle = () => ({project_id:'p',asset:{asset_id:'a',duration_ms:10000},people:[{person_id:'near',team_id:'n'},{person_id:'far',team_id:'f'}],records:[]});
const self = {subject_role:'self',subject_person_id:'near'};
const foot = taxonomy.labels.find(l=>l.dimension==='footwork'&&l.selectable&&l.kinds.includes('segment'));
const stroke = taxonomy.labels.find(l=>l.dimension==='stroke'&&l.selectable&&l.kinds.includes('segment'));
function marked() {
  const b=bundle(); b.records=[{record_id:'r',kind:'rally',start_ms:1000,end_ms:6000,dead_ball_id:'d'},
    {record_id:'d',kind:'dead_ball',at_ms:6000,rally_id:'r'},
    {record_id:'s',kind:'segment',start_ms:2000,end_ms:4000,rally_id:'r',judgements:[]}]; return b;
}
test('all 156 leaves across eight domains can be placed without turning 37 groups into labels',()=>{
  assert.equal(taxonomy.labels.filter(l=>l.selectable).length,156);
  assert.equal(new Set(taxonomy.labels.filter(l=>l.selectable).map(l=>l.dimension)).size,8);
  assert.equal(taxonomy.labels.filter(l=>!l.selectable).length,37);
  for(const label of taxonomy.labels) {
    if(!label.selectable) { assert.throws(()=>ui.addLabel(bundle(),taxonomy,label.label_id,{at_ms:2000},self,'agent',()=>label.label_id),/目录/); continue; }
    const result=ui.addLabel(bundle(),taxonomy,label.label_id,{at_ms:2000},self,'agent',()=>label.label_id);
    const r=result.bundle.records[0]; assert.ok(label.kinds.includes(r.kind)); assert.equal(r.review.status,'pending'); assert.equal(r.judgements[0].value,'unknown'); assert.equal(r.person_id,'near');
  }
});
test('multiple domains coexist and duplicate drops preserve the original judgement without dirty rewrite',()=>{
  let result=ui.addLabel(bundle(),taxonomy,stroke.label_id,{at_ms:2000},self,'agent',()=> 's');
  result=ui.addLabel(result.bundle,taxonomy,foot.label_id,{record_id:'s'},self,'agent',()=> 'x');
  assert.equal(result.bundle.records[0].judgements.length,2);
  result.bundle.records[0].judgements[0].value='absent';result.bundle.records[0].judgements[0].reason='explicit reviewed observation';
  const before=JSON.stringify(result.bundle);
  const duplicate=ui.addLabel(result.bundle,taxonomy,stroke.label_id,{record_id:'s'},self,'agent',()=> 'x');
  assert.equal(duplicate.added,false); assert.equal(JSON.stringify(duplicate.bundle),before);
});
test('roles and manually registered people stay separate; mismatched or unknown people do not mutate input',()=>{
  const first=ui.addLabel(bundle(),taxonomy,stroke.label_id,{at_ms:2000},self,'agent',()=> 's');
  const other=ui.addLabel(first.bundle,taxonomy,stroke.label_id,{record_id:'s'},{subject_role:'opponent',subject_person_id:'far'},'agent',()=> 'x');
  assert.equal(other.bundle.records[0].judgements.length,2);assert.equal(other.bundle.records[0].state.opponent.team_id,'f');
  const before=JSON.stringify(other.bundle);
  assert.throws(()=>ui.addLabel(other.bundle,taxonomy,foot.label_id,{record_id:'s'},{subject_role:'opponent',subject_person_id:'near'},'agent',()=> 'x'),/人物/);
  assert.throws(()=>ui.addLabel(other.bundle,taxonomy,foot.label_id,{at_ms:2000},{subject_role:'self',subject_person_id:'unregistered'},'agent',()=> 'x'),/手动/);
  assert.equal(JSON.stringify(other.bundle),before);
});
test('range drag atomically follows dead ball but cannot cut children, escape source or erase evidence anchors',()=>{
  const b=marked(), before=JSON.stringify(b);
  const moved=ui.retimeRecords(b,'r',{start_ms:1500,end_ms:6500},'agent'); assert.equal(moved.find(r=>r.record_id==='d').at_ms,6500);
  assert.equal(moved.find(r=>r.record_id==='s').start_ms,2000);
  for(const patch of [{start_ms:3000},{end_ms:3000},{start_ms:-1},{end_ms:Infinity},{end_ms:10001},{end_ms:1000}]) assert.throws(()=>ui.retimeRecords(b,'r',patch,'agent'));
  assert.equal(JSON.stringify(b),before);
  b.records[2].evidence=[{type:'image_region',at_ms:2500}];
  assert.throws(()=>ui.retimeRecords(b,'s',{start_ms:3000,end_ms:5000},'agent'),/区域/);
  assert.equal(ui.retimeRecords(b,'s',{start_ms:2200,end_ms:4500},'agent')[2].evidence[0].at_ms,2500);
});
test('implicit self and all four roles enforce known person and side exclusivity atomically',()=>{
  const first=ui.addLabel(bundle(),taxonomy,stroke.label_id,{at_ms:2000},self,'agent',()=> 's').bundle;
  const before=JSON.stringify(first);
  assert.throws(()=>ui.addLabel(first,taxonomy,stroke.label_id,{record_id:'s'},{subject_role:'opponent',subject_person_id:'near'},'agent',()=> 'x'),/多个角色/);
  assert.throws(()=>ui.addLabel(first,taxonomy,stroke.label_id,{record_id:'s'},{subject_role:'partner',subject_person_id:'far'},'agent',()=> 'x'),/队伍关系/);
  assert.equal(JSON.stringify(first),before);
});
test('point uncertainty and single-frame regions are never silently moved with a contact',()=>{
  const b=bundle();b.records=[{record_id:'c',kind:'contact',at_ms:2000,uncertainty_start_ms:1900,uncertainty_end_ms:2100}];
  assert.throws(()=>ui.retimeRecords(b,'c',{at_ms:2200},'agent'),/不确定/);
  b.records[0].evidence=[{type:'image_region',at_ms:2000}];assert.throws(()=>ui.retimeRecords(b,'c',{at_ms:2050},'agent'),/区域/);
  assert.throws(()=>ui.retimeRecords(b,'c',{start_ms:2000},'agent'),/时间修改/);
});
test('new intervals remain inside the source and current rally; invalid drop has no side effects',()=>{
  const b=marked(), before=JSON.stringify(b);
  const r=ui.addLabel(b,taxonomy,foot.label_id,{at_ms:5500},self,'agent',()=> 'f').bundle.records.at(-1);
  assert.equal(r.end_ms,6000); assert.equal(r.rally_id,'r');
  for(const at_ms of [NaN,Infinity,true,-1,10000,2000.5]) assert.throws(()=>ui.addLabel(b,taxonomy,foot.label_id,{at_ms},self,'agent',()=> 'f'));
  assert.equal(JSON.stringify(b),before);
});

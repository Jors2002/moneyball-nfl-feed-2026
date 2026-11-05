/* Run with node tests/test_moneyball8_apps_script.js. No Google account needed. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const zlib = require('node:zlib');
const code = fs.readFileSync(path.join(__dirname,'../apps_script/moneyball8_extension.js'),'utf8');
let tests=0;
function check(name, fn) { fn(); tests++; process.stdout.write('PASS '+name+'\n'); }
const context = vm.createContext({Date, Number, Object, Array, JSON, Error, Logger:{log() {}}});
vm.runInContext(code, context);
const run = source => vm.runInContext(source, context);
function fixture() { return {schemaVersion:80,season:2026,asOfWeek:8,targetWeek:9,
  generatedAt:new Date().toISOString(),bySleeper:{'123':{
    position:'RB',projection:12,interval80:{lower:2,upper:22},model:'season_mean',priorGames:6,lastObservedWeek:8}}}; }
function valid(feed=fixture(),week=9) { context.input=feed;context.week=week;return run('mb8Validate_(input,week)'); }
check('embedded installation tests',()=>run('probarMoneyball8()'));
check('valid feed',()=>assert.equal(valid().status,'VERIFICADO_TECNICAMENTE'));
check('reject schema',()=>assert.throws(()=>valid({...fixture(),schemaVersion:72})));
check('reject season',()=>assert.throws(()=>valid({...fixture(),season:2025})));
check('reject future observed week',()=>assert.throws(()=>valid({...fixture(),asOfWeek:9})));
check('reject target mismatch',()=>assert.throws(()=>valid({...fixture(),targetWeek:10})));
check('reject stale timestamp',()=>assert.throws(()=>valid({...fixture(),generatedAt:'2026-01-01T00:00:00Z'})));
check('reject timezone unknown',()=>assert.throws(()=>valid({...fixture(),generatedAt:'2026-11-04T12:00:00'})));
check('reject future timestamp',()=>assert.throws(()=>valid({...fixture(),generatedAt:'2099-01-01T00:00:00Z'})));
check('reject stale source under fresh envelope',()=>assert.throws(()=>valid({...fixture(),sourceGeneratedAt:'2026-01-01T00:00:00Z'})));
check('reject absent mean',()=>{const f=fixture();delete f.bySleeper['123'].projection;assert.throws(()=>valid(f));});
check('reject NaN',()=>{const f=fixture();f.bySleeper['123'].projection=NaN;assert.throws(()=>valid(f));});
check('reject Infinity',()=>{const f=fixture();f.bySleeper['123'].interval80.upper=Infinity;assert.throws(()=>valid(f));});
check('reject reversed interval',()=>{const f=fixture();f.bySleeper['123'].interval80.lower=23;assert.throws(()=>valid(f));});
check('reject model missing',()=>{const f=fixture();delete f.bySleeper['123'].model;assert.throws(()=>valid(f));});
check('reject non offense position',()=>{const f=fixture();f.bySleeper['123'].position='K';assert.throws(()=>valid(f));});
check('null is retained, not zero',()=>{const f=fixture();Object.assign(f.bySleeper['123'],{projection:null,interval80:{lower:null,upper:null}});assert.equal(valid(f).data.bySleeper['123'].projection,null);});
check('reject empty payload',()=>assert.throws(()=>valid({...fixture(),bySleeper:{}})));
check('reject player history after cutoff',()=>{const f=fixture();f.bySleeper['123'].lastObservedWeek=9;assert.throws(()=>valid(f));});
check('reject noninteger sample size',()=>{const f=fixture();f.bySleeper['123'].priorGames=1.5;assert.throws(()=>valid(f));});
check('quality uses readable numerical rows and preserves zero',()=>{
  context.validation={positions:{RB:{selected_model:'season_mean',
    test:{season_mean:{n:20,mae:5,rmse:7,bias:0}},test_interval80_coverage:0.8}}};
  const rows=run('mb8QualityRows_(validation)');
  assert.equal(rows.find(row=>row[0]==='RB validación 2025 BIAS')[1],0);
  assert.equal(rows.find(row=>row[0]==='RB validación 2025 MAE')[1],5);
});
check('final 2026 quality uses frozen policy metrics',()=>{
  context.validation={positions:{QB:{selected_model:'opportunity_ridge',
    final_test:{season:2026,selected_model:{n:40,mae:6,rmse:8,bias:0},
      interval80_coverage:0,policy_frozen_before_this_partition:true}}}};
  const rows=run('mb8QualityRows_(validation)');
  assert.equal(rows.find(row=>row[0]==='QB final 2026 MAE')[1],6);
  assert.equal(rows.find(row=>row[0]==='QB cobertura intervalo80 final 2026')[1],0);
});
check('separates evaluated model from data-selected deployment policy',()=>{
  context.validation={positions:{RB:{selected_model:'position_ridge',
    deployment_model:'recent4',deployment_status:'PROSPECTIVE_VALIDATION_PENDING',
    deployment_selection_partition:'2026 W4–8'}}};
  const rows=run('mb8QualityRows_(validation)');
  assert.equal(rows.find(row=>row[0]==='RB modelo evaluado final congelado')[1],'position_ridge');
  assert.equal(rows.find(row=>row[0]==='RB modelo desplegado')[1],'recent4');
  assert.equal(rows.find(row=>row[0]==='RB estado validación política desplegada')[1],'PROSPECTIVE_VALIDATION_PENDING');
  assert.ok(rows.find(row=>row[0]==='RB advertencia selección despliegue')[1].includes('NO son prueba fuera de muestra'));
});
check('real gzip consumer with HTTP fallback',()=>{
  const feed=fixture();
  for(let i=1000;i<1100;i++) feed.bySleeper[String(i)]=Object.assign({},feed.bySleeper['123']);
  const bytes=zlib.gzipSync(Buffer.from(JSON.stringify(feed)));
  const blob={getBytes:()=>bytes};
  const calls=[];
  context.UrlFetchApp={fetch:(url,options)=>{
    calls.push(url);
    if(calls.length===1) return {getResponseCode:()=>503};
    return {getResponseCode:()=>200,getContentText:()=>JSON.stringify({encoding:'base64',content:bytes.toString('base64')})};
  }};
  context.Utilities={newBlob:bytes=>({getBytes:()=>bytes}),base64Decode:text=>Buffer.from(text,'base64'),
    ungzip:blob=>({getDataAsString:()=>zlib.gunzipSync(blob.getBytes()).toString('utf8')})};
  assert.equal(run('mb8Fetch_(9)').status,'VERIFICADO_TECNICAMENTE');
  assert.equal(calls.length,2);assert.ok(calls[1].includes('api.github.com'));
});
check('fetch rejects insufficient coverage across all sources',()=>{
  const bytes=zlib.gzipSync(Buffer.from(JSON.stringify(fixture())));
  context.UrlFetchApp={fetch:url=>({getResponseCode:()=>200,getBlob:()=>({getBytes:()=>bytes}),
    getContentText:()=>JSON.stringify({encoding:'base64',content:bytes.toString('base64')})})};
  assert.throws(()=>run('mb8Fetch_(9)'));
});

class Sheet {
  constructor(values) { this.values=values; }
  getDataRange() { return {getValues:()=>this.values.map(r=>r.slice())}; }
  getRange(r,c,nr,nc) { return {getValue:()=>this.values[r-1]?.[c-1],setValues:v=>{this.values=v.map(row=>row.slice());}}; }
  getLastRow() { return this.values.length; }
  clearContents() { this.values=[]; }
}
function harness(fail) {
  const sheets = {LINEUP:new Sheet([['DO NOT CHANGE'],[1]]),MB8_PROYECCIONES:new Sheet([['old'],[7]])};
  const ss = {getSheetByName:n=>sheets[n],getId:()=>'test-dashboard',deleteSheet:s=>{
    for(const n of Object.keys(sheets)) if(sheets[n]===s) delete sheets[n];},
    insertSheet:n=>{sheets[n]=new Sheet([]);return sheets[n];}};
  const manifests=[];
  context.ss=ss;context.folder={};context.checked=valid();
  context.SpreadsheetApp={flush(){}};
  context.mb42SaveFile_=(folder,name,data)=>manifests.push(JSON.parse(JSON.stringify(data)));
  context.mb5WriteSheet_=(ss,name,header,rows)=>{
    if(fail && name==='MB8_CALIDAD') throw Error('simulated write failure');
    sheets[name]=new Sheet([header,...rows]);
  };
  return {sheets,ss,manifests};
}
check('publishes only new tabs and reads back',()=>{
  const h=harness(false);const result=run('mb8Publish_(ss,checked,folder)');
  assert.equal(result.stage,'COMPLETED');assert.equal(h.sheets.LINEUP.values[0][0],'DO NOT CHANGE');
  assert.equal(h.sheets.MB8_PROYECCIONES.values[1][4],12);
  assert.equal(h.manifests[0].stage,'PENDING');assert.equal(h.manifests[1].stage,'COMPLETED');
});
check('partial write rolls back values and preserves old modules',()=>{
  const h=harness(true);assert.throws(()=>run('mb8Publish_(ss,checked,folder)'));
  assert.equal(h.sheets.MB8_PROYECCIONES.values[0][0],'old');
  assert.equal(h.sheets.LINEUP.values[0][0],'DO NOT CHANGE');
  assert.equal(h.manifests.at(-1).stage,'ROLLED_BACK');
});
check('recovers durable pending checkpoint after hard interruption',()=>{
  const h=harness(false);
  context.mb42ReadFile_=()=>({stage:'PENDING',dashboardId:'test-dashboard',previous:[
    {name:'MB8_PROYECCIONES',existed:true,values:[['before interruption']]},
    {name:'MB8_CALIDAD',existed:false,values:null}]});
  run('mb8Recover_(folder,ss)');
  assert.equal(h.sheets.MB8_PROYECCIONES.values[0][0],'before interruption');
  assert.equal(h.manifests.at(-1).stage,'RECOVERED_PREVIOUS');
});
check('rejects foreign checkpoint',()=>{
  harness(false);context.mb42ReadFile_=()=>({stage:'PENDING',dashboardId:'other',previous:[]});
  assert.throws(()=>run('mb8Recover_(folder,ss)'));
});
check('no new trigger and no Sleeper mutation',()=>{
  assert.equal(/ScriptApp\.|\.newTrigger\(/.test(code),false);
  assert.equal(/method\s*:\s*['"](?:post|put|delete|patch)/i.test(code),false);
});
function roleFixture(feed) {
  feed.predictionVintage='vintage-test';
  return {schemaVersion:81,season:2026,asOfWeek:8,targetWeek:9,forecastVintage:'vintage-test',
    generatedAt:new Date().toISOString(),bySleeper:{'123':{name:'Test',position:'RB',team:'SEA',
      originalProjection:12,adjustedProjection:null,decisionProjection:null,
      roleEvaluation:{status:'ABRUPT_PARTICIPATION_LOSS',quality:'OBSERVED_SNAPS',decisionAllowed:false,
        participationProbability:null,cause:'UNKNOWN',signals:['Explicit observed zero'],causeEvidence:[]}}}};
}
check('role sidecar preserves original point and vetoes unsafe use',()=>{
  context.f=fixture();context.r=roleFixture(context.f);
  assert.equal(run('mb8ValidateRole_(r,f)').bySleeper['123'].originalProjection,12);
  const rows=run('mb8RoleRows_(f,r)');assert.equal(rows[0][8],12);assert.match(rows[0][9],/no validado/);
});
check('role wrong vintage rejects matching player names',()=>{
  context.f=fixture();context.r=roleFixture(context.f);context.r.forecastVintage='different';
  assert.throws(()=>run('mb8ValidateRole_(r,f)'));
});
check('unvalidated point haircut and participation probabilities rejected',()=>{
  context.f=fixture();context.r=roleFixture(context.f);context.r.bySleeper['123'].adjustedProjection=0;
  assert.throws(()=>run('mb8ValidateRole_(r,f)'));
  context.r=roleFixture(context.f);context.r.bySleeper['123'].roleEvaluation.participationProbability=.5;
  assert.throws(()=>run('mb8ValidateRole_(r,f)'));
});
check('review-required positive decision points cannot leak',()=>{
  context.f=fixture();context.r=roleFixture(context.f);context.r.bySleeper['123'].decisionProjection=12;
  assert.throws(()=>run('mb8ValidateRole_(r,f)'));
});
check('missing role marks references unavailable instead of clear',()=>{
  const h=harness(false);run('mb8Publish_(ss,checked,folder)');
  assert.equal(h.sheets.MB8_PROYECCIONES.values[1][9],'ROL_NO_VERIFICADO');
  assert.equal(h.sheets.MB8_ALERTAS_ROL.values[1][6],'ROL_NO_VERIFICADO');
  assert.equal(h.manifests.at(-1).roleVerified,false);
});
check('role tab failure restores prior two tabs',()=>{
  const h=harness(false),write=context.mb5WriteSheet_;
  context.mb5WriteSheet_=(ss,name,head,rows)=>{if(name==='MB8_ALERTAS_ROL')throw Error('role write failure');write(ss,name,head,rows);};
  assert.throws(()=>run('mb8Publish_(ss,checked,folder)'));
  assert.equal(h.sheets.MB8_PROYECCIONES.values[0][0],'old');
  assert.equal(h.sheets.MB8_CALIDAD,undefined);
  assert.equal(h.sheets.LINEUP.values[0][0],'DO NOT CHANGE');
});
check('complete role publication is recorded separately from predictive validity',()=>{
  const h=harness(false);context.checked.data.predictionVintage='vintage-test';
  context.checked.roles=roleFixture(context.checked.data);
  const m=run('mb8Publish_(ss,checked,folder)');
  assert.equal(m.roleVerified,true);assert.equal(m.stage,'COMPLETED');
  assert.match(h.sheets.MB8_PROYECCIONES.values[1][9],/REVISAR_ROL/);
});
console.log('MONEYBALL8_APPS_TESTS_OK '+tests);

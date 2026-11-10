// Node regression tests for the Apps Script private adapter; entirely synthetic.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync('apps_script/moneyball82_integrity.gs', 'utf8');
let mockId = 'private-doc-id';
const fake = {
  schema_version: 1, league_id: 'fixture-league', facts: [{id: 'FACT1'}],
  decisions: [
    {id:'PIT_HEDGE', asset:'DST_PLAYOFF', protected:true, status:'ACTIVA',
      why:'Playoff rotation', decided_at:'2026-11-09', source:'Fixture', linked_fact_ids:['FACT1']},
    {id:'BYE', asset:'QB', kind:'LINEUP_GAP', status:'PENDIENTE',
      why:'Roster coverage', decided_at:'2026-11-09', source:'Fixture'}
  ]
};
let raw = 'private header\nBEGIN_MONEYBALL_DECISIONS_JSON\n' +
  JSON.stringify(fake) + '\nEND_MONEYBALL_DECISIONS_JSON';
const c = {
  Logger: {log() {}},
  PropertiesService: {getScriptProperties() {return {getProperty(k) {
    assert.equal(k,'MB82_DECISIONS_DOC_ID');return mockId;}};}},
  DocumentApp: {openById(id) {assert.equal(id,mockId);
    return {getBody() {return {getText() {return raw;}};}};}}
};
vm.createContext(c);
vm.runInContext(src, c, {filename:'moneyball82_integrity.gs'});
const date='2026-11-10T06:00:00Z';
const complete = () => ({
  league_id:'fixture-league',kind:'WAIVER',drops:[],gives:[],
  receives:['FREE_RB'],scoring_source:'SLEEPER_BRR',snapshot_at:'2026-11-10T05:00:00Z',
  checks:Object.fromEntries(['roster','scoring','health','role','replacement','lineup',
    'all_drops','do_nothing','playoffs','deadline','bye_gaps_reviewed']
    .map(k => [k,true])),
  horizons:Object.fromEntries(['week','next_3_5','playoffs_15_17'].map(k=>[k,{reviewed:true}])),
  user_authorized:true
});
assert.equal(c.verificarContinuidadMoneyball().decision_count,2);
assert.equal(c.mb82Review_(fake,complete(),date).state,'APROBADA');
let cut=complete();cut.drops=['DST_PLAYOFF'];
let blocked=c.mb82Review_(fake,cut,date);
assert.equal(blocked.state,'CONDICIONADA');
assert.ok(blocked.reasons.includes('HISTORICAL_DECISION_NEEDS_NEW_EVIDENCE_AND_COST'));
let unauth=complete();unauth.user_authorized=false;
assert.equal(c.mb82Review_(fake,unauth,date).state,'APROBADA');
assert.equal(c.mb82Review_(fake,unauth,date).execution_authorized,false);
let score=complete();score.scoring_source='GENERIC_PPR';
assert.ok(c.mb82Review_(fake,score,date).reasons.includes('LEAGUE_SCORING_SOURCE'));
let stale=complete();stale.snapshot_at='2026-11-01T00:00:00Z';
assert.ok(c.mb82Review_(fake,stale,date).reasons.includes('SNAPSHOT_STALE_OR_UNKNOWN'));
let gaps=complete();gaps.checks.bye_gaps_reviewed=false;
assert.ok(c.mb82Review_(fake,gaps,date).reasons.includes('EXISTING_BYE_GAPS'));
let trade=complete();trade.kind='TRADE';
assert.ok(c.mb82Review_(fake,trade,date).reasons.includes('CHECK_TWO_MARKET_SOURCES'));
let reversed=complete();reversed.drops=['DST_PLAYOFF'];
reversed.reversal={before:'hedge',new_evidence:'replacement',change:'cut',
 cost:'loss of playoff hedge',source:'fixture',user_authorized:false};
assert.equal(c.mb82Review_(fake,reversed,date).state,'APROBADA');
assert.equal(c.mb82Review_(fake,reversed,date).executed,false);
assert.equal(c.mb82Review_(fake,reversed,date).recommendation_allowed,true);
assert.equal(c.mb82Review_(fake,{...complete(),league_id:'other'},date).state,'DESCARTADA');
assert.throws(() => c.mb82RegistryFromText_(raw+raw),/marcadores/);
console.log('MONEYBALL82_APPS_SCRIPT_TESTS_OK: flexible-strategy checks');

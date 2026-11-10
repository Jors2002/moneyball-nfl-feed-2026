/**
 * MONEYBALL 8.2: optional PRIVATE Drive decision-integrity gate for Apps Script.
 * Add this file to the existing Apps Script project; do not replace Code.gs.
 * Script property MB82_DECISIONS_DOC_ID must hold the PRIVATE Google Doc ID.
 * No Sleeper mutation, no public GitHub upload, no automatic approval.
 */
var MB82 = Object.freeze({
  start: 'BEGIN_MONEYBALL_DECISIONS_JSON',
  end: 'END_MONEYBALL_DECISIONS_JSON',
  required: ['roster', 'scoring', 'health', 'role', 'replacement', 'lineup',
    'all_drops', 'do_nothing', 'playoffs', 'deadline'],
  horizons: ['week', 'next_3_5', 'playoffs_15_17']
});

function mb82RegistryFromText_(raw) {
  if (typeof raw !== 'string' || raw.split(MB82.start).length !== 2 ||
      raw.split(MB82.end).length !== 2) {
    throw Error('8.2: marcadores del registro faltantes o repetidos');
  }
  var data = JSON.parse(raw.split(MB82.start)[1].split(MB82.end)[0]);
  if (!data || data.schema_version !== 1 || !data.league_id ||
      !Array.isArray(data.decisions) || !Array.isArray(data.facts)) {
    throw Error('8.2: esquema del registro inválido');
  }
  var all = {};
  data.decisions.concat(data.facts).forEach(function(d) {
    if (!d || typeof d.id !== 'string' || !d.id || all[d.id]) {
      throw Error('8.2: identificador de decisión duplicado o inválido');
    }
    all[d.id] = true;
  });
  var facts = {};
  data.facts.forEach(function(f) { facts[f.id] = true; });
  data.decisions.forEach(function(d) {
    if (!d.status || !d.why || !d.decided_at || !d.source) {
      throw Error('8.2: decisión sin procedencia/justificación');
    }
    (d.linked_fact_ids || []).forEach(function(id) {
      if (!facts[id]) throw Error('8.2: referencia a hecho no registrado');
    });
  });
  return data;
}

function mb82ReadRegistry_() {
  var id = PropertiesService.getScriptProperties().getProperty('MB82_DECISIONS_DOC_ID');
  if (!id) throw Error('8.2: configure MB82_DECISIONS_DOC_ID en Script Properties');
  // Only internal private Drive access. Never transmit text to public NFL feed.
  return mb82RegistryFromText_(DocumentApp.openById(id).getBody().getText());
}

function mb82Review_(registry, p, nowIso) {
  if (!p || !registry || registry.schema_version !== 1 ||
      registry.league_id !== p.league_id) {
    return {state: 'DESCARTADA', reasons: ['WRONG_LEAGUE_OR_SCHEMA'],
      executed: false, conflicts: []};
  }
  if (['WAIVER', 'DROP', 'TRADE', 'LINEUP', 'NO_MOVE'].indexOf(p.kind) === -1) {
    throw Error('8.2: tipo de movimiento inválido');
  }
  var checks = p.checks && typeof p.checks === 'object' &&
    !Array.isArray(p.checks) ? p.checks : {};
  var reasons = [];
  MB82.required.forEach(function(k) {
    if (checks[k] !== true) reasons.push('CHECK_' + k.toUpperCase());
  });
  if (p.scoring_source !== 'SLEEPER_BRR') reasons.push('LEAGUE_SCORING_SOURCE');
  var now = nowIso ? Date.parse(nowIso) : Date.now();
  var snapshot = Date.parse(p.snapshot_at || '');
  if (!isFinite(snapshot) || !isFinite(now) || snapshot > now ||
      (now - snapshot) > 72 * 3600000) reasons.push('SNAPSHOT_STALE_OR_UNKNOWN');
  MB82.horizons.forEach(function(h) {
    if (!p.horizons || !p.horizons[h] || p.horizons[h].reviewed !== true) {
      reasons.push('HORIZON_' + h.toUpperCase());
    }
  });
  if (p.kind === 'TRADE') {
    ['opponent_lineup', 'acceptance', 'two_market_sources', 'rival_risk'].forEach(function(k) {
      if (checks[k] !== true) reasons.push('CHECK_' + k.toUpperCase());
    });
  }
  var drops = (p.drops || []).concat(p.gives || []);
  if (!Array.isArray(p.drops || []) || !Array.isArray(p.gives || []) ||
      drops.some(function(x) { return typeof x !== 'string' || !x; }) ||
      new Set(drops).size !== drops.length) throw Error('8.2: baja duplicada/inválida');
  var conflicts = [];
  (registry.decisions || []).forEach(function(d) {
    if (d.status !== 'ACTIVA' && d.status !== 'PENDIENTE') return;
    if (d.protected === true && drops.indexOf(d.asset) !== -1) {
      conflicts.push({id: d.id, asset: d.asset, reason: 'PROTECTED_ASSET'});
    }
    if (d.kind === 'LINEUP_GAP' && ['WAIVER', 'DROP', 'TRADE'].indexOf(p.kind) !== -1 &&
        checks.bye_gaps_reviewed !== true) reasons.push('EXISTING_BYE_GAPS');
  });
  var r = p.reversal, reversalOK = r && r.user_authorized === true &&
    ['before', 'new_evidence', 'change', 'cost', 'source'].every(function(k) {
      return typeof r[k] === 'string' && r[k].trim();
    });
  if (conflicts.length && !reversalOK) reasons.push('PROTECTED_ASSET_REQUIRES_REVERSAL');
  if (p.user_authorized !== true) reasons.push('USER_AUTHORIZATION');
  reasons = Array.from(new Set(reasons)).sort();
  return {state: reasons.length ? 'CONDICIONADA' : 'APROBADA',
    reasons: reasons, conflicts: conflicts, executed: false,
    interpretation: 'Auditoría, NO ejecución en Sleeper'};
}

/** Executable Apps Script smoke test. Only validates private doc; logs no private details. */
function verificarContinuidadMoneyball() {
  var registry = mb82ReadRegistry_();
  Logger.log('MONEYBALL82_REGISTRO_OK decisions=' + registry.decisions.length +
             ' facts=' + registry.facts.length + ' (sin datos privados en log)');
  return {status: 'OK', schema_version: registry.schema_version,
    decision_count: registry.decisions.length, fact_count: registry.facts.length};
}

/**
 * Can be invoked by a private orchestrator using a fully specified proposal.
 * Crucially does NOT submit claims/trades nor change roster or source documents.
 */
function evaluarMovimientoMoneyball82(proposal) {
  return mb82Review_(mb82ReadRegistry_(), proposal);
}

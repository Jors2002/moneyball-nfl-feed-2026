/** MONEYBALL 8.0 public-feed adapter. No league data is sent to the feed host.
 * Requires the existing MB5 dashboard and helpers; creates no trigger.
 */
const MB8 = Object.freeze({
  version: '8.1.0', season: 2026, schema: 80,
  url: 'https://raw.githubusercontent.com/Jors2002/moneyball-nfl-feed-2026/main/data/_MONEYBALL8_FORECAST_2026.json.gz',
  manifest: '_MONEYBALL_MANIFIESTO_8.json', maxAgeHours: 72,
  maxGzipBytes: 2000000, maxTextChars: 15000000,
  sheets: ['MB8_PROYECCIONES', 'MB8_CALIDAD', 'MB8_ALERTAS_ROL']
});

function mb8ValidateRole_(role, feed) {
  if(!role || role.schemaVersion !== 81 || role.season !== feed.season ||
     role.asOfWeek !== feed.asOfWeek || role.targetWeek !== feed.targetWeek ||
     !feed.predictionVintage || role.forecastVintage !== feed.predictionVintage || !role.bySleeper)
    throw Error('8.1 rol: vintage/semana/esquema incompatible');
  const generated = mb8Timestamp_(role.generatedAt);
  if(Date.now() - generated > MB8.maxAgeHours*3600000) throw Error('8.1 evidencia de rol obsoleta');
  if(Object.keys(role.bySleeper).length !== Object.keys(feed.bySleeper).length)
    throw Error('8.1 cobertura de rol incompleta');
  Object.keys(feed.bySleeper).forEach(id => {
    const r=role.bySleeper[id], p=feed.bySleeper[id];
    if(!r || r.originalProjection !== p.projection || r.adjustedProjection !== null ||
       !r.roleEvaluation || typeof r.roleEvaluation.decisionAllowed !== 'boolean' ||
       r.roleEvaluation.participationProbability !== null)
      throw Error('8.1 rol inválido o ajuste no aprobado '+id);
    if(r.decisionProjection !== (r.roleEvaluation.decisionAllowed ? p.projection : null))
      throw Error('8.1 proyección no utilizable expuesta '+id);
  });
  return role;
}

function mb8RoleFetch_(feed) {
  const path='data/_MONEYBALL8_ROLE_2026.json.gz';
  const urls=[
    ['gzip','https://raw.githubusercontent.com/Jors2002/moneyball-nfl-feed-2026/main/'+path],
    ['api','https://api.github.com/repos/Jors2002/moneyball-nfl-feed-2026/contents/'+path+'?ref=main']
  ];
  const errors=[];
  for(const [kind,url] of urls) {
    try {
      const response=UrlFetchApp.fetch(url,{muteHttpExceptions:true,followRedirects:true});
      if(response.getResponseCode()!==200) throw Error('HTTP '+response.getResponseCode());
      let blob=response.getBlob();
      if(kind==='api') {
        const api=JSON.parse(response.getContentText());
        if(api.encoding!=='base64' || typeof api.content!=='string') throw Error('API base64 inválida');
        blob=Utilities.newBlob(Utilities.base64Decode(api.content.replace(/\s/g,'')));
      }
      if(blob.getBytes().length>MB8.maxGzipBytes) throw Error('gzip de rol demasiado grande');
      const text=Utilities.ungzip(blob).getDataAsString('UTF-8');
      if(text.length>MB8.maxTextChars) throw Error('JSON de rol demasiado grande');
      return mb8ValidateRole_(JSON.parse(text),feed);
    } catch(error) {errors.push(String(error.message||error));}
  }
  throw Error('8.1 rol no disponible: '+errors.join(';'));
}

function mb8RoleRows_(feed, roles) {
  return Object.keys(feed.bySleeper).filter(id => {
    const role=roles && roles.bySleeper[id] && roles.bySleeper[id].roleEvaluation;
    return !role || !role.decisionAllowed || role.status==='SUSTAINED_UTILIZATION_INCREASE';
  }).map(id => {
    const p=feed.bySleeper[id], r=roles && roles.bySleeper[id], role=r && r.roleEvaluation;
    return [p.name,p.position,r && r.team || 'N/D',feed.targetWeek,
      role && role.previous ? mb8UtilizationText_(role.previous,false) : 'N/D',
      role && role.recent ? mb8UtilizationText_(role.recent,true) : 'N/D',
      role ? role.status : 'ROL_NO_VERIFICADO',role ? role.quality : 'SIN_EVIDENCIA',
      p.projection,'N/D: ajuste no validado',role ? role.cause : 'DESCONOCIDA',
      role && role.action || 'Verificar rol; no usar automáticamente la referencia histórica',
      role ? role.signals.join('; ') : 'Falta sidecar de rol del mismo vintage',
      role ? role.causeEvidence.map(e=>e.sourceUrl+' | '+e.publishedAt).join('; ') : ''];
  });
}

function mb8UtilizationText_(metrics,recent) {
  const share=metrics[recent ? 'snapShareLatest' : 'snapShareMedian3'];
  const show=k=>mb8Finite_(metrics[k]) ? Number(metrics[k].toFixed(2)) : 'N/D';
  return (recent ? 'Snaps último: ' : 'Snaps mediana 3: ')+
    (mb8Finite_(share) ? (share*100).toFixed(1)+'%' : 'N/D')+
    '; acarreos '+show('carries')+'; targets '+show('targets')+
    '; rutas '+show('routes')+'; acarreos ZR '+show('redzoneCarries');
}

function mb8RoleQualityRows_(roles) {
  const summary=roles && roles.validationSummary, rows=[];
  if(!summary)return [['Rol: comparación numérica','N/D; no presuponer mejora de precisión']];
  rows.push(['Rol: interpretación de métricas',summary.label+'; ajuste NO promovido']);
  rows.push(['Rol: ceros ofensivos sin resultado PPR verificable',JSON.stringify(summary.zeroOffenseMissingFantasyOutcome)]);
  rows.push(['Rol: faltantes que cumplían elegibilidad baseline',JSON.stringify(summary.baselineEligibleZeroOffenseMissingOutcome||{})]);
  Object.keys(summary.positions||{}).sort().forEach(pos=>{
    const all=summary.positions[pos].all,changed=summary.positions[pos].abrupt_loss;
    ['original','candidate'].forEach(model=>{
      ['n','mae','bias','interval80_coverage'].forEach(k=>rows.push([
        'Rol '+pos+' '+model+' '+k,all[model][k]===null ? 'N/D' : all[model][k]]));
      ['n','mae'].forEach(k=>rows.push(['Rol '+pos+' pérdida abrupta '+model+' '+k,changed[model][k]]));
    });
  });
  return rows;
}

function mb8Finite_(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function mb8Timestamp_(value) {
  if(typeof value !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(value))
    throw Error('8.0 timestamp sin zona horaria');
  const stamp = Date.parse(value);
  if(!Number.isFinite(stamp) || stamp > Date.now() + 300000)
    throw Error('8.0 timestamp inválido o futuro');
  return stamp;
}

/** Validation is separate from display; null never becomes a numerical zero. */
function mb8Validate_(feed, week) {
  if(!feed || feed.schemaVersion !== MB8.schema || feed.season !== MB8.season ||
     !feed.bySleeper || typeof feed.bySleeper !== 'object' || Array.isArray(feed.bySleeper))
    throw Error('8.0 esquema/temporada inválidos');
  if(!Number.isInteger(week) || week < 1 || week > 18 ||
     !Number.isInteger(feed.asOfWeek) || feed.asOfWeek < 1 || feed.asOfWeek >= week ||
     feed.targetWeek !== feed.asOfWeek + 1 || feed.targetWeek !== week)
    throw Error('8.0 semana objetivo incompatible o posible información futura');
  const generated = mb8Timestamp_(feed.generatedAt);
  const source = mb8Timestamp_(feed.sourceGeneratedAt || feed.generatedAt);
  if(source > generated + 300000) throw Error('8.0 fuente posterior a generación');
  if(Date.now() - source > MB8.maxAgeHours * 3600000 ||
     Date.now() - generated > MB8.maxAgeHours * 3600000)
    throw Error('8.0 feed obsoleto; se conserva último corte visible');
  const ids = Object.keys(feed.bySleeper);
  if(!ids.length) throw Error('8.0 feed sin jugadores');
  ids.forEach(id => {
    if(!/^\d+$/.test(id)) throw Error('8.0 ID no válido');
    const player = feed.bySleeper[id];
    if(!player || !['QB','RB','WR','TE'].includes(player.position))
      throw Error('8.0 posición no soportada ' + id);
    if(!Number.isInteger(player.priorGames) || player.priorGames < 0 ||
       !Number.isInteger(player.lastObservedWeek) || player.lastObservedWeek < 1 ||
       player.lastObservedWeek > feed.asOfWeek)
      throw Error('8.0 historial inválido o posterior al corte ' + id);
    if(player.projection !== null && !mb8Finite_(player.projection))
      throw Error('8.0 media inválida ' + id);
    if(!player.interval80 || typeof player.interval80 !== 'object')
      throw Error('8.0 sin declaración de intervalo ' + id);
    ['lower','upper'].forEach(bound => {
      if(player.interval80[bound] !== null && !mb8Finite_(player.interval80[bound]))
        throw Error('8.0 límite inválido ' + id);
    });
    if(player.projection !== null) {
      if(typeof player.model !== 'string' || !player.model)
        throw Error('8.0 proyección sin modelo ' + id);
      if(player.interval80.lower !== null || player.interval80.upper !== null) {
        if(!mb8Finite_(player.interval80.lower) || !mb8Finite_(player.interval80.upper) ||
           player.interval80.lower > player.interval80.upper || player.interval80.lower > player.projection || player.interval80.upper < player.projection)
          throw Error('8.0 intervalo inválido ' + id);
      }
    }
  });
  return {data: feed, status: 'VERIFICADO_TECNICAMENTE', sourceAt: new Date(source).toISOString()};
}

/** Fetches only NFL data. Never sends a roster, player query or token. */
function mb8Fetch_(week) {
  const sources = [
    {kind:'gzip',url:MB8.url},
    {kind:'api',url:'https://api.github.com/repos/Jors2002/moneyball-nfl-feed-2026/contents/data/_MONEYBALL8_FORECAST_2026.json.gz?ref=main'},
    {kind:'gzip',url:'https://cdn.jsdelivr.net/gh/Jors2002/moneyball-nfl-feed-2026@main/data/_MONEYBALL8_FORECAST_2026.json.gz'}
  ];
  const errors = [];
  for(const source of sources) {
    try {
      const response = UrlFetchApp.fetch(source.url, {
        muteHttpExceptions:true, followRedirects:true,
        headers:{Accept:source.kind === 'api' ? 'application/vnd.github+json' : 'application/octet-stream',
          'User-Agent':'MoneyballGM-Personal/8.0'}
      });
      if(response.getResponseCode() !== 200) throw Error('HTTP ' + response.getResponseCode());
      let blob;
      if(source.kind === 'api') {
        const encoded = response.getContentText('UTF-8');
        if(encoded.length > Math.ceil(MB8.maxGzipBytes * 4/3) + 10000)
          throw Error('respuesta API fuera de límites');
        const item = JSON.parse(encoded);
        if(item.encoding !== 'base64' || typeof item.content !== 'string')
          throw Error('API sin contenido base64');
        blob = Utilities.newBlob(Utilities.base64Decode(item.content.replace(/\s/g,'')),
          'application/gzip','MONEYBALL8.json.gz');
      } else blob = response.getBlob();
      const size = blob.getBytes().length;
      if(!size || size > MB8.maxGzipBytes) throw Error('gzip fuera de límites');
      const text = Utilities.ungzip(blob).getDataAsString('UTF-8');
      if(!text || text.length > MB8.maxTextChars) throw Error('JSON fuera de límites');
      const checked = mb8Validate_(JSON.parse(text), week);
      if(Object.keys(checked.data.bySleeper).length < 100)
        throw Error('cobertura de fuente real insuficiente');
      return checked;
    } catch(error) { errors.push(String(error.message || error).slice(0,180)); }
  }
  throw Error('8.0 fallaron las tres vías públicas: ' + errors.join(' | '));
}

function mb8RestoreSheets_(ss, previous) {
  if(!Array.isArray(previous) || ![2,MB8.sheets.length].includes(previous.length) ||
     previous.some((prior,index) => prior.name !== MB8.sheets[index] ||
       typeof prior.existed !== 'boolean' || (prior.existed && !Array.isArray(prior.values))))
    throw Error('8.0 checkpoint inválido; revisar publicación antes de continuar');
  previous.forEach(prior => {
    let sheet = ss.getSheetByName(prior.name);
    if(prior.existed) {
      if(!sheet) sheet = ss.insertSheet(prior.name);
      sheet.clearContents();
      if(prior.values.length && prior.values[0].length)
        sheet.getRange(1,1,prior.values.length,prior.values[0].length).setValues(prior.values);
    } else if(sheet) ss.deleteSheet(sheet);
  });
  SpreadsheetApp.flush();
}

function mb8Recover_(folder, ss) {
  const pending = mb42ReadFile_(folder, MB8.manifest);
  if(!pending || pending.stage !== 'PENDING') return;
  if(pending.dashboardId !== ss.getId()) throw Error('8.0 checkpoint de otro dashboard');
  mb8RestoreSheets_(ss, pending.previous);
  pending.stage = 'RECOVERED_PREVIOUS'; pending.recoveredAt = new Date().toISOString();
  mb42SaveFile_(folder, MB8.manifest, pending);
  Logger.log('MONEYBALL 8.0 recuperó el corte anterior tras publicación interrumpida.');
}

/** One numerical metric per row; never hide the validation in one JSON cell. */
function mb8QualityRows_(validation) {
  const rows = [];
  const positions = validation.positions || {};
  Object.keys(positions).sort().forEach(position => {
    const p = positions[position], selected = p.selected_model;
    rows.push([position + ' modelo evaluado final congelado', selected || 'N/D']);
    rows.push([position + ' modelo desplegado', p.deployment_model || selected || 'N/D']);
    rows.push([position + ' estado validación política desplegada',
      p.deployment_status || 'NO VERIFICADO']);
    rows.push([position + ' partición selección despliegue',
      p.deployment_selection_partition || 'NO VERIFICADA']);
    if(p.deployment_model) {
      rows.push([position + ' radio intervalo80 desplegado',
        mb8Finite_(p.deployment_interval80_radius) ? p.deployment_interval80_radius : 'N/D']);
      rows.push([position + ' cobertura selección despliegue NO OOS',
        mb8Finite_(p.deployment_interval80_selection_coverage) ? p.deployment_interval80_selection_coverage : 'N/D']);
    }
    if(p.deployment_model) rows.push([position + ' advertencia selección despliegue',
      'Selección de despliegue usó resultados 2026 W4–8; sus errores NO son prueba fuera de muestra de esta política. Validación prospectiva pendiente.']);
    rows.push([position + ' gate de promoción', p.promotion_gate || 'N/D']);
    const test = (p.test || {})[selected] || {};
    ['n','mae','rmse','bias'].forEach(metric => {
      rows.push([position + ' validación 2025 ' + metric.toUpperCase(),
        mb8Finite_(test[metric]) ? test[metric] : 'N/D']);
    });
    rows.push([position + ' cobertura intervalo80 validación 2025',
      mb8Finite_(p.test_interval80_coverage) ? p.test_interval80_coverage : 'N/D']);
    Object.keys(p.test || {}).forEach(model => {
      const score = p.test[model];
      rows.push([position + ' validación 2025 MAE ' + model,
        mb8Finite_(score.mae) ? score.mae : 'N/D']);
    });
    rows.push([position + ' afirmación calibración', p.calibration_claim || 'NO ESTABLECIDA']);
    const final = p.final_test;
    if(final) {
      const scores = final.selected_model || {};
      ['n','mae','rmse','bias'].forEach(metric => {
        rows.push([position + ' final 2026 ' + metric.toUpperCase(),
          mb8Finite_(scores[metric]) ? scores[metric] : 'N/D']);
      });
      rows.push([position + ' cobertura intervalo80 final 2026',
        mb8Finite_(final.interval80_coverage) ? final.interval80_coverage : 'N/D']);
      rows.push([position + ' final 2026 política congelada',
        final.policy_frozen_before_this_partition === true ? 'SÍ' : 'NO VERIFICADO']);
    }
  });
  return rows;
}

/** Only these two tabs are modified. A durable snapshot restores the preceding
 * values after ordinary errors, or on the next run after a hard termination.
 * Google services are not transactional: trust only a COMPLETED manifest.
 */
function mb8Publish_(ss, checked, folder) {
  const feed = checked.data;
  const previous = MB8.sheets.map(name => {
    const sheet = ss.getSheetByName(name);
    return {name:name, existed:!!sheet, values:sheet ? sheet.getDataRange().getValues() : null};
  });
  const rows = Object.keys(feed.bySleeper).map(id => {
    const p = feed.bySleeper[id];
    const role=checked.roles && checked.roles.bySleeper[id].roleEvaluation;
    return [id, p.name || '', p.position, feed.targetWeek,
      p.projection === null ? 'N/D' : p.projection, p.interval80.lower === null ? 'N/D' : p.interval80.lower,
      p.interval80.upper === null ? 'N/D' : p.interval80.upper, p.model || 'N/D',
      p.priorGames === undefined ? 'N/D' : p.priorGames,
      role ? (role.decisionAllowed ? role.status : 'REVISAR_ROL: '+role.status) : 'ROL_NO_VERIFICADO', feed.generatedAt,
      role && !role.decisionAllowed ? 'Referencia histórica NO UTILIZABLE automáticamente: '+role.signals.join('; ') :
      'Sin ajuste de lesión, rival ni probabilidad de participar; K/DEF no modelados'];
  });
  const metrics = feed.validation || {};
  const quality = [
    ['Versión', MB8.version], ['Corte fuente UTC', checked.sourceAt],
    ['Generado UTC', feed.generatedAt], ['Semana observada', feed.asOfWeek],
    ['Semana objetivo', feed.targetWeek], ['Jugadores', rows.length],
    ['Estado técnico', checked.status], ['Validación predictiva', metrics.status || 'VER REPORTE; NO PRESUPONER CALIBRACIÓN'],
    ['Intervalos', 'Condicionales a partido observado; cobertura publicada corresponde al modelo evaluado, no valida una política elegida con resultados 2026'],
    ['Lesiones/prácticas', 'No verificadas por este feed'],
    ['K/DEF', 'Sin proyección 8.0; conservar contexto 7.1'],
    ['Campeonato', 'NO CALIBRADO; no publicar porcentajes'],
    ['Operaciones Sleeper', 'NINGUNA'], ['Última publicación UTC', new Date().toISOString()]
  ].concat(mb8QualityRows_(metrics)).concat([
    ['Módulo rol',checked.roles ? 'VERIFICADO_TECNICAMENTE_8.1' : 'ROL_NO_VERIFICADO: no usar automáticamente'],
    ['Rol: fecha evidencia',checked.roles ? checked.roles.generatedAt : 'N/D'],
    ['Rol: conteos',checked.roles ? JSON.stringify((checked.roles.quality||{}).statusCounts||{}) : 'N/D'],
    ['Rol: ajuste predictivo','NO PROMOVIDO; proyección original y vintage se conservan'],
    ['Rol: validación','Comparación retrospectiva 2024/2025; no prueba prospectiva ni causas etiquetadas'],
    ['Rol: disponibilidad','No hay modelo validado de probabilidad de participar'],
    ['Rol: umbrales','Colas empíricas por posición calibradas sólo en 2023; cero ofensivo requiere evidencia de participación'],
    ['Rol: cobertura','BYE, inactivo, falta de cobertura, lesión y cambio de equipo no equivalen a pérdida táctica']
  ]).concat(mb8RoleQualityRows_(checked.roles));
  const manifest = {version:MB8.version, stage:'PENDING', sourceAt:checked.sourceAt,
    generatedAt:feed.generatedAt, targetWeek:feed.targetWeek, dashboardId:ss.getId(),
    previous:previous, roleVerified:!!checked.roles,
    roleVintage:checked.roles ? checked.roles.forecastVintage : null};
  mb42SaveFile_(folder, MB8.manifest, manifest);
  try {
    mb5WriteSheet_(ss, MB8.sheets[0],
      ['Sleeper ID','Jugador','Posición','Semana','PPR central','Límite inferior','Límite superior',
       'Modelo','Juegos previos','Estado','Generado UTC','Limitación'], rows);
    mb5WriteSheet_(ss, MB8.sheets[1], ['Control','Resultado'], quality);
    mb5WriteSheet_(ss, MB8.sheets[2],
      ['Jugador','Posición','Equipo','Semana','Utilización anterior','Utilización reciente',
       'Cambio detectado','Calidad de evidencia','Proyección original','Proyección ajustada',
       'Causa verificada o desconocida','Acción sugerida','Señales observadas','Fuente/fecha de contexto'],
      mb8RoleRows_(feed,checked.roles));
    SpreadsheetApp.flush();
    const header = ss.getSheetByName(MB8.sheets[0]).getRange(1,1).getValue();
    if(header !== 'Sleeper ID') throw Error('8.0 readback de encabezado falló');
    if(ss.getSheetByName(MB8.sheets[0]).getLastRow() !== rows.length + 1)
      throw Error('8.0 readback de cobertura falló');
    manifest.stage = 'COMPLETED'; manifest.publishedAt = new Date().toISOString();
    delete manifest.previous;
    mb42SaveFile_(folder, MB8.manifest, manifest);
  } catch(error) {
    mb8RestoreSheets_(ss, previous);
    manifest.stage = 'ROLLED_BACK'; manifest.error = String(error.message || error);
    mb42SaveFile_(folder, MB8.manifest, manifest);
    throw error;
  }
  Logger.log('MONEYBALL 8.0 PUBLICADO: ' + rows.length + ' jugadores; no implica precisión demostrada.');
  return manifest;
}

function mb8Run_(folder, week) {
  const dashboardId = PropertiesService.getScriptProperties().getProperty(MB5.dashboardProperty);
  if(!dashboardId) throw Error('8.0 requiere dashboard existente; ejecutar actualizarMoneyball');
  const ss = SpreadsheetApp.openById(dashboardId);
  mb8Recover_(folder, ss);
  const checked=mb8Fetch_(week);
  try {checked.roles=mb8RoleFetch_(checked.data);}
  catch(error) {Logger.log(error.message+'; todas las referencias se marcan rol no verificado');}
  return mb8Publish_(ss, checked, folder);
}

/** Manual refresh or existing scheduler entry. Never installs another trigger. */
function actualizarMoneyball8() {
  const lock = LockService.getScriptLock();
  if(!lock.tryLock(10000)) throw Error('8.0 otra sincronización en curso');
  try {
    const nfl = mbGet_('/state/nfl'), week = Number(nfl.week || nfl.leg);
    return mb8Run_(mbFolder_(), week);
  } finally { lock.releaseLock(); }
}

function verificarMoneyball8() {
  const manifest = mb42ReadFile_(mbFolder_(), MB8.manifest);
  if(!manifest || manifest.stage !== 'COMPLETED') throw Error('8.0 sin publicación completa');
  if(!manifest.roleVerified) throw Error('8.1 rol sin verificación; no certificar integración completa');
  mb8Timestamp_(manifest.publishedAt);
  if(Date.now() - Date.parse(manifest.sourceAt) > MB8.maxAgeHours * 3600000)
    throw Error('8.0 última publicación obsoleta');
  const ss = SpreadsheetApp.openById(manifest.dashboardId);
  MB8.sheets.forEach(name => { if(!ss.getSheetByName(name)) throw Error('8.0 falta pestaña ' + name); });
  if(ss.getSheetByName(MB8.sheets[0]).getRange(1,1).getValue() !== 'Sleeper ID')
    throw Error('8.0 encabezado alterado');
  Logger.log('MONEYBALL 8.0 INSTALACIÓN VERIFICADA; revisar métricas para precisión predictiva.');
  return manifest;
}

function probarFuenteRealMoneyball8() {
  const nfl = mbGet_('/state/nfl'), checked = mb8Fetch_(Number(nfl.week || nfl.leg));
  const roles=mb8RoleFetch_(checked.data);
  Logger.log('8.0 FUENTE ' + checked.status + ' / S' + checked.data.targetWeek);
  Logger.log('8.1 ROL VERIFICADO_TECNICAMENTE: '+Object.keys(roles.bySleeper).length+' jugadores; ajuste NO promovido');
}

function probarMoneyball8() {
  const feed = {schemaVersion:80, season:2026, asOfWeek:8, targetWeek:9,
    generatedAt:new Date().toISOString(), bySleeper:{'123':{
      position:'RB',projection:12,interval80:{lower:2,upper:22},model:'season_mean',priorGames:6,lastObservedWeek:8}}};
  mb8Validate_(feed,9);
  const bad = JSON.parse(JSON.stringify(feed)); bad.bySleeper['123'].projection = null;
  bad.bySleeper['123'].interval80.lower = null; bad.bySleeper['123'].interval80.upper = null;
  mb8Validate_(bad,9);
  let rejected = false;
  try { mb8Validate_(Object.assign({},feed,{targetWeek:10}),9); } catch(error) { rejected=true; }
  if(!rejected) throw Error('8.0 admitió semana futura');
  rejected=false; bad.bySleeper['123'].projection=NaN;
  try { mb8Validate_(bad,9); } catch(error) { rejected=true; }
  if(!rejected) throw Error('8.0 admitió NaN');
  Logger.log('MONEYBALL 8.0 PRUEBAS LOCALES OK');
}

/** Optional menu when run from a bound spreadsheet; standalone projects may use
 * the function picker in Apps Script. Does not create an installable trigger.
 */
function menuMoneyball8() {
  SpreadsheetApp.getUi().createMenu('Moneyball 8.0')
    .addItem('Probar instalación','probarMoneyball8')
    .addItem('Probar fuente pública','probarFuenteRealMoneyball8')
    .addItem('Actualizar proyecciones','actualizarMoneyball8')
    .addItem('Verificar publicación','verificarMoneyball8').addToUi();
}

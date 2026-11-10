# Moneyball 8.2 — Decision Integrity (NO cambia Moneyball 8.1)

Moneyball 8.1 sigue siendo el motor predictivo y de detección de cambios de rol. 8.2 añade una barrera **conservadora y privada** para propuestas humanas; no cambia estimaciones, no realiza operaciones de Sleeper y no fabrica odds.

## Qué se implementó

- `moneyball82_integrity.py`: parser de registro privado exportado de Google Docs, verificación de hechos enlazados, scoring real, vigencia (72 h), 3 horizontes, todas las bajas, controles específicos de trades y protección de activos. Ausencia de datos => `CONDICIONADA`; mismatch de liga => `DESCARTADA`.
- `apps_script/moneyball82_integrity.gs`: puente **opcional** para el proyecto existente de Apps Script. Consulta un Google Doc privado usando una propiedad de script y expone `verificarContinuidadMoneyball()` y `evaluarMovimientoMoneyball82(proposal)`. No reescribe `Code.gs`, no crea triggers y no sube registros a GitHub.
- Pruebas sintéticas de regresión: no cortar una defensa protegida por defecto, scoring con fumble, archivos faltantes, fotos viejas, byes, ofertas sin referencias y acciones sin autorización.

## Registro privado — ¡NO PUBLICAR EN ESTE REPO!

El registro `MONEYBALL_DECISIONES_VIGENTES` está guardado en la carpeta privada de Google Drive de BRR. Contiene un bloque delimitado por:
```
BEGIN_MONEYBALL_DECISIONS_JSON
{ ... schema_version: 1, league_id, facts: [], decisions: [] ... }
END_MONEYBALL_DECISIONS_JSON
```
Las razones históricas (POR QUÉ) no sustituyen el historial de transacciones (QUÉ). El script consume una copia exportada local del documento únicamente si la persona usuaria la aporta: `python moneyball82_integrity.py --registry-text /ruta/privada/decisiones.txt --proposal /ruta/privada/propuesta.json`. **Nunca versionar estos archivos ni colocar capturas, rosters o mensajes de managers en GitHub.**

## Activación opcional en Apps Script (requiere paso manual)

1. En el **proyecto privado Apps Script existente**, crear un archivo `Moneyball82Integrity.gs` con el contenido íntegro de `apps_script/moneyball82_integrity.gs`. Conservar todos los archivos y triggers actuales.
2. En Project Settings → Script Properties, crear `MB82_DECISIONS_DOC_ID` con el **ID real del Google Doc privado** (no pegarlo en GitHub). La cuenta ejecutora necesita acceso al Doc.
3. Guardar y ejecutar `verificarContinuidadMoneyball` desde el selector de funciones. Debe devolver `status: OK` y número de decisiones/hechos. Este paso solo valida lectura; no publica ni escribe nada.
4. Para propuestas concretas, un orquestador **privado** debe aportar snapshots verificables y un `proposal` completo a `evaluarMovimientoMoneyball82`. Sin el orquestador que rellene estos campos la validación es manual; **no afirmar que todas las sugerencias de ChatGPT o los waivers de Sleeper estén bloqueados automáticamente**.

## Esquema mínimo de propuesta

```json
{
  "league_id": "id_que_coincida_con_registro_privado",
  "kind": "WAIVER",
  "drops": ["id_jugador_a_cortar"],
  "gives": [],
  "receives": ["id_jugador_entrante"],
  "scoring_source": "SLEEPER_BRR",
  "snapshot_at": "2026-11-10T06:00:00Z",
  "checks": {
    "roster": true, "scoring": true, "health": true, "role": true,
    "replacement": true, "lineup": true, "all_drops": true,
    "do_nothing": true, "playoffs": true, "deadline": true,
    "bye_gaps_reviewed": true
  },
  "horizons": {
    "week": {"reviewed": true},
    "next_3_5": {"reviewed": true},
    "playoffs_15_17": {"reviewed": true}
  },
  "user_authorized": false
}
```

`true` significa **evidencia comprobada externamente**; nunca inventar ni rellenar los controles por defecto. Si se propone cortar un activo protegido, hace falta un bloque `reversal` con `before`, `new_evidence`, `change`, `cost`, `source` y `user_authorized:true`. Un resultado `APROBADA` significa que el expediente superó las validaciones entregadas, **no** que la fuente externa exista, que el equipo aceptó ni que la transacción se ejecutó.

## Límites y seguridad

- No existe permiso de ejecución Sleeper en este módulo.
- La API pública no revela ofertas privadas, Trade Block íntegro ni reclamaciones pendientes.
- Rutas y snaps faltantes NO equivalen a cero.
- Los registros de 8.1 siguen intactos.
- Pendiente: integrar un orquestador privado que registre nuevas decisiones en Drive y ejecute el control automáticamente al construir cada recomendación. No se considera desplegado hasta validar acceso, permisos y lectura desde el proyecto Apps Script real.

## Pruebas

```sh
python -m pytest -q tests/test_moneyball82_integrity.py
node tests/test_moneyball82_apps_script.js
```

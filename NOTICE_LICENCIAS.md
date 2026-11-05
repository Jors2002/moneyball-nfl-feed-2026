# Licencias y atribuciones de fuentes de Moneyball 5.0

- **nflverse**: https://github.com/nflverse — la mayoría de conjuntos están bajo Creative Commons Attribution 4.0 (CC-BY 4.0). Atribución a colaboradores, fuente y enlace a la licencia.
- **FTN Data vía nflverse**: https://ftnfantasy.com/data y https://nflreadr.nflverse.com/reference/load_ftn_charting.html — CC-BY-SA 4.0. Atribuir a FTN Data y nflverse; si redistribuyes un archivo derivado, respeta las obligaciones de compartir bajo la misma licencia y atribuir claramente. Texto: https://creativecommons.org/licenses/by-sa/4.0/
- **DynastyProcess**: https://github.com/dynastyprocess/data — verificar términos vigentes antes de redistribuir sus datos de identificadores.
- **Sleeper**: https://docs.sleeper.com/ — API pública solo lectura; este sistema no hace cambios en liga.

`moneyball5_etl.py` emite solo estadísticas deportivas de fuentes públicas, sin roster de nuestra liga ni datos personales. **No publiques ni introduzcas tokens, correos, waivers pendientes o screenshots privados** en el feed de GitHub.

No se recopilan rutas premium sin exportación y permiso válido del proveedor. Una licencia de consulta no equivale a derecho de extracción automatizada.

## Extensión 8.0 (2026-11-04)

Los modelos 8.0 usan estadísticas semanales `stats_player` de nflverse, temporadas 2023–2026, CC-BY 4.0; no incorporan FTN ni tracking premium. Las predicciones transforman esos datos mediante medias históricas y regresión ridge. Los archivos emitidos incluyen URL, SHA-256, fecha de descarga, modelo y limitaciones. Fuentes oficiales: https://github.com/nflverse y https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md . nflverse no avala estas predicciones.

El repositorio DynastyProcess declara GNU GPL v3. El crosswalk se usa solo para resolver identidad sin redistribuir el CSV completo: https://github.com/dynastyprocess/data/blob/master/LICENSE . El lector oficial de Chiefs preserva hechos mínimos y la URL; no redistribuye artículos/HTML y no implica una licencia general de su contenido. Sleeper se consulta solo en privado y en lectura: https://docs.sleeper.com/ .

Las fuentes históricas son versiones revisadas, no un archivo de lo conocido antes de cada kickoff. La descarga no demuestra fecha de evento ni permiso de extraer rutas de un proveedor premium.

## Role detection 8.1

NFLverse/PFR snap counts2023–2026, NFLverse weekly player statistics and nfldata game schedules retain existing attribution and CC-BY4.0 terms of the nflverse releases. No full official article is redistributed: the Seattle context file preserves minimal facts, source URL and source timestamps. No premium route or tracking data is fabricated. Historical source hashes identify revised snapshots, not publication-time archives.

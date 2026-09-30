# Fase 2b — Walk-forward del PROCEDIMIENTO (genético re-optimizado por ventana) frente a control aleatorio y nulo permutado

Fecha: 2026-09-30. Rama `phase-2b-wf-procedure`. Run `phase2b_wf_eurusd_r1` (EURUSD).
- Configuración preregistrada: `configs/wf_procedure.yaml`, commiteada en `ccd14b0` antes de cualquier run con datos reales.
- Única corrección posterior: `3eb92ec` (fix del script: YAML lee la clave `null:` como `None`). No cambió ningún valor del config. Afectó solo a los shards del nulo, que fallaron al arrancar sin escribir nada y se relanzaron.
- Resultados completos: `docs/reports/phase2b_run.json`, `runs/phase2b_wf_eurusd_r1/`.

## Veredicto

**El procedimiento no demuestra edge con los criterios preregistrados.** Cumple 2 de 4 condiciones.

| Criterio de aceptación (todos obligatorios) | Valor | ¿Cumple? |
|---|---|---|
| mean R OOS 2010–2018 con costes ×1 > 0 | +0,0294 R | sí |
| mean R OOS con costes ×2 > 0 | −0,0092 R | **no** |
| p-valor frente a 100 mercados permutados ≤ 0,05 | 0,109 (10 de 100 nulos ≥ observado) | **no** |
| Supera al control aleatorio (mismo criterio y presupuesto) | +0,0294 frente a −0,0396 | sí |

- No se aflojan umbrales ni se relanza con otra semilla.
- No se tocó 2019–2022: el M15 se truncó en 2019-01-01 antes de construir cualquier mercado.
- El holdout tampoco se tocó: 0 accesos.

## Qué se midió

**Diseño:** para cada año OOS Y (2010–2018):
- El genético se entrena solo en Y−4..Y−1: 20.000 estrategias únicas por ventana; fitness = peor t-estadístico entre 2 bloques de 2 años.
- Selecciona top-10 dentro del entrenamiento: ≥60 trades, PF ≥ 1,10, mean R > 0,03 y mean R > 0 con costes ×2.
- Las congela y las opera en Y (ejecución M15, drawdown a mercado).
- Solo se concatenan los años OOS.
- El control hace lo mismo con búsqueda aleatoria del mismo tamaño.
- El nulo repite ambos procedimientos, con las mismas semillas, sobre 100 mercados con las barras M15 permutadas.

| | Genético | Control aleatorio |
|---|---:|---:|
| Evaluaciones (9 ventanas × 20.000) | 180.000 | 180.000 |
| Trades OOS (10 estrategias × 9 años) | 3.089 | 5.944 |
| mean R OOS, costes ×1 | **+0,0294** (t = 1,49) | −0,0396 (t = −2,59) |
| mean R OOS, costes ×2 | −0,0092 | −0,0851 |
| p-valor frente al nulo permutado (×1) | **0,109** | 0,495 |
| Nulo: media / p95 / máx. de mean R | −0,041 / +0,056 / +0,071 | −0,043 / −0,009 / −0,001 |
| Años OOS con mean R > 0 | 5 de 9 | 2 de 9 |
| Cartera equiponderada: Sharpe anual | 0,18 | −0,52 |
| Cartera: retorno 2010–2018 / DD máx. (a 0,5 % de riesgo por trade) | +4,3 % / 7,3 % | −11,4 % / 13,4 % |
| Cartera: PSR frente a 0 / DSR (N = 2 procedimientos, Var[SR] de los nulos) | 0,71 / 0,51 | 0,06 / 0,02 |

**Por año, genético** (mean R ×1 / ×2 / DD a mercado medio por estrategia):

| Año | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 |
|---|---|---|---|---|---|---|---|---|---|
| Trades | 799 | 333 | 437 | 418 | 102 | 293 | 189 | 198 | 320 |
| mean R ×1 | −0,054 | +0,045 | **+0,288** | −0,110 | −0,068 | +0,166 | −0,085 | +0,006 | +0,038 |
| mean R ×2 | −0,070 | +0,018 | +0,210 | −0,152 | −0,117 | +0,140 | −0,115 | −0,031 | −0,024 |
| DD a mercado medio | 5,9 % | 2,5 % | 7,5 % | 3,1 % | 1,4 % | 0,9 % | 3,2 % | 1,4 % | 3,0 % |

El resultado positivo agregado depende sobre todo de 2012 y 2015. Sin 2012, el mean R agregado ×1 es negativo (−0,0132).

**Análisis post hoc** (informativo, no forma parte del preregistro):
- Diferencia genético − control: +0,069R, con p = 0,129 bajo el nulo (media nula +0,002, p95 +0,092). Batir al control no es significativo.
- Con costes ×2 el genético tiene p = 0,119 frente a su nulo.
- El control aleatorio se comporta exactamente como su nulo (p = 0,50): la selección sin optimizar no aporta nada, como era de esperar.

## Número de ensayos
- **Contador `trials/ledger.jsonl`: 729.070 evaluaciones sobre datos reales**, de las cuales 459.000 de selección.
  - Fase 2: 99.000.
  - Fase 2b: 180.000 del genético + 180.000 del control.
  - Resto de ingeniería, incluidas 180.000 de regenerar los archivos del genético con las mismas semillas para calcular N_eff.
- **Nulos:** 100 × 360.000 = 36 millones de evaluaciones sobre datos permutados (sintéticos). No se suman al contador, que cuenta solo datos reales; están guardadas en `runs/phase2b_wf_eurusd_r1/null_shard*.jsonl`.
- **N efectivo a nivel de procedimiento: 2** (genético y control, según `trials/procedure_ledger.jsonl`). Con ese N, el DSR de la cartera OOS del genético es 0,51, lejos del 0,95.
- **N efectivo a nivel de estrategia** (informativo), N_eff = ρ̄ + (1 − ρ̄)·N por ventana, con N = 20.000:
  - ρ̄ va de 0,05 a 0,26.
  - N_eff va de 14.902 a 19.024.
  - Las estrategias del genético están poco correlacionadas entre sí, así que la corrección por ensayos apenas se reduce por redundancia.

## Lectura
1. **Hay una señal débil que no alcanza significación.**
   - El genético es el único de los dos que queda en positivo tras costes reales (+0,03R, t = 1,5).
   - El nulo produce valores así en ~10 % de los casos.
   - Con costes ×2 desaparece.
   - Es coherente con la Fase 2, donde el walk-forward eliminó el 97,5 % de los candidatos.
2. **El genético optimiza algo que el azar no:** en los datos reales sus OOS son mejores que las del control, y en los nulos ambos pierden por igual. Pero la diferencia (p = 0,13) tampoco es concluyente con 9 años de un solo par.
3. **Concentración temporal:** 2012 aporta casi todo. No hay persistencia año a año (5 de 9 positivos).
4. **Sin indicios de bug:**
   - Los nulos pierden de media −0,04R, que es el coste por trade, como en la Fase 1.
   - Nada supera los límites de "demasiado bueno".

## Qué se construyó
- `sqxf.funnel.wf_procedure`: ventanas rolling, generación (genético o aleatorio), selección top-K preregistrada, operación OOS, resumen, nulo por permutación de barras M15 y N_eff por correlación.
- `scripts/wf_procedure.py` (`observed` una sola vez por `run_name`; `null` por shards reanudables; `report`). Exige el config commiteado (`provenance.require_committed`).
- `trials/procedure_ledger.jsonl`: procedimientos evaluados sobre los años OOS.
- Tests (`tests/test_wf_procedure.py`):
  - La permutación conserva barras válidas y la distribución de formas de barra, y rompe el orden temporal.
  - El truncado elimina los datos posteriores.
  - El entrenamiento queda estrictamente antes de la ventana OOS.
  - **La generación y la selección no cambian si se alteran todos los precios del año OOS en adelante** (genético y aleatorio).
  - El procedimiento es determinista.

`pytest -q`: **65 passed** (mostrado en la conversación). `ruff`: limpio. Duración: observado ~6 min; nulo ~50 min en 4 procesos.

## Limitaciones
- **Solo EURUSD y 9 años OOS:** poca potencia estadística. Con σ ≈ 1R por trade y ~3.000 trades OOS, el error estándar de mean R es ~0,02R, del mismo orden que el edge que se busca.
- **El nulo permutado destruye también el clustering de volatilidad y la estacionalidad intradía.** Es un nulo de "ninguna estructura temporal"; la hipótesis de "estructura sí, edge explotable no" queda sin contrastar.
- **Los años 2010–2018 no son vírgenes para el investigador:** la Fase 2 ya los usó con la misma gramática y la misma forma de fitness. El procedimiento no reutiliza ninguna estrategia ni resultado de aquel run.
- **Sin swap**, coste fijo.
- **Selección y fitness en ejecución H1** (conservadora), operación en M15.

## Propuestas (cada una sería un run nuevo con su propio preregistro; decide Jaime)
1. **Más potencia antes que más búsqueda:** el mismo procedimiento sobre los 6 pares (reglas por par o compartidas) multiplica los trades OOS por ~6 con el mismo número de procedimientos.
2. **Gramática reducida y con motivación económica** (sesión, hora, régimen) para reducir la varianza de selección.
3. **Selección por robustez más estricta dentro del entrenamiento** (por ejemplo, exigir costes ×2 con PF ≥ 1,1): hoy la selección deja pasar estrategias que no sobreviven a costes ×2 fuera de muestra.
4. **Completar el embudo** (Monte Carlo, ruido, plateau, PBO) y añadir swap antes de cualquier búsqueda nueva.

# Fase 2 (compacta) — Generador genético, embudo y Deflated Sharpe

Fecha: 2026-09-30. Rama `phase-2-funnel`. Run `phase2_eurusd_g1_r1` (EURUSD, semilla 20260930, código `ef3843c`, dataset SHA256 `fec7a625…`).
Informe completo del run: `docs/reports/phase2_run.json`. Umbrales: `configs/funnel.yaml`, commiteado (`ef3843c`) antes del run.

## Resultado

**No sobrevive ninguna estrategia.**
- 415 estrategias pasan el walk-forward 2015–2018.
- Ninguna pasa el Deflated Sharpe con N = 168.590 ensayos.
- El bloque final 2019–2022 no llegó a evaluarse: no quedaba ninguna candidata (0 accesos).
- El holdout (2023 en adelante) no se ha cargado (0 accesos).

| Etapa | Periodo | Supervivientes | % de la etapa anterior |
|---|---|---:|---:|
| Generadas por el genético (únicas) | fitness 2004–2014 | 99.000 | — |
| Básico (≥200 trades, PF ≥ 1,15, mean R > 0,05, DD MTM ≤ 25 %) | 2004–2014 | 20.159 | 20,4 % |
| Estabilidad (mean R > 0 en los 3 bloques) | 2004–2014 | 16.985 | 84,3 % |
| Costes ×2 (PF ≥ 1,05, mean R > 0) | 2004–2014 | 16.568 | 97,5 % |
| Ejecución: entrada con 1 barra de retraso (PF ≥ 1,05, mean R > 0) | 2004–2014 | 16.433 | 99,2 % |
| Walk-forward (≥3/4 años con mean R > 0, PF ≥ 1,10 agregado, ≥40 trades) | 2015–2018 | 415 | 2,5 % |
| **Deflated Sharpe ≥ 0,95** | 2004–2018 | **0** | 0 % |
| Bloque final (no visto por el genético) | 2019–2022 | 0 | — |

## Ensayos
- Contador versionado `trials/ledger.jsonl`, que incluye las 67.190 evaluaciones de la Fase 1.
- **Total actual: 189.070 evaluaciones.** De ellas, 99.000 de selección (este run) y el resto de ingeniería: tests, benchmarks y el análisis de sensibilidad de abajo.
- **N usado en el DSR: 168.590**, que era el total del contador en el momento del cálculo.

## Por qué no pasa nada al DSR
- Las 20 mejores candidatas según el DSR tienen un Sharpe anual de 0,91–1,12 en 2004–2018 (3.911 días), con kurtosis de 6–17.
- La mejor: LONG con 4 predicados (ROC 32 < 0, ROC 8 > 0, RSI > 50 y pendiente de la EMA10 negativa), SL 2, TP 2, 24 barras. Sharpe anual 1,12 y DSR = 0,000.
- **El listón SR\*** es el Sharpe máximo esperado entre N estrategias sin edge. Con Var[SR] medida entre los ensayos (desviación del Sharpe anual 0,50) y N = 168.590, SR\* = **2,24 anual**.

**Sensibilidad** (post hoc y solo informativa: no cambia ningún umbral ni el resultado):

| Supuesto | SR\* anual | DSR de la mejor |
|---|---:|---:|
| Var[SR] con 20.000 estrategias aleatorias, filtro de ≥30 / ≥200 / ≥1.000 trades | 2,69 / 2,66 / 2,64 | ≈0 |
| Nula de ruido puro (Var[SR] = 1/T), N = 188.590 | 1,17 | 0,43 |
| Nula de ruido puro, N = 99.000 (solo el genético) | 1,13 | 0,48 |
| Nula de ruido puro, N = 1.000 | 0,84 | 0,86 |

Ni con la nula más indulgente ni contando solo los ensayos del genético se acerca al 0,95. El resultado negativo no depende de cómo se estime Var[SR].

## Lectura
1. **El walk-forward elimina el 97,5 %** de lo que pasa todas las etapas en muestra. Es la firma del sobreajuste: el edge de 2004–2014 no persiste en 2015–2018.
2. **Los estreses en muestra apenas filtran.** Costes ×2 conserva el 97,5 % y el retraso de 1 barra el 99,2 %. Los umbrales de esas etapas (PF ≥ 1,05) son laxos comparados con la etapa básica (PF ≥ 1,15, mean R > 0,05); se fijaron así de antemano. No se cambian a posteriori.
3. **El genético sí optimiza.** La fitness (peor t-estadístico entre bloques) sube de 1,09 (generación 1) a 2,40 (generación 100). Pero un t ≈ 2,4 en el peor bloque, tras 99.000 intentos, está dentro de lo que produce el azar.
4. **No hay indicios de bugs ni fugas.** No hay ningún aviso de "demasiado bueno" y las métricas son coherentes con la Fase 1 (las estrategias aleatorias pierden el coste).

## Qué se construyó
- **Drawdown a mercado** (`max_dd_mtm`): equity marcada en cada barra de ejecución (M15 en el embudo) al extremo adverso. Oráculo = Numba. Tests:
  - `test_mark_to_market_drawdown_sees_intratrade_losses`: una bajada de −0,9R seguida de TP da 0,45 % de DD a mercado y 0 % en trades cerrados.
  - `test_mtm_drawdown_is_at_least_closed_trade_drawdown`.
- **Contador versionado** `trials/ledger.jsonl` y log del bloque final `trials/final_block_access.jsonl`. El pipeline se niega a repetir un `run_name` que ya miró el bloque final.
- **Genético** `sqxf.generators.genetic`:
  - Torneo, cruce de predicados y salidas, mutación, élite, inmigrantes y deduplicación por hash canónico.
  - Determinista (`test_genetic_is_deterministic_and_counts_unique`).
  - Aislado: si se alteran todos los precios posteriores a 2014 (en sintético), la trayectoria del genético no cambia ni un bit (`test_genetic_never_sees_data_after_the_training_windows`).
- **Embudo** `sqxf.funnel.pipeline` y `sqxf funnel`:
  - Todos los umbrales salen del YAML.
  - El CLI se niega a correr si el YAML no está commiteado.
  - Retornos diarios verificados: su producto es igual a la equity final (`test_daily_returns_compound_to_final_equity`).
- **Deflated Sharpe** `sqxf.stats.dsr`. Tests:
  - SR\* coincide con una simulación Monte Carlo del máximo (±3 %).
  - PSR = 0,5 en el umbral.
  - "El mejor de 2.000 ruidos" tiene PSR bruto > 0,99 pero DSR < 0,9.

`pytest -q`: **59 passed** (se muestra en la conversación). `ruff`: limpio. Duración del run: 79 s.

## Límites de esta versión compacta
- **Solo EURUSD.** No hay validación en otros pares, pendiente de la Fase 3.
- **El walk-forward es con estrategias fijas y ventanas anuales hacia delante**, sin re-optimización. 2015–2018 participa en la selección, así que solo 2019–2022 es realmente fuera de muestra respecto a toda la selección.
- **Faltan etapas de la Fase 2 completa de `CLAUDE.md`:** plateau relativo, Monte Carlo de orden y remuestreo, ruido en precios, PBO/CSCV. Por eso **no se etiqueta `v0.2` ni se hace merge a `main`**: la rama queda para revisión.
- **Sin swap/rollover.**
- **La fitness usa ejecución H1** (conservadora) y el embudo M15. Un candidato bueno en M15 pero mediocre en H1 se pierde. El sesgo medido en la Fase 1 es pequeño (+0,003R).
- **El listón del DSR es duro por construcción.** Usar el total del contador, incluidas las evaluaciones de ingeniería, fue decisión previa. El análisis de sensibilidad muestra que no cambia la conclusión.

## Qué proponer (requiere decisión de Jaime; cada cambio es un run nuevo con su propio preregistro)
1. **Más datos por hipótesis en lugar de más hipótesis:** evaluar la misma regla en los 6 pares a la vez, con fitness y DSR sobre el retorno agregado. Multiplica T y reduce el número de "ensayos efectivos" por la correlación.
2. **Gramática más pequeña y con motivación económica**, con menos N. Por ejemplo: sesión y hora del día, ruptura del rango asiático, reversión tras un movimiento extremo con filtro de régimen. El SR\* crece con √(2 ln N); reducir N en dos órdenes de magnitud baja el listón ~20–25 %.
3. **Evaluar a nivel de portfolio:** muchas estrategias débiles poco correlacionadas pueden superar un DSR que ninguna supera sola (Fase 5).
4. **Walk-forward con re-optimización** (Fase 3): mide si el *procedimiento* tiene edge fuera de muestra, que es la pregunta relevante.
5. **Completar el embudo** (Monte Carlo, ruido, plateau, PBO) y añadir swap antes de cualquier run nuevo.

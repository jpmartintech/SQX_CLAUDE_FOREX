# Fase 1 — Evaluador correcto y rápido

Fecha: 2026-09-29. Rama `phase-1-evaluator` → `main`, tag `v0.1`. Código `sqxf 0.1.0`.

## Qué se construyó

| Módulo | Contenido |
|---|---|
| `sqxf.data.m15` | Loader canónico de M15: valida (orden, duplicados, rejilla, NaN, OHLC) y **falla** en vez de reparar. EET → UTC con DST europeo. Descarta el holdout sellado (EET ≥ 2023-01-01) antes de devolver o cachear nada. Máscara `no_trade` de festivos, volumen desbordado → NaN, `day_id` (día de trading FX). Caché parquet invalidada por SHA256 del CSV y versión del esquema. |
| `sqxf.data.holdout` | Única vía al holdout: exige variable de entorno y motivo, y registra cada acceso en `runs/holdout_access.jsonl`. Accesos hasta hoy: 0. |
| `sqxf.data.h1` | H1 derivado de M15: barra `t` = M15 con `t <= ts < t+1h`, sin relleno ni barras sintéticas, con `n_m15`, `complete`, `close_ts` y el rango M15 de cada hora. |
| `sqxf.features.bank` | 77 features causales (incluido el ATR) en H1: EMA, pendientes, cruces, breakouts contra máximos previos, ROC en unidades de ATR, RSI de Wilder, Williams %R, régimen de ATR, Bollinger/Keltner y fractales confirmados en `p+d`. |
| `sqxf.grammar` | Gramática `g1`: 170 predicados y rejillas de salida (SL 1–3 ATR, TP 1–4 ATR, 12–96 barras), fijadas ex ante. |
| `sqxf.features.predicates` | Predicados → bool → bitsets `uint64` (64 barras por palabra). |
| `sqxf.strategy.definition` | Definición portable con hash SHA256 canónico (predicados ordenados y deduplicados, orientación de los pares EMA normalizada). |
| `sqxf.backtest.oracle` | Evaluador Python de referencia (oráculo): bucle plano sobre arrays booleanos, sin bitsets ni Numba. |
| `sqxf.backtest.kernels` | Numba: núcleo único `_core` → kernel ligero `evaluate_batch_light` (`prange` sobre estrategias, solo agregados) y kernel rico `simulate_rich` (trades completos). Señales por AND de bitsets con salto de palabra en palabra. |
| `sqxf.backtest.evaluator` | API: `load_market`, `evaluate_light`, `evaluate_rich`, `evaluate_oracle`, `derive_metrics`. Ejecución sobre **H1** o sobre el **camino M15** dentro de cada hora con el mismo kernel. |
| `sqxf.trials` | Registro append-only de evaluaciones (`runs/trial_ledger.jsonl`). |
| CLI | `sqxf build-data` valida y cachea los 6 pares. |

### Contrato del evaluador (resumen; detalle en `docs/DECISIONS.md`)
- Señal en la barra H1 `t` cerrada, completa, fuera de festivos y con ATR válido.
- Entrada al open de la barra `t+1+delay`. **Antes de esa barra la posición no existe.**
- SL/TP = múltiplos del ATR(14) de `t`, anclados al precio real de entrada.
- En cada barra de ejecución se comprueba, por este orden:
  1. Gap en el open que supera el SL → sale al open.
  2. Gap en el open que supera el TP → sale al open.
  3. El rango toca el SL → sale en el SL. **Si en la misma barra se tocan SL y TP, gana el SL.**
  4. El rango toca el TP → sale en el TP.
- Salida por tiempo al close de `entry + max_bars − 1`.
- Resultados:
  - R = (dirección·(salida − entrada) − coste) / riesgo inicial.
  - Equity compuesta: `eq *= 1 + 0.5 %·R`.
  - Drawdown en % del pico.
  - Sharpe de retornos diarios, incluidos los días sin trades, anualizado con √260.
- Costes por par en `configs/costs.yaml`, siempre presentes. EURUSD: 1,0 pip de spread + 2 × 0,25 pip de slippage = 1,5 pips por round-trip.

## Criterios de aceptación y cómo se demuestran

| Criterio (`CLAUDE.md`) | Evidencia |
|---|---|
| Trades en R, equity con riesgo fraccional, drawdown en % | `test_drawdown_is_percent_of_equity_with_fractional_risk`: 10 pérdidas de −1R → DD = 1 − 0,995¹⁰ = 4,89 % (en la referencia sería ~1e-5). `test_costs_are_charged_in_r`, `test_sharpe_is_daily_and_counts_flat_days`. |
| `entry_delay` corregido | `test_entry_delay_position_does_not_exist_before_entry[1,2,3]`: el precio se hunde entre la señal y la entrada, y no sale ningún trade antes de la entrada. Invariantes `entry_idx == signal_idx + 1 + delay`, `exit_idx >= entry_idx`, `bars_held >= 1` sobre 60 estrategias × 2 delays (sintético) y 40 estrategias × 4 configuraciones (EURUSD real). |
| Kernel ligero + kernel rico, `prange`, bitsets | `evaluate_batch_light` (paralelo) y `simulate_rich` comparten `_core`. Test: agregados ligero == rico **bit a bit**. `test_bitset_roundtrip_and_layout`, `test_next_signal_matches_naive_scan`. |
| Equivalencia Python/Numba | `test_numba_rich_and_light_equal_python_oracle`: 120 estrategias × {H1, M15} × delay {0,1,3} en sintético; `test_real_oracle_equals_numba`: 40 estrategias × 4 configuraciones en EURUSD 2004–2022. Trades idénticos **exactamente** (índices, precios, R, equity). Agregados a `rtol=1e-12` en los casos dorados y `1e-9` en el resto; la única fuente de diferencia es el Sharpe (numpy frente a sumas acumuladas). |
| Casos dorados SL/TP en la misma barra | `test_sl_and_tp_in_same_bar_stop_wins`, `test_short_same_bar_stop_wins_and_target`, `test_gap_through_stop_exits_at_open`, `test_time_exit_counts_bars_from_entry_and_end_clipping`, `test_next_signal_may_be_the_exit_bar`. |
| H1 desde M15 sin fuga | `test_h1_matches_groupby_oracle`, `test_h1_bar_only_contains_its_own_hour`, `test_h1_prefix_invariance[4 cortes]`, `test_features_are_prefix_invariant[3 cortes]` (las 77 features). |
| Fuga en todo el pipeline | `test_future_perturbation_does_not_change_past_trades`: se altera el precio a partir de T; los trades que salen antes de T no cambian ni un bit (H1 + features + bitsets + kernel, delay 1). |
| Equivalencia H1/M15 sin ambigüedad | `test_h1_and_m15_execution_agree_until_an_ambiguous_bar`: con M15 continuo, la primera discrepancia siempre es una barra H1 que toca SL y TP. |
| Benchmark documentado frente a la referencia | Sección siguiente (`docs/reports/phase1_bench.json`). |

**Los tests detectan los fallos (mutación manual):** se reintrodujo el bug de `entry_delay` en el kernel y fallaron 8 tests. Se dio prioridad al TP sobre el SL y fallaron otros 8. Tras restaurar, todo en verde.

`pytest -q`: **49 passed** en ~44 s, 6 de ellos con datos reales (se saltan si falta `data/raw`). `ruff check`: limpio.

## Benchmark (medido)

Configuración:
- Máquina: 12 CPU lógicas, WSL2, Python 3.12.3, numba 0.67.0, numpy 2.5.3.
- Datos: EURUSD, 118.675 barras H1 en la ventana 2004-01-01 → 2022-12-30 (491.185 M15 en la ejecución M15).
- Estrategias aleatorias de 1 a 4 predicados AND, con la gramática de cada motor. Semilla 1. Código `b4296b556b03`.

| Motor | Modo | Estrategias/s |
|---|---|---|
| **sqxf ligero, ejecución H1** | 12 hilos | **19.051** |
| sqxf ligero, ejecución H1 | 1 hilo | 2.640 |
| **sqxf ligero, ejecución M15** | 12 hilos | **9.583** |
| sqxf ligero, ejecución M15 | 1 hilo | 1.101 |
| sqxf rico (trades completos, M15) | 1 hilo | 191 |
| referencia `FastEvaluator` (numba) | 1 proceso | 616 |
| referencia `ParallelEvaluator` | 11 procesos | 1.219 |

- Aceleración frente al mejor caso de la referencia: **15,6×** (ejecución H1) y **7,9×** (ejecución M15, más precisa).
- Por núcleo: 2.640 frente a 616 = 4,3×.
- Preparar un mercado (H1, features, 170 bitsets, arrays M15) desde la caché: 0,56 s.

Matices de la comparación:
- La referencia evalúa estrategias de su propia gramática (178 predicados, con OR) y con su semántica, que tiene los bugs 1–5.
- Su `ParallelEvaluator` serializa cada estrategia por proceso: con lotes mayores escalaría algo mejor.
- Las cifras de WSL varían ±10 % entre ejecuciones.

## Otras mediciones

**Ejecución H1 frente a M15** (2.000 estrategias aleatorias, EURUSD; `docs/reports/phase1_h1_vs_m15.json`). H1 es sistemáticamente conservador:
- mean R (M15 − H1): mediana +0,0034R por trade, p95 +0,017R.
- El número de trades no cambia.
- El drawdown es ~0,9 puntos menor con M15 (mediana).
- Solo el 0,23 % de las estrategias cambia de lado respecto a PF = 1.

Consecuencia: el kernel ligero en H1 sirve como primer filtro barato y M15 queda para los supervivientes.

**Comprobación de costes (no es selección):**
- De 20.000 estrategias aleatorias, 17.477 tienen 30 trades o más.
- Su mean R mediano es **−0,060R**, coherente con un coste de ~0,06–0,08R por trade (1,5 pips sobre un riesgo de 1–3 ATR).
- Solo el 4,5 % tiene PF > 1.
- No hay indicios de fuga ni de costes ausentes.

## Ensayos

Registro `runs/trial_ledger.jsonl`: **67.190 evaluaciones de ingeniería**, entre tests con datos reales, benchmarks y la comparación H1/M15. **0 usadas para seleccionar.** No se ha elegido ni guardado ninguna estrategia. El holdout no se ha tocado en esta fase (0 accesos).

## Decisiones (detalle en `docs/DECISIONS.md`)
- Costes como round-trip fijo en precio, restado en R. Sin swap. Triggers sobre las barras del proveedor.
- Núcleo Numba único para los kernels ligero y rico; el oráculo Python es código independiente.
- `entry_delay` es un parámetro de evaluación, no de la estrategia.
- Por defecto, en ausencia de respuesta de Jaime: festivos como `no_trade`, XAUUSD fuera, Development desde 2004, volumen ignorado.
- Tag `v0.1` según `CLAUDE.md` (`v0.1, v0.2, …`), que prevalece sobre el `vN.0` de `AUTONOMY.md`.

## Limitaciones y riesgos conocidos
1. **Sin swap/rollover.** Las estrategias de hasta 96 barras H1 cruzan noches y fines de semana. Hay que añadirlo antes de medir rentabilidad (Fase 2, etapa de costes).
2. **Coste fijo.** No modela el ensanchamiento del spread en el rollover (~00:00 EET), en la apertura del lunes ni en noticias. Mitigación prevista: estrés de costes ×1,5–2 en el embudo.
3. **Drawdown sobre la equity de trades cerrados**, sin mark-to-market intratrade. Con riesgo por trade de 0,5 % la infraestimación está acotada (~0,5 % + gaps).
4. **`max_bars` cuenta barras H1 existentes**: un trade abierto el viernes puede durar un fin de semana entero sin consumir barras.
5. **Se permite mantener posiciones durante el fin de semana y entrar en la apertura del lunes.** Es realista, pero con riesgo de gap. Queda como filtro de la Fase 6 (sesiones).
6. La ejecución M15 también resuelve las ambigüedades con "gana el SL", ahora dentro de 15 minutos. Es residual.
7. **Exposición previa del holdout durante la auditoría** (solo calidad de datos, antes de AUTONOMY.md; anotada en `DECISIONS.md`). Jaime decide si lo considera quemado.
8. `runs/` está ignorado por git: el registro de ensayos persiste en disco, pero no en el repositorio. Hay que plantear en la Fase 2 si conviene versionarlo o copiarlo.
9. El benchmark de la referencia compara motores con semánticas distintas. La cifra mide throughput, no equivalencia de resultados.

## Siguiente (Fase 2, pendiente de aprobación de Jaime)
- Generador aleatorio y genético sobre `g1`, con contador de ensayos persistente conectado a `sqxf.trials`.
- Embudo de etapas baratas a caras con umbrales preregistrados en `configs/` antes de ver resultados.
- Deflated Sharpe y PBO/CSCV.
- Swap y estrés de costes.

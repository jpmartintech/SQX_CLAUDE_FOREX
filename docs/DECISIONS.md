# DECISIONS

Formato: fecha — decisión. Alternativas. Motivo.

## 2026-09-29 — Datos
- **Dato base M15, H1 derivado** (instrucción de Jaime). Ver `docs/DATA_AUDIT.md`.
- **Decisiones pendientes de la auditoría tomadas por defecto** (Jaime no respondió; ninguna depende de resultados):
  festivos → máscara `no_trade` sin borrar datos; volumen ignorado y NaN si desbordado; XAUUSD fuera de las fases 1–5;
  Development desde 2004-01-01 EET. Jaime puede revertirlas: todas están en `configs/data.yaml`.
- **Holdout sellado = barras con hora local EET >= 2023-01-01 00:00.** El loader lee el CSV completo (necesario para el SHA256)
  pero descarta el holdout antes de devolver nada y no lo escribe en `data/derived/`. Solo `sqxf.data.holdout.load_sealed_holdout`
  lo devuelve, exige un motivo y registra cada acceso en `runs/holdout_access.jsonl`.
- **Exposición previa del holdout (anotada por transparencia):** la auditoría de calidad del 2026-09-29 (anterior a AUTONOMY.md)
  leyó el rango completo 2003–2026: recuentos, huecos y spikes, incluidos algunos de 2023–2026 (p. ej. XAU 2026).
  No se evaluó ninguna estrategia, feature ni rentabilidad. No se considera quemado, pero Jaime tiene la última palabra.
- Identidad git local del repo = autor del commit inicial (`jaime <jaime@localhost>`), porque no había identidad configurada.

## 2026-09-29 — Fase 1: evaluador
- **Costes:** round-trip = spread + 2·slippage por lado, restado del PnL en precio de cada trade (`configs/costs.yaml`).
  Los triggers SL/TP se evalúan sobre las barras del proveedor (bid). Alternativa: modelar bid/ask por separado. Descartada por ahora:
  el proveedor no da ask y el coste fijo es conservador y idéntico en Python y Numba. Sin swap/rollover (limitación documentada).
- **Unidades:** cada trade en R = (dir·(exit−entry) − coste) / (sl_atr·ATR[t]). Equity compuesta con `risk_per_trade` (0.5 %):
  `eq *= 1 + risk·R`. Drawdown en % sobre equity de trades cerrados.
- **Sharpe temporal:** retornos diarios (día de trading = fecha local EET, que cierra a las 17:00 NY) incluyendo días sin trades,
  anualizado con √260. Sustituye al Sharpe por trade × √252 de la referencia.
- **Semántica de ejecución:** señal en la barra H1 `t` (cerrada, completa, fuera de festivos, ATR válido) → entrada al open de la barra H1
  `t+1+delay` (primera M15 de esa hora). La posición no existe antes. SL/TP fijados en la entrada con el ATR de `t`.
  Si el open de una barra de ejecución ya supera el SL (o el TP), se sale a ese open (gap). SL y TP tocados en la misma barra → gana el SL.
  Salida por tiempo al close de la barra H1 `entry + max_bars − 1`. `max_bars` cuenta barras H1 existentes, no horas de reloj.
  Una posición a la vez; la siguiente señal válida puede ser la barra de salida.
  Fin de ventana: cierre forzado al close de la última barra (motivo END).
- **Un único núcleo Numba** para los kernels ligero y rico (el rico además registra trades), para que sean idénticos por construcción.
  El oráculo Python es código independiente (bool arrays, sin bitsets) y es la referencia.
- **Predicados como bitsets** `uint64[n_pred, n_words]` (bit i de la palabra w = barra 64·w+i). La máscara de barras operables va en una fila aparte.
- **Ejecución M15 o H1** con el mismo kernel: se le pasa el array de barras de ejecución y el mapa H1 → [inicio, fin) en ese array.
- **`entry_delay` es un parámetro de evaluación**, no de la estrategia (no entra en el hash).
- **Registro de evaluaciones** (`runs/trial_ledger.jsonl`, append-only). Los tests con datos reales y los benchmarks se registran como
  `used_for_selection=false`. En la Fase 1 no se ha seleccionado ninguna estrategia.
- **Tag de fase:** `v0.1` para la Fase 1 (y `v0.0` para la 0), según `CLAUDE.md` ("v0.1, v0.2, …"), que prevalece sobre el `vN.0` de AUTONOMY.md.
- **Benchmark frente a la referencia:** se importa `reference/SQX_ENGINE/src` sin escribir en él (`NUMBA_CACHE_DIR` en `runs/`, sin bytecode).
  Cada motor usa su propia gramática; se mide throughput, no equivalencia de resultados.
- **Rendimiento del kernel rico:** el cuello de botella era convertir timestamps con zona horaria a objetos (0,1 s/estrategia).
  Se precalcula `Market.ts_utc` (datetime64): de 10 a 190–240 estrategias/s.

## 2026-09-30 — Fase 2 (compacta), antes de cualquier run
- **Instrucción de Jaime (texto pegado en la conversación):** Fase 2 compacta: drawdown MTM con M15, contador versionado, umbrales
  preregistrados, genético con fitness solo en ventanas de entrenamiento, bloque 2019–2022 invisible al genético, estrés de costes ×2,
  walk-forward, Deflated Sharpe. Se toma como aprobación del inicio de la Fase 2.
- **Drawdown a mercado:** en cada barra de ejecución con la posición abierta, equity marcada al extremo adverso (low en largos, high en
  cortos) para el drawdown y al close para el pico; en la barra de salida, el extremo adverso previo (el propio precio en stops y gaps).
  Nuevo agregado `max_dd_mtm`; `max_dd` (trades cerrados) se conserva. El embudo usa `max_dd_mtm` con ejecución M15.
- **Contador versionado:** `trials/ledger.jsonl` (en git) con todo el historial de `runs/trial_ledger.jsonl`: 69.110 evaluaciones
  (67.190 del informe de Fase 1 más 4 ejecuciones posteriores de los tests con datos reales). El DSR usa el total general,
  incluidas las evaluaciones de ingeniería (N más grande = corrección más dura).
- **Periodos:** fitness 2004–2014 en 3 bloques; walk-forward de estrategias fijas en 2015, 2016, 2017 y 2018; bloque final 2019–2022.
  Alternativa descartada: walk-forward con re-optimización del genético por ventana (evalúa el procedimiento, no estrategias
  concretas; queda para la Fase 3). Limitación asumida: 2015–2018 se usa para seleccionar (etapa walk-forward), así que el DSR
  se calcula sobre 2004–2018 completo y solo 2019–2022 es realmente fuera de muestra respecto a toda la selección.
- **Fitness** = peor t-estadístico de R entre los 3 bloques (costes ×1, ejecución H1), −inf con menos de 30 trades en algún bloque.
  Premia la consistencia frente a un único periodo bueno.
- **Var[SR] del DSR:** varianza del Sharpe diario 2004–2018 de todas las estrategias evaluadas por el genético con ≥ 30 trades.
- **Un solo par (EURUSD)** en esta fase compacta; la validación en otros pares queda para la Fase 3.
- **Sin Monte Carlo ni ruido de precios** en esta versión compacta (no pedidos); pendientes para completar la Fase 2.
- **Sin swap** (sigue siendo una limitación); el estrés de costes ×2 lo cubre solo en parte.
- **Umbrales:** fijados en `configs/funnel.yaml` antes de cualquier run con datos reales. El CLI (`sqxf funnel`) se niega a correr
  si el YAML no está commiteado. Un run que ya miró el bloque final no puede repetirse con el mismo `run_name`.

## 2026-09-30 — Fase 2, después del run `phase2_eurusd_g1_r1`
- **Resultado reportado tal cual:** 0 supervivientes. No se aflojan umbrales ni se relanza con otra semilla.
- **Análisis de sensibilidad del DSR** (20.000 estrategias aleatorias, `used_for_selection=false`, contado en el contador):
  solo informativo, no cambia ningún umbral.
- **Sin merge ni tag `v0.2`:** la versión compacta no cubre todas las etapas de la Fase 2 de CLAUDE.md (plateau, Monte Carlo,
  ruido, PBO). La rama `phase-2-funnel` queda para revisión.

## 2026-09-30 — Cierre de la Fase 2 compacta (instrucción de Jaime, texto pegado)
- **Resultado del DSR de la Fase 2: 0 supervivientes** (run `phase2_eurusd_g1_r1`: 99.000 generadas → 415 tras walk-forward → 0 tras DSR).
  El bloque final 2019–2022 no se evaluó (0 accesos). Merge a `main` con tag `v0.2-compact` por instrucción de Jaime.
- **Reconciliación 168.590 frente a 189.070 ensayos** (según `trials/ledger.jsonl`):
  - 69.590 antes del run: 67.190 del informe de la Fase 1 (benchmarks 5.450 + 56.300, comparación H1/M15 4.000, 3 ejecuciones de
    tests con datos reales × 480) + 5 ejecuciones más de los tests con datos reales (5 × 480 = 2.400) antes del run.
  - +99.000 del genético = **168.590**, el total del contador cuando se calculó el DSR (el N usado).
  - +20.000 del análisis de sensibilidad del DSR (aleatorias, sin selección) + 480 de la ejecución final de `pytest` = **189.070**.
  - Las evaluaciones posteriores al cálculo del DSR no cambian el resultado; con N = 189.070 el listón sube (1,17 frente a 1,13 anual con la nula de ruido puro).

## 2026-09-30 — Fase 2b: evaluación del procedimiento (instrucción de Jaime, texto pegado), antes de cualquier run
- **Pregunta:** ¿tiene edge fuera de muestra el *procedimiento* (genético + selección), no una estrategia concreta?
- **Walk-forward con re-optimización:** para cada año OOS Y (2010–2018), el genético se entrena solo en Y−4..Y−1 (fitness = peor
  t-estadístico en 2 bloques de 2 años), la selección top-10 se hace solo en entrenamiento, y las estrategias congeladas operan Y.
  Solo se concatenan los años OOS.
- **Datos:** M15 truncado en 2019-01-01 antes de construir el mercado; 2019–2022 y el holdout no se cargan.
- **Control:** búsqueda aleatoria con el mismo presupuesto por ventana, la misma fitness, los mismos filtros y el mismo top-K.
  Sin control, un resultado positivo podría deberse a la gramática o al criterio de selección, no al genético.
- **Nulo:** 100 mercados con las barras M15 permutadas (se conserva la distribución de formas de barra y se destruye toda
  dependencia temporal). El procedimiento completo (genético y control) se repite en cada uno con las mismas semillas.
  p-valor = (1 + #nulos ≥ observado) / 101. Alternativa descartada: bootstrap por bloques (conserva estructura de corto plazo que
  podría ser el propio edge buscado). Limitación: la permutación también destruye el clustering de volatilidad, así que el nulo
  prueba "cualquier estructura temporal", no específicamente la parte explotable tras costes.
- **Estadístico primario:** mean R por trade de todos los trades OOS (costes ×1). También se reportan costes ×2, el Sharpe de la
  cartera equiponderada, su DD y los resultados por año.
- **Número efectivo de ensayos:** (a) a nivel de procedimiento: N = procedimientos evaluados en los años OOS según
  `trials/procedure_ledger.jsonl` (2 en este run: genético y control), con DSR de la cartera OOS usando Var[SR] de los nulos;
  (b) a nivel de estrategia, informativo: N_eff = ρ̄ + (1 − ρ̄)·N con ρ̄ = correlación media de retornos diarios de 300 estrategias
  por archivo del genético.
- **Presupuesto:** ~20.000 evaluaciones únicas por ventana (500 × 40 generaciones), elegido por tiempo de cómputo (~1 min por
  procedimiento completo medido sobre datos permutados, sin mirar resultados reales).
- **Evaluaciones de los nulos:** son sobre datos sintéticos (permutados), no se suman a `trials/ledger.jsonl` (que cuenta
  evaluaciones sobre datos reales); se guardan en `runs/<run>/null_shard*.jsonl` y su total se reporta.
- **Solapamiento a declarar:** el run de la Fase 2 ya usó 2004–2018 (incluidos 2015–2018 para seleccionar). Los años OOS de este
  procedimiento no son vírgenes para el investigador (gramática y forma de la fitness son las mismas que en la Fase 2),
  aunque el procedimiento no usa ninguna estrategia ni resultado de aquel run.

## 2026-09-30 — Fase 2b, después del run `phase2b_wf_eurusd_r1`
- **Veredicto reportado tal cual:** el procedimiento no demuestra edge (p = 0,109; costes ×2 negativos). No se aflojan umbrales ni se relanza.
- **Incidente:** los 4 shards del nulo fallaron al arrancar (`KeyError: 'null'`: YAML interpreta la clave `null:` como `None`) sin escribir
  ningún resultado. Fix solo en el script (`3eb92ec`), config intacto, y los shards se relanzaron con las mismas semillas.
- **Análisis post hoc** (diferencia genético − control bajo el nulo, p-valor con costes ×2, mean R sin 2012): informativos, fuera del preregistro.
- **N_eff por correlación:** hubo que regenerar los archivos del genético con las mismas semillas (180.000 evaluaciones de ingeniería,
  contadas en el contador), porque el procedimiento no los guarda.

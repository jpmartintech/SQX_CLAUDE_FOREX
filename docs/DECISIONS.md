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

## 2026-09-30 — Fase 2c: infraestructura (instrucción de Jaime vía /goal)
- Merge de `phase-2b-wf-procedure` a `main` con tag `v0.2b`.
- **pytest ya no escribe en `trials/ledger.jsonl`:** un fixture autouse redirige el contador, el log del bloque final y el del holdout
  a un directorio temporal, y `record_evaluations` lanza un error si se intenta escribir en el contador versionado bajo pytest.
  Las evaluaciones de los tests son sobre datos reales pero no seleccionan nada; las ya registradas (11 × 480) se quedan en el
  historial, que nunca se reescribe.
- **Cargador YAML estricto** (`provenance.load_yaml_strict`, usado por `load_config` y los scripts): falla si una clave no se carga
  como el texto escrito (`null:`, `yes:`, `on:`, `1:`…). Test sobre todos los `configs/*.yaml`.
- **`configs/wf_procedure.yaml`:** la clave `null:` pasa a `"null":` (entrecomillada) para cumplir el cargador estricto. Solo cambia
  el formato; todos los valores son idénticos a los preregistrados en `ccd14b0` y el run de la Fase 2b ya estaba hecho.

## 2026-09-30 — Fase 2c: preregistro (`configs/wf_6pairs.yaml`), antes de cualquier run con datos reales
- **Mismo procedimiento que la 2b sin cambios** (ventanas, genético, fitness, selección base, top-10) en los 6 pares, OOS 2010–2018,
  con reglas por par (un genético por par y ventana). Semillas: EURUSD usa las de la 2b (debe reproducir su resultado base);
  el resto, desplazamientos fijos de 1.000.
- **Una única variante preregistrada** `x2robust`: los mismos filtros de selección deben cumplirse con costes ×2 en entrenamiento
  (PF ≥ 1,10 y mean R > 0,03). Motivo: en la 2b el procedimiento perdía con costes ×2 fuera de muestra. Se aplica al mismo archivo
  generado, así que no añade evaluaciones.
- **Aceptación sobre el agregado** de los 6 pares, por variante del genético: mean R ×1 > 0, ×2 > 0, p ≤ 0,025 (Bonferroni por
  2 variantes), bate al control aleatorio con la misma variante, DSR de la cartera ≥ 0,95. El resultado por par se reporta pero no decide.
- **DSR:** N = procedimientos evaluados sobre 2010–2018 según `trials/procedure_ledger.jsonl` = 2 (2b) + 4 (este run) = 6;
  Var[SR] de las carteras del mismo procedimiento en los nulos.
- **Nulo:** permutación de días completos dentro de su mes natural, con el mismo mapeo en los 6 pares. Conserva la trayectoria
  intradía, la volatilidad realizada mensual (clustering a escala de mes) y la correlación entre pares; destruye el orden de los días
  dentro del mes. Alternativas descartadas: permutación por barras (2b), que destruye el clustering; bloques semanales, que conservan
  estructura multi-día que el grammar podría explotar (nulo con edge). Limitación: todo edge puramente intradía sobrevive en el
  nulo, así que el test es conservador para ese tipo de edge.
- **60 permutaciones** (resolución 1/61 ≈ 0,016 < 0,025), elegidas por coste: ~7 min por permutación de los 6 pares medido sobre
  datos permutados, sin mirar resultados reales.

## 2026-09-30 — Fase 2c, después del run `phase2c_wf_6pairs_r1`
- **Veredicto reportado tal cual:** ninguna variante cumple los criterios (agregado negativo con costes ×1 y ×2, p = 0,066 > 0,025,
  DSR 0,01). No se aflojan umbrales ni se relanza.
- **Hallazgo:** la variante `x2robust` no cambia ninguna selección del genético (54/54 idénticas), porque sus candidatos tienen en
  entrenamiento R medios de 0,25–0,6 muy por encima de los umbrales incluso con costes ×2. Se sigue contando como procedimiento
  en el DSR (N = 6), según el preregistro.
- **Diagnóstico post hoc** (una ventana de GBPUSD, solo datos de entrenamiento): 169 de las 200 mejores pasan ambos filtros; informativo.

## 2026-09-30 — Auditoría de datos cripto (instrucción de Jaime, texto pegado; rama `phase-c0-crypto-audit`)
- Rama creada desde `phase-2c-6pairs` (último estado, sin merge), para conservar la infraestructura y la documentación más recientes.
- **Holdout cripto fijado antes de cualquier estadístico:** los últimos 18 meses de cada moneda (BTC desde 2024-11-02, el resto desde
  2024-12-04). La auditoría lo leyó **solo para calidad**; los estadísticos de rendimiento son solo anteriores al holdout.
  Accesos en `trials/crypto_holdout_access.jsonl` (2 ejecuciones del script). Propuesta pendiente: holdout común desde 2024-11-01.
- No se ha ejecutado ninguna estrategia ni ningún backtest cripto; nada se suma a `trials/ledger.jsonl`.
- `CLAUDE.md` no se modifica: la sección cripto queda como diff propuesto en `docs/proposals/CLAUDE_md_crypto.diff`.

## 2026-09-30 — Fase C1, Parte 1 (instrucción de Jaime vía /goal)
- Merges: `phase-2c-6pairs` → `main` (tag `v0.2c`) y `phase-c0-crypto-audit` → `main` (tag `v0.c0`). Rama `phase-c1-crypto`.
- **Remoto:** no hay `origin` y `gh` no está instalado en WSL; crear el repo requiere autenticación interactiva de Jaime (ver PROGRESS).
- **CLAUDE.md:** aplicada la sección "Cripto (módulo aparte)" del diff propuesto, actualizada con las decisiones de Jaime (universo sin TRX,
  holdout común 2024-11-01, perpetuos con spot como proxy, comisión 0,05 %, reparación de LINK solo en la copia derivada).
- **Datos de perpetuos:** API pública de Binance sin claves (instrucción expresa de Jaime, excepción a AUTONOMY §3 "red externa"),
  solo < 2024-11-01; exposición accidental de 3 tasas de funding de 2026 en la prueba de conectividad, registrada.
- **Contrato del evaluador ampliado** (retrocompatible, forex bit a bit idéntico sobre 300 estrategias H1/M15 y 65.981 trades):
  `cost_rel` por barra de señal, funding con signo y `fr_abs` a ambos lados en la apertura de cada barra de ejecución posterior a la de
  entrada (conservador: una salida en la apertura de la barra del evento también paga), estrés de funding solo sobre pagos,
  `frac = min(risk_per_trade, max_lev · riesgo/entrada)`.
- **Funding antes del listado:** media de |tasa| del perpetuo de cada moneda antes del bloque de selección, en cada hora 00/08/16 UTC
  anterior al primer evento real, a largos y cortos.
- **D1:** la ejecución solo puede ser M15 (los eventos de 08/16 UTC caen dentro de la barra diaria).
- **Veredicto del proxy:** válido para retornos H4/D1 (corr ≥ 0,9988 salvo SOL 0,9945), algo optimista en stops (perp toca un 3–8 % más);
  se añade al preregistro un chequeo informativo con precios de perpetuo. Recomendación a Jaime: usar precios de perpetuo donde existan.
- **Preregistro `configs/crypto_c1.yaml`:** umbrales de aceptación PROPUESTOS por Claude, pendientes de revisión de Jaime; nada se ejecuta en la Parte 1.

## 2026-10-01 — Fase C1 Parte 2: cambios al preregistro (revisión de Jaime vía /goal), ANTES de cualquier run
`configs/crypto_c1.yaml` pasa de `crypto_c1_wf_r1` (nunca ejecutado) a **`crypto_c1_wf_r2`**. Cambios, uno por uno:
1. **Nulo:** 60 → **200** permutaciones de días UTC completos dentro de su mes (mismo mapeo en las 8 monedas). Motivo: más resolución
   del p-valor (1/201). Instrucción de Jaime.
2. **Control emparejado:** **200** réplicas con el mismo número, sentido y duración de trades (ya eran 200; se confirma).
3. **Criterio por moneda:** 3 → **4 de 5** monedas por separado con mean R ×1 > 0, **cada una con ≥ 50 trades fuera de muestra**
   (las que tengan menos cuentan como no positivas). Elegí 50 porque con σ ≈ 1R el error estándar del mean R es ~0,14R: por debajo,
   el signo de una moneda es casi ruido. Fijado sin ver resultados.
4. **Nuevo criterio:** mean R ×1 agregado > 0 en **al menos 3 de las 5 ventanas** fuera de muestra.
5. **Precios:** **perpetuo USDT-M desde la fecha de cambio de cada moneda y spot antes**. La fecha es el primer día completo
   ≥ listado + 7 días, para saltar las barras planas de la semana de listado: BTC 2019-09-16, ETH 2019-12-05, BNB 2020-02-18,
   LINK 2020-01-25, ADA 2020-02-08, SOL 2020-09-22, DOGE 2020-07-18, AVAX 2020-10-01. Todas las ventanas fuera de muestra (2021–2023)
   usan precios de perpetuo. El filtro de liquidez de $20M y las bandas de slippage siguen midiéndose con el volumen **spot**.
6. **Reparación de LINK:** solo afecta a barras de origen spot; en r2 la barra del 2020-03-12 10:45 viene del perpetuo (low 1,813, real),
   así que no se repara nada. El chequeo informativo pasa a ser reoperar las estrategias seleccionadas sobre spot sin reparar,
   que sirve a la vez de estrés de mechas y de medida del proxy.
7. **Sin cambios:** comisión 0,05 % taker con estrés ×2 en costes y funding, el resto de umbrales, semillas, ventanas, genético,
   selección y variantes (H4 principal, D1 variante), y DSR con N = 2 × 2,4.
- **Datos usados:** solo M15 < 2023-11-01 (spot y perpetuo ya descargados). No hace falta descargar nada del bloque de selección
  ni del holdout, así que no se descarga nada nuevo.
- **Evaluaciones del nulo:** son sobre precios permutados y no se suman a `trials/ledger.jsonl`; sí las del genético sobre datos reales.

## 2026-10-01 — Fase C1 Parte 2, después del run `crypto_c1_wf_r2`
- **Veredicto reportado tal cual:** ninguna variante cumple (H4 2/8 criterios, D1 3/8). No se aflojan umbrales ni se relanza.
- **Nulo parcial en el informe (44/200):** el nulo completo (~8–9 h) no cabe en el límite de turnos. Los 11 shards siguen en segundo
  plano con las semillas preregistradas y el informe se regenera con `scripts/crypto_c1.py report`. El veredicto no depende del nulo
  (fallan criterios deterministas). No es un cambio del preregistro: es el mismo nulo, aún incompleto.
- **AVAX H4 (+0,277R, t = 4,9)** revisado como posible "demasiado bueno": PF 1,52, 3 ventanas, trades solapados entre clones, datos limpios;
  sin bug. Los t por trade sobrestiman la evidencia porque las top-10 se solapan; los contrastes válidos son el nulo, el control y el DSR.

## 2026-10-01 — Cierre de C1 (instrucción de Jaime: parar el nulo "en 44 de 200")
- Al ir a detener los procesos, **el nulo ya había completado las 200 permutaciones** (200 `j` distintos, 0…199; el último shard
  terminó a las 15:12). No había nada que parar. Se regeneró el informe con el nulo completo: H4 p = 0,378 y DSR 0,074; D1 p = 0,129
  y DSR 0,242. **Veredicto sin cambios** (ninguna variante cumple). `docs/reports/phase-c1.md` actualizado; el intermedio de 44
  permutaciones se conserva en `phase-c1_run_interim.json`.
- Merge de `phase-c1-crypto` a `main` con tag `v0.c1`.

## 2026-10-01 — Fase S, Parte 1 (instrucción de Jaime vía /goal): preregistro `configs/states_ribbon.yaml`
- **Anclajes:** H1/H4/H8 en el reloj local EET/EEST alineado a las 00:00 locales (H4 00/04/08/12/16/20, H8 00/08/16), que coincide
  con el cierre de Nueva York de los brokers; D1 = día de trading FX (00:00–24:00 EET, las barras del domingo por la tarde
  pertenecen al lunes). Una barra está disponible al FINAL de su intervalo, aunque falten M15; solo las barras completas entran en el
  contexto multi-timeframe, y solo si `available_utc <=` cierre de la barra H1 base. Alternativa descartada: anclar en UTC (partiría
  la sesión respecto al cierre de NY que usan los brokers).
- **Descriptores con histéresis** fijados a priori, sin mirar datos: orden 6/2, percentil de anchura 0,80/0,65 y 0,20/0,35 sobre 500
  barras, pendiente de la EMA34 a 5 barras 0,30/0,10 ATR. Estado combinado ≤ 27: régimen (D1 y H8), pendiente H4 y orden H1.
- **Evaluador:** trailing stop en ATR (la barra solo mueve el stop para las siguientes) y salida por señal (al cierre de una barra de
  señal, salida en la apertura siguiente); con ambos apagados, forex es bit a bit idéntico (300 estrategias H1/M15, 65.981 trades).
- **Swap:** `configs/swap.yaml` con valor conservador por defecto, 1,0 pip/noche que pagan largos y cortos y triple el jueves a las
  00:00 EET. **Pendiente de verificar con el broker de Jaime.**
- **Umbrales de persistencia y de aceptación PROPUESTOS por Claude**, pendientes de revisión de Jaime. Parte 1 no lee retornos.
- **Fase descriptiva ejecutada** después del preregistro (`docs/reports/states_descriptive.md`), solo sobre el periodo de desarrollo y
  sin retornos. Criterio de sistema cumplido (4,1–4,3 cambios por 100 H1 frente a un máximo de 15). Incumplimiento por timeframe:
  EURUSD D1, duración mínima 2,64 < 3; se reporta tal cual. Quedan fijados **15 estados × 3 horizontes = 45 tests** en EURUSD
  antes de leer ningún retorno.

## 2026-10-01 — Fase S, Parte 2: registro ANTES de ejecutar (instrucción de Jaime vía /goal)
- **Preregistro intacto:** `configs/states_ribbon.yaml` en HEAD es idéntico al de `1748f2d` (`git diff` vacío).
- **Desviación conocida:** en EURUSD D1, un estado con ≥ 1 % del tiempo tiene una duración media de 2,64 barras, por debajo del
  mínimo propuesto de 3. Se acepta como desviación conocida y no se cambia ningún umbral. El criterio que detiene la fase es el de
  sistema (≤ 15 cambios por 100 H1) y se cumple (4,26 en EURUSD).
- **Swap:** se mantiene `configs/swap.yaml` conservador (1 pip/noche que pagan largos y cortos, triple el jueves), **pendiente de
  verificar con el broker**; no bloquea.
- **Tests predictivos fijados antes de leer retornos:** EURUSD, 15 estados utilizables con dirección (0, 1, 3, 4, 8, 9, 10, 16, 17,
  18, 19, 22, 23, 25, 26) × 3 horizontes (6, 24, 120 H1) = **45 pares estado-horizonte**. Holm sobre los 45. Réplica: los mismos 45
  en cada uno de los 5 pares restantes (validación, no selección).
- **Pares efectivos** (antes de evaluar ninguna estrategia): PCA de los retornos diarios logarítmicos de los cierres D1 completos de
  los 6 pares en desarrollo (2004–2014, 2.753 días comunes): autovalores 3,27 · 1,29 · 0,50 · 0,43 · 0,35 · 0,17; participation
  ratio **2,78** (`docs/reports/states_effective_pairs.json`). **N del DSR = 5 estrategias × 2,78 = 13,92.**
- **Detalles de implementación que el YAML no fija** (decididos ahora, sin ver resultados; ninguno toca un umbral):
  - Regla simétrica: las patas larga y corta se evalúan como dos subcuentas independientes con 0,5 % de riesgo cada una y se
    agrupan sus trades. En R1, R2 y R4 no pueden coincidir (los regímenes se excluyen); en R3 sí (régimen 0).
  - Espejos de las salidas: R1 corto sale si régimen ≠ −1 o pendiente H4 = +1; R2 corto sale si régimen ≠ −1.
  - Transiciones ("cambia a", "deja", "sale de"): valor en la barra H1 t distinto del de t−1, sobre los valores alineados de barras cerradas.
  - Años positivos: por año de entrada del trade. Pares positivos: mean R ×1 > 0 con ≥ 20 trades.
  - DSR: retornos diarios de la cartera equiponderada de los 6 pares (subcuentas de 0,5 % por par); Var[SR] = varianza del Sharpe
    diario de las 30 combinaciones estrategia × par, como dice el YAML.
  - p del bootstrap tal cual dice el YAML: fracción de las 10.000 medias remuestreadas ≤ 0 (semilla 20261002), con un bloque circular
    de max(5·h, 120) barras H1 sobre la serie completa de validación (todas las barras con retorno futuro disponible).
  - Retorno futuro: entrada en la apertura de la barra H1 t+1 y salida en el cierre de la barra t+h (h barras H1 existentes); se
    descarta si t+h no existe antes del 2019-01-01. Coste: 1,5 pips con el pip de cada par.
  - Control aleatorio emparejado (solo informativo; lo pide la instrucción y no es un criterio del YAML): 200 réplicas por estrategia,
    entradas aleatorias entre las barras operables de la validación, mismo número de trades, sentido, barras mantenidas y distancia de
    stop en fracción del precio, salida por tiempo, mismos costes y swap.
  - Ventana: señales en [2015-01-01, 2019-01-01) local; posiciones abiertas al final se cierran en la última barra (END).
- **Incidente en la pasada única (antes de ver ningún resultado):** la primera ejecución de `scripts/states_validate.py` se cayó al
  agregar R2, porque **R2 no genera ninguna entrada**: su condición (régimen +1, pendiente H4 +1 y orden H1 −1) no se da en ninguna
  barra de los 6 pares entre 2003 y 2018. Verificado solo con recuentos de señales, sin retornos; cuadra con la fase descriptiva, donde
  el estado combinado 24 no aparece. El script no mostró ni guardó resultados, ni escribió en el contador; solo dejó dos CSV de trades
  (CAL1 y R1) que no se abrieron y que la reejecución sobrescribe.
  **Decisión:** no se cambia la regla. R2 se evalúa tal cual (0 trades, falla el mínimo de trades) y cuenta como ensayo. El único
  cambio es de robustez del código (agregar una estrategia sin trades). La reejecución es la misma pasada: mismo config, mismas
  semillas, y el cálculo es determinista. No es una repetición con otros parámetros.

## 2026-10-01 — Fase S, Parte 2: resultado y cierre
- **Pasada única ejecutada** (`states_ribbon_s1`): test predictivo 0/45; calibración con la firma esperada (4/4) pero rentabilidad
  negativa (−0,090R, PF 0,76); R1–R4 ninguna aceptada (R2 sin trades); DSR ≤ 0,016 (N = 13,92); sin avisos de "demasiado bueno".
  Informe `docs/reports/phase-s2.md`. No se aflojan umbrales ni se lanzan búsquedas nuevas en esta fase.
- **Formato:** `results.json` serializó como texto los booleanos de numpy de los criterios predictivos; los veredictos se calcularon
  en memoria con booleanos reales. La copia `docs/reports/phase-s2_results.json` solo convierte el formato.
- **Verificación:** el p crudo idéntico del estado 0 en h = 24 y h = 120 (0,3165) se comprobó con el mismo código y semilla: los
  remuestreos coinciden solo en el 57 %; es una coincidencia.
- **Cierre:** se cumplen los criterios de la fase (pasada única preregistrada, informe con número de ensayos, tablas completas,
  criterio a criterio, años, pares, drawdown y limitaciones, y tests en verde). Un resultado negativo es válido (AUTONOMY §1),
  así que se hace merge a `main` con tag `v0.s2`.

## 2026-10-02 — Control positivo de la Fase S y descomposición de costes (instrucción de Jaime vía /goal)
- Rama `phase-s-control` desde `main`. Preregistro `configs/positive_control.yaml`, commiteado antes de ejecutar nada.
- **Mundo nulo:** días completos de desarrollo (2004–2014) barajados sin reemplazo y en el mismo orden para los 6 pares, sobre un
  calendario sintético de 7 años: 3 de calentamiento y los 4 últimos como ventana de prueba (misma longitud que 2015–2018).
- **Edge inyectado de forma causal** tras el estado 26, con tamaños netos de +2, +5, +10 y +20 pips a 24 h (bruto = neto + 1,5).
  La inyección se calcula con el estado del mundo NULO en las 24 barras previas; el test mide sobre los estados del mundo inyectado,
  que pueden diferir ligeramente, y por eso se reporta también el edge realizado.
- **Parte C:** AR(1) de los retornos H4 con φ ∈ {0,03; 0,06; 0,12} (más la referencia 0), 20 réplicas por nivel, y la misma tubería
  y aceptación que la calibración de la Parte 2, con el DSR de la Parte 2 (N = 13,92; Var[SR] = 0,00148).
- **Contador:** las evaluaciones sintéticas van a `trials/synthetic_ledger.jsonl`, nunca a `trials/ledger.jsonl`.
- **Nota de transparencia sobre la Parte 2:** el cargador (`load_m15`) devuelve todo lo anterior a 2023 y después se recortaba en
  2019-01-01. Las filas de 2019–2022 estuvieron en memoria durante esos runs, aunque ningún cálculo las usó. Para este control se usa
  un cargador que filtra al leer el parquet (`load_m15_period`) y solo materializa 2004–2014.
- **Resultado del control** (`docs/reports/positive_control.md`):
  - Parte A: CAL1, R1 y R4 pierden en bruto; solo R3 es positiva en bruto y la vuelven negativa los costes.
  - Parte B: falsos positivos 0/50; potencia 0 / 0 / 0,04 / 0,16 para +2 / +5 / +10 / +20 pips.
  - Parte C: ningún φ ≤ 0,12 hace aceptable la calibración.
  - Diagnóstico de potencia en `docs/BLOCKERS.md`, sin cambiar ningún umbral.
  - Merge de `phase-s-control` a `main` con pytest en verde.

## 2026-10-02 — Control positivo de la fábrica completa (embudo de la Fase 2) (instrucción de Jaime vía /goal)
- Rama `phase-s-funnel-control` desde `main`. Preregistro `configs/funnel_control.yaml` antes de ejecutar nada. Umbrales de
  `configs/funnel.yaml` sin cambios. md5 de `trials/ledger.jsonl` antes: `0eef3ea96eb2c809a340545fedeb0b53`.
- **Calendario:** solo hay 3.716 días completos de EURUSD en 2004–2018 frente a los 3.911 laborables del calendario de 15 años. Se usan
  los 3.716 permutados más 195 días muestreados con reemplazo, para que valgan exactamente los periodos de la Fase 2.
- **Tercera estrategia:** g1 no tiene predicados de hora ni de sesión, así que la estrategia "de sesión" pedida no existe en la
  gramática actual. Se sustituye por una de estructura y volatilidad (V) y queda anotado en `docs/BLOCKERS.md`.
- **Viabilidad comprobada solo con recuentos de trades** en un mundo de prueba (semilla 99999, fuera de las réplicas): T 1.029,
  R 1.053 y V 1.720 trades en 2004–2014.
- **Etapas:** se usan las de la Fase 2 hasta el DSR; el bloque final (2019–2022) no existe en un mundo de 15 años.

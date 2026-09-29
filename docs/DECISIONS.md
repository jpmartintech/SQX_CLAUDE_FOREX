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

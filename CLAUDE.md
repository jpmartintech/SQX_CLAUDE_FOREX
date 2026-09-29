# SQX_CLAUDE_FOREX

Motor en Python, lo más rápido y efectivo posible, para **generar estrategias rentables de forex con un motor genético, estresarlas para medir su robustez, guardarlas en una library y combinarlas con un motor de portfolio aparte** para potenciar la rentabilidad.

Dueño del proyecto: Jaime (investigador cuantitativo). Entorno: Ubuntu/WSL, Python. Idioma de trabajo: español (código, identificadores y commits en inglés).

## Cómo trabajar en este proyecto

- Tienes autonomía total dentro de `~/SQX_CLAUDE_FOREX`. Itera sin pedir permiso: escribe, ejecuta, testea, corrige y commitea hasta cumplir los criterios de cada fase.
- **Límites (no negociables):**
  - No toques nada fuera de `~/SQX_CLAUDE_FOREX`. `reference/SQX_ENGINE` es solo lectura.
  - Nada de `git push --force`, ni reescribir historia de `main`.
  - No guardes ni leas credenciales (brokers, exchanges, tokens) y no las metas en el repo.
  - No ejecutes nada que pida `sudo` sin avisar antes.
  - No borres datos en `data/` sin copia.
- **Git:** una rama por hito (`phase-1-evaluator`, ...). Commits pequeños y descriptivos. Cada commit deja los tests en verde. Al cerrar una fase: merge a `main` y tag (`v0.1`, `v0.2`, ...). Haz push al remoto cuando exista (`origin`).
- **Bucle de iteración:** planificar la fase → escribir tests primero cuando sea un bug o una regla de corrección → implementar → `pytest -q` → medir → commit. Si algo falla dos veces con el mismo enfoque, para y cambia de estrategia en lugar de insistir.
- **Preferencias de Jaime:**
  - Entrega **archivos completos reescritos**, no parches parciales.
  - `.py`, no Jupyter notebooks.
  - Gráficos con matplotlib en **tema oscuro**.
  - Respuestas directas y sin relleno.
- Mantén un `docs/PROGRESS.md` con: fase actual, decisiones tomadas, resultados medidos y siguientes pasos. Léelo al empezar cada sesión y actualízalo al terminar.

## Referencia: `reference/SQX_ENGINE`

Copia de https://github.com/jpmartintech/SQX_ENGINE (clonada en `reference/`, ignorada por git). Es la raíz de las ideas, pero **no se copia a ciegas**. Se lee, se reutiliza lo bueno y se reescribe lo que falla.

**Reutilizar (adaptando):**
- `strategy/definition.py`: estrategia portable con hash canónico (dedupe y trazabilidad).
- `grammar.py` y `features/engine.py`: gramática finita y features causales (fractales confirmados en p+d, breakouts con swings previos).
- `data/split.py`: split cronológico y auditoría del dataset (SHA256, duplicados, orden).
- `backtest/numba_core.py`: kernels Numba con regla conservadora (si SL y TP caen en la misma barra, gana el SL).
- Disciplina de procedencia: manifiesto de descubrimiento solo con Development, `TRUE_OOS` frente a `RETROSPECTIVE_SPLIT_TEST`.
- Checkpoints con fsync y renombrado atómico, y reanudación.

**No reutilizar tal cual (bugs y debilidades ya verificados):**
1. **`entry_delay` roto.** Con delay ≥ 1 la posición se abre en la barra de la señal pero el precio de entrada es el open de `i+1+delay`; las barras intermedias evalúan SL/TP contra una entrada inexistente y salen trades con `exit < entry`. Invalida `execution_stress`. Ocurre igual en Python y en Numba.
2. **Unidades del drawdown.** El PnL está en unidades de precio (~0.0005/trade) y se divide por `initial_capital=10000`, así que `max_drawdown` ~1e-5 y el gate de drawdown nunca filtra.
3. **`monte_carlo_score` fijado a 0.0**, sin Monte Carlo real.
4. **Plateau mal etiquetado:** `relative_median` usa `min_pf` como baseline, no el PF de la estrategia.
5. **Sharpe por trade × √252**, no un Sharpe temporal.
6. **Fitness genético en muestra** sobre todo Development, con el término de drawdown constante por el bug 2.
7. **Configs base sin costes** (`spread: 0`, `slippage: 0`).
8. **Se desvió a cripto/FTMO/prop firms** y acumuló ~75 scripts versionados sin contrato común. Aquí solo forex H1.
9. Tests que no cubren `entry_delay`. Los 14 tests que fallan en ese repo son por artefactos ausentes, salvo `test_crypto_portfolio_v3` (`1.02 <= 1.0`).

## Datos

- Dataset objetivo: **más de 10 años de H1 de forex** (empezar por EURUSD y ampliar a otros pares).
- Ubicación: `data/raw/` (ignorado por git). Formato: CSV/parquet con `timestamp` (UTC), `open`, `high`, `low`, `close`, `volume`.
- **Primera tarea de la primera sesión:** localizar el dataset con Jaime (ruta y pares disponibles) y auditarlo: orden, duplicados, huecos, fines de semana, NaN.
- Nunca ordenes, dedupliques ni rellenes en silencio: reporta y decide.

## Reglas de corrección (siempre)

1. **Causalidad:** una señal en la barra `t` solo usa información cerrada en `t`; la entrada es al open de `t+1` como mínimo. Con `entry_delay = d`, la posición **no existe** hasta la barra de entrada real: ni SL, ni TP, ni salida por tiempo antes de ella. Invariante testeado: `exit_idx >= entry_idx` y `bars_held >= 1`.
2. **Unidades:** el evaluador mide cada trade en **R** (múltiplos del riesgo inicial). El equity en dinero y el drawdown en **% del capital** se calculan con riesgo fraccional configurable (`risk_per_trade`, por defecto 0.5 %). El sizing real se decide en el motor de portfolio, no en el descubrimiento.
3. **Costes siempre presentes** en cualquier evaluación (spread + slippage realistas por par), incluida la de descubrimiento.
4. **Consistencia Python/Numba:** el evaluador Python es el oráculo; Numba debe dar resultados idénticos (tests de equivalencia con tolerancia estricta).
5. **Determinismo:** misma semilla y misma config, mismos resultados. Todo run guarda config, hash del dataset, versión del código y semilla.
6. **El OOS es un recurso finito.** Cada vez que se mira para decidir algo, se degrada. Registra cuántas veces se usa.

## Arquitectura objetivo

```
SQX_CLAUDE_FOREX/
  CLAUDE.md
  docs/PROGRESS.md
  pyproject.toml
  configs/                 # YAML por run (costes, splits, generador, embudo)
  data/raw/                # ignorado por git
  reference/SQX_ENGINE/    # solo lectura, ignorado por git
  src/sqxf/
    data/                  # carga, auditoría, splits, walk-forward
    features/              # features causales + caché
    strategy/              # definición portable, hash canónico
    backtest/              # kernels Numba (ligero y rico) + oráculo Python
    generators/            # random + genético (con conteo de ensayos)
    funnel/                # etapas de estrés y puntuación
    stats/                 # Deflated Sharpe, PBO/CSCV, Monte Carlo
    library/               # almacén de estrategias + PnL diario alineado
    portfolio/             # selección, pesos y validación (motor aparte)
    reports/               # informes y gráficos (tema oscuro)
    cli.py
  tests/
  scripts/
```

## Fases y criterios de aceptación

**Fase 0 — Bootstrap.** Estructura, `pyproject.toml`, entorno virtual, CI local (`pytest`), lint. *Hecho cuando:* `pytest -q` corre y `sqxf --help` funciona.

**Fase 1 — Evaluador correcto y rápido.**
- Reescribir el backtest con trades en R, equity con riesgo fraccional y drawdown en %.
- Arreglar `entry_delay` (la posición no existe hasta la entrada real).
- Kernel ligero (solo métricas del embudo) y kernel rico (trades/equity) solo para supervivientes; `prange` sobre lotes de estrategias; predicados como bitsets.
- Tests: causalidad (`exit_idx >= entry_idx`), equivalencia Python/Numba, casos dorados de SL/TP en la misma barra, unidades del drawdown.
- *Hecho cuando:* tests en verde y un benchmark documentado (estrategias/segundo) frente al de referencia.

**Fase 2 — Generador y embudo con estadística honesta.**
- Random + genético sobre la gramática, con **conteo de ensayos** persistente.
- Embudo por etapas baratas → caras: básico, estabilidad, plateau **realmente relativo**, costes, ejecución (ya corregida), Monte Carlo (remuestreo/orden de trades), ruido en precios.
- Deflated Sharpe y/o PBO/CSCV usando el número de ensayos.
- *Hecho cuando:* un run de prueba reporta cuántas estrategias probó, cuántas pasan cada etapa y cuántas sobreviven tras la corrección por ensayos.

**Fase 3 — Validación walk-forward.**
- Ventanas deslizantes (p. ej. entrenar 4 años / probar 1) en lugar de un único OOS.
- Criterio de supervivencia: rendimiento aceptable en la mayoría de ventanas, no en una.
- Validación cruzada en otros pares (GBPUSD, USDJPY, ...) como test de sobreajuste.
- *Hecho cuando:* cada estrategia candidata tiene su perfil por ventana y por par.

**Fase 4 — Library.**
- SQLite/parquet con la definición, hash, métricas por etapa y **PnL diario alineado por fecha** de cada estrategia (in-sample y walk-forward).
- *Hecho cuando:* el motor de portfolio puede reconstruir cualquier combinación sin volver a simular.

**Fase 5 — Motor de portfolio (independiente del generador).**
- Filtro de clones, clustering por correlación, pesos por riesgo (risk parity / HRP), límites de drawdown objetivo y sizing por estrategia.
- **Selección en un periodo, medición en otro posterior.** Nunca reportar como resultado un portfolio medido en el mismo periodo con el que se eligió.
- *Hecho cuando:* informe con retorno, drawdown, Calmar, correlaciones y comparación frente a la mejor estrategia individual y frente a un portfolio aleatorio.

**Fase 6 — Ampliar el espacio de búsqueda** (solo cuando 1–5 estén sólidas): sesión y hora del día, multi-timeframe con barras cerradas, geometría de salida (trailing, breakeven, salida por señal, entradas límite), filtros de régimen, fuerza de divisas multi-par. Cada ampliación multiplica los ensayos y debe pasar por el conteo de la Fase 2.

**Fase 7 (opcional) — Puente a MetaTrader 5/MQL5** para las estrategias del portfolio final.

## Honestidad de resultados

- Las métricas históricas son salidas de ingeniería, no evidencia de edge. Toda cifra de rentabilidad se acompaña de drawdown, número de ensayos y resultado fuera de muestra.
- Si un resultado parece demasiado bueno, busca primero un bug (fuga de información, costes ausentes, unidades) antes de celebrarlo.
- Reporta lo negativo con la misma claridad: si el embudo corregido no deja supervivientes, dilo y propón cómo ampliar o cambiar el espacio de búsqueda.

## Al terminar cada sesión

1. Tests en verde y commit hecho.
2. `docs/PROGRESS.md` actualizado (qué se hizo, qué se midió, qué sigue).
3. Resumen breve a Jaime: lo conseguido, lo que falló y la siguiente fase.

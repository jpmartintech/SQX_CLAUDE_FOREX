# PROGRESS

## Fase actual
**Fase 1 cerrada (tag `v0.1`, 2026-09-29).** Esperando revisión de Jaime antes de empezar la Fase 2 (AUTONOMY.md §7).

## Hecho
- Fase 0 (`v0.0`): auditoría M15 (`docs/DATA_AUDIT.md`), `pyproject.toml`, `.venv`, pytest, ruff, `sqxf --help`.
- Fase 1 (`v0.1`): loader M15 canónico con holdout sellado, H1 derivado, 77 features causales, gramática `g1` (170 predicados),
  bitsets, oráculo Python, kernels Numba ligero/rico con ejecución H1 o M15, registro de evaluaciones, `sqxf build-data`.
  Informe: `docs/reports/phase-1.md`.

## Resultados medidos (Fase 1)
- `pytest -q`: 49 passed (~44 s). Trades del oráculo == Numba exactamente (sintético y EURUSD real 2004–2022).
- Benchmark EURUSD H1 (118.675 barras): ligero H1 19.051 estrategias/s (12 hilos), ligero M15 9.583/s, rico M15 191/s;
  referencia 616/s (1 proceso) y 1.219/s (11 procesos) → 15,6× / 7,9×.
- H1 frente a M15: H1 es conservador (+0,0034R/trade de mediana a favor de M15); el lado de PF = 1 cambia en el 0,23 % de las estrategias.
- Estrategias aleatorias tras costes: mean R mediano −0,060R, 4,5 % con PF > 1 (coherente con los costes).
- Registro: 67.190 evaluaciones de ingeniería, 0 de selección. Holdout: 0 accesos.

## Pendiente de decisión (Jaime)
1. Revisar los valores por defecto tomados en la auditoría (festivos `no_trade`, volumen, XAUUSD fuera, Development desde 2004).
2. Si la exposición del holdout durante la auditoría de calidad lo deja quemado (ver `DECISIONS.md`).
3. Costes por par de `configs/costs.yaml` (fijados sin mirar resultados; conviene validarlos con spreads reales del broker).
4. Aprobar el inicio de la Fase 2.

## Siguientes pasos (Fase 2, no iniciada)
- Swap/rollover y estrés de costes.
- Generador aleatorio y genético con contador de ensayos conectado a `sqxf.trials`; umbrales del embudo preregistrados en `configs/`.
- Deflated Sharpe, PBO/CSCV y Monte Carlo real.

# PROGRESS

## Fase actual
**Fase 2 compacta hecha (rama `phase-2-funnel`, sin merge ni tag).** Resultado: 0 supervivientes. Esperando revisión de Jaime.
Informe: `docs/reports/phase-2.md`.

## Hecho
- Fase 0 (`v0.0`) y Fase 1 (`v0.1`): ver `docs/reports/phase-1.md`.
- Fase 2 compacta: drawdown a mercado con M15, contador versionado `trials/ledger.jsonl`, `configs/funnel.yaml` preregistrado,
  genético con fitness solo en 2004–2014, embudo (básico, estabilidad, costes x2, retraso 1 barra, walk-forward 2015–2018,
  DSR, bloque final 2019–2022), Deflated Sharpe, `sqxf funnel`.

## Resultados medidos (run `phase2_eurusd_g1_r1`)
- 99.000 → básico 20.159 → estabilidad 16.985 → costes x2 16.568 → retraso 16.433 → walk-forward 415 → DSR 0 → final 0.
- Mejor candidata: Sharpe anual 1,12 (2004–2018) frente a SR* 2,24 (N = 168.590). DSR ≈ 0. Robusto al supuesto de Var[SR].
- Contador: 189.070 evaluaciones (99.000 de selección). Bloque final: 0 accesos. Holdout: 0 accesos.
- `pytest -q`: 59 passed.

## Pendiente de decisión (Jaime)
1. Cómo seguir tras el resultado negativo (propuestas en el informe: multi-par, gramática reducida, portfolio, WF con re-optimización).
2. Completar las etapas pendientes de la Fase 2 (plateau, Monte Carlo, ruido, PBO) y el swap antes de cerrar `v0.2`.
3. Decisiones pendientes anteriores: valores por defecto de datos, exposición del holdout en la auditoría, costes por par.

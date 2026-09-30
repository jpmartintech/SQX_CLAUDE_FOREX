# PROGRESS

## Fase actual
**Fase 2b hecha (rama `phase-2b-wf-procedure`, sin merge).** El procedimiento no demuestra edge. Esperando revisión de Jaime.
Informes: `docs/reports/phase-2.md` (tag `v0.2-compact`), `docs/reports/phase-2b.md`.

## Resultados medidos
- Fase 2 (`phase2_eurusd_g1_r1`): 99.000 → walk-forward 415 → DSR 0 supervivientes.
- Fase 2b (`phase2b_wf_eurusd_r1`), walk-forward con re-optimización 2010–2018, EURUSD:
  - genético: mean R OOS +0,0294 (×1), −0,0092 (×2), p = 0,109 frente a 100 nulos permutados; 3.089 trades; 5/9 años positivos.
  - control aleatorio: −0,0396 (×1), p = 0,495. Diferencia genético − control p = 0,129 (post hoc).
  - Veredicto preregistrado: sin edge (falla costes ×2 y p-valor).
- Contador: 729.070 evaluaciones sobre datos reales (459.000 de selección). Procedimientos evaluados en OOS: 2.
- 2019–2022: 0 accesos. Holdout: 0 accesos. `pytest -q`: 65 passed.

## Pendiente de decisión (Jaime)
1. Siguiente paso (propuestas en `phase-2b.md`): multi-par, gramática reducida, selección más estricta, completar el embudo + swap.
2. Merge de `phase-2b-wf-procedure` a `main`.
3. Decisiones anteriores aún abiertas: valores por defecto de datos, exposición del holdout en la auditoría, costes por par.

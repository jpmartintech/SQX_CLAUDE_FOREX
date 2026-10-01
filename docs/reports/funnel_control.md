# Control positivo de la fábrica completa (embudo de la Fase 2) con estrategias plantadas de edge conocido

Fecha: 2026-10-02. Rama `phase-s-funnel-control`.
- **Preregistro:** `configs/funnel_control.yaml` (`237174e`, antes de ejecutar nada). Umbrales de `configs/funnel.yaml` sin cambios.
- **Scripts:** `scripts/funnel_control.py` (calibración, A, B, C, informe) y `scripts/funnel_control_sensitivity.py` (post hoc, informativo).
- **Resultados:** `docs/reports/funnel_control_results.json`; réplicas en `runs/funnel_control_s1/`. Figura en `docs/reports/figures/fc_survival_and_killers.png`.
- **Reglas:** no se ha cargado nada de 2019 en adelante ni del holdout (cargador que filtra al leer: EURUSD 2004–2018). Evaluaciones sintéticas solo en `trials/synthetic_ledger.jsonl`. `trials/ledger.jsonl` sin cambios (md5 `0eef3ea9…` antes y después). Ningún umbral modificado y nada real reejecutado.

## Resumen
- **El embudo no deja pasar ninguna estrategia plantada:** 0 % de supervivencia en todos los tamaños (Sharpe objetivo 0,3 / 0,6 / 1,0 / 1,5; realizado en las réplicas ≈ 0,26–1,16), para tendencia (T) y reversión (R), en 10 réplicas por combinación.
- **Falsos positivos en el mundo nulo:** 0/10.
- **Qué mata:**
  - la **etapa básica** a los edges pequeños (Sharpe ≤ 0,6);
  - el **Deflated Sharpe** a todos los que llegan al final. El walk-forward deja pasar el 50–70 % de los edges mayores; el DSR, ninguno.
- **El listón del DSR** (N = 168.590; Var[SR] del pool) equivale a un Sharpe anual de **≈ 2,6** sostenido durante 15 años. Con el N efectivo por clustering (≈ 66.000) apenas baja y el DSR de las plantadas sigue ≈ 0.
- **Un Sharpe neto de 0,6–1,0** (rango realista de una estrategia aprovechable) **no habría sobrevivido.**
- **Interpretación:** los 0 supervivientes de la Fase 2 no son evidencia de que no haya edges aprovechables; el embudo no puede dejarlos pasar.
- **Dos desviaciones del diseño pedido, documentadas:**
  1. No existe estrategia de sesión en g1; se sustituyó por una de estructura y volatilidad (V), que además **no se pudo calibrar** con la regla de deriva y quedó excluida.
  2. La deriva plantada se convierte en una tendencia de todo el mercado (ver *Limitaciones*).

## Estrategias plantadas y calibración

Calibración por bisección en un mundo dedicado (semilla 69999), objetivo ±0,05. La deriva se mide en pips por barra H1 y se aplica durante las `max_bars` barras posteriores a cada señal nula.

| estrategia | definición | objetivo | δ (pips/H1) | Sharpe de calibración | R/trade | trades 2004–2018 |
|---|---|---:|---:|---:|---:|---:|
| T_trend | LARGO · ema_pair 20/100 > 0 y breakout_high.20 > 0 · SL 2 / TP 3 ATR / 48 barras | 0.3 | 0.1953 | 0.294 | +0.035 | 1553 |
| T_trend | LARGO · ema_pair 20/100 > 0 y breakout_high.20 > 0 · SL 2 / TP 3 ATR / 48 barras | 0.6 | 0.2441 | 0.623 | +0.075 | 1573 |
| T_trend | LARGO · ema_pair 20/100 > 0 y breakout_high.20 > 0 · SL 2 / TP 3 ATR / 48 barras | 1.0 | 0.3125 | 0.969 | +0.116 | 1617 |
| T_trend | LARGO · ema_pair 20/100 > 0 y breakout_high.20 > 0 · SL 2 / TP 3 ATR / 48 barras | 1.5 | 0.4688 | 1.491 | +0.176 | 1730 |
| R_reversion | LARGO · RSI14 < 30 y bb_lower.20.2 < 0 · SL 1,5 / TP 1,5 ATR / 24 barras | 0.3 | 0.5469 | 0.260 | +0.028 | 1248 |
| R_reversion | LARGO · RSI14 < 30 y bb_lower.20.2 < 0 · SL 1,5 / TP 1,5 ATR / 24 barras | 0.6 | 0.7031 | 0.643 | +0.070 | 1211 |
| R_reversion | LARGO · RSI14 < 30 y bb_lower.20.2 < 0 · SL 1,5 / TP 1,5 ATR / 24 barras | 1.0 | 0.8984 | 0.999 | +0.112 | 1151 |
| R_reversion | LARGO · RSI14 < 30 y bb_lower.20.2 < 0 · SL 1,5 / TP 1,5 ATR / 24 barras | 1.5 | 1.0938 | 1.454 | +0.165 | 1110 |

**V (estructura/volatilidad, CORTO · break_low.3 < 0 y atr_regime.14.50 > 0):** no calibrable. Su Sharpe frente a la deriva sube de −0,44 a un máximo de +0,05 (δ = 0,3) y vuelve a caer: la deriva bajista acumulada hunde el precio (de 1,19 a 0,16) y el coste fijo en pips se dispara en R. Excluida de A, B y C, sin cambiar la regla.

**Incidentes de la calibración:** dos ajustes de robustez, anotados en `DECISIONS.md`, para tratar como "deriva demasiado fuerte" los mundos cuyo precio colapsa o explota. La calibración final de T y R es idéntica bit a bit a la primera.

## Parte A — Embudo de la Fase 2 sobre un pool de 20.000 estrategias aleatorias de g1 más la plantada

Mismas etapas, umbrales y ventanas que la Fase 2 (básico y estabilidad en 2004–2014; costes ×2; retraso de 1 barra; walk-forward 2015–2018; DSR con N = 168.590 y Var[SR] del pool). 10 réplicas (semillas 61000–61009). El mismo pool (semilla 51000) en todas.

**Mundo nulo (sin plantar):** tasa de falsos positivos **0.00** (supervivientes medios 0.0). Recuento medio por etapa: generated 20000.0 → basic 36.3 → stability 19.6 → cost_stress 18.6 → execution_stress 15.2 → walk_forward 1.1 → deflated_sharpe 0.0.

| estrategia | Sharpe objetivo | Sharpe realizado (media ± sd) | R/trade | trades | basic | stability | cost_stress | execution_stress | walk_forward | deflated_sharpe | **embudo completo** | etapa que la mata | DSR mediano (si llega) |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| T_trend | 0.3 | 0.26 ± 0.23 | +0.031 | 1529 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | **0.0** | basic 10 | — |
| T_trend | 0.6 | 0.42 ± 0.20 | +0.050 | 1557 | 0.1 | 0.1 | 0.1 | 0.1 | 0.0 | 0.0 | **0.0** | basic 9, walk_forward 1 | — |
| T_trend | 1.0 | 0.63 ± 0.20 | +0.075 | 1597 | 0.3 | 0.3 | 0.3 | 0.3 | 0.1 | 0.0 | **0.0** | basic 7, walk_forward 2, deflated_sharpe 1 | 0.000 |
| T_trend | 1.5 | 1.03 ± 0.22 | +0.120 | 1685 | 0.9 | 0.8 | 0.8 | 0.8 | 0.7 | 0.0 | **0.0** | deflated_sharpe 7, stability 1, basic 1, walk_forward 1 | 0.000 |
| R_reversion | 0.3 | 0.26 ± 0.19 | +0.027 | 1276 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | **0.0** | basic 10 | — |
| R_reversion | 0.6 | 0.51 ± 0.20 | +0.055 | 1240 | 0.2 | 0.2 | 0.2 | 0.2 | 0.1 | 0.0 | **0.0** | basic 8, walk_forward 1, deflated_sharpe 1 | 0.000 |
| R_reversion | 1.0 | 0.87 ± 0.21 | +0.094 | 1198 | 0.7 | 0.6 | 0.6 | 0.6 | 0.5 | 0.0 | **0.0** | deflated_sharpe 5, basic 3, stability 1, walk_forward 1 | 0.000 |
| R_reversion | 1.5 | 1.16 ± 0.25 | +0.128 | 1156 | 1.0 | 0.8 | 0.8 | 0.8 | 0.6 | 0.0 | **0.0** | deflated_sharpe 6, stability 2, walk_forward 2 | 0.000 |

**Etapa que elimina a la plantada** (80 casos): basic 48, deflated_sharpe 20, walk_forward 8, stability 4.
- Con Sharpe ≤ 0,6 domina la etapa básica: mean R ≥ 0,05R y PF ≥ 1,15 en 2004–2014, con un edge de +0,03 a +0,05R por trade.
- Con los edges mayores, la etapa que más mata es el DSR. El walk-forward de 4 años quita otro 10–20 %.
- **Edge mínimo con supervivencia ≥ 80 %:** ninguno de los tamaños probados (máximo realizado ≈ 1,16).

## Parte B — Genético sobre mundos plantados (tamaños 1,0 y 1,5; réplicas 0–2)

Genético de la Fase 2 (100.000 evaluaciones; fitness solo en los 3 bloques de entrenamiento). Su archivo pasa por el mismo embudo. "Equivalente" = mismo hash canónico o correlación diaria > 0,8 con la plantada, entre las 500 mejores por fitness y los supervivientes.

| estrategia | tamaño | réplica | hash de la plantada en el archivo | correlación máx. (top 500) | equivalentes | básico | walk-forward | DSR (supervivientes) |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| R_reversion | 1.0 | 0 | no | 0.21 | 0 | 65100 | 63262 | 0 |
| R_reversion | 1.0 | 1 | no | 0.38 | 0 | 55229 | 50324 | 0 |
| R_reversion | 1.0 | 2 | no | 0.39 | 0 | 45730 | 42531 | 0 |
| R_reversion | 1.5 | 0 | no | 0.29 | 0 | 74445 | 73054 | 0 |
| R_reversion | 1.5 | 1 | no | 0.43 | 0 | 67222 | 64937 | 0 |
| R_reversion | 1.5 | 2 | no | 0.47 | 0 | 57618 | 55607 | 0 |
| T_trend | 1.0 | 0 | no | 0.56 | 0 | 50981 | 47097 | 0 |
| T_trend | 1.0 | 1 | no | 0.47 | 0 | 25242 | 16083 | 0 |
| T_trend | 1.0 | 2 | sí | 0.42 | 0 | 45815 | 19508 | 0 |
| T_trend | 1.5 | 0 | no | 0.61 | 0 | 70521 | 68765 | 0 |
| T_trend | 1.5 | 1 | no | 0.54 | 0 | 57733 | 51858 | 0 |
| T_trend | 1.5 | 2 | no | 0.47 | 0 | 61701 | 54144 | 0 |

- El genético **no encuentra** la plantada ni un equivalente (correlación > 0,8) entre sus 500 mejores en ninguna de las 12 ejecuciones (hash exacto en 1/12; correlación máxima 0,21–0,61).
- En los mundos plantados, **entre 16.000 y 73.000 estrategias superan el walk-forward:** la deriva plantada es en la práctica una tendencia de todo el mercado (ver la sensibilidad). Aun así, **0 sobreviven al DSR**.

## Parte C — Número efectivo de ensayos por clustering (informativo)

2.000 estrategias del pool con ≥ 30 trades (réplica 0, mundo nulo), retornos diarios 2004–2018, clustering de enlace medio con distancia 1 − ρ y corte en 0,5:
- **785 grupos**, de donde N_eff = 168.590 × 785/2.000 = **66,172**;
- |ρ| medio = 0.20.

| estrategia | Sharpe | DSR con N = 168.590 | DSR con N_eff |
|---|---:|---:|---:|
| plantada T_trend|1.0 | 0.35 | 0 | 0 |
| plantada R_reversion|1.0 | 0.70 | 0 | 9.44e-16 |
| mejor del pool nulo #1 | 0.69 | 0 | 0 |
| mejor del pool nulo #2 | 0.68 | 0 | 0 |
| mejor del pool nulo #3 | 0.64 | 0 | 0 |
| mejor del pool nulo #4 | 0.63 | 5.85e-13 | 1.04e-11 |
| mejor del pool nulo #5 | 0.63 | 0 | 0 |

Con N_eff el listón apenas baja, porque SR\* crece con √(2 ln N) y pasar de 168.590 a 66.000 casi no cambia ese valor. El factor dominante es Var[SR].

## Sensibilidad post hoc (informativa; no cambia nada)

| combinación | precio fin/inicio (nulo 0,91) | Sharpe plantada | % del pool con Sharpe mayor | % del pool con Sharpe > 0 | Var[SR] mundo plantado | Var[SR] mundo nulo | DSR (Var plantado) | DSR (Var nulo) | SR\* anual (Var nulo) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R_reversion|0.3 | 2.51 | 0.26 | 10.7% | 22.2% | 0.0014 | 0.0013 | 0.000 | 0.000 | 2.64 |
| R_reversion|0.6 | 3.37 | 0.51 | 8.1% | 28.2% | 0.0018 | 0.0013 | 0.000 | 0.000 | 2.64 |
| R_reversion|1.0 | 4.88 | 0.87 | 5.8% | 33.7% | 0.0026 | 0.0013 | 0.000 | 0.000 | 2.64 |
| R_reversion|1.5 | 7.07 | 1.16 | 5.9% | 37.7% | 0.0036 | 0.0013 | 0.000 | 0.000 | 2.64 |
| T_trend|0.3 | 1.90 | 0.26 | 6.9% | 15.7% | 0.0011 | 0.0013 | 0.000 | 0.000 | 2.64 |
| T_trend|0.6 | 2.29 | 0.42 | 4.1% | 20.3% | 0.0013 | 0.0013 | 0.000 | 0.000 | 2.64 |
| T_trend|1.0 | 2.97 | 0.63 | 2.9% | 26.7% | 0.0016 | 0.0013 | 0.000 | 0.000 | 2.64 |
| T_trend|1.5 | 5.43 | 1.03 | 3.2% | 37.0% | 0.0026 | 0.0013 | 0.000 | 0.000 | 2.64 |

- La deriva plantada sube el precio del mundo entre 1,9 y 7,1 veces y beneficia también a muchas estrategias del pool; entre el 3 % y el 11 % tienen un Sharpe mayor que la plantada.
- **La conclusión no depende de esa confusión:** con la Var[SR] del mundo NULO, SR\* = 2,64 anual y el DSR de la plantada es 0,00 en todos los tamaños.

## Lectura
1. **Supervivencia por tamaño:** 0 % en todos (T y R; Sharpe realizado 0,26–1,16). No hay un tamaño de edge, dentro de lo probado, con supervivencia ≥ 80 %.
2. **Falsos positivos:** 0 de 10 en el mundo nulo; el embudo es muy conservador.
3. **Qué mata más edges reales:**
   - **la etapa básica** con edges pequeños (mean R ≥ 0,05R y PF ≥ 1,15 están al nivel del propio edge);
   - **el Deflated Sharpe** con edges grandes. El walk-forward de 4 años elimina una parte menor (10–20 %). El DSR por sí solo bastaría para eliminarlos a todos.
4. **Un Sharpe neto de 0,6–1,0 NO habría sobrevivido.** Ni siquiera Sharpe ≈ 1,0–1,2 sostenido durante 15 años lo consigue: el listón del DSR (≈ 2,6 anual) está por encima de lo que es realista en FX.
5. **Implicación para la Fase 2:** sus 0 supervivientes no prueban que no hubiera edges aprovechables en la gramática; con N = 168.590 y la Var[SR] del pool aleatorio, el embudo no deja pasar edges de ese tamaño. Diagnóstico en `docs/BLOCKERS.md`. No se propone cambiar umbrales.

## Limitaciones
- **No hay estrategia de sesión** (g1 no tiene predicados temporales), y **V no se pudo calibrar**: el control se apoya en 2 estrategias (tendencia y reversión), ambas largas.
- **La deriva plantada no es un edge localizado:** al activarse tras cada señal durante `max_bars` barras (T y R activas en una fracción grande del tiempo), crea una tendencia global que también beneficia al pool y al genético. Un edge real y estrecho sería más difícil de imitar por el pool, pero el DSR lo eliminaría igual (sensibilidad con la Var[SR] nula).
- **El Sharpe realizado en las réplicas es menor que el calibrado** (p. ej., 1,5 → 1,03–1,16): la calibración se hizo en un único mundo.
- **10 réplicas por combinación;** la Parte B se hizo en un subconjunto (2 tamaños × 3 réplicas) por cómputo.
- **El mundo sintético** baraja días de 2004–2018 (incluye 195 días repetidos): sin dependencia entre días ni regímenes de volatilidad largos.
- **N_eff por clustering:** corte en 0,5 y escalado lineal de una muestra de 2.000 (aproximación).

# Control positivo del embudo de la Fase S y descomposición de costes de la Parte 2

Fecha: 2026-10-02. Rama `phase-s-control`.
- **Preregistro:** `configs/positive_control.yaml` (`bc8da75`), commiteado antes de ejecutar nada.
- **Scripts:** `scripts/control_part_a.py`, `scripts/positive_control.py`.
- **Resultados:** `docs/reports/positive_control_part_a.json` y `docs/reports/positive_control_results.json`; réplicas en `runs/positive_control_s1/`.
- **Figuras:** `docs/reports/figures/pc_part_a_decomposition.png` y `pc_power_and_momentum.png`.
- **Reglas cumplidas:**
  - No se ha cargado nada de 2019 en adelante ni del holdout. Las Partes B y C solo materializan M15 de 2004–2014, con un filtro en la lectura del parquet.
  - La Parte A solo lee los trades guardados y los timestamps M15 hasta el 2019-01-01.
  - Los resultados y umbrales de la Parte 2 no se han tocado, y no se ha reejecutado nada de la Parte 2.
  - Las evaluaciones sintéticas están en `trials/synthetic_ledger.jsonl` (70 entradas); `trials/ledger.jsonl` no ha cambiado (mismo md5 antes y después).

## Resumen
- **A.** El swap conservador no explica la pérdida de la Parte 2. CAL1, R1 y R4 ya pierden **en bruto**, antes de costes. R3 es la única positiva en bruto (+0,038R) y los costes (−0,065R) la vuelven negativa.
- **B. Test predictivo:**
  - 0 % de falsos positivos en el mundo nulo (0/50).
  - **Potencia muy baja:** 0 % con +2 y +5 pips, 4 % con +10 pips y 16 % con +20 pips netos a 24 h.
  - El efecto mínimo detectable con 80 % de potencia queda por encima de +20 pips; por extrapolación rondaría los 33 pips.
  - El nulo de la Parte 2 **no descarta** edges condicionales de hasta al menos +20 pips a 24 h por estado. Diagnóstico en `docs/BLOCKERS.md`.
- **C. Estrategias:** la tubería de la calibración responde de forma monótona a la persistencia H4 (de −0,046R a −0,023R), pero **ningún nivel preregistrado** (φ ≤ 0,12) la hace rentable ni aceptable (0/20 en todos).
- **La tubería no está ciega por un bug:** Python y Numba son idénticos (224 trades), y perturbar el futuro no cambia ni los estados ni los 149 trades anteriores.

## Parte A — Descomposición de los trades de la Parte 2 (sin reevaluar)

R bruto = dirección · (salida − entrada) / riesgo. Coste = round-trip de `configs/costs.yaml` / riesgo. Swap = columna `funding` / riesgo (1 pip/noche, jueves ×3). Bruto − coste + swap reconstruye el R guardado (error máximo < 3e-13).

| estrategia | par | trades | R bruto | tras costes | tras swap | coste R | swap R | swap pips/trade | noches cobradas/trade | rollovers/trade |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CAL1 | ALL | 1252 | -0.035 | -0.054 | -0.090 | 0.019 | -0.036 | 3.93 | 3.93 | 3.33 |
| CAL1 | EURUSD | 222 | +0.019 | +0.005 | -0.029 | 0.015 | -0.034 | 3.64 | 3.64 | 3.05 |
| CAL1 | GBPUSD | 221 | -0.074 | -0.089 | -0.116 | 0.015 | -0.027 | 4.05 | 4.05 | 3.41 |
| CAL1 | NZDUSD | 178 | +0.052 | +0.025 | -0.026 | 0.027 | -0.051 | 4.69 | 4.69 | 3.97 |
| CAL1 | USDCAD | 226 | +0.001 | -0.019 | -0.050 | 0.020 | -0.032 | 3.85 | 3.85 | 3.26 |
| CAL1 | USDCHF | 212 | -0.131 | -0.155 | -0.195 | 0.024 | -0.040 | 3.66 | 3.66 | 3.12 |
| CAL1 | USDJPY | 193 | -0.068 | -0.084 | -0.118 | 0.016 | -0.034 | 3.83 | 3.83 | 3.26 |
| R1 | ALL | 130 | -0.198 | -0.243 | -0.343 | 0.044 | -0.101 | 4.97 | 4.97 | 4.11 |
| R1 | EURUSD | 18 | -0.293 | -0.327 | -0.420 | 0.033 | -0.094 | 4.89 | 4.89 | 4.00 |
| R1 | GBPUSD | 27 | -0.623 | -0.655 | -0.711 | 0.032 | -0.056 | 4.07 | 4.07 | 3.44 |
| R1 | NZDUSD | 21 | -0.400 | -0.460 | -0.570 | 0.060 | -0.110 | 4.52 | 4.52 | 3.86 |
| R1 | USDCAD | 22 | +0.589 | +0.546 | +0.433 | 0.043 | -0.113 | 6.91 | 6.91 | 5.73 |
| R1 | USDCHF | 21 | -0.218 | -0.274 | -0.373 | 0.056 | -0.099 | 3.76 | 3.76 | 3.10 |
| R1 | USDJPY | 21 | -0.175 | -0.218 | -0.361 | 0.043 | -0.143 | 5.81 | 5.81 | 4.62 |
| R3 | ALL | 221 | +0.038 | -0.027 | -0.049 | 0.065 | -0.022 | 0.83 | 0.83 | 0.77 |
| R3 | EURUSD | 42 | +0.264 | +0.216 | +0.197 | 0.047 | -0.020 | 0.81 | 0.81 | 0.88 |
| R3 | GBPUSD | 26 | +0.106 | +0.056 | +0.038 | 0.050 | -0.017 | 0.96 | 0.96 | 0.88 |
| R3 | NZDUSD | 40 | +0.138 | +0.053 | +0.022 | 0.086 | -0.030 | 0.90 | 0.90 | 0.80 |
| R3 | USDCAD | 38 | +0.043 | -0.028 | -0.053 | 0.071 | -0.025 | 0.92 | 0.92 | 0.76 |
| R3 | USDCHF | 28 | -0.439 | -0.512 | -0.530 | 0.073 | -0.018 | 0.61 | 0.61 | 0.57 |
| R3 | USDJPY | 47 | -0.008 | -0.067 | -0.088 | 0.059 | -0.021 | 0.77 | 0.77 | 0.72 |
| R4 | ALL | 180 | -0.148 | -0.164 | -0.249 | 0.016 | -0.085 | 10.93 | 10.93 | 9.11 |
| R4 | EURUSD | 34 | -0.333 | -0.344 | -0.427 | 0.012 | -0.083 | 10.53 | 10.53 | 8.44 |
| R4 | GBPUSD | 27 | +0.563 | +0.550 | +0.462 | 0.012 | -0.088 | 13.70 | 13.70 | 11.56 |
| R4 | NZDUSD | 31 | -0.344 | -0.366 | -0.467 | 0.022 | -0.101 | 10.06 | 10.06 | 8.48 |
| R4 | USDCAD | 27 | -0.084 | -0.100 | -0.177 | 0.016 | -0.077 | 11.19 | 11.19 | 9.19 |
| R4 | USDCHF | 29 | -0.300 | -0.320 | -0.408 | 0.020 | -0.089 | 10.52 | 10.52 | 8.76 |
| R4 | USDJPY | 32 | -0.279 | -0.294 | -0.367 | 0.015 | -0.073 | 10.00 | 10.00 | 8.59 |

**Lectura:**
- **CAL1:** pierde en bruto (−0,035R). Los costes (−0,019R) y el swap (−0,036R) duplican de sobra la pérdida, pero no la crean.
- **R1:** −0,198R en bruto.
- **R4:** −0,148R en bruto; es la que más swap paga (10,9 noches cobradas por trade).
- **R3:** la única positiva en bruto (+0,038R). Su coste por trade en R (0,065) es el más alto porque usa un stop de seguridad estrecho (2 ATR de H1); los costes, no el swap (−0,022R), la vuelven negativa.
- **Swap conservador:** un swap neutro (0 pips) solo habría dejado R3 cerca de cero (−0,027R) y no habría hecho rentable ninguna estrategia. Esto es contabilidad sobre los trades guardados, no una reejecución.

## Parte B — Control positivo del test predictivo

**Mundo nulo:** días completos de desarrollo de los 6 pares barajados sin reemplazo, en el mismo orden para todos, sobre un calendario sintético de 7 años. Los 4 últimos son la ventana de prueba, con la misma longitud que 2015–2018. Se conservan la trayectoria intradía y la correlación entre pares; se destruye la estructura entre días.

**Edge:** tras el estado 26 (régimen +1, pendiente H4 +1, orden H1 +1), deriva causal durante las 24 barras H1 siguientes. El bruto inyectado es el neto + 1,5 pips, en los 6 pares. La inyección usa el estado del mundo NULO; el test mide sobre el mundo inyectado, cuyos estados coinciden en un 74–89 % y por eso se reporta el edge realizado.

**Test:** exactamente el de la Parte 2: 45 pares estado-horizonte, bootstrap circular (semilla 20261002, 10.000 remuestreos, bloque max(5·h, 120)), Holm, neto ≥ 1 pip, ≥ 3/4 años y ≥ 3/5 pares de réplica. 50 réplicas (semillas 31000–31049), el mismo mundo nulo para todos los tamaños.

**Mundo nulo:**
- Tasa de falsos positivos en familia (≥ 1 aceptado de 45): **0.00**.
- Por test: **0.000**.
- Recuento medio por réplica de criterios superados: Holm 0.02/45, neto ≥ 1 pip 14.3/45, estabilidad 6.4/45, réplica 13.9/45.
- Media neta a 24 h del estado 26: −2,80 pips de media entre réplicas, **desviación típica 8,41** (de −34,4 a +12,5).

| edge neto nominal (pips, 24 h) | potencia (todos los criterios) | pasa Holm | pasa neto ≥ 1 | pasa estabilidad | pasa réplica | edge realizado (pips) | p crudo mediano | p Holm mediano | otro test aceptado (FP) | coincidencia de estados |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| +2 | **0.00** | 0.00 | 0.54 | 0.14 | 0.52 | +3.4 ± 1.6 | 0.4244 | 1.000 | 0.02 | 0.880 |
| +5 | **0.00** | 0.00 | 0.76 | 0.22 | 0.76 | +6.4 ± 2.4 | 0.2675 | 1.000 | 0.04 | 0.850 |
| +10 | **0.04** | 0.04 | 0.84 | 0.34 | 0.90 | +11.4 ± 3.1 | 0.1098 | 1.000 | 0.10 | 0.807 |
| +20 | **0.16** | 0.20 | 0.98 | 0.52 | 1.00 | +21.7 ± 4.9 | 0.0073 | 0.315 | 0.18 | 0.740 |

**Efecto mínimo detectable:**
- No se alcanza una potencia ≥ 0,50 (ni ≥ 0,80) con ningún tamaño preregistrado (máximo +20 pips: 0,16).
- Extrapolación, no medida: con un ruido de 8,4 pips en la media condicional y la exigencia de Holm (p ≤ 0,0011), el umbral del 80 % rondaría los 33 pips netos a 24 h.
- **Qué habría quedado sin detectar en 2015–2018:** cualquier edge condicional por estado de hasta al menos +20 pips netos a 24 h (detección ≤ 16 %), y con alta probabilidad también edges mayores.

**Qué limita la potencia** (detalle en `docs/BLOCKERS.md`):
- el ruido de la media condicional en 4 años (rachas largas y retornos solapados);
- Holm sobre 45;
- la estabilidad de ≥ 3 de 4 años;
- un bootstrap percentil sobre muestras efectivas pequeñas.

Los costes (1,5 pips) no son el cuello de botella.

## Parte C — Control positivo de la tubería de estrategias (calibración)

**Mundo:** el mismo mundo nulo (semillas 41000–41019) con AR(1) causal en los retornos H4 (barras EET 00/04/…): inj_k = φ · R_{k−1}, repartido en las 16 M15 de la barra.

**Estrategia y criterios:** la calibración de la Parte 2 sin cambios: H4 EMA50/200 con ADX > 25, stop y trailing de 3 ATR, salida por cruce contrario, costes de `configs/costs.yaml` y swap conservador. Aceptación de `acceptance_strategies`, con DSR de N = 13,92 y Var[SR] = 0,00148 de la Parte 2.

| φ (AR H4) | réplicas | aceptadas | mean R ×1 | mean R ×2 | PF mediano | DSR mediano | trades medios | R ×1 > 0 | R ×2 > 0 | PF ≥ 1,10 | ≥ 4/6 pares | ≥ 3/4 años |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.0 | 20 | **0.00** | -0.046 | -0.089 | 0.86 | 0.0001 | 1170 | 0.10 | 0.00 | 0.00 | 0.10 | 0.00 |
| 0.03 | 20 | **0.00** | -0.041 | -0.084 | 0.88 | 0.0004 | 1205 | 0.10 | 0.00 | 0.00 | 0.10 | 0.00 |
| 0.06 | 20 | **0.00** | -0.036 | -0.078 | 0.90 | 0.0006 | 1240 | 0.20 | 0.00 | 0.00 | 0.15 | 0.00 |
| 0.12 | 20 | **0.00** | -0.023 | -0.064 | 0.93 | 0.0024 | 1318 | 0.25 | 0.05 | 0.05 | 0.20 | 0.05 |

- **Sistema de tendencia:** acierto del 35–36 % y payoff de 1,56 → 1,71 al subir φ, coherente con un sistema de tendencia.
- **Sharpe medio de la cartera:** −0,79, −0,69, −0,60 y −0,39 para φ = 0; 0,03; 0,06; 0,12.
- **Drawdown medio:** 6,0–6,6 %.
- **Lectura:** la tubería no es ciega (responde de forma monótona a la persistencia), pero el nivel a partir del cual la calibración sería rentable y aceptada está **por encima de φ = 0,12**, fuera del rango preregistrado. No se determina aquí.

**Chequeos de la tubería** (mundo sintético con φ = 0,12, EURUSD):
- Python = Numba: **True** (224 trades comparados).
- Estados sin cambios antes de la perturbación: **True**.
- Trades sin cambios antes de la perturbación: **True** (149 trades).

## Qué implica para interpretar el nulo de la Parte 2
1. **Test predictivo:** el 0/45 de la Parte 2 es compatible con la ausencia de edge, pero también con edges condicionales grandes. Con este diseño y 4 años, un edge de +20 pips netos a 24 h por estado se habría detectado solo 16 de cada 100 veces. El resultado es "no demostrado", no "no existe", y la capacidad del test para demostrar algo es muy limitada.
2. **Estrategias:** las pérdidas de CAL1, R1 y R4 ya existen en bruto, sin costes ni swap. No son un artefacto del swap conservador. R3 tiene un bruto ligeramente positivo que los costes eliminan.
3. **Calibración:** que la calibración no sea rentable es compatible con su comportamiento en mundos con momentum H4 moderado (φ ≤ 0,12): incluso ahí pierde tras costes. Por tanto, su resultado en 2015–2018 no permite inferir la ausencia de tendencias explotables de otro tipo (memoria más larga).
4. **Sin bug:** el embudo no está ciego por un error de implementación. La equivalencia con el oráculo, la causalidad y la respuesta monótona de C lo confirman.

## Limitaciones
- **El mundo nulo destruye la dependencia entre días,** pero conserva la intradía y la correlación entre pares. Las rachas de estados del mundo nulo son más cortas que las reales, así que el ruido real de la media condicional podría ser algo distinto.
- **El edge inyectado depende del estado del mundo nulo;** la inyección altera los estados posteriores (coincidencia del 74–89 %). Se reporta el edge realizado; la potencia medida es la del test sobre los estados observados.
- **Edge en un solo estado (26) y a un solo horizonte (24 h):** otros estados más raros tendrían todavía menos potencia.
- **50 réplicas por tamaño:** error estándar de la potencia de ~0,05 a 0,16.
- **Parte C:** solo tres niveles de φ (más la referencia), un único tipo de persistencia (AR(1) de lag 1) y 20 réplicas por nivel.
- **El MDE de ~33 pips es una extrapolación,** no una medición.
- **No se ha cambiado ningún umbral del embudo** y no se propone hacerlo.

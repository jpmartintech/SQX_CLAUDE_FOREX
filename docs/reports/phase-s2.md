# Fase S, Parte 2 — Test predictivo, calibración y reglas sobre los estados del ribbon EMA (validación 2015–2018)

Fecha: 2026-10-01. Rama `phase-s-states`. Run `states_ribbon_s1`.
- **Preregistro:** `configs/states_ribbon.yaml` (`1748f2d`), idéntico en HEAD (verificado con `git diff`).
- **Pasada única:** `scripts/states_validate.py`.
- **Resultados:** `docs/reports/phase-s2_results.json` (copia de `runs/states_ribbon_s1/results.json`, con los indicadores de criterio como booleanos; el original los serializó como texto). Trades en `runs/states_ribbon_s1/trades_*.csv`.
- **Datos:** M15 cortado en 2019-01-01; ni 2019–2022 ni el holdout se han cargado. Desarrollo 2004–2014 solo para descripción (Parte 1).

## Resumen
- **Test predictivo:** ninguno de los 45 pares estado-horizonte de EURUSD cumple los criterios. El p de Holm más bajo es 1,000 (p crudo mínimo 0,034).
- **Calibración (H4 EMA50/200 + ADX > 25 + stop y trailing de 3 ATR):** reproduce la firma esperada en EURUSD (4/4 comprobaciones). Pierde tras costes en los 6 pares: −0,090R por trade, PF 0,76.
- **Reglas R1–R4:** ninguna cumple la aceptación. **R2 no genera ninguna entrada:** su condición previa no se da nunca entre 2003 y 2018.
- **"Demasiado bueno":** ningún aviso (PF > 2 con ≥ 50 trades o Sharpe > 3, en agregado y por par).
- **Lectura:** con 4 años de validación la potencia es baja. "No demostrado en este periodo" no significa "no existe".

## Ensayos
- **Contador `trials/ledger.jsonl`:** 4.489.850 evaluaciones sobre datos reales, de ellas 4.219.075 de selección. Esta fase añade 300:
  - 45 tests predictivos en EURUSD (selección);
  - 225 réplicas en los otros 5 pares (validación, no selección);
  - 30 combinaciones estrategia × par: 5 estrategias × 6 pares.
- **Pares efectivos** (PCA de retornos diarios, desarrollo, calculado antes de evaluar): 2,78. **N del DSR = 5 × 2,78 = 13,92.** Var[SR diario] entre las 30 combinaciones = 0,00148, de donde **SR\* anual = 1,08**.
- **Incidente:** la primera ejecución se cayó al agregar R2 (0 trades) sin mostrar ni guardar resultados ni escribir en el contador. Se corrigió solo la robustez del código y se repitió la misma pasada, con el mismo config y las mismas semillas, de forma determinista. Anotado en `DECISIONS.md`.

## (A) Test predictivo — EURUSD, retorno neto (1,5 pips) condicionado al estado, validación 2015–2018

Dirección por estado = régimen, o la pendiente H4 si el régimen es 0. Bootstrap circular por bloques de max(5·h, 120) barras H1, 10.000 remuestreos, semilla 20261002. p = fracción de medias remuestreadas ≤ 0. Holm sobre los 45.

Criterios (✓/·): Holm ≤ 0,05 · neto ≥ +1 pip · ≥ 3/4 años positivos · ≥ 3/5 pares de réplica positivos.

Estados: 0–8 régimen −1, 9–17 régimen 0, 18–26 régimen +1. Dentro de cada régimen, pendiente H4 −1/0/+1 en bloques de 3; dentro de cada bloque, orden H1 −1/0/+1.

| estado | dir. | h (H1) | n barras | neto medio (pips) | p crudo | p Holm | años + | réplica + | criterios |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0 | -1 | 6 | 2706 | +0.24 | 0.4478 | 1.000 | 2/4 | 0/5 | · · · · |
| 1 | -1 | 6 | 744 | -2.76 | 0.8150 | 1.000 | 1/4 | 1/5 | · · · · |
| 3 | -1 | 6 | 263 | -10.70 | 0.9417 | 1.000 | 1/4 | 3/5 | · · · ✓ |
| 4 | -1 | 6 | 1316 | -5.40 | 0.9909 | 1.000 | 1/4 | 0/5 | · · · · |
| 8 | -1 | 6 | 673 | +1.13 | 0.3745 | 1.000 | 3/4 | 1/5 | · ✓ ✓ · |
| 9 | -1 | 6 | 3995 | -1.79 | 0.9817 | 1.000 | 0/4 | 0/5 | · · · · |
| 10 | -1 | 6 | 1281 | +0.99 | 0.2867 | 1.000 | 2/4 | 0/5 | · · · · |
| 16 | +1 | 6 | 1241 | -0.70 | 0.6583 | 1.000 | 3/4 | 2/5 | · · ✓ · |
| 17 | +1 | 6 | 4119 | -2.26 | 0.9711 | 1.000 | 0/4 | 0/5 | · · · · |
| 18 | +1 | 6 | 597 | -0.95 | 0.6520 | 1.000 | 1/4 | 1/5 | · · · · |
| 19 | +1 | 6 | 244 | -6.51 | 0.9977 | 1.000 | 0/4 | 1/5 | · · · · |
| 22 | +1 | 6 | 1005 | -2.36 | 0.9279 | 1.000 | 0/4 | 1/5 | · · · · |
| 23 | +1 | 6 | 244 | -0.48 | 0.5918 | 1.000 | 2/4 | 2/5 | · · · · |
| 25 | +1 | 6 | 569 | -1.82 | 0.7512 | 1.000 | 1/4 | 1/5 | · · · · |
| 26 | +1 | 6 | 1764 | -2.98 | 0.9551 | 1.000 | 0/4 | 1/5 | · · · · |
| 0 | -1 | 24 | 2706 | +3.01 | 0.3165 | 1.000 | 2/4 | 0/5 | · ✓ · · |
| 1 | -1 | 24 | 744 | -3.95 | 0.6619 | 1.000 | 1/4 | 1/5 | · · · · |
| 3 | -1 | 24 | 263 | -3.74 | 0.6225 | 1.000 | 2/4 | 3/5 | · · · ✓ |
| 4 | -1 | 24 | 1316 | -11.05 | 0.9177 | 1.000 | 1/4 | 0/5 | · · · · |
| 8 | -1 | 24 | 673 | +1.43 | 0.4270 | 1.000 | 2/4 | 1/5 | · ✓ · · |
| 9 | -1 | 24 | 3995 | -2.12 | 0.7599 | 1.000 | 1/4 | 2/5 | · · · · |
| 10 | -1 | 24 | 1281 | +9.91 | 0.0337 | 1.000 | 4/4 | 0/5 | · ✓ ✓ · |
| 16 | +1 | 24 | 1241 | +5.21 | 0.2178 | 1.000 | 2/4 | 2/5 | · ✓ · · |
| 17 | +1 | 24 | 4101 | -4.78 | 0.8594 | 1.000 | 1/4 | 2/5 | · · · · |
| 18 | +1 | 24 | 597 | +2.40 | 0.3356 | 1.000 | 1/4 | 1/5 | · ✓ · · |
| 19 | +1 | 24 | 244 | -1.45 | 0.5392 | 1.000 | 1/4 | 1/5 | · · · · |
| 22 | +1 | 24 | 1005 | -6.09 | 0.8616 | 1.000 | 1/4 | 1/5 | · · · · |
| 23 | +1 | 24 | 244 | -11.01 | 0.7862 | 1.000 | 2/4 | 3/5 | · · · ✓ |
| 25 | +1 | 24 | 569 | +0.50 | 0.4766 | 1.000 | 1/4 | 1/5 | · · · · |
| 26 | +1 | 24 | 1764 | -5.51 | 0.8336 | 1.000 | 1/4 | 2/5 | · · · · |
| 0 | -1 | 120 | 2706 | +15.73 | 0.3165 | 1.000 | 2/4 | 2/5 | · ✓ · · |
| 1 | -1 | 120 | 744 | -34.34 | 0.8715 | 1.000 | 0/4 | 2/5 | · · · · |
| 3 | -1 | 120 | 263 | +12.62 | 0.4170 | 1.000 | 2/4 | 2/5 | · ✓ · · |
| 4 | -1 | 120 | 1316 | -27.23 | 0.9012 | 1.000 | 1/4 | 2/5 | · · · · |
| 8 | -1 | 120 | 673 | +14.06 | 0.2744 | 1.000 | 2/4 | 1/5 | · ✓ · · |
| 9 | -1 | 120 | 3995 | -8.34 | 0.7403 | 1.000 | 2/4 | 0/5 | · · · · |
| 10 | -1 | 120 | 1281 | -8.81 | 0.6668 | 1.000 | 2/4 | 2/5 | · · · · |
| 16 | +1 | 120 | 1241 | +4.22 | 0.4033 | 1.000 | 2/4 | 3/5 | · ✓ · ✓ |
| 17 | +1 | 120 | 4084 | -29.31 | 0.9953 | 1.000 | 1/4 | 1/5 | · · · · |
| 18 | +1 | 120 | 597 | +6.46 | 0.4171 | 1.000 | 1/4 | 0/5 | · ✓ · · |
| 19 | +1 | 120 | 244 | -3.44 | 0.5660 | 1.000 | 1/4 | 1/5 | · · · · |
| 22 | +1 | 120 | 1005 | -3.06 | 0.5685 | 1.000 | 1/4 | 1/5 | · · · · |
| 23 | +1 | 120 | 244 | -43.39 | 0.9599 | 1.000 | 0/4 | 2/5 | · · · · |
| 25 | +1 | 120 | 569 | +23.41 | 0.2121 | 1.000 | 2/4 | 1/5 | · ✓ · · |
| 26 | +1 | 120 | 1764 | -11.98 | 0.7161 | 1.000 | 1/4 | 2/5 | · · · · |

**Recuento por criterio:** Holm 0/45 · neto ≥ +1 pip 12/45 · estabilidad 3/45 · réplica 4/45 · **los cuatro a la vez: 0/45**.
- El p crudo más bajo (estado 10, h = 24, +9,9 pips, 4/4 años) no se replica: 0 de 5 pares positivos. Tras Holm (×45) queda en 1,0.
- Comprobación de un posible bug: el estado 0 da el mismo p crudo (0,3165) en h = 24 y h = 120. Recalculado con el mismo código y semilla, las secuencias remuestreadas coinciden solo en el 57 % y los demás estados difieren entre horizontes: es una coincidencia, no un error.

## (B) Calibración — hipótesis 1 (H4, EMA50/EMA200, ADX14 > 25, stop inicial y trailing de 3 ATR, salida por cruce contrario)

**Firma esperada en EURUSD** (preregistrada; no es una afirmación de rentabilidad):

| comprobación | esperado | observado | ¿cumple? |
|---|---|---|---|
| tasa de acierto | 25 %–50 % | 36.5% | sí |
| payoff (R ganador medio / \|R perdedor medio\|) | ≥ 1,5 | 1.60 | sí |
| trades EURUSD 2015–2018 | ≥ 30 | 222 | sí |
| salidas por trailing o señal | ≥ 60 % | 100% (TRAIL 199, SIGNAL 23) | sí |

**El evaluador reproduce el comportamiento típico de un sistema de tendencia:** pocas ganancias grandes y muchas pérdidas pequeñas. No hace falta buscar un bug por ausencia de firma.

**Matiz:** como el stop inicial y el trailing son ambos de 3 ATR, el stop se mueve en cuanto el precio avanza y casi cualquier salida posterior se etiqueta como TRAIL. El criterio del 60 % se cumple casi por construcción y aporta poca información.

**Rentabilidad** (6 pares, costes y swap ×1): 1252 trades, mean R -0.090, PF 0.76. Detalle en (C).

## (C) Calibración y reglas en los 6 pares — validación 2015–2018

Riesgo de 0,5 % por trade y por pata (largos y cortos como subcuentas). Costes de `configs/costs.yaml`. Swap conservador de 1 pip/noche en ambos sentidos, sin verificar con el broker. ×2 = costes y swap ×2.

| estrategia | trades | mean R ×1 | mean R ×2 | PF | acierto | payoff | pips/trade | pares + (≥20 trades) | años + | DD cartera | Sharpe cartera | DSR | control: media / p95 / p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| CAL1_H4_EMA50_200_ADX | 1252 | -0.090 | -0.144 | +0.76 | 34.4% | +1.45 | -12.4 | 0/6 | 0/4 | 10.4% | -1.54 | 0.000 | -0.055 / -0.014 / 0.88 |
| R1_trend_continuation | 130 | -0.343 | -0.488 | +0.59 | 19.2% | +2.48 | -14.2 | 1/6 | 1/4 | 4.7% | -1.02 | 0.000 | -0.135 / +0.261 / 0.84 |
| R2_pullback_end | 0 | — | — | — | — | — | — | 0/6 | 0/4 | 0.0% | +0.00 | 0.016 | — |
| R3_compression_release | 221 | -0.049 | -0.136 | +0.91 | 33.0% | +1.85 | -1.5 | 3/6 | 2/4 | 2.0% | -0.23 | 0.006 | -0.089 / +0.094 / 0.39 |
| R4_regime_change | 180 | -0.249 | -0.351 | +0.61 | 26.1% | +1.74 | -34.2 | 1/6 | 0/4 | 3.7% | -1.12 | 0.000 | -0.087 / +0.088 / 0.93 |

- **R4** usa un stop de seguridad de 8 ATR y su R no es comparable con el de las demás. En pips pierde −34,2 por trade.
- **Control aleatorio emparejado** (200 réplicas, mismo número, sentido, duración y distancia de stop, salida por tiempo): solo informativo. Ninguna estrategia lo supera con p ≤ 0,05 (p de 0,39 a 0,93).

**Criterios de aceptación** (`acceptance_strategies`, tal cual):

| estrategia | R ×1 > 0 | R ×2 > 0 | PF ≥ 1,10 | ≥ 4/6 pares | ≥ 3/4 años | ≥ 100 trades | DSR ≥ 0,95 | **aceptada** |
|---|---|---|---|---|---|---|---|---|
| CAL1_H4_EMA50_200_ADX | **no** | **no** | **no** | **no** | **no** | sí | **no** | **no** |
| R1_trend_continuation | **no** | **no** | **no** | **no** | **no** | sí | **no** | **no** |
| R2_pullback_end | **no** | **no** | **no** | **no** | **no** | **no** | **no** | **no** |
| R3_compression_release | **no** | **no** | **no** | **no** | **no** | sí | **no** | **no** |
| R4_regime_change | **no** | **no** | **no** | **no** | **no** | sí | **no** | **no** |

**Por año** (mean R ×1 agregado, por año de entrada):

| estrategia | 2015 | 2016 | 2017 | 2018 |
|---|---:|---:|---:|---:|
| CAL1_H4_EMA50_200_ADX | -0.058 | -0.192 | -0.091 | -0.002 |
| R1_trend_continuation | +0.339 | -0.817 | -0.352 | -0.491 |
| R2_pullback_end | — | — | — | — |
| R3_compression_release | -0.094 | +0.291 | +0.048 | -0.436 |
| R4_regime_change | -0.182 | -0.382 | -0.008 | -0.347 |

**Por par** (trades · mean R ×1 · mean R ×2 · PF · DD máx. de la subcuenta del par · pips/trade):

| estrategia | EURUSD | GBPUSD | USDJPY | USDCHF | USDCAD | NZDUSD |
|---|---|---|---|---|---|---|
| CAL1_H4_EMA50_200_ADX | 222 · -0.029 · -0.077 · +0.92 · 12.5% · -6.5 | 221 · -0.116 · -0.157 · +0.69 · 13.2% · -15.2 | 193 · -0.118 · -0.167 · +0.71 · 12.7% · -14.9 | 212 · -0.195 · -0.260 · +0.54 · 22.3% · -25.1 | 226 · -0.050 · -0.102 · +0.86 · 10.5% · -8.2 | 178 · -0.026 · -0.103 · +0.92 · 7.8% · -3.9 |
| R1_trend_continuation | 18 · -0.420 · -0.547 · +0.54 · 6.7% · -15.6 | 27 · -0.711 · -0.800 · +0.12 · 9.2% · -37.7 | 21 · -0.361 · -0.546 · +0.57 · 6.5% · -18.2 | 21 · -0.373 · -0.529 · +0.61 · 6.8% · -19.6 | 22 · +0.433 · +0.278 · +1.60 · 4.5% · +34.0 | 21 · -0.570 · -0.740 · +0.32 · 6.7% · -24.2 |
| R2_pullback_end | 0 trades | 0 trades | 0 trades | 0 trades | 0 trades | 0 trades |
| R3_compression_release | 42 · +0.197 · +0.129 · +1.37 · 4.1% · +5.9 | 26 · +0.038 · -0.030 · +1.07 · 2.6% · -1.2 | 47 · -0.088 · -0.168 · +0.83 · 4.4% · +1.9 | 28 · -0.530 · -0.621 · +0.24 · 7.2% · -25.0 | 38 · -0.053 · -0.149 · +0.89 · 3.6% · +1.5 | 40 · +0.022 · -0.094 · +1.04 · 5.6% · -0.0 |
| R4_regime_change | 34 · -0.427 · -0.522 · +0.43 · 7.1% · -62.0 | 27 · +0.462 · +0.362 · +1.95 · 2.0% · +45.8 | 32 · -0.367 · -0.455 · +0.43 · 5.7% · -36.4 | 29 · -0.408 · -0.517 · +0.40 · 6.2% · -44.2 | 27 · -0.177 · -0.271 · +0.72 · 4.6% · -45.5 | 31 · -0.467 · -0.590 · +0.29 · 7.3% · -51.8 |

**Largos y cortos** (trades, mean R ×1):

| estrategia | largos | cortos |
|---|---|---|
| CAL1_H4_EMA50_200_ADX | 643 · -0.105 | 609 · -0.073 |
| R1_trend_continuation | 64 · -0.174 | 66 · -0.507 |
| R2_pullback_end | — | — |
| R3_compression_release | 118 · -0.008 | 103 · -0.096 |
| R4_regime_change | 95 · -0.280 | 85 · -0.216 |

**Motivos de salida:**

- CAL1_H4_EMA50_200_ADX: TRAIL 85%, SIGNAL 13%, STOP_GAP 1%, STOP 1%, END 0%
- R1_trend_continuation: STOP 72%, SIGNAL 25%, TIME 2%, STOP_GAP 1%, END 1%
- R2_pullback_end: sin trades
- R3_compression_release: TRAIL 72%, STOP 28%
- R4_regime_change: STOP 43%, SIGNAL 37%, TIME 20%, STOP_GAP 1%

## (D) Aceptación y "demasiado bueno"
- **Test predictivo:** 0 de 45 estados-horizonte predictivos.
- **Estrategias:** ninguna aceptada.
  - La calibración y R1, R3 y R4 tienen mean R negativo con costes ×1 y ×2.
  - R3 es la más cercana a cero (−0,049R, PF 0,91, 3 de 6 pares y 2 de 4 años positivos), pero no cumple ningún criterio de rentabilidad ni el DSR.
  - R2 no tiene trades.
- **DSR** de 0,000 a 0,016 frente a SR\* = 1,08 anual.
- **"Demasiado bueno":** ningún aviso. No hubo que buscar fugas.

## Limitaciones
- **Poca potencia:** solo 4 años de validación. Un resultado nulo aquí es "no demostrado en 2015–2018", no "no existe".
- **R2 está mal especificada** respecto a la histéresis elegida: el orden H1 = −1 exige el orden bajista perfecto de 7 EMAs, que nunca coincide con régimen +1 y pendiente H4 +1. Es un defecto de diseño del preregistro detectado al ejecutar. No se corrige dentro de esta fase.
- **Calibración:** el criterio de salidas por trailing o señal es poco informativo, porque el stop inicial y el trailing son iguales (3 ATR).
- **Swap sin verificar:** conservador, 1 pip/noche en ambos sentidos. Penaliza más a las reglas que mantienen posiciones varios días (calibración y R4).
- **Subcuentas:** las patas largas y cortas son subcuentas independientes; en R3 pueden coexistir. El drawdown de cartera es la media equiponderada de los 6 pares.
- **El p del bootstrap es la fracción de medias remuestreadas ≤ 0**, tal como dice el preregistro (método percentil, no un test centrado bajo H0).
- **Variaciones como pruebas:** las estrategias se evalúan una sola vez, sin variantes. Las réplicas validan, no seleccionan.

## Construido en la Parte 2
- **`sqxf.states.validate`:**
  - mercados sobre barras locales con swap;
  - evaluación de señales arbitrarias con el kernel Numba (verificada contra el oráculo Python);
  - retorno neto futuro, bootstrap circular por bloques, Holm y control emparejado;
  - señales de la calibración y de R1–R4.
- **`scripts/states_validate.py`:** pasada única; se niega a repetir y comprueba que el YAML coincide con `1748f2d`.
- **`tests/test_states_validate.py`:** equivalencia con el oráculo (swap, trailing y salidas), alineación del retorno futuro, bootstrap determinista y calibrado, Holm, señales y control.

# Fase C1 — Procedimiento walk-forward en perpetuos cripto (H4 y variante D1)

Fecha: 2026-10-01. Rama `phase-c1-crypto`. Run **`crypto_c1_wf_r2`**.
- **Preregistro:** `configs/crypto_c1.yaml`, commiteado en `8979f92` **antes** de ejecutar. Los cambios respecto a r1 (`aa7b994`, nunca ejecutado) están en `DECISIONS.md`.
- **Datos:** solo M15 < 2023-11-01: precios de perpetuo desde la fecha de cambio de cada moneda y spot antes. El bloque de selección y el holdout no se han cargado ni descargado; ningún acceso nuevo en `trials/crypto_holdout_access.jsonl`.
- **Resultados:** `docs/reports/phase-c1_run_interim.json` (copia de `runs/crypto_c1_wf_r2/report.json`); trades en `runs/crypto_c1_wf_r2/`.

> **Nulo COMPLETO: 200 de 200 permutaciones** (actualizado el 2026-10-01). La primera versión de este informe usaba un nulo parcial de 44; las 200 terminaron en segundo plano antes de la orden de parada. Cifras finales en `docs/reports/phase-c1_run.json`; el intermedio queda en `phase-c1_run_interim.json`. **El veredicto no cambia.**

## Veredicto

**Ninguna de las dos variantes cumple los criterios preregistrados.** H4 cumple 2 de 8 y D1 cumple 3 de 8. No se aflojan umbrales ni se relanza.

| Criterio | H4 (principal) | D1 (variante) |
|---|---|---|
| mean R agregado, costes ×1 > 0 | −0,0220 → **no** | +0,0119 → sí |
| mean R agregado, costes y funding ×2 > 0 | −0,0745 → **no** | −0,0291 → **no** |
| mean R sin 2021 > 0 | +0,0030 → sí | −0,0211 → **no** |
| p-valor frente al nulo ≤ 0,025 (200 perm.) | 0,378 → **no** | 0,129 → **no** |
| p-valor frente al control emparejado ≤ 0,025 (200 réplicas) | 0,010 → sí | 0,005 → sí |
| DSR de la cartera ≥ 0,95 (N = 2 × 2,4 = 4,8) | 0,074 → **no** | 0,242 → **no** |
| ≥ 4 de 5 monedas validadas por separado en positivo, cada una con ≥ 50 trades | 1/5 (ETH) → **no** | 3/5 (ETH, LINK, ADA) → **no** |
| ≥ 3 de 5 ventanas en positivo | 1/5 → **no** | 3/5 → sí |

## Cifras

**Agregado, 8 monedas, 5 ventanas** (mayo de 2021 a octubre de 2023):

| | H4 | D1 |
|---|---:|---:|
| Evaluaciones del genético (8 monedas × 5 ventanas × 20.000) | 800.000 | 800.000 |
| Trades fuera de muestra | 6.984 | 3.898 |
| mean R ×1 / ×2 | −0,0220 / −0,0745 | +0,0119 / −0,0291 |
| t (trades tratados como independientes, ver nota) | −1,73 | +0,72 |
| Funding medio por trade (en R) | −0,0013 | −0,0048 |
| Nulo (200): media / p95 / máximo de mean R | −0,029 / +0,011 / +0,035 | −0,024 / +0,027 / +0,048 |
| Control emparejado (200): media / p95 | −0,059 / −0,036 | −0,051 / −0,024 |
| Cartera equiponderada (0,5 % de riesgo por trade, ≤ 1x): Sharpe / retorno / DD | −0,30 / −0,96 % / 2,2 % | +0,13 / +0,28 % / 1,8 % |
| PSR frente a 0 / DSR (SR\* anual) | 0,32 / 0,074 (0,63) | 0,58 / 0,242 (0,57) |
| Chequeo informativo: mismas estrategias sobre spot sin corregir, mean R ×1 / ×2 | −0,0529 / −0,1081 | +0,0122 / −0,0297 |

**Por moneda** (mean R ×1 / ×2, trades). Las 5 primeras se validan por separado; SOL, DOGE y AVAX cuentan solo en el agregado:

| Moneda | H4 | D1 |
|---|---|---|
| BTC | −0,150 / −0,189 (784) | −0,091 / −0,131 (580) |
| ETH | +0,015 / −0,045 (917) | +0,082 / +0,033 (572) |
| BNB | −0,096 / −0,146 (832) | −0,031 / −0,062 (569) |
| LINK | −0,115 / −0,169 (1.141) | +0,103 / +0,060 (556) |
| ADA | −0,065 / −0,114 (851) | +0,015 / −0,031 (600) |
| SOL | −0,098 / −0,129 (785) | +0,143 / +0,107 (363) |
| DOGE | +0,077 / +0,014 (847) | −0,043 / −0,078 (471) |
| AVAX | +0,277 / +0,204 (827) | −0,151 / −0,199 (187) |

**Por ventana, frente a comprar y mantener** (B&H: largo 1x equiponderado en las 8 monedas, una ida y vuelta de costes; en perpetuo, con funding pagado):

| Ventana | H4 mean R ×1 (trades) | D1 mean R ×1 (trades) | B&H spot | B&H perp |
|---|---|---|---:|---:|
| 2021-05 → 2021-11 | −0,055 (1.054) | **+0,236** (453) | +65,1 % | +53,8 % |
| 2021-11 → 2022-05 | −0,123 (967) | −0,056 (516) | −44,2 % | −47,1 % |
| 2022-05 → 2022-11 | −0,002 (1.845) | −0,138 (837) | −38,2 % | −37,8 % |
| 2022-11 → 2023-05 | −0,043 (1.536) | +0,061 (1.307) | −3,5 % | −2,4 % |
| 2023-05 → 2023-11 | +0,058 (1.582) | +0,006 (785) | +4,7 % | +3,3 % |

**Largos frente a cortos** (mean R ×1 / ×2; funding en R por trade):

| | H4 largos | H4 cortos | D1 largos | D1 cortos |
|---|---|---|---|---|
| Trades | 4.649 | 2.335 | 2.885 | 1.013 |
| mean R | −0,048 / −0,091 | +0,030 / −0,042 | −0,011 / −0,052 | +0,076 / +0,037 |
| Funding | −0,0044 | +0,0047 | −0,0104 | +0,0114 |

**Sin 2021** (trades con entrada en 2021 eliminados): H4 +0,0030 (5.563 trades), D1 −0,0211 (3.238 trades).
- El resultado positivo de D1 depende de la ventana de mayo a noviembre de 2021: +0,236R, cuando el mercado subió un 65 %.
- H4 sin 2021 queda en cero.

## Lectura
1. **El procedimiento no tiene edge tras costes en perpetuos cripto**, ni en H4 ni en D1.
   - H4 pierde −0,022R por trade y en 7 de 8 monedas no supera los costes ×2.
   - D1 gana +0,012R con costes reales (t = 0,7), pero lo pierde con costes ×2 y sin 2021.
2. **Sí supera claramente al control emparejado** (p = 0,010 y 0,005): el momento de entrada que elige el genético es mejor que entrar al azar con la misma exposición y dirección. Pero:
   - el control pierde −0,05/−0,06R por costes, funding y salidas por tiempo;
   - batirlo no basta para ser rentable;
   - **no supera al nulo** (p = 0,38 en H4 y 0,13 en D1): en datos sin orden diario el procedimiento obtiene resultados parecidos.
3. **Los cortos funcionan mejor que los largos** en ambas variantes (H4 +0,030 frente a −0,048; D1 +0,076 frente a −0,011). En parte es el funding: los cortos lo cobran (+0,005 a +0,011R por trade). En parte es el régimen: 2021-11 → 2022-11 fue un mercado bajista de −44 % y −38 %.
4. **Comprar y mantener** del agregado fue muy negativo en estas ventanas (−44 %, −38 %) salvo mayo a noviembre de 2021 (+65 %). Las estrategias, con riesgo de 0,5 % por trade y tope de 1x, tienen un drawdown del ~2 %: es otra escala de riesgo, así que la comparación directa de retornos no es homogénea.
5. **Proxy spot:** reoperar lo mismo sobre spot sin corregir empeora H4 (−0,053 frente a −0,022) y deja D1 igual. Cuadra con lo medido en la Parte 1: el spot difiere sobre todo en los stops y las mechas.

**Nota sobre los t:** las 10 estrategias elegidas en cada ventana suelen ser variantes muy parecidas que operan lo mismo, así que los trades no son independientes y los t por moneda (AVAX H4 t = 4,9, BTC H4 t = −5,0) sobrestiman la evidencia. Los contrastes honestos son el nulo, el control y el DSR.

**AVAX H4 (+0,277R)** se revisó por si era demasiado bueno:
- PF 1,52; opera solo en 3 ventanas.
- Largos en 2022-05 (+0,30R) y cortos en 2023-05 (+0,60R).
- Las 20 mejores operaciones aportan el 33 %.
- Datos del perpetuo sin huecos y R máximo = take profit de 4 ATR.
- Sin bug. Es una moneda solo de agregado y no cambia el veredicto.

## Número de ensayos
- **Contador `trials/ledger.jsonl`: 4.489.550 evaluaciones sobre datos reales** (4.219.000 de selección). Esta fase añade 1.600.000 (800.000 × 2 variantes); antes había 2.889.550.
- **Nulos:** 200 × 1,6 M = 320 M evaluaciones sobre datos permutados. No cuentan en el contador.
- **DSR:** N = 2 procedimientos (`trials/crypto_procedure_ledger.jsonl`) × 2,4 series independientes = **4,8**. Var[SR] sale de las 200 carteras nulas: SR\* anual 0,63 (H4) y 0,57 (D1). DSR de 0,074 y 0,242.

## Qué se construyó en la Parte 2
- **Precios híbridos** (`load_hybrid_m15` / `load_hybrid_market`): perpetuo desde la fecha de cambio preregistrada de cada moneda y spot antes. La liquidez siempre se mide con el volumen spot y por fecha UTC.
- **`sqxf.crypto.procedure`:**
  - ventanas de 24 + 6 meses;
  - genético y selección reutilizando forex;
  - operación fuera de muestra en M15 con costes y funding ×1/×2;
  - agregados por moneda, ventana, sentido y sin 2021;
  - control emparejado (mismo número, sentido, duración y distancia de stop, sin solapes, costes y funding iguales; 98–100 % de los trades colocados);
  - comprar y mantener en spot y en perpetuo.
- **`scripts/crypto_c1.py`:** modos observado, nulo por shards reanudables e informe, más `scripts/crypto_c1_tables.py`.
- **Tests:**
  - las ventanas;
  - el determinismo y la contabilidad del resumen;
  - el control conserva número, sentido y duración, y su R coincide con el cálculo manual;
  - el nulo con calendario UTC conserva la volatilidad mensual;
  - el empalme spot→perpetuo con datos reales.

`pytest -q`: **114 passed** (mostrado en la conversación). `ruff`: limpio.

## Limitaciones
- **Solo 5 ventanas de 6 meses** (2,5 años fuera de muestra), dominadas por un único ciclo (euforia de 2021 → bajista de 2022 → lateral de 2023).
- **Universo de supervivientes** (sesgo declarado). La correlación entre monedas deja ~2,4 series independientes.
- **Comisión de 0,05 % taker sin verificar** con tu cuenta. Sin modelar liquidaciones: con un tope de 1x no se alcanzan.

## Siguiente (decide Jaime)
- Con esta gramática, el procedimiento ha fallado ya en forex (2, 2b, 2c) y en cripto (C1). **No propongo más búsquedas con la gramática g1.**
- Si se sigue, cambiar la hipótesis: carry/funding como señal explícita (los cortos cobran funding), estrategias de régimen o tendencia a D1/W1 con pocas reglas y preregistradas, o selección por robustez entre monedas (una regla común para las 8) en lugar de reglas por moneda.

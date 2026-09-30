# Fase 2c — El procedimiento de la 2b en 6 pares, con variante robusta a costes, control aleatorio y nulo por bloques

Fecha: 2026-09-30. Rama `phase-2c-6pairs`. Run `phase2c_wf_6pairs_r1`.
- Preregistro: `configs/wf_6pairs.yaml`, commiteado en `b535307` antes de cualquier run con datos reales. No se modificó después.
- Resultados completos: `docs/reports/phase2c_run.json`, `runs/phase2c_wf_6pairs_r1/`.
- Pares: EURUSD, GBPUSD, USDJPY, USDCHF, USDCAD y NZDUSD (sin XAUUSD). OOS 2010–2018. M15 truncado en 2019-01-01 antes de construir cualquier mercado.
- 2019–2022: sin cargar. Holdout: 0 accesos.

## Veredicto

**Ninguna de las dos variantes preregistradas cumple los criterios.** Cada una falla 4 de 5 condiciones. No se aflojan umbrales ni se relanza con otra semilla.

| Criterio (sobre el agregado de los 6 pares) | Genético `base` | Genético `x2robust` |
|---|---|---|
| mean R OOS con costes ×1 > 0 | −0,0317 → **no** | −0,0317 → **no** |
| mean R OOS con costes ×2 > 0 | −0,0848 → **no** | −0,0848 → **no** |
| p-valor frente al nulo ≤ 0,025 (Bonferroni, 2 variantes) | 0,066 → **no** | 0,066 → **no** |
| Supera al control aleatorio con la misma variante | −0,032 frente a −0,051 → sí | −0,032 frente a −0,052 → sí |
| DSR de la cartera ≥ 0,95 (N = 6 procedimientos) | 0,010 → **no** | 0,010 → **no** |

## Cifras

**Agregado 2010–2018, 6 pares** (cartera equiponderada por fecha, 0,5 % de riesgo por trade):

| | Genético base | Genético x2robust | Aleatorio base | Aleatorio x2robust |
|---|---:|---:|---:|---:|
| Trades OOS | 16.472 | 16.472 | 28.937 | 25.323 |
| mean R ×1 (t) | −0,0317 (−4,22) | −0,0317 (−4,22) | −0,0511 (−7,58) | −0,0522 (−7,32) |
| mean R ×2 | −0,0848 | −0,0848 | −0,1168 | −0,1157 |
| p-valor ×1 / ×2 frente al nulo | 0,066 / 0,082 | 0,066 / 0,082 | 0,164 / 0,246 | 0,213 / 0,230 |
| Nulo mean R ×1: media / p95 / máx. | −0,054 / −0,032 / −0,020 | igual | −0,061 / −0,045 / −0,034 | −0,061 / −0,043 / −0,032 |
| Cartera: Sharpe / retorno / DD máx. | −0,51 / −4,3 % / 5,7 % | igual | −1,43 / −11,6 % / 12,1 % | — |
| Cartera: PSR frente a 0 / DSR (SR\* anual) | 0,065 / 0,010 (0,27) | igual | 0,000 / 0,000 (0,40) | 0,000 / 0,000 (0,44) |

**Por par, genético base** (el p-valor por par es informativo, no decide):

| Par | Trades | mean R ×1 | mean R ×2 | Años + (de 9) | p (informativo) |
|---|---:|---:|---:|---:|---:|
| EURUSD | 3.089 | **+0,0294** | −0,0092 | 5 | 0,066 |
| GBPUSD | 3.014 | −0,0735 | −0,1212 | 3 | 0,721 |
| USDJPY | 3.265 | −0,0459 | −0,0966 | 5 | 0,393 |
| USDCHF | 2.288 | −0,0341 | −0,0905 | 4 | 0,328 |
| USDCAD | 2.348 | +0,0044 | −0,0556 | 4 | 0,180 |
| NZDUSD | 2.468 | −0,0706 | −0,1419 | 3 | 0,656 |

EURUSD reproduce exactamente la Fase 2b (3.089 trades y +0,0294R), como debía por las semillas compartidas.

**Por año, agregado del genético base (mean R ×1):**

| 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 |
|---|---|---|---|---|---|---|---|---|
| −0,063 | −0,065 | −0,057 | −0,042 | −0,087 | +0,032 | −0,013 | −0,035 | +0,039 |

## Lectura
1. **El resultado de la 2b en EURUSD no generaliza.** Al aplicar el mismo procedimiento a 6 pares, el agregado pierde 0,03R por trade con costes reales (t = −4,2). El único par positivo claro es precisamente el que ya se había mirado (EURUSD).
2. **El genético pierde menos que el azar, pero pierde.**
   - Frente al nulo por bloques (−0,054R de media), el observado supera a 57 de los 60 nulos (p = 0,066). Frente al control aleatorio con la misma variante también queda por encima.
   - Hay algo de estructura que el genético captura mejor que la búsqueda aleatoria, pero no alcanza para cubrir los costes.
   - Tampoco es significativo con la corrección preregistrada (0,025).
3. **La variante `x2robust` no actúa sobre el genético.** Las 54 selecciones (6 pares × 9 años) son idénticas a las de la base.
   - Causa: las 10 mejores por fitness tienen en entrenamiento 0,25–0,6R por trade. Duplicar el coste (~0,03–0,04R) no las acerca al umbral.
   - Ejemplo en GBPUSD 2010: de las 200 mejores pasan 169 con la regla base y exactamente las mismas 169 con la `x2robust`.
   - En el control aleatorio sí cambia 31 de 54 selecciones.
   - Conclusión: la fragilidad frente a costes fuera de muestra no se detecta en entrenamiento, porque el edge de entrenamiento es sobre todo sobreajuste, no margen escaso.
   - En el DSR se cuentan igualmente las dos variantes (N = 6), aunque en el genético sean idénticas.
4. **Sin indicios de bug:**
   - El nulo pierde −0,054/−0,061R, coherente con los costes.
   - EURUSD reproduce la 2b.
   - No hay ningún resultado "demasiado bueno".

## Número de ensayos
- **Contador `trials/ledger.jsonl`: 2.889.550 evaluaciones sobre datos reales** (2.619.000 de selección).
  - Antes de la 2c había 729.550: los 729.070 del informe de la 2b más los 480 de la última ejecución de `pytest`, anterior al arreglo.
  - La 2c añade 6 pares × (180.000 del genético + 180.000 del control) = 2.160.000.
  - Las dos variantes de selección se aplican al mismo archivo, así que no añaden evaluaciones.
- **Nulos:** 60 × 2.160.000 = 129,6 millones de evaluaciones sobre datos permutados. No se suman al contador (que cuenta datos reales); están en `runs/phase2c_wf_6pairs_r1/null_shard*.jsonl`.
- **Procedimientos evaluados sobre 2010–2018** (`trials/procedure_ledger.jsonl`): 2 (2b) + 4 (2c) = **6**, usado como N del DSR.

## Cambios de infraestructura de esta fase
- **pytest ya no escribe en el contador de ensayos.**
  - Un fixture autouse redirige el contador y los logs de acceso a un directorio temporal.
  - `record_evaluations` lanza un error si se intenta escribir en el contador versionado bajo pytest.
  - Verificado: el md5 de `trials/ledger.jsonl` es idéntico antes y después de `pytest -q`.
- **Cargador YAML estricto** (`provenance.load_yaml_strict`): falla si una clave no se carga como el texto escrito (`null:`, `yes:`, `on:`, `1:`). Hay tests con casos malos y sobre todos los `configs/*.yaml`. En `wf_procedure.yaml` se entrecomilló `"null":` (mismo valor).
- **Nulo por bloques:** días completos (96 M15 en los 6 pares) permutados dentro de su mes natural, con el mismo mapeo en todos los pares.
  - Tests: conserva exactamente la volatilidad realizada de cada mes.
  - Mueve la trayectoria intradía completa de cada día.
  - Deja los demás días en su sitio.
  - El mapeo es el mismo para todos los pares.
- **`run_multi`:** procedimiento multi-par y multi-variante.
  - Test: con un solo par reproduce exactamente el procedimiento de la 2b.
  - Test: el agregado es la suma de los pares.

`pytest -q`: **83 passed** (se muestra en la conversación). `ruff`: limpio. Duración: observado ~20 min; nulo ~4 h en 10 procesos.

## Limitaciones
- **El nulo por bloques conserva todo lo intradía.** Un edge puramente intradía sobreviviría en el nulo, así que el test es conservador para ese tipo de edge. El grammar no tiene features de hora ni de sesión.
- **Los años 2010–2018 ya se miraron en las Fases 2 y 2b** (EURUSD). En los otros 5 pares es la primera vez.
- **Sin swap**, coste fijo por par (`configs/costs.yaml`, sin validar con un broker real).
- **60 permutaciones:** el p-valor tiene una resolución de 1/61. Con p = 0,066, un nulo mayor no cambiaría el veredicto, porque ya fallan los criterios de signo.

## Qué queda claro y qué propondría (decide Jaime)
- Con esta gramática (170 predicados técnicos genéricos sobre H1), esta forma de fitness y estos costes, **tres diseños distintos no han encontrado edge**: embudo con DSR (2), walk-forward del procedimiento en 1 par (2b) y en 6 pares (2c).
- Seguir buscando con la misma gramática sería pescar.
- Propuestas con otra hipótesis económica, cada una con su propio preregistro:
  1. **Sesión y hora del día** (Fase 6), que el nulo por bloques no puede capturar como edge falso porque conserva lo intradía.
  2. **Horizontes más largos:** señales diarias o semanales, con menos trades y menos peso relativo del coste.
  3. **Fuerza relativa entre divisas** (multi-par).
- Antes de cualquier búsqueda nueva, añadir el swap y validar los costes por par con datos de un broker real.

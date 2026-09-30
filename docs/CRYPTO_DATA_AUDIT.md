# Auditoría de datos cripto (M15) — 2026-09-30

- **Alcance:** solo lectura, sin tocar el motor. No se ha ejecutado ninguna estrategia ni ningún backtest.
- **Rama:** `phase-c0-crypto-audit`.
- **Origen:** `/mnt/c/Users/xaume/Documents/DATOS SQX 15 MINS/crypto`, sin modificar.
- **Copia de trabajo:** `data/raw/crypto/` (ignorada por git), con `SHA256SUMS.txt` verificado contra el origen (18/18 OK).
- **Manifiesto:** `docs/crypto_manifest.json` (SHA256, filas, primera y última fecha, inicio del holdout por fichero).
- **Script:** `scripts/audit_crypto.py`. Salida completa en `runs/audit_crypto.txt`.

## 0. Holdout sellado (fijado antes de cualquier estadístico)

**Holdout = los últimos 18 meses de cada moneda**, desde `normalize(última barra − 18 meses)` en UTC:
- BTCUSDT: desde el **2024-11-02** (sus datos terminan el 2026-05-02 14:45).
- Las otras 8 monedas: desde el **2024-12-04** (terminan el 2026-06-04).

Uso de los datos:
- **Calidad** (integridad, huecos, anomalías, volumen, formato): lee todo el rango, holdout incluido.
- **Rendimiento** (retornos, volatilidad, deriva, comprar y mantener, correlaciones, PCA, regímenes): solo datos anteriores al holdout.

Cada ejecución del script añade una línea en `trials/crypto_holdout_access.jsonl` con `performance_stats_on_holdout: false`. Hay 2 líneas: la primera ejecución y la reejecución tras corregir la agrupación de huecos.

**Propuesta para los splits** (§10): usar un único inicio común de holdout, el **2024-11-01**, para las 9 monedas. Sella como mínimo 18 meses en cada una y permite carteras con un calendario común.

## 1. Inventario

| Moneda | Filas M15 | Primera barra (UTC) | Última barra (UTC) | Inicio holdout | Decimales precio | Volumen |
|---|---:|---|---|---|---:|---|
| ADAUSDT | 284.811 | 2018-04-17 04:00 | 2026-06-04 23:45 | 2024-12-04 | 5 | entero |
| AVAXUSDT | 199.752 | 2020-09-22 06:30 | 2026-06-04 23:45 | 2024-12-04 | 4 | entero |
| BNBUSDT | 300.215 | 2017-11-06 03:45 | 2026-06-04 23:45 | 2024-12-04 | 4 | entero |
| BTCUSDT | 304.759 | 2017-08-17 04:00 | **2026-05-02 14:45** | 2024-11-02 | 2 | decimal |
| DOGEUSDT | 242.342 | 2019-07-05 12:00 | 2026-06-04 23:45 | 2024-12-04 | 7 | entero |
| ETHUSDT | 307.963 | 2017-08-17 04:00 | 2026-06-04 23:45 | 2024-12-04 | 2 | entero |
| LINKUSDT | 258.592 | 2019-01-16 10:00 | 2026-06-04 21:15 | 2024-12-04 | 4 | entero |
| SOLUSDT | 203.776 | 2020-08-11 06:00 | 2026-06-04 21:15 | 2024-12-04 | 4 | entero |
| TRXUSDT | 279.501 | 2018-06-11 11:30 | 2026-06-04 23:45 | 2024-12-04 | 5 | entero |

**Formato:**
- CSV ASCII, separador `,`, cabecera `datetime,open,high,low,close,volume`.
- Fecha `YYYY-MM-DD HH:MM:SS`, orden ascendente. El timestamp marca la **apertura de la barra**: la primera es la de las 04:00 y el 1H de las 04:00 agrega las M15 de 04:00 a 04:45.
- Es M15 confirmado: 0 barras fuera de la rejilla de 15 minutos.
- Hay además 9 ficheros `*_1H.csv`, que resultan ser agregados de estas mismas M15 (ver §3). **No aportan nada; propongo ignorarlos.**

**Cotización:** USDT en las 9 monedas (sufijo `USDT`).

**Exchange de origen: Binance, casi con seguridad** (no hay metadato que lo diga; es una inferencia con estas evidencias):
- Las primeras barras coinciden con la apertura de los pares USDT en Binance spot: BTC y ETH el 2017-08-17 a las 04:00 (inicio del histórico de klines de Binance), BNB el 2017-11-06, SOL el 2020-08-11 a las 06:00, DOGE el 2019-07-05 a las 12:00, etc.
- **Los 33 huecos del histórico son de todo el exchange:** afectan a todas las monedas listadas en ese momento, sin ningún hueco de una sola moneda.
- Varios coinciden con paradas documentadas de Binance: la de 33,75 h del 2018-02-08/09, la del 2019-05-15 tras el hackeo y la del 2023-03-24 de 12:30 a 14:00 UTC.
- **Verifícalo tú:** cómo se descargaron los datos (¿importación de SQX desde Binance?).

**Spot, no perpetuos:**
- El histórico empieza en 2017, antes de que existieran los perpetuos USDT-M de Binance (septiembre de 2019).
- No hay funding, mark price ni open interest.
- Los volúmenes encajan con spot.

**Zona horaria: UTC, con evidencia:**
1. Los 32 días de cambio de hora de EEUU y de la UE entre 2018 y 2025 tienen exactamente 96 barras en BTC y ETH. Una zona local con cambio de hora daría 92/100 barras o huecos y duplicados.
2. El pico intradía de volumen de BTC **se desplaza con el horario de verano de EEUU**:
   - Verano: máximo a las 14h UTC (13h y 14h: 0,057 / 0,061).
   - Invierno: máximo a las 15h UTC (13h y 14h: 0,051 / 0,061).
   - Es la firma de la apertura de Wall Street (13:30 UTC en verano, 14:30 UTC en invierno) vista desde UTC. Con un desfase fijo distinto de cero, el pico caería a otra hora.
3. Las primeras barras coinciden con horas de listado de Binance publicadas en UTC (por ejemplo, SOL el 2020-08-11 a las 06:00 UTC).

## 2. Integridad

| Moneda | NaN | Duplicados | Desorden | OHLC incoherente | Precio ≤ 0 | Volumen = 0 | Volumen < 0 | Barras planas | Congelado ≥ 8 barras (máx. racha) |
|---|---|---|---|---|---|---|---|---|---|
| ADAUSDT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 14 | 0 (5) |
| AVAXUSDT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 15 | 0 (5) |
| BNBUSDT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 303 | 0 (5) |
| BTCUSDT | 0 | 0 | 0 | 0 | 0 | **56** | 0 | 143 | 0 (5) |
| DOGEUSDT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 933 | 0 (5) |
| ETHUSDT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 221 | 0 (6) |
| LINKUSDT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 280 | 0 (5) |
| SOLUSDT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 12 | 0 (5) |
| TRXUSDT | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 14 | 0 (5) |

- **Volumen cero en BTC:** 42 de las 56 barras son de agosto a octubre de 2017, en el arranque del par. El resto cae junto a paradas (2019-06-07, 2021-02-11, 2023-03-24).
- **Volumen redondeado a enteros en 8 de las 9 monedas** (todas salvo BTC). Se pierde precisión cuando las barras tienen poco volumen, por ejemplo ETH en 2017 con barras de 5 unidades. No afecta a los precios, pero **cualquier feature de volumen fino queda contaminado**.
- **Barras planas (high = low):** son poco liquidez, no datos congelados. No hay ninguna racha de 8 o más barras idénticas.

## 3. Huecos (rejilla continua 24/7 de 15 minutos)

| Moneda | Barras faltantes (% de la rejilla) | Huecos | Horas H1 incompletas (<4 M15) | Horas sin ninguna barra |
|---|---|---:|---:|---:|
| ADAUSDT | 389 (0,136 %) | 26 | 19 | 88 |
| AVAXUSDT | 94 (0,047 %) | 10 | 8 | 20 |
| BNBUSDT | 538 (0,179 %) | 32 | 27 | 122 |
| BTCUSDT | 565 (0,185 %) | 33 | 27 | 128 |
| DOGEUSDT | 202 (0,083 %) | 18 | 14 | 44 |
| ETHUSDT | 565 (0,183 %) | 33 | 27 | 128 |
| LINKUSDT | 270 (0,104 %) | 21 | 17 | 60 |
| SOLUSDT | 94 (0,046 %) | 10 | 8 | 20 |
| TRXUSDT | 389 (0,139 %) | 26 | 20 | 88 |

**Por año** (huecos / barras faltantes, BTC): 2017 3/33 · 2018 9/262 · 2019 6/117 · 2020 8/83 · 2021 6/65 · 2022 0 · 2023 1/5 · 2024–2026 0. Las demás monedas tienen los mismos huecos en los años en que cotizan (detalle en `runs/audit_crypto.txt`).

**Cortes agrupados:** 33 intervalos distintos, y los **33 afectan a todas las monedas listadas en ese momento**. Son mantenimientos o paradas del exchange, no fallos del fichero. Los de más de 3 horas:

| Inicio → fin (UTC) | Horas | Monedas afectadas / listadas |
|---|---:|---|
| 2018-02-08 00:15 → 2018-02-09 10:00 | **33,75** | 3/3 |
| 2018-06-26 01:45 → 12:00 | 10,25 | 5/5 |
| 2019-05-15 02:45 → 13:00 | 10,25 | 6/6 |
| 2019-08-15 01:45 → 10:00 | 8,25 | 7/7 |
| 2018-07-04 00:15 → 08:00 | 7,75 | 5/5 |
| 2018-11-14 01:45 → 09:00 | 7,25 | 5/5 |
| 2017-09-06 16:00 → 23:00 | 7,00 | 2/2 |
| 2019-03-12 01:45 → 08:00 | 6,25 | 6/6 |
| 2020-02-19 11:30 → 17:30 | 6,00 | 7/7 |
| 2021-04-25 04:00 → 08:45 | 4,75 | 9/9 |
| 2021-08-13 01:45 → 06:30 | 4,75 | 9/9 |
| 2020-12-21 13:45 → 18:00 | 4,25 | 9/9 |
| 2018-10-19, 2020-06-28 | 3,75 | todas |

Muchos empiezan a las 01:45 UTC, la franja típica de mantenimiento programado. Desde 2022 solo hay un corte, el 2023-03-24 de 12:30 a 14:00. Además hay 3 huecos de menos de 1 hora. **No se rellena nada.**

**Ficheros 1H:**
- Donde la hora tiene sus 4 M15, OHLCV coincide **exactamente** con la agregación de las M15 (diferencia relativa máxima 0 en precios; 2e-16 en volumen).
- Contienen además las horas incompletas (8–27 por moneda), agregadas en silencio a partir de menos barras.
- Son un derivado de las M15, no una fuente independiente. **No usarlos.**

## 4. Anomalías

- **Saltos de escala** (splits, redenominaciones 1000X): **ninguno**. No hay ningún salto persistente de más de ×3 sin reversión.
- **Volúmenes negativos:** ninguno.
- **Volúmenes extremos** (>100× la mediana semanal): DOGE 275 barras (casi todas en el bombeo de enero de 2021, hasta 601×), TRX 7, LINK 7, AVAX 4, ADA 3, BNB 1. Coinciden con eventos reales (DOGE y TRX el 28–29 de enero de 2021, LINK el 13-06-2019).

**Movimientos reales que se conservan** (caída máxima de 15 min y rango del periodo):

| Evento | BTC | ETH | Alts |
|---|---|---|---|
| COVID, 2020-03-12/13 | −12,7 % en 15 min; rango −53 % | −12,4 %; −56 % | BNB −15,7 %, TRX −15,6 % |
| Mayo 2021, 2021-05-19/20 | −8,7 %; −31 % | −10,6 %; −45 % | LINK −18,8 %, ADA −17 % |
| LUNA, 2022-05-09/13 | −4,3 %; −22 % | −5,8 %; −29 % | AVAX −19,6 %, SOL −12,9 % |
| FTX, 2022-11-08/10 | −4,2 %; −25 % | −4,6 %; −32 % | SOL −12,4 % (rango −61 %) |
| 2019-09-24 19:30 | BTC a 7.800 (−9 % en 15 min) | ETH −11 %, rebote +9 % | real: el detector la marca como "pico que revierte", pero es el crash de ese día |
| **2025-10-10 21:15** (en el holdout; solo mirado para calidad) | — | — | AVAX low 8,52 desde 23,09; LINK 7,90 desde 17,98; BNB 860 desde 1.113 |

El evento del 10 de octubre de 2025 fue un crash de liquidaciones real. La profundidad de las mechas es propia del libro de Binance.

**Sospechosos** (marcar; propuesta abajo):

| Moneda | Barra (UTC) | Qué ocurre |
|---|---|---|
| **LINKUSDT** | **2020-03-12 10:45** | **low 0,0001** con O 2,63 / C 2,47: mecha del −99,996 %. Casi seguro un print imposible de ejecutar. Por eso el rango "COVID" de LINK sale −100 %. |
| BNBUSDT | 2017-11-06 03:45 | primera barra del par: low 0,5 con O 1,5 / C 1,7 (subasta de apertura) |
| LINKUSDT | 2020-12-23 22:15 | −8,6 % y revierte en la barra siguiente |
| SOLUSDT | 2020-09-05 11:15 | mecha −24 % (el día sí fue bajista) |
| ADAUSDT | 2024-03-05 19:45 | mecha −17 % |
| ETHUSDT | 2025-02-03 02:00 (holdout) | mecha −15 % |
| Varias | 2021 | mechas aisladas del 10–20 % en AVAX, DOGE, SOL y TRX (lista en `runs/audit_crypto.txt`) |

**Propuesta para los sospechosos** (decides tú):
- No borrar ni editar.
- Guardar un flag `suspect_wick` cuando la mecha supera en más de un 10 % el cuerpo y en más de un 8 % a las dos barras vecinas.
- En ejecución, dos opciones:
  - (a) no permitir que una barra marcada llene un stop o target más allá del extremo de sus vecinas;
  - (b) conservarla tal cual como escenario de estrés.
- Recomiendo (a) para el evaluador y (b) como etapa del embudo.

## 5. Volumen y liquidez

**Es volumen en moneda base** (unidades de la cripto), no en USDT:
- Mediana de volumen / precio: BTC 0,015; DOGE 8,3e7, etc.
- Volumen × precio da órdenes de magnitud coherentes con el spot público de Binance (BTC 2021: $2.900M diarios de mediana).
- 8 de 9 monedas lo tienen redondeado a enteros (§2).

**Mediana del volumen diario en USD** (volumen base × precio medio OHLC, millones; incluye el holdout porque es una medida de calidad, no de rendimiento):

| Moneda | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC | 10 | 242 | 268 | 614 | 2.931 | 2.664 | 1.306 | 1.922 | 1.811 | 1.408 |
| ETH | 3 | 74 | 55 | 205 | 1.790 | 1.207 | 611 | 1.033 | 1.580 | 794 |
| BNB | 1 | 17 | 38 | 54 | 637 | 172 | 103 | 190 | 178 | 82 |
| SOL | — | — | — | 4 | 185 | 165 | 93 | 578 | 590 | 254 |
| DOGE | — | — | 0,2 | 0,8 | 320 | 79 | 63 | 151 | 213 | 84 |
| ADA | — | 14 | 6 | 24 | 397 | 89 | 33 | 46 | 96 | 32 |
| LINK | — | — | 6 | 60 | 175 | 45 | 29 | 49 | 64 | 26 |
| TRX | — | 15 | 14 | 18 | 123 | 55 | 22 | 40 | 101 | 42 |
| AVAX | — | — | — | 2 | 96 | 85 | 26 | 68 | 54 | 22 |

**Inicio operable** (primera fecha en que la mediana móvil de 90 días, que solo usa el pasado, supera $20M/día) y años hasta el holdout:

| Moneda | ≥ $20M desde | Años hasta el holdout | % de días posteriores bajo $20M |
|---|---|---:|---:|
| BTC | 2017-12-29 | 6,8 | 0 % |
| ETH | 2018-01-25 | 6,9 | 0 % |
| BNB | 2018-03-14 | 6,7 | 7,9 % |
| TRX | 2018-09-08 | 6,2 | **37 %** |
| LINK | 2020-03-21 | 4,7 | 3,4 % |
| ADA | 2020-07-14 | 4,4 | 4,7 % |
| SOL | 2021-03-07 | 3,7 | 0 % |
| DOGE | 2021-02-27 | 3,8 | 0 % |
| AVAX | 2021-03-11 | 3,7 | 10 % |

**Filtro de liquidez propuesto** (causal, sin mirar el futuro): una moneda solo puede generar señales en un día si la mediana móvil de 90 días de su volumen diario en USD, calculada hasta el día anterior, es **≥ $20M**. Para tamaños pequeños o medianos de cuenta sobra con margen. Como alternativa conservadora, ≥ $50M. Este criterio no depende de ningún resultado.

## 6. Sesgo de supervivencia

- **Las 9 monedas son supervivientes de gran capitalización en 2026.** Se eligieron por ser grandes hoy. Cualquier resultado de cartera o de sección cruzada sobre estas 9 está sesgado al alza: comprar y mantener parece excelente (+355 % a +40.700 % antes del holdout) porque las perdedoras no están.
- **Faltan** (conocimiento público; verificar la lista exacta de Binance):
  - Muertas o colapsadas: LUNA (mayo de 2022), FTT (noviembre de 2022).
  - Retiradas o migradas: BCC/BCH en 2018, VEN → VET.
  - Grandes de 2017–2018 que perdieron ranking y no están: XRP, LTC, EOS, XLM, NEO, IOTA, etc.
- **Inicio real de cotización frente al inicio de los datos** (fechas públicas aproximadas; verificar):

| Moneda | Cotiza desde | Datos desde | Historia perdida |
|---|---|---|---|
| BTC | 2010 | 2017-08 (Binance USDT) | ~7 años |
| ETH | 2015-08 | 2017-08 | ~2 años |
| BNB | 2017-07 (BNB/BTC) | 2017-11 | meses |
| ADA | 2017-10 | 2018-04 | ~6 meses |
| TRX | 2017-09 | 2018-06 | ~9 meses |
| DOGE | 2013-12 | 2019-07 | ~5,5 años |
| LINK | 2017-09 | 2019-01 | ~1,3 años |
| SOL | 2020-03/04 | 2020-08 | ~4 meses |
| AVAX | 2020-09-21 | 2020-09-22 | ~0 |

Además, **los primeros meses de cada par USDT son de muy poca liquidez** (DOGE 2019–2020 < $1M/día). El filtro del §5 los excluye.

## 7. Perpetuos

**No hay datos de perpetuos**: ni funding, ni mark price, ni open interest. Todo indica que los datos son spot. Si en el futuro se opera con perpetuos, harían falta el funding histórico cada 8 h por moneda (Binance USDT-M desde 2019-09), el mark price para liquidaciones y el OI para features, además de modelar el funding como coste o ingreso.

## 8. Estructura entre monedas (solo antes del holdout)

**Solapamiento** (años de datos diarios comunes): de 4,1 años (AVAX con BTC) a 7,1 años (BTC con ETH). El periodo común a las 9 va del 2020-09-24 al 2024-11-01 (1.490 días).

**Correlación de retornos diarios con BTC, por año:**

| | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
|---|---|---|---|---|---|---|---|---|
| ETH | 0,46 | 0,82 | 0,81 | 0,87 | 0,78 | 0,90 | 0,83 | 0,82 |
| BNB | 0,55 | 0,68 | 0,57 | 0,81 | 0,65 | 0,83 | 0,63 | 0,67 |
| ADA | — | 0,83 | 0,71 | 0,75 | 0,59 | 0,78 | 0,66 | 0,75 |
| TRX | — | 0,77 | 0,63 | 0,73 | 0,68 | 0,63 | 0,59 | 0,39 |
| LINK | — | — | 0,35 | 0,67 | 0,71 | 0,76 | 0,60 | 0,68 |
| DOGE | — | — | 0,73 | 0,57 | 0,41 | 0,68 | 0,62 | 0,78 |
| SOL | — | — | — | 0,30 | 0,43 | 0,79 | 0,62 | 0,76 |
| AVAX | — | — | — | 0,34 | 0,50 | 0,81 | 0,60 | 0,73 |

**PCA** (correlación de retornos diarios, 1.490 días comunes):
- Autovalores: 5,72 · 0,73 · 0,57 · 0,43 · 0,42 · 0,37 · 0,30 · 0,28 · 0,16.
- **El primer componente (el "mercado cripto") explica el 63,6 %.**
- **Número efectivo de series independientes (participation ratio) ≈ 2,4 de 9.**
- Consecuencia: validar una estrategia en las 9 monedas no equivale a 9 pruebas independientes, sino a unas 2–3. Esto debe entrar en el conteo de ensayos y en el DSR.

## 9. Regímenes por año (solo antes del holdout; cierres diarios a las 00:00 UTC)

**Retorno anual:**

| | 2017* | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024* |
|---|---|---|---|---|---|---|---|---|
| BTC | +234 % | −72 % | +89 % | +302 % | +58 % | −65 % | +154 % | +57 % |
| ETH | +150 % | −83 % | −7 % | +463 % | +404 % | −68 % | +90 % | +54 % |
| BNB | +374 % | −28 % | +129 % | +172 % | +1.254 % | −53 % | +28 % | +134 % |
| ADA | — | −85 % | −22 % | +442 % | +647 % | −82 % | +138 % | +91 % |
| TRX | — | −57 % | −31 % | +102 % | +181 % | −29 % | +96 % | +302 % |
| LINK | — | — | +272 % | +520 % | +65 % | −73 % | +165 % | +55 % |
| DOGE | — | — | −42 % | +131 % | +2.898 % | −59 % | +27 % | +342 % |
| SOL | — | — | — | −60 % | **+9.128 %** | −94 % | +918 % | +113 % |
| AVAX | — | — | — | −10 % | +2.898 % | −90 % | +255 % | +21 % |

\*2017: desde el inicio de los datos. 2024: hasta el holdout (BTC hasta el 2024-11-01, el resto hasta el 2024-12-03).

**Volatilidad anualizada** (√365): BTC 0,44–1,11; ETH 0,47–1,21; alts 0,43–2,59. 2023 es el año más tranquilo y 2021 el más volátil.

**Drawdown máximo dentro del año:** hasta −95 % (SOL 2022) y −94 % (ETH 2018).

**Comprar y mantener hasta el holdout:**

| Moneda | Retorno total | CAGR | DD máximo |
|---|---|---|---|
| BTC | +1.592 % | +48 % | −83 % |
| ETH | +1.130 % | +41 % | −94 % |
| BNB | +40.713 % | +134 % | −80 % |
| ADA | +355 % | +26 % | −94 % |
| TRX | +901 % | +43 % | −83 % |
| LINK | +4.965 % | +95 % | −90 % |
| DOGE | +11.509 % | +141 % | −92 % |
| SOL | +6.128 % | +161 % | −96 % |
| AVAX | +1.340 % | +89 % | −94 % |

Estas cifras están infladas por el sesgo de supervivencia (§6). Los regímenes están muy concentrados: 2021 multiplica ×13 a ×92 varias alts. Cualquier estrategia larga de tendencia parecerá buena si incluye 2021. **Hay que medir por año y excluyendo 2021 como prueba de robustez.**

## 10. Propuesta de splits

Hay poca historia (4,2–7,3 años antes del holdout) y la liquidez real empieza en 2018 o en 2021 según la moneda. Propongo un **calendario común** para las 9 monedas (UTC):

| Tramo | Fechas | Uso |
|---|---|---|
| Holdout | **2024-11-01 → fin** (≥ 18 meses en todas) | sellado; se mira una vez al final |
| Bloque de selección | 2023-11-01 → 2024-10-31 (12 meses) | invisible al generador; como 2019–2022 en forex |
| Walk-forward OOS | 2021-05-01 → 2023-10-31 | ventanas rolling de 24 meses de entrenamiento y 6 meses de prueba (5 ventanas) |
| Desarrollo / primer entrenamiento | desde el inicio operable (§5) → 2021-04-30 | solo entrenamiento |

**Monedas que cumplen historia y liquidez mínimas** (≥ 3 años de liquidez ≥ $20M antes del bloque de selección, 2023-11-01):
- **Nivel A** (≥ 5 años líquidos): **BTC, ETH, BNB**. Aptas para walk-forward por moneda.
- **Nivel B** (3–5 años): **LINK (3,6), ADA (3,3)**. Aptas con cautela (menos ventanas).
- **TRX:** tiene historia suficiente, pero pasa el 37 % de los días por debajo de $20M incluso después de alcanzarlo. Apta solo con el filtro diario del §5.
- **Nivel C** (< 3 años líquidos antes de 2023-11): **SOL, DOGE, AVAX** (~2,7 años). Solo en procedimientos agregados o de sección cruzada, no para validar reglas por moneda.

Barras completas disponibles **antes del holdout** (sin contar el filtro de liquidez):

| Moneda | Años | H1 | H4 | D1 | W1 |
|---|---:|---:|---:|---:|---:|
| BTC | 7,2 | 63.057 | 15.737 | 2.599 | 347 |
| ETH | 7,3 | 63.825 | 15.929 | 2.631 | 352 |
| BNB | 7,1 | 61.888 | 15.445 | 2.551 | 341 |
| ADA | 6,6 | 58.041 | 14.488 | 2.396 | 322 |
| TRX | 6,5 | 56.713 | 14.156 | 2.341 | 314 |
| LINK | 5,9 | 51.490 | 12.853 | 2.127 | 287 |
| DOGE | 5,4 | 47.426 | 11.840 | 1.960 | 266 |
| SOL | 4,3 | 37.791 | 9.438 | 1.565 | 216 |
| AVAX | 4,2 | 36.782 | 9.186 | 1.523 | 210 |

Con el holdout común del 2024-11-01, las cifras de las 8 monedas que no son BTC bajan ~1 mes. **En D1 y W1 hay pocas barras** (200–350 semanas): estrategias semanales darían muy pocos trades para cualquier test estadístico.

## 11. Perfil de costes propuesto (spot) — **VERIFICA en tu exchange** lo marcado con ⚠

| Componente | Propuesta | Verificar |
|---|---|---|
| Comisión por lado | **0,10 %** taker (tarifa estándar de Binance spot); 0,075 % si pagas con BNB; menos en niveles VIP | ⚠ tu nivel de comisiones, descuento BNB, si operas maker o taker, y que el exchange esté disponible en tu jurisdicción |
| Slippage por lado, según la mediana de 90 días del volumen diario | ≥ $500M: 0,01 %; $100–500M: 0,03 %; $20–100M: 0,05 %; < $20M: no operable | ⚠ tamaño de orden previsto frente a la profundidad del libro en tus horas de operación |
| Spread | incluido en el slippage (tick de BTC/ETH ≈ 0,01 USDT, despreciable) | — |
| Funding | no aplica en spot. En perpetuos: funding cada 8 h, hoy sin datos (§7) | ⚠ si vas a operar perpetuos o solo spot |
| Round-trip de ejemplo | BTC taker: 2 × 0,10 % + 2 × 0,01 % = **0,22 %**; alt de $20–100M: **0,30 %** | — |
| Estrés | ×2 (como en forex) | — |

**Aviso de escala (estimación, sin medir con el evaluador):** con una volatilidad horaria típica de BTC de ~0,6–1 %, un round-trip de 0,22–0,30 % equivale a ~0,15–0,25R para un stop de 1,5 ATR en H1. Es **3–4 veces más que en forex** (~0,06R en EURUSD). En cripto, H1 queda muy penalizado por costes; H4 y D1 son más razonables.

## 12. H1 desde M15 en UTC sin fuga

Las mismas reglas que en forex, sin la lógica EET:
- La barra H1 con etiqueta `t` (UTC, hora en punto) contiene exactamente las M15 con `t ≤ ts < t + 1h`.
- `O` = primer open, `H` = máximo, `L` = mínimo, `C` = último close, `V` = suma. Se guardan `n_m15` y `close_ts = t + 1h`.
- **Sin forward-fill ni barras sintéticas:** las horas sin ninguna M15 no existen (20–128 por moneda).
- **Una hora incompleta (`n_m15 < 4`) se conserva pero no genera señales** (8–27 por moneda).
- La feature de la barra `t` está disponible en `t + 1h`. La entrada más temprana es el open de la primera M15 con `ts ≥ t + 1h`. La ejecución (SL/TP/salidas) recorre el camino M15.
- **Sin máscara de festivos:** cripto cotiza 24/7. Las paradas del exchange son huecos reales; nunca se cruza un hueco al agregar.
- **No usar los `*_1H.csv` del proveedor:** incluyen horas incompletas agregadas sin marca.
- Tests a reutilizar de forex: oráculo por groupby, invariancia por prefijo, que ninguna barra contenga M15 de fuera de su intervalo, y perturbar el futuro sin que cambie el pasado.

## 13. H4 y D1 (y W1) sin fuga

| Marco | Intervalo (UTC, cerrado a la izquierda) | Barras M15 de una barra completa | `close_ts` |
|---|---|---:|---|
| H4 | `[t, t+4h)` con `t ∈ {00,04,08,12,16,20}` | 16 | `t + 4h` |
| D1 | `[00:00, 24:00)`: **el cierre diario es a las 00:00 UTC** | 96 | día siguiente a las 00:00 |
| W1 | lunes 00:00 → lunes siguiente 00:00 UTC | 672 | lunes siguiente a las 00:00 |

- **Barra completa = todas sus M15 presentes.** Si una parada del exchange le quita barras, se conserva, se marca incompleta y no genera señales. Esto afecta, por ejemplo, al D1 del 2018-02-08/09.
- **Multi-marco sin fuga:** en una barra H1 que cierra en `T`, una feature H4, D1 o W1 solo puede usar barras de ese marco con `close_ts ≤ T`, es decir, la última barra **cerrada**, nunca la que está en formación. Hay que testearlo con invariancia por prefijo sobre el marco mayor y con perturbación del futuro.
- Barras disponibles antes del holdout: tabla del §10 (D1 1.523–2.631; W1 210–352).

## Decisiones que te tocan
1. Holdout común desde el 2024-11-01 (propuesto) o por moneda (últimos 18 meses exactos).
2. Tratamiento de las mechas sospechosas (§4): opción (a) en el evaluador + (b) como estrés, u otra.
3. Filtro de liquidez: $20M (propuesto) o $50M de mediana móvil de 90 días.
4. Universo: niveles A y B para validación por moneda; SOL, DOGE y AVAX solo en agregado.
5. Costes: confirmar comisión, BNB, maker o taker, spot o perpetuos, y jurisdicción (§11).
6. Sesgo de supervivencia: ¿conseguir datos de monedas muertas o retiradas (LUNA, FTT, BCC…) o limitarse a estrategias por moneda sin selección de sección cruzada?
7. Ignorar los `*_1H.csv` del proveedor y derivar H1, H4 y D1 desde M15.

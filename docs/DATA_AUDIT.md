# Auditoría del dataset M15 (2026-09-29)

Origen: `/mnt/c/Users/xaume/Documents/DATOS SQX 15 MINS/FOREX` (sin modificar).
Copia: `data/raw/*_15M.csv`, con `data/raw/SHA256SUMS.txt` verificado contra el origen.
Script: `scripts/audit_m15.py` (solo lectura). Salida completa: `runs/audit_m15.txt`.

## Formato

- CSV ASCII, separador `,`, fin de línea LF, cabecera `Date,Time,Open,High,Low,Close,Volume`.
- `Date` = `YYYYMMDD`, `Time` = `HH:MM:SS`. Orden cronológico ascendente.
- Timestamp = **apertura de la barra** (primera barra semanal lunes 00:00, última viernes 23:45).
- Decimales: 5 (pares USD), 3 (USDJPY), 2 (XAUUSD).
- `Volume` es volumen de ticks agregado del proveedor (escala arbitraria, no usar como dato de mercado real).

## Pares y rangos

| Par | Filas | Desde | Hasta | SHA256 (12) |
|---|---|---|---|---|
| EURUSD | 572 903 | 2003-05-05 03:00 | 2026-04-14 02:45 | fec7a62567a2 |
| GBPUSD | 572 858 | 2003-05-05 03:00 | 2026-04-14 02:45 | 06a5632608e9 |
| USDJPY | 572 792 | 2003-05-05 03:00 | 2026-04-14 02:45 | a1d555e8d0d6 |
| USDCHF | 572 697 | 2003-05-05 03:00 | 2026-04-14 02:45 | cc40c7e89406 |
| USDCAD | 566 524 | 2003-08-04 03:00 | 2026-04-14 02:45 | cbf42bd86c33 |
| NZDUSD | 566 316 | 2003-08-04 03:00 | 2026-04-14 02:45 | 3655496d43db |
| XAUUSD | 552 629 | 2003-05-05 03:00 | 2026-04-14 02:45 | 2ceadd651adc |

~23 años por par. La última semana está incompleta (termina martes 02:45).

## Zona horaria

**EET/EEST con reglas DST europeas (`Europe/Athens`: UTC+2 invierno, UTC+3 verano).**
Evidencia (EURUSD, semanas desde 2008): con `Europe/Athens` 925/954 aperturas semanales caen en domingo 17:00 Nueva York
(la apertura estándar del FX); con UTC+2 fijo solo 423; con "NY+7" (DST de EEUU) 859. Las semanas en que la apertura es
domingo 23:00 caen exactamente en marzo (entre el cambio de EEUU y el de la UE) y finales de octubre: es la firma de las reglas DST europeas.
Antes de 2008 el patrón es menos limpio (proveedor).

Consecuencias:
- El día de trading = día natural en EET (cierre 17:00 NY), 5 días de 24 h, sin "barra de domingo" salvo esas semanas de desajuste DST.
- Conversión a UTC **sin ambigüedad**: las horas inexistentes/repetidas del DST europeo caen en domingo de madrugada, con mercado cerrado.
  Verificado en los 7 ficheros: UTC resultante estrictamente creciente y único.

## Integridad

| Chequeo | Resultado |
|---|---|
| Timestamps no parseables / NaN en OHLCV | 0 en todos |
| Orden estrictamente creciente | Sí en todos |
| Timestamps duplicados / filas idénticas | 0 en todos |
| Fuera de la rejilla de 15 min | 0 |
| OHLC incoherentes (H<L, H<max(O,C), L>min(O,C), precio ≤ 0) | 0 |
| Barras planas (H==L) | 0.006–0.018 % FX; 0.068 % XAU |
| Salto open vs close previo (barras contiguas) | máx. 0.3–1.4 %; 23–44 % exactamente 0: sin costuras |

## Fines de semana

- Sábado: 8 barras (2005-04-02 00:00–00:45, las mismas en todos los pares): cola del viernes 2005-04-01 → artefacto del proveedor, inocuo.
- Domingo: 460–490 barras, todas a las 23:00 EET (semanas de desajuste DST). Son mercado real (17:00 NY).

## Huecos intrasemana

| Par | Huecos | Barras faltantes | Horas H1 incompletas |
|---|---|---|---|
| EURUSD | 81 | ~1 893 | 52 (0.04 %) |
| GBPUSD | 75 | ~1 920 | 49 (0.03 %) |
| USDJPY | 75 | ~1 970 | 45 (0.03 %) |
| USDCHF | 101 | ~2 093 | 85 (0.06 %) |
| USDCAD | 101 | ~2 033 | 79 (0.06 %) |
| NZDUSD | 127 | ~2 207 | 104 (0.07 %) |
| XAUUSD | 4 862 | ~21 084 | 2 287 (1.64 %) |

- FX: casi todo son festivos (1 de enero completo, 25 de diciembre desde ~10:00, Año Nuevo 2016 y 2021 con 3 días) y huecos de 30 min–2 h
  concentrados hacia la 01:00 EET (rollover/baja liquidez).
- XAUUSD: pausa diaria de CME (23:00–00:00 EET; desde 2013 abre el lunes a las 01:00) y cierres por festivos (Viernes Santo, Navidad).
  Es un instrumento distinto (horario, costes, volatilidad): tratarlo aparte.

## Precios anómalos

Movimientos reales (se conservan): SNB USDCHF 2015-01-15 (−20 % en una barra), flash crash GBP 2016-10-07, Brexit 2016-06-24,
BCE 2015-12-03, JPY 2016/2022 (intervenciones), XAU 2026 (máximos en ~5 400).

Ticks sospechosos en festivos (spike que revierte en la barra siguiente, liquidez nula):
- GBPUSD 2008-12-25 20:30–20:45: 1.4674 → 1.4971 → 1.4670.
- USDJPY 2009-01-01 19:30–19:45: 91.21 → 89.46 → 90.68.
- USDCHF 2007-12-25 11:30–11:45: mínimo 1.1238 y cierre 1.1568 tras bajar desde 1.148.
- XAUUSD 2012-12-25 22:00 → 2012-12-26 00:45: 12 barras planas a 1658.20 (cotización congelada).

Otros:
- USDJPY 2008-01-30 20:30: `Volume = 92233720368547` (= int64 max / 1e5, desbordamiento del proveedor).
- Volumen: escala distinta entre pares y entre épocas: no comparable.

## Decisiones pendientes (Jaime)

1. **Festivos:** propuesta: no borrar nada; generar una máscara `no_trade` (24-dic 20:00 → 27-dic 00:00 y 31-dic 20:00 → 2-ene 00:00 EET)
   en la que no se generan señales ni entradas; las posiciones abiertas siguen viéndose con los precios reales.
2. **Volumen:** no usarlo en la gramática; marcar el valor desbordado de USDJPY como NaN en el derivado.
3. **XAUUSD:** fuera del universo forex de las fases 1–5 (o tratarlo aparte con costes y horario propios).
4. **Inicio útil:** empezar el Development en 2004-01-01 (evita el arranque parcial de 2003 y el de NZD/CAD en agosto).

## Propuesta: H1 derivado de M15 sin fuga

1. **Canonicalizar M15** (`data/derived/m15/<PAR>.parquet`): `ts_utc` (apertura de barra, UTC), `ts_eet` (para la sesión y el día),
   OHLC `float64`, `volume` (NaN si está desbordado) y flag `holiday`. Nada de reordenar, deduplicar ni rellenar: el loader **falla** si encuentra
   desorden o duplicados.
2. **Agregar a H1** por hora de reloj, cerrado por la izquierda: la barra H1 con etiqueta `t` contiene exactamente las M15 con
   `t <= ts < t+1h`. `O` = primer open, `H` = máx., `L` = mín., `C` = último close, `V` = suma, `n_m15` = número de M15 (1–4), `close_ts = t + 1h`.
   Horas sin ninguna M15 **no existen** (sin forward-fill ni barras sintéticas). Como EET y UTC difieren en horas enteras, la rejilla H1 es la misma en ambas.
3. **Causalidad:** una feature de la barra H1 `t` solo está disponible en `close_ts = t+1h`. La entrada más temprana es el open de la primera M15 con
   `ts >= t+1h` (= open de la siguiente H1 existente). Horas incompletas (`n_m15 < 4`): se conservan, pero no generan señal (su close no es un cierre de hora completo).
4. **Ejecución en M15:** señales en H1, pero SL/TP/salida por tiempo se simulan recorriendo las M15 de cada hora. Esto reduce muchísimo los casos
   "SL y TP en la misma barra" (y los que queden siguen la regla conservadora: gana el SL). El kernel ligero puede usar H1 y el rico, M15; un test compara ambos.
5. **Tests del derivado:**
   - Oráculo independiente: `H1.high[t] == max(M15.high en [t, t+1h))`, igual para O/L/C/V y `n_m15`.
   - Invariancia por prefijo: construir H1 con los datos truncados en cualquier instante `T` produce exactamente las mismas barras cerradas antes de `T`
     (ninguna barra H1 cerrada cambia al añadir datos futuros).
   - Features sobre H1: calcularlas con el dataset completo y con el truncado da los mismos valores hasta `T` (detecta cualquier `shift` mal hecho, `center=True`, etc.).
   - Las M15 de un H1 no traspasan fines de semana ni huecos (nunca se agrega a través de un hueco).
6. **Procedencia:** el H1 derivado guarda el SHA256 del CSV de origen y la versión del código; se regenera si cambia cualquiera de los dos.

# ¿Es el spot un proxy válido del perpetuo USDT-M de Binance? — datos reales

Fecha: 2026-09-30.
- **Datos:** velas M15 de los perpetuos y funding histórico descargados de la API pública de Binance (`fapi.binance.com`, sin claves), **solo anteriores al holdout** (< 2024-11-01). Están en `data/raw/crypto_perp/` con `SHA256SUMS.txt` y manifiesto `docs/crypto_perp_manifest.json` (18 ficheros, última barra 2024-10-31 23:45).
- **Periodo del análisis:** desde la primera semana completa de cada perpetuo hasta el **2023-10-31**. El bloque de selección no se ha usado en ninguna métrica.
- **Script:** `scripts/crypto_spot_vs_perp.py`. Cifras completas en `docs/reports/crypto_spot_vs_perp.json`.
- **Incidencia registrada:** en la prueba de conectividad, `fundingRate?startTime=0` devolvió los 3 funding más recientes de BTC (septiembre de 2026, dentro del holdout). Se vieron en la terminal; no se guardaron ni se usan. Anotado en `trials/crypto_holdout_access.jsonl`.

## Resultados (barras M15 presentes en ambos)

| Moneda | Barras | Basis mediano | Media \|basis\| | p1 / p99 | Corr. M15 | Corr. H4 | TE H4 / vol. | Mechas bajas > 0,5 % | Stops 1,5 ATR H4 (spot / perp) | Desacuerdo de stops |
|---|---:|---:|---:|---|---:|---:|---:|---:|---|---:|
| BTC | 144.527 | −3,0 pb | 5,3 pb | −9 / +19 pb | 0,9971 | 0,99954 | 0,031 | 0,18 % | 937 / 966 | 9,3 % |
| ETH | 136.904 | −2,5 | 6,0 | −9 / +25 | 0,9952 | 0,99941 | 0,035 | 0,25 % | 863 / 933 | 9,7 % |
| BNB | 129.707 | −1,3 | 8,2 | −29 / +31 | 0,9891 | 0,99877 | 0,050 | 0,75 % | 769 / 810 | 11,8 % |
| LINK | 132.007 | −2,6 | 7,9 | −22 / +33 | 0,9933 | 0,99924 | 0,039 | 0,58 % | 726 / 759 | 8,9 % |
| ADA | 130.663 | −2,5 | 7,9 | −18 / +32 | 0,9916 | 0,99939 | 0,035 | 0,38 % | 763 / 825 | 10,7 % |
| SOL | 108.934 | −3,0 | 10,6 | −43 / +34 | 0,9798 | 0,99452 | 0,106 | 1,57 % | 641 / 662 | 9,2 % |
| DOGE | 115.262 | −2,9 | 8,2 | −24 / +39 | 0,9941 | 0,99941 | 0,034 | 1,03 % | 762 / 794 | 9,3 % |
| AVAX | 108.070 | −3,5 | 9,5 | −36 / +41 | 0,9919 | 0,99903 | 0,044 | 1,24 % | 604 / 624 | 9,6 % |
| TRX | 132.199 | −4,4 | 8,7 | −26 / +32 | 0,9862 | 0,99910 | 0,045 | 0,61 % | 798 / 828 | 11,1 % |

Cómo leer la tabla:
- **Basis** = cierre del perpetuo / cierre del spot − 1.
- **TE H4 / vol.** = desviación típica de la diferencia de retornos H4 dividida entre la volatilidad H4 del spot.
- **Desacuerdo de stops:** entre las barras H4 en que un stop hipotético a 1,5 × ATR(14) del cierre anterior salta en el spot o en el perpetuo, qué fracción salta solo en uno de los dos.

**Basis por año** (mediana): contango de +1 a +7 pb en 2020–2021 y backwardation de −4 a −7,5 pb en 2022–2023, igual en todas las monedas.

**Extremos:** solo en crashes:
- 2021-05-19 13:15–13:30: ETH −9,6 %, ADA −15,7 %, TRX −21,8 %.
- 2022-11-09 (FTX): SOL −24 %.
- 2020-03-13: BTC −3,1 %.

**LINK 2020-03-12 10:45:** spot O 2,63 / H 2,88 / **L 0,0001** / C 2,4693; perpetuo O 2,607 / H 2,88 / **L 1,813** / C 2,45.
- Confirma que el 0,0001 del spot es un print imposible.
- Pero en el perpetuo sí hubo una mecha real del −31 %.
- La corrección preregistrada (low = min(open, close) = 2,4693) es **más suave** que el perpetuo real. La variante de estrés sin corregir es **más dura**. La realidad queda entre las dos.

## Funding (antes del 2023-11-01)

| Moneda | Primer funding | Media por evento | Media \|tasa\| | Anualizado (media × 3 × 365) | % positivo | Eventos fuera de 00/08/16 UTC |
|---|---|---:|---:|---:|---:|---:|
| BTC | 2019-09-10 | +1,31 pb | 1,58 pb | **+14,4 %** | 86 % | 0 |
| ETH | 2019-11-27 | +1,67 | 1,93 | **+18,3 %** | 87 % | 0 |
| BNB | 2020-02-10 | +0,08 | 2,43 | +0,8 % | 24 % | 0 |
| LINK | 2020-01-17 | +1,61 | 2,20 | **+17,6 %** | 81 % | 0 |
| ADA | 2020-01-19 | +1,65 | 2,26 | **+18,0 %** | 81 % | 0 |
| SOL | 2020-09-13 | −0,43 | 3,28 | −4,7 % | 72 % | 75 |
| DOGE | 2020-07-10 | +1,47 | 2,18 | **+16,0 %** | 84 % | 0 |
| AVAX | 2020-09-22 | +0,78 | 2,51 | +8,5 % | 73 % | 0 |
| TRX | 2020-01-15 | +0,56 | 2,39 | +6,1 % | 67 % | 0 |

- **El funding es un coste de primer orden para los largos:** mantener un largo en perpetuo de BTC, ETH, LINK, ADA o DOGE costó ~14–18 % anual de media en 2019–2023, más que las comisiones de cualquier estrategia de baja rotación. Los cortos lo cobraron.
- Por año cambia mucho: en 2021, +28 % a +38 % anual; en 2022, entre −35 % y +3 % según la moneda.
- SOL tuvo 75 eventos con intervalos de 4 h (fuera de 00/08/16). Caen en aperturas de H4 y M15, así que el módulo los aplica igual.

## Veredicto

**El spot es un proxy válido del perpetuo para precios y retornos a escala H4 y D1, con dos reservas cuantificadas:**
1. **Retornos:** correlación H4 ≥ 0,9988 en 8 de 9 monedas (SOL 0,9945), tracking error del 3–5 % de la volatilidad (SOL 10,6 %, por FTX) y basis típico de unos pocos pb, muy por debajo de los costes (≥ 12 pb por round-trip). Para el P&L de estrategias H4/D1 la diferencia es de segundo orden.
2. **Stops (reserva 1):** el perpetuo toca stops un **3–8 % más a menudo** que el spot, y ~10 % de los eventos de stop no coinciden. Con el spot como proxy, **los resultados de estrategias con stops salen algo optimistas**. Mitigación: el estrés de costes ×2 y, en la Parte 2, un chequeo solo informativo que reopera las estrategias seleccionadas con precios del perpetuo (añadido al preregistro).
3. **Crashes (reserva 2):** en días de pánico (mayo de 2021, FTX) el basis llega al −10 % / −24 % durante minutos. Lo que ocurra en esas barras con precios spot no representa el perpetuo.
4. **El funding no es proxy de nada:** se aplica el histórico real. Antes de que existiera cada perpetuo (2017–2020 según la moneda) rige la regla preregistrada: el funding medio en valor absoluto se cobra a ambos lados.

**Mi recomendación** (decides tú): para la Parte 2 sería más fiel usar **precios del perpetuo donde existen** (desde 2019-09 para BTC y 2020 para el resto; todo el periodo OOS de 2021–2023 está cubierto) y el spot solo antes. Tu instrucción fija el spot como proxy, así que el preregistro lo mantiene y añade el chequeo con perpetuo como informe.

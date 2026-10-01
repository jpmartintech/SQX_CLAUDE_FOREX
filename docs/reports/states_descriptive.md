# Fase S — Fase descriptiva de los estados del ribbon EMA (sin retornos)

Fecha: 2026-10-01.
- **Preregistro:** `configs/states_ribbon.yaml` (`1748f2d`, commiteado antes de esta ejecución).
- **Script:** `scripts/states_describe.py`. Cifras completas en `docs/reports/states_descriptive.json`.
- **Periodo:** desarrollo 2004-01-01 → 2015-01-01 (hora local EET). Antes solo hay calentamiento de EMAs, ATR y percentiles.
- **Datos cortados en 2019-01-01:** 2019–2022 y el holdout no se cargan.
- **No se ha leído ningún retorno:** solo estados, duraciones y transiciones.

## Resultado frente a los criterios de persistencia preregistrados

**Nivel de sistema:** el estado combinado cambia 4,1–4,3 veces cada 100 barras H1 en los 6 pares, muy por debajo del máximo de 15. **Cumple.** La fase continúa.

**Por timeframe:** máximo de 25 cambios por cada 100 barras y duración media ≥ 3 barras en cada estado con ≥ 1 % del tiempo:
- Todos los timeframes cumplen el máximo de cambios (10,6–12,5).
- Cumplen la duración **salvo EURUSD D1**: algún estado de D1 con ≥ 1 % del tiempo dura de media 2,64 barras.
- Se reporta tal cual. El preregistro no asocia ninguna consecuencia a este criterio por timeframe y no se cambia nada. D1 solo entra en el estado combinado a través de su orden (régimen), que es más estable. **Decisión para Jaime.**

## Tabla por par

| par | cambios/100 H1 (combinado) | estados utilizables | tiempo cubierto | H1 / H4 / H8 / D1 cambios por 100 barras | duración mín. (estados ≥1 %) H1/H4/H8/D1 |
|---|---:|---:|---:|---|---|
| EURUSD | 4.26 | 18 | 98.4% | 11.3 / 11.4 / 11.3 / 12.5 | 4.77 / 4.35 / 4.18 / 2.64 ✗ |
| GBPUSD | 4.26 | 18 | 98.3% | 11.3 / 12.0 / 12.4 / 12.2 | 4.67 / 3.90 / 3.98 / 3.00 |
| USDJPY | 4.21 | 17 | 97.1% | 10.7 / 11.6 / 11.3 / 11.8 | 4.50 / 4.02 / 4.58 / 3.79 |
| USDCHF | 4.22 | 18 | 98.4% | 11.5 / 11.4 / 11.7 / 11.8 | 4.73 / 4.27 / 3.96 / 3.75 |
| USDCAD | 4.24 | 17 | 97.1% | 11.4 / 11.7 / 12.1 / 12.0 | 4.77 / 3.78 / 3.29 / 3.69 |
| NZDUSD | 4.12 | 17 | 97.5% | 10.6 / 11.4 / 11.3 / 11.9 | 4.85 / 3.53 / 4.10 / 4.40 |

## Estados combinados de EURUSD (desarrollo)

Utilizable = fracción ≥ 1 % y duración media ≥ 6 barras H1 (preregistrado). Los estados 2, 6, 11, 20 y 24 no aparecen (por ejemplo, pendiente H4 bajista con orden H1 alcista).

| # | estado combinado | fracción | duración media (H1) | ¿utilizable? |
|---:|---|---:|---:|---|
| 0 | reg −1 · H4 slope −1 · H1 order −1 | 7.4% | 47.8 | sí |
| 1 | reg −1 · H4 slope −1 · H1 order 0 | 2.1% | 13.1 | sí |
| 3 | reg −1 · H4 slope 0 · H1 order −1 | 1.0% | 10.9 | sí |
| 4 | reg −1 · H4 slope 0 · H1 order 0 | 3.6% | 20.1 | sí |
| 5 | reg −1 · H4 slope 0 · H1 order +1 | 0.5% | 9.8 | no |
| 7 | reg −1 · H4 slope +1 · H1 order 0 | 0.7% | 10.0 | no |
| 8 | reg −1 · H4 slope +1 · H1 order +1 | 1.4% | 23.4 | sí |
| 9 | reg 0 · H4 slope −1 · H1 order −1 | 16.8% | 44.6 | sí |
| 10 | reg 0 · H4 slope −1 · H1 order 0 | 5.2% | 12.5 | sí |
| 12 | reg 0 · H4 slope 0 · H1 order −1 | 2.1% | 11.1 | sí |
| 13 | reg 0 · H4 slope 0 · H1 order 0 | 9.7% | 19.9 | sí |
| 14 | reg 0 · H4 slope 0 · H1 order +1 | 1.5% | 9.7 | sí |
| 15 | reg 0 · H4 slope +1 · H1 order −1 | 0.0% | 1.0 | no |
| 16 | reg 0 · H4 slope +1 · H1 order 0 | 4.0% | 12.9 | sí |
| 17 | reg 0 · H4 slope +1 · H1 order +1 | 14.4% | 48.5 | sí |
| 18 | reg +1 · H4 slope −1 · H1 order −1 | 3.1% | 29.3 | sí |
| 19 | reg +1 · H4 slope −1 · H1 order 0 | 1.2% | 9.6 | sí |
| 21 | reg +1 · H4 slope 0 · H1 order −1 | 0.5% | 10.6 | no |
| 22 | reg +1 · H4 slope 0 · H1 order 0 | 5.3% | 19.1 | sí |
| 23 | reg +1 · H4 slope 0 · H1 order +1 | 2.1% | 14.4 | sí |
| 25 | reg +1 · H4 slope +1 · H1 order 0 | 3.3% | 11.7 | sí |
| 26 | reg +1 · H4 slope +1 · H1 order +1 | 14.1% | 49.6 | sí |

**Estados que se testearán** (fijados ahora, antes de leer retornos): los utilizables con dirección definida, es decir, régimen ≠ 0 o, si el régimen es 0, pendiente H4 ≠ 0.
- En EURUSD son 15: 0, 1, 3, 4, 8, 9, 10, 16, 17, 18, 19, 22, 23, 25, 26.
- Los estados 12, 13 y 14 son utilizables pero sin dirección: solo se describen.
- Con 3 horizontes (6, 24 y 120 barras H1) suman **45 tests** para la corrección de Holm.

**Lectura:**
- Los tres estados alineados (bajista 0, alcista 26 y neutral con H4 y H1 alcistas, 17) son los más persistentes: 45–50 barras H1 de media.
- El régimen es neutral (D1 y H8 no coinciden) el 54 % del tiempo en EURUSD.
- La histéresis cumple su función: el estado combinado cambia ~4 veces cada 100 horas.

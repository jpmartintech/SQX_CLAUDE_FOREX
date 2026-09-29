# PROGRESS

## Fase actual
0 (bootstrap + auditoría de datos). Fase 1 **no iniciada**: pendiente de revisión de la auditoría por Jaime.

## Decisiones tomadas
- Proyecto nuevo; referencia en `reference/SQX_ENGINE` (solo lectura).
- 2026-09-29: el dato base es **M15** (no H1). H1 se deriva de M15 (ver `docs/DATA_AUDIT.md`, sección "Propuesta").
- Datos copiados sin modificar a `data/raw/` con `SHA256SUMS.txt` verificado contra el origen.
- Zona horaria de los CSV: EET/EEST (`Europe/Athens`), timestamp = apertura de barra.

## Resultados medidos (auditoría 2026-09-29)
- 7 ficheros (6 pares FX + XAUUSD), ~23 años, 552k–573k filas cada uno.
- 0 NaN, 0 duplicados, orden estrictamente creciente, 0 incoherencias OHLC.
- Huecos intrasemana FX: 75–127 por par (~0.35 % de barras), casi todos festivos. XAUUSD: 4 862 (pausa diaria CME).
- Anomalías: 3 spikes en festivos (GBPUSD 2008-12-25, USDJPY 2009-01-01, USDCHF 2007-12-25), XAU congelado 2012-12-25/26,
  volumen desbordado en USDJPY 2008-01-30 20:30, 8 barras de sábado en 2005-04-02.

## Pendiente de decisión (Jaime)
1. Máscara `no_trade` en festivos (Navidad, Año Nuevo) en lugar de borrar datos.
2. Ignorar volumen; NaN en el valor desbordado.
3. XAUUSD fuera de las fases 1–5.
4. Development desde 2004-01-01.

## Siguientes pasos
- Fase 0: `pyproject.toml`, venv, pytest, lint, `sqxf --help`.
- Fase 1: loader M15 canónico + constructor H1 con tests (oráculo, invariancia por prefijo), después el evaluador.

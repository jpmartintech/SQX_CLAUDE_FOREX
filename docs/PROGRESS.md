# PROGRESS

## Fase actual
**Fase C1 Parte 2 hecha (rama `phase-c1-crypto`, run `crypto_c1_wf_r2`): ninguna variante cumple los criterios** (`docs/reports/phase-c1.md`).
Nulo completo (200/200): H4 p = 0,378 / DSR 0,074; D1 p = 0,129 / DSR 0,242.
Contador: 4.489.550 evaluaciones sobre datos reales. Bloque de selección y holdout cripto: sin tocar.

**Fase C1 (cripto), Parte 1 hecha (rama `phase-c1-crypto`):** módulo cripto, datos de perpetuos y funding, informe spot frente a perpetuo
(`docs/reports/crypto_spot_vs_perp.md`) y preregistro `configs/crypto_c1.yaml` commiteado. **No se ha ejecutado ninguna búsqueda.**
Pendiente: revisión de Jaime de los umbrales propuestos y de la recomendación de usar precios de perpetuo.
Remoto GitHub pendiente: `sudo apt install gh` → `gh auth login` → `gh repo create SQX_CLAUDE_FOREX --private --source . --remote origin`
→ `git push origin --all && git push origin --tags`.

**Auditoría cripto hecha (rama `phase-c0-crypto-audit`, sin merge): `docs/CRYPTO_DATA_AUDIT.md`. Esperando revisión de Jaime.**

**Fase 2c hecha (rama `phase-2c-6pairs`, sin merge).** Ninguna variante del procedimiento cumple los criterios. Esperando revisión de Jaime.
Informes: `docs/reports/phase-2.md` (`v0.2-compact`), `phase-2b.md` (`v0.2b`), `phase-2c.md`.

## Resultados medidos
- Fase 2: 99.000 → walk-forward 415 → DSR 0.
- Fase 2b (EURUSD): genético +0,0294R OOS, p = 0,109; sin edge.
- Fase 2c (6 pares, run `phase2c_wf_6pairs_r1`): genético agregado −0,0317R (×1), −0,0848R (×2), p = 0,066 frente a 60 nulos por
  bloques, DSR 0,010 (N = 6); control aleatorio −0,0511R. La variante `x2robust` da la misma selección que la base en el genético.
  Solo EURUSD (+0,029) y USDCAD (+0,004) quedan en positivo.
- Contador: 2.889.550 evaluaciones sobre datos reales (2.619.000 de selección). Procedimientos sobre 2010–2018: 6.
- 2019–2022: sin cargar. Holdout: 0 accesos. `pytest -q`: 83 passed (ya no escribe en el contador).

## Pendiente de decisión (Jaime)
0. Cripto: las 7 decisiones al final de `docs/CRYPTO_DATA_AUDIT.md` y el diff propuesto `docs/proposals/CLAUDE_md_crypto.diff`.
1. Cambiar de hipótesis (sesión/hora, horizontes diarios, fuerza relativa entre divisas) o parar la búsqueda con esta gramática.
2. Swap y validación de costes por par con un broker real antes de cualquier búsqueda nueva.
3. Merge de `phase-2c-6pairs`.
4. Decisiones anteriores abiertas: valores por defecto de datos, exposición del holdout en la auditoría.

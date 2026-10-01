# BLOCKERS

## 2026-10-02 — El test predictivo de la Fase S no detecta ni edges grandes en una ventana de 4 años (control positivo)
**Estado:** documentado; no se ha cambiado nada del embudo ni de sus umbrales (fuera del alcance de la tarea). Decide Jaime.

**Evidencia** (`docs/reports/positive_control.md`, `configs/positive_control.yaml`, 50 réplicas por tamaño):
- **Potencia** del test predictivo completo (Holm sobre 45 · neto ≥ 1 pip · ≥ 3/4 años · ≥ 3/5 pares) para un edge causal inyectado tras el
  estado 26 a 24 h, en los 6 pares:
  - +2 pips: 0 %;
  - +5 pips: 0 %;
  - +10 pips: 4 %;
  - **+20 pips: 16 %** (edge realizado +21,7 ± 4,9 pips).
- **Falsos positivos** en el mundo nulo: 0/50 réplicas con algún aceptado (en familia).

**Diagnóstico** (sin cambiar nada):
1. **Ruido de la media condicional en 4 años:** en el mundo nulo, la media neta a 24 h del estado 26 varía entre réplicas con
   desviación típica de 8,4 pips (de −34 a +13). Las barras de un mismo estado vienen en rachas largas (~50 H1) y los retornos a 24 h se
   solapan, así que el tamaño efectivo de la muestra es muy inferior al número de barras (~2.700–3.800).
2. **Holm sobre 45 tests:** el menor p necesita ≤ 0,05/45 = 0,0011. Con +20 pips solo el 20 % de las réplicas llega; con p ≤ 0,05 sin
   corregir llegaría el 72 %.
3. **Estabilidad de ≥ 3 de 4 años:** cada año contiene ~1/4 de la muestra; con +20 pips solo el 52 % de las réplicas tiene 3 o más años
   positivos.
4. **Bloque del bootstrap:** max(5·h, 120) = 120 barras H1 para h = 24, del orden de 2–3 rachas del estado. El p del preregistro (fracción
   de medias ≤ 0) es un percentil, no un test centrado; con ruido de 8 pips da p crudos medianos de 0,007 incluso con +20 pips.
5. **Costes:** irrelevantes aquí (1,5 pips frente a un ruido de 8,4).
6. **Ventana:** 4 años. El efecto mínimo detectable con 80 % de potencia, por extrapolación y no medido, rondaría los 33 pips netos a 24 h
   (≈ (3,1 + 0,84) × 8,4), un tamaño irreal para FX.

**Implicación:** el nulo de la Parte 2 (0/45) no puede descartar edges condicionales de hasta al menos +20 pips a 24 h por estado. Con este
diseño, el test predictivo no tiene capacidad para validar estados en una ventana de 4 años.

## 2026-10-02 — Control positivo de estrategias: ningún nivel preregistrado de persistencia hace rentable la calibración
- AR(1) en los retornos H4 con φ = 0 / 0,03 / 0,06 / 0,12: mean R ×1 de −0,046 / −0,041 / −0,036 / −0,023 y 0 % aceptadas en las 20
  réplicas de cada nivel.
- La mejora es monótona, así que la tubería sí responde a la persistencia, pero no alcanza la rentabilidad tras costes y swap en el
  rango preregistrado. No se puede fijar el nivel a partir del cual cumpliría la aceptación (está por encima de φ = 0,12).
- Diagnóstico: la memoria del AR(1) se agota en 1–2 barras H4, mientras que el cruce EMA50/200 con trailing de 3 ATR responde a tendencias
  largas. La ratio de varianzas a largo plazo con φ = 0,12 es solo ≈ 1,27. Los costes y el swap conservador restan ~0,05R por trade
  (Parte A: CAL1 −0,019R de costes y −0,036R de swap).

## 2026-10-02 — No hay estrategias de hora o sesión en la gramática g1
- El control de la fábrica pedía plantar una estrategia "basada en hora o sesión" de la gramática actual. g1 (170 predicados) no tiene
  ningún predicado temporal; se planta en su lugar una estrategia de estructura y volatilidad (`configs/funnel_control.yaml`, V).
- Por tanto, ni la Fase 2 ni este control pueden decir nada de edges de sesión: el genético no puede generarlos. Añadir predicados
  de sesión sería ampliar el espacio de búsqueda (Fase 6), con su propio preregistro y conteo de ensayos. Decide Jaime.

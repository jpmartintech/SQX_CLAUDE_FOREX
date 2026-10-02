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

## 2026-10-02 — El embudo de la Fase 2 no deja pasar edges reales plantados, ni con Sharpe ≈ 1 (control de la fábrica)
**Estado:** documentado; no se ha cambiado ningún umbral de `configs/funnel.yaml`. Decide Jaime. Detalle en
`docs/reports/funnel_control.md`.

**Evidencia** (EURUSD sintético de 15 años, pool de 20.000 estrategias aleatorias de g1 más la plantada, N del DSR = 168.590,
10 réplicas por combinación):
- **Supervivencia al embudo completo = 0/10 en todos los tamaños**, para la estrategia de tendencia (T) y la de reversión (R). Sharpe
  realizado medio en las réplicas:
  - T: 0,26 / 0,42 / 0,63 / 1,03;
  - R: 0,26 / 0,51 / 0,87 / 1,16.
- **Falsos positivos** en el mundo nulo: 0/10 (de media 1,1 estrategias del pool superan el walk-forward y ninguna el DSR).
- **Qué mata:**
  - **Etapa básica** con Sharpe ≤ 0,6: PF ≥ 1,15 y mean R ≥ 0,05R en 2004–2014; el edge plantado da de +0,03 a +0,05R por trade.
  - **Deflated Sharpe** con los edges mayores: el walk-forward deja pasar el 60–70 % con Sharpe ~1,0–1,2, y el DSR mata a todas
    (DSR mediano 0,00).

**Diagnóstico** (sin cambiar nada):
1. **El listón del DSR es inalcanzable para un edge realista.** Con N = 168.590 y la Var[SR] del pool (Sharpe diario, 0,0016 → desviación
   anual de 0,65), el Sharpe máximo esperado bajo el nulo es ≈ 2,6–2,7 anual. Una estrategia con Sharpe 1,0–1,2 sostenido durante
   15 años tiene DSR ≈ 0.
2. **La Var[SR] del pool no mide solo ruido:** refleja diferencias estructurales entre estrategias aleatorias (el arrastre de costes
   varía mucho), lo que infla SR\*.
3. **El N efectivo por clustering** (785 grupos de cada 2.000, N_eff ≈ 66.000) apenas baja el listón: con N_eff el DSR de las plantadas
   sigue ≈ 0 (Parte C).
4. **La etapa básica exige mean R ≥ 0,05R y PF ≥ 1,15;** un edge de Sharpe 0,3–0,6 con ~1.500 trades en 15 años son ~0,03–0,05R
   por trade, justo en el umbral, y cae por ruido.
5. **Implicación:** los 0 supervivientes de la Fase 2 no indican ausencia de edges aprovechables (Sharpe 0,6–1,0). Con estos umbrales y
   este N, el embudo no los habría dejado pasar.

## 2026-10-02 — El embudo v2 calibrado por simulación no es válido (Fase K, run `funnel_v2_k2`)
- **Resultado:**
  - FP del diseño elegido (D1, t de R): 3 % en 100 mundos nulos independientes. Umbral p95 del máximo nulo: t = 3,65.
  - Supervivencia ≥ 80 % con Sharpe realizado ≤ 1,0: ninguna plantada. Las mejores fueron RS 1,30 → 20 % y TL 1,16 → 10 %.
  - Incluso con Sharpe ≈ 2 (TL 1,5) la supervivencia es del 60 %. Informe: `docs/reports/funnel_calibration.md`.
- **Causa:** con 4 años de OOS, una estrategia con Sharpe ~1 tiene t ≈ 2. El máximo de las ~9.400 candidatas nulas que llegan a la puerta
  tiene mediana 2,57 y p95 3,65. En muestra, la estabilidad (3 bloques positivos) y los costes ×2 matan los edges ≤ 0,6.
  El genético no reconstruye la plantada (correlación máxima mediana 0,51).
- **Consecuencia:** no se aplica a datos reales. Un nulo de este embudo no descartaría edges de Sharpe ≤ ~1,3.
- **Opciones (decisión de Jaime; cada una requiere un nuevo preregistro):**
  1. **Reducir el número efectivo de candidatas que llegan a la puerta.**
     - Elegir en entrenamiento solo las K mejores (p. ej. 10–50) por fitness o por cluster.
     - El umbral bajaría de forma aproximada con log K.
  2. **Alargar el OOS.**
     - Walk-forward con reoptimización (que incluya 2019–2022).
     - Validación cruzada combinatoria (CPCV) sobre 2004–2018, en lugar de un único bloque de 4 años.
  3. **Usar el estadístico conjunto de varios pares** como réplica independiente (el t combinado crece con √pares si el edge es común).
  4. **Aceptar un objetivo de potencia menor** o un edge mínimo detectable mayor (Sharpe ≈ 2). Hay que decirlo explícitamente.

# AUTONOMY.md — protocolo de trabajo autónomo

Este archivo manda sobre cómo iteras cuando trabajas sin supervisión. Complementa a `CLAUDE.md` (que define el proyecto, las reglas de corrección y las fases). Si hay conflicto, gana `CLAUDE.md`.

## 1. Qué significa "éxito"

El objetivo final es una fábrica que produzca estrategias rentables y un portfolio que las combine. **Pero "rentable en el backtest" no es la condición de parada de nada.** Con miles de estrategias probadas, cualquier filtro deja pasar suerte.

Éxito, en orden:

1. **Corrección:** tests en verde, invariantes de causalidad, unidades y costes cumplidos.
2. **Honestidad estadística:** cada resultado va acompañado del número de ensayos, del Deflated Sharpe / PBO y del comportamiento fuera de muestra.
3. **Robustez:** las estrategias sobreviven en walk-forward, con costes estresados y en otros pares.
4. **Rentabilidad:** solo cuenta si 1–3 se cumplen. Se mide con drawdown y Calmar, nunca sola.

**Si con los umbrales corregidos no sobrevive ninguna estrategia, ese es un resultado válido.** Se reporta tal cual. Está prohibido aflojar umbrales para "obtener algo".

## 2. Bucle de cada iteración

1. Lee `docs/PROGRESS.md` y `docs/DECISIONS.md`. Comprueba en qué fase estás y qué falta para cerrarla (criterios de aceptación en `CLAUDE.md`).
2. Elige **una** tarea pequeña que acerque la fase a su criterio de cierre. Formula una hipótesis o un objetivo concreto y comprobable.
3. Si es un bug o una regla de corrección: escribe primero el test que falla.
4. Implementa. Archivos completos reescritos, `.py`, sin notebooks.
5. Ejecuta `pytest -q`. Si algo falla, corrige. Si el mismo enfoque falla dos veces, cambia de enfoque.
6. Mide y registra el resultado (números reales, no estimaciones) en `docs/PROGRESS.md`.
7. Commit en la rama de la fase con mensaje descriptivo. Nunca dejes un commit con tests en rojo.
8. Vuelve al paso 1.

## 3. Qué puedes decidir solo y cuándo parar

**Decides tú, y lo anotas en `docs/DECISIONS.md`** (fecha, decisión, alternativas, motivo): diseño de módulos, estructuras de datos, optimizaciones de rendimiento, orden de tareas dentro de una fase, elección de librerías estándar, valores por defecto de configuración que no dependan de resultados fuera de muestra.

**Paras y dejas el asunto planteado en `docs/BLOCKERS.md`:**
- Una decisión irreversible o destructiva (borrar datos, reescribir historia de git, cambiar el dataset base).
- Algo que requiera credenciales, sudo, red externa distinta de GitHub y gestores de paquetes, o salir de `~/SQX_CLAUDE_FOREX`.
- Tres iteraciones seguidas sin progreso medible.
- Un resultado **demasiado bueno** (por ejemplo, PF > 2 sostenido, Sharpe anual > 3 tras costes, o casi ninguna pérdida). Antes de celebrarlo, busca fuga de información, costes ausentes o unidades erróneas. Si no lo explicas, para.
- Ambigüedad en los requisitos que cambie el diseño de forma importante.
- La fase cumple sus criterios de cierre (ver sección 7).

## 4. Reglas anti-sobreajuste (innegociables)

1. **Pre-registro de umbrales.** Los umbrales del embudo y de aceptación se fijan en `configs/` y se commitean **antes** de ver resultados de la fase que los usa. Cambiarlos exige una entrada en `DECISIONS.md` con un motivo que no se base en resultados fuera de muestra. Cada cambio se cuenta.
2. **Contador de ensayos.** Toda estrategia evaluada suma al contador persistente. El Deflated Sharpe y el PBO usan ese número. No se resetea nunca.
3. **Holdout sellado.** El tramo 2023 hasta abril de 2026 no se carga en ningún experimento, ni para "solo mirar". Se evalúa una única vez, al final de la Fase 5, con una función que registra el acceso. Si por accidente se toca, anótalo en `DECISIONS.md` y el holdout queda quemado.
4. **Selección y medición en periodos distintos.** Un portfolio nunca se reporta sobre el mismo periodo con el que se eligió.
5. **Sin pescar.** No lances búsquedas repetidas cambiando semilla o configuración hasta que "salga algo". Cada run tiene hipótesis, config commiteada y semilla registrada.
6. **Los datos de referencia son de solo lectura.** No modifiques `data/raw/` ni `reference/`.

## 5. Trabajos largos

- Lanza las búsquedas genéticas y otros trabajos largos en segundo plano (`nohup ... > logs/run_X.log 2>&1 &`), guarda el PID y el config, y **no gastes turnos esperando**: haz otra tarea útil de la fase o comprueba el log a intervalos largos.
- Los runs deben ser reanudables (checkpoints) y reproducibles (semilla, hash del dataset, versión del código, config).
- Mide antes de optimizar: perfila y documenta el cuello de botella real.

## 6. Git

- Una rama por fase (`phase-N-nombre`). Commits pequeños. `pytest -q` en verde antes de cada commit.
- Al cerrar la fase: informe en `docs/reports/phase-N.md`, merge a `main`, tag `vN.0`.
- Nunca `git push --force` ni reescribir historia de `main`. Si hay remoto, haz push al terminar cada fase.

## 7. Cierre de fase

Una fase se cierra cuando **todos** sus criterios de aceptación de `CLAUDE.md` se cumplen y están demostrados por tests o por números medidos. Entonces:

1. Escribe `docs/reports/phase-N.md` con: qué se construyó, qué se midió (con cifras), qué decisiones se tomaron, limitaciones conocidas y riesgos.
2. Actualiza `docs/PROGRESS.md`.
3. Haz merge y tag.
4. **Para y espera revisión humana.** No empieces la fase siguiente sin que Jaime la apruebe.

Al terminar, responde con una línea: `FASE N COMPLETA` o `BLOQUEADO: <motivo>`.

## 8. Informe honesto

En cualquier informe: cifras reales, número de ensayos, resultados fuera de muestra, drawdown y lo que no funcionó. Sin adjetivos triunfales. Si algo es una suposición, dilo.

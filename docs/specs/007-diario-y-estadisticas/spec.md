# 007 · Diario y estadísticas

- **Estado:** Borrador, aplazada a la fase 6 (2026-10-16). El usuario aclaró que por "estrategias" quería decir backtest de estrategias escritas en código ([spec 008](../008-backtest-de-estrategias/spec.md), fase 5), pero el diario manual también le interesa. Antes de aprobarla hay que revisarla: la "estrategia" de una operación manual debería poder ser una de `estrategias/`, para comparar el trading manual con el backtest.
- **Fase:** 5
- **Creada:** 2026-10-16 · **Actualizada:** 2026-10-16

## Problema

Con las fases 3 y 4 se opera y se ve el balance de cada cuenta, pero no se sabe **qué** funciona. Para mejorar hay que poder decir "esto lo hice con la estrategia X" y luego preguntar: ¿qué acierto tiene X en NQ durante la sesión de Nueva York?, ¿gano más por la mañana o por la tarde?, ¿cuánto pierdo por no respetar el stop? Hoy las operaciones no tienen etiqueta, no se pueden filtrar y no hay métricas por grupos.

## Alcance

**Incluye:**
- Etiquetar cada operación cerrada con una estrategia, etiquetas libres (setup, errores...) y notas, al operar o después.
- Capturas del gráfico asociadas a cada operación.
- Una ventana "Diario" con la lista de operaciones, filtros, métricas, desglose por grupos y curva de capital.
- Conservar las operaciones en el diario aunque se reinicie la cuenta.

**No incluye:**
- Exportar a CSV (fase 7).
- Volver a ver una operación pasada en el gráfico (saltar el replay a su fecha). Puede añadirse en la fase 7.
- MAE y MFE (cuánto fue en contra y a favor antes de cerrar). Hacen falta las velas de cada operación; se puede añadir después **(decidido por Claude)**.
- Comparar con el backtest automático (fase 6).

## Requisitos

### Qué es una operación
1. **RF-1 · Operación.** La unidad del diario es la operación de la spec 005: desde que una posición sale de cero hasta que vuelve a cero, con su contrato, lado, entrada y salida medias, cantidad, PnL bruto, comisiones, PnL neto, apertura, cierre y SL inicial. Solo entran las cerradas.
2. **RF-2 · Ganadora o perdedora.** Se clasifica por el PnL **neto** (con comisiones), como el resumen de cuentas de la 006: ganadora si es > 0, perdedora si es < 0, y nula si es 0.
3. **RF-3 · Riesgo y R.** Si la operación tuvo SL desde la entrada, el riesgo inicial es |entrada − SL inicial| × $ por punto × contratos de entrada, y el resultado en R es PnL neto ÷ riesgo inicial. Sin SL inicial no tiene R, y las métricas en R lo dicen ("R de 12 de 15 operaciones").

### Anotar
4. **RF-4 · Estrategias.** Hay una lista de estrategias con nombre y descripción opcional. Se crean, se renombran y se borran desde el diario. Al borrar una, sus operaciones pasan a "Sin estrategia". Son comunes a todas las cuentas.
5. **RF-5 · Estrategia al operar.** La boleta tiene un selector de estrategia ("Sin estrategia" por defecto) que se recuerda entre órdenes. La operación que abre una orden lleva esa estrategia. Así no hay que anotar después **(decidido por Claude)**.
6. **RF-6 · Anotar después.** En el diario, cada operación se puede editar: estrategia, etiquetas y notas. Las etiquetas son palabras libres (por ejemplo "ruptura", "fuera de plan", "moví el stop") y el campo sugiere las que ya existen. Una operación puede tener varias.
7. **RF-7 · Desde el panel.** En la lista de operaciones cerradas del panel de operar, cada fila tiene un botón "Anotar" que abre esa operación en el diario. No sale nada solo al cerrar, para no cortar el play **(decidido por Claude)**.
8. **RF-8 · Capturas.** Al cerrarse una operación, si el gráfico muestra su instrumento, se guarda sola una captura del gráfico (con dibujos, indicadores y marcas). En el detalle de una operación hay además un botón para añadir una captura del gráfico tal como está ahora, y otro para borrar cada captura. Se guardan como PNG en `datos/capturas/` **(decidido por Claude)**.

### Conservar
9. **RF-9 · Reiniciar no borra el diario.** Al reiniciar una cuenta (spec 005, RF-27; spec 006, RF-14) sus operaciones dejan de contar para el balance, los días y las reglas del reto, pero siguen en el diario, marcadas con el intento al que pertenecían. Cambia lo que decían esas specs, que las borraban **(decidido por Claude)**.
10. **RF-10 · Borrar sí borra.** Borrar una cuenta (spec 005, RF-28) borra también sus operaciones del diario y sus capturas. El aviso de confirmación lo dice.

### Ver y filtrar
11. **RF-11 · Ventana "Diario".** Un botón "Diario" en la barra de arriba, junto a "Cuentas", visible siempre (también fuera del replay), abre una ventana grande con los filtros arriba y, debajo: métricas, curva de capital, desglose y lista de operaciones.
12. **RF-12 · Filtros.** Se combinan entre sí. Al cambiar uno se recalcula todo lo de la ventana:
    - **Cuenta:** todas o una, y si incluir los intentos anteriores (por defecto, sí).
    - **Estrategia:** todas, una o "Sin estrategia".
    - **Etiqueta:** cualquiera, o las operaciones que tengan una concreta.
    - **Instrumento:** NQ, ES o GC (mini y micro juntos).
    - **Lado:** largos, cortos o los dos.
    - **Sesión:** Asia, Londres o Nueva York, según la hora ET de la **apertura** y con los mismos horarios que el botón de momento aleatorio (Asia 18:00–03:00, Londres 03:00–09:30, Nueva York 09:30–17:00).
    - **Día de la semana**, del día de trading de la apertura (el que empieza a las 18:00 ET de la víspera, como la vela diaria).
    - **Periodo:** desde y hasta (fechas del mercado), con atajos por año.
13. **RF-13 · Métricas.** De las operaciones filtradas:
    - Operaciones, ganadoras, perdedoras y % de acierto.
    - Beneficio neto, bruto y comisiones.
    - Ganancia media, pérdida media y su proporción.
    - **Profit factor:** suma de ganancias netas ÷ suma de pérdidas netas (en valor absoluto). Sin pérdidas se muestra "∞".
    - **Esperanza:** beneficio neto ÷ operaciones, en $ y en R (media de R de las que la tienen).
    - **R medio** de las ganadoras y de las perdedoras.
    - **Drawdown máximo:** la mayor caída desde un máximo de la curva de capital, en $.
    - **Rachas:** la más larga de ganadoras y de perdedoras, y la actual.
    - Duración media de una operación (tiempo de mercado, de la apertura al cierre).
14. **RF-14 · Curva de capital.** Línea con el beneficio neto acumulado de las operaciones filtradas, en el orden en que se hicieron (no por fecha del mercado, porque con saltos aleatorios se opera 2023 después de 2025) **(decidido por Claude)**. El eje horizontal es el número de operación. Al pasar el ratón por un punto se ve esa operación.
15. **RF-15 · Desglose.** Tablas con una fila por estrategia, por instrumento, por sesión y por día de la semana, cada una con operaciones, % de acierto, beneficio neto, profit factor y esperanza en R. Responde de un vistazo "¿dónde gano y dónde pierdo?".
16. **RF-16 · Lista y detalle.** La lista de operaciones filtradas, de la más reciente a la más antigua, con fecha y hora de apertura (ET), cuenta, contrato, lado, cantidad, entrada, salida, PnL neto, R, estrategia y etiquetas. Al pulsar una se abre su detalle: todo lo anterior más SL inicial, riesgo, duración, comisiones, notas, capturas y los controles para editar (RF-6, RF-8).
17. **RF-17 · Modo a ciegas.** Mientras haya un replay en marcha en modo a ciegas, las operaciones de ese replay salen sin fecha ("este replay") en la lista, en el detalle y en la curva. Las de replays anteriores sí la enseñan, porque ya no delatan nada **(decidido por Claude)**.

## Criterios de aceptación

- [ ] Con operaciones sintéticas de dos estrategias, dos instrumentos y las tres sesiones, el filtro "estrategia X, NQ, Nueva York, 2024" devuelve solo las que tocan y su % de acierto, profit factor, esperanza, drawdown máximo y rachas cuadran con el cálculo a mano (test).
- [ ] R: una operación de 2 NQ con entrada 18000 y SL inicial 17990 (riesgo 400 $) que gana 790 $ netos da 1,975 R; una sin SL no tiene R y no cuenta en la media (test).
- [ ] Sesión y día de la semana: una operación abierta el domingo a las 19:00 ET es de Asia y del lunes (test).
- [ ] La estrategia elegida en la boleta queda en la operación que abre la orden, también con órdenes límite que se ejecutan más tarde (test).
- [ ] Reiniciar una cuenta deja su balance como nuevo, el reto sin días, y sus operaciones siguen en el diario con el intento anterior; borrarla las quita (test).
- [ ] Borrar una estrategia deja sus operaciones como "Sin estrategia" (test).
- [ ] En Chrome, con datos reales: operar con una estrategia elegida, ver la captura automática al cerrar, añadir etiquetas y notas desde "Anotar", y filtrar en el diario hasta ver esa operación sola con sus métricas.
- [ ] En Chrome: en modo a ciegas con un replay en marcha, el diario no enseña la fecha de las operaciones de ese replay.

## Dudas

- **RF-9:** ¿te parece bien que reiniciar una cuenta conserve sus operaciones en el diario? Es lo que propongo, porque si no cada reto suspendido y reiniciado se llevaría por delante datos de tus estrategias.
- **RF-5:** ¿la estrategia se elige en la boleta antes de operar (propuesta), o prefieres anotarla siempre después?
- ¿Echas algo en falta en las métricas o en los filtros? Por ejemplo, filtrar por hora concreta (9:30–10:30) o por tipo de cuenta (libre o reto).

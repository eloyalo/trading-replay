# 008 · Backtest de estrategias

- **Estado:** Hecha (el usuario la prueba y la da por buena el 2026-10-17)
- **Fase:** 5
- **Creada:** 2026-10-16 · **Actualizada:** 2026-10-17 (aprobada; antes, respuestas del usuario y RF-18)

## Problema

El usuario quiere saber si una estrategia funciona antes de practicarla o usarla: cuántas operaciones salen bien y cuántas mal, qué % de acierto tiene y si es rentable a lo largo del histórico. La idea es que él explique una estrategia con sus palabras, Claude la escriba en código, se pase por los 4 años de datos y el resultado se vea en números y **en el gráfico**, operación por operación, como una calculadora. Viendo las operaciones en el gráfico, el usuario comprueba además que el código hace lo que él explicó.

Sustituye a la spec 007 (diario manual), que se descartó al aclarar el usuario qué quería decir con "estrategias".

## Alcance

**Incluye:**
- Estrategias escritas en Python en una carpeta del proyecto, con parámetros que se cambian desde la interfaz sin tocar el código. Las escribe Claude a partir de la explicación del usuario, y el usuario puede retocarlas a mano.
- Ejecutarlas sobre el histórico (un instrumento y un periodo) con el mismo motor de órdenes que el trading manual (spec 005): mismas reglas de ejecución, spread y comisiones.
- Resultados: % de acierto, beneficio, profit factor, esperanza, R, drawdown, rachas, curva de capital y desglose por año, sesión, día de la semana y lado.
- Ver las operaciones del backtest en el gráfico: entrada, salida, SL, TP y lo que la estrategia quiera dibujar para explicarse (un rango, un nivel...).
- Guardar cada ejecución para compararla con otras (otros parámetros, otro instrumento).
- Una guía para escribir estrategias y dos estrategias de ejemplo.

**No incluye:**
- Un editor de estrategias sin código (reglas con menús), y editar el código dentro de la app: se edita con el editor de siempre (VS Code) y la app recarga el archivo (RF-1) **(decidido por Claude)**.
- Optimizar parámetros solo (probar cientos de combinaciones y quedarse con la mejor). Se puede añadir después; además, es la forma más fácil de engañarse con un backtest.
- Pasar el backtest por las reglas de un reto de prop firm. Se puede añadir después reutilizando la spec 006.
- Comparar el backtest con el trading manual de la misma estrategia, y el diario manual (spec 007, aparcada).
- Datos de ticks: se usa 1m, con su limitación (RF-8).

## Requisitos

### Estrategias
1. **RF-1 · Archivos.** Cada estrategia es un archivo Python en `estrategias/`, en la raíz del proyecto, con nombre, descripción en palabras (la explicación del usuario) y la lista de sus parámetros con su valor por defecto (por ejemplo: minutos del rango = 15, objetivo = 2 R). La app las lista solas y las vuelve a cargar si cambia un archivo, como los perfiles de reto. El código tiene que poder leerlo y retocarlo el usuario: nombres en español, comentarios que explican cada regla y nada de trucos (pedido por el usuario).
2. **RF-2 · Qué ve una estrategia.** Se le avisa al cerrar cada vela de su timeframe (1m, 5m, 15m...) y ve las velas cerradas hasta ese momento, nunca las futuras. Tiene a mano los mismos indicadores que el gráfico (EMA, SMA, VWAP, RSI, ATR, niveles del día anterior y overnight), calculados igual, y sabe la hora ET, la sesión y si tiene una posición abierta.
3. **RF-3 · Qué puede hacer.** Enviar órdenes a mercado, límite y stop con SL y TP (en puntos, en precio o en R), mover o cancelar sus órdenes y cerrar la posición. Cantidad en contratos, mini o micro.
4. **RF-4 · Explicarse en el gráfico.** Una estrategia puede dejar marcas asociadas a cada operación: niveles horizontales, rectángulos (un rango) y textos cortos ("ruptura del máximo"). Sirven para ver por qué entró.
5. **RF-5 · Errores.** Si una estrategia tiene un error, la app lo enseña con el archivo, la línea y el mensaje, y no se cae.
6. **RF-6 · Guía y ejemplos.** `estrategias/LEEME.md` explica cómo se escribe una estrategia. Se incluyen dos de ejemplo **(decididas por Claude)**:
   - **Ruptura del rango de apertura:** rango de los primeros N minutos desde las 9:30 ET; entra en la ruptura con el SL al otro lado y el TP a X R; cierra a las 16:00 si sigue abierta.
   - **Cruce de medias:** EMA rápida y lenta; entra en el cruce con SL a N ATR y TP a X R.

### Ejecutar
7. **RF-7 · Lanzar.** Se elige estrategia, instrumento, periodo (por defecto todo el histórico), valores de los parámetros y costes (por defecto los de una cuenta nueva: spread 1 tick, comisiones de 2,50 $ y 0,75 $ por lado). Se ve el progreso y se puede cancelar.
8. **RF-8 · Ejecución realista.** Las órdenes se ejecutan con el motor de la spec 005, minuto a minuto y igual que al operar a mano: una orden a mercado enviada al cerrar una vela sale al cierre de esa vela, que es el último precio conocido; las límite y stop, y el SL y el TP, se ejecutan como pronto en el minuto siguiente, nunca con precios de la vela que las provocó. Si el SL y el TP caen en el mismo minuto, cuenta el SL. Los resultados dicen cuántas operaciones se resolvieron así ("8 de 412 con SL y TP en el mismo minuto"), para saber cuánto pesa esa duda.
9. **RF-9 · Rapidez.** 4 años de NQ con la estrategia de ejemplo de ruptura, en 1m, en menos de 1 minuto **(decidido por Claude)**.

### Resultados
10. **RF-10 · Métricas.** De las operaciones del backtest (y de las que queden al filtrar, RF-12):
    - Operaciones, ganadoras, perdedoras y **% de acierto**. Ganadora o perdedora según el PnL neto (con comisiones).
    - Beneficio neto, bruto y comisiones.
    - Ganancia media, pérdida media y su proporción.
    - **Profit factor:** ganancias netas ÷ pérdidas netas en valor absoluto.
    - **Esperanza:** beneficio neto medio por operación, en $ y en R. La R es PnL neto ÷ riesgo inicial, y el riesgo inicial es la distancia de la entrada al SL × $ por punto × contratos.
    - **Drawdown máximo** en $ y en R, y **rachas** máximas de ganadoras y de perdedoras.
    - Duración media de una operación y operaciones por mes.
11. **RF-11 · Curva y desglose.** Curva de capital por fecha. Tablas por año, por sesión (Asia, Londres y Nueva York, con los horarios del botón de momento aleatorio), por día de la semana y por lado (largos y cortos), cada una con operaciones, % de acierto, beneficio, profit factor y esperanza en R.
12. **RF-12 · Filtros.** Sobre una ejecución ya hecha se puede filtrar por año o periodo, sesión, día de la semana y lado, y las métricas, la curva y la lista se recalculan. Así se responde "¿qué % de acierto tiene en NQ en la sesión de Nueva York en 2024?" sin repetir el backtest.
13. **RF-13 · Lista de operaciones.** Fecha y hora de entrada (ET), lado, cantidad, entrada, salida, SL, TP, motivo de salida (SL, TP, cierre de la estrategia), PnL neto y R.

### En el gráfico
14. **RF-14 · Modo backtest.** Desde los resultados se pasa a ver la ejecución en el gráfico, sin replay: el gráfico se sitúa en una operación y enseña su entrada y su salida (marcas), las líneas y zonas de SL y TP, y las marcas de la estrategia (RF-4). Se puede cambiar de timeframe y usar indicadores y dibujos como siempre.
15. **RF-15 · Recorrer las operaciones.** Botones (y atajos de teclado) de anterior y siguiente, y clic en una fila de la lista para ir a esa operación. Se ve su número ("operación 37 de 412") y su resultado. Las marcas de entrada y salida del resto de operaciones también se ven al desplazar el gráfico.
16. **RF-16 · Fuera del replay.** El backtest (lanzar, resultados y gráfico) solo se usa sin un replay en marcha, porque enseña todo el histórico y delataría el futuro del replay **(decidido por Claude)**. Mientras se mira un backtest en el gráfico no se puede empezar un replay ni operar, y un botón (o Esc) vuelve al gráfico normal.

### Guardar y comparar
17. **RF-17 · Historial de ejecuciones.** Cada ejecución se guarda con la estrategia, la versión del archivo (para saber si el código cambió después), los parámetros, el instrumento, el periodo, los costes, las métricas principales y sus operaciones. Hay una lista de ejecuciones anteriores con sus métricas lado a lado, para reabrir una o borrarla.

### Retocar estrategias
18. **RF-18 · Probar cambios** (pedido por el usuario). Para retocar una estrategia sin perder la original:
    - En la app se ve la ruta del archivo y su código (solo lectura), para saber qué se está ejecutando.
    - Un botón "Duplicar" crea una copia con otro nombre (`ruptura_rango_2.py`) que aparece en la lista y se edita aparte.
    - Al guardar el archivo, la siguiente ejecución usa el código nuevo. Si tiene un error, se ve como en RF-5.

## Criterios de aceptación

- [x] Con velas sintéticas donde se conoce a mano el resultado, la estrategia de ruptura hace las operaciones esperadas, al precio esperado, y las métricas (% de acierto, profit factor, esperanza, drawdown, rachas) cuadran con el cálculo a mano (test).
- [x] Una estrategia no puede ver velas futuras: una estrategia de prueba que intenta leer la vela siguiente falla, y una orden límite o stop enviada al cerrar una vela no se ejecuta con precios de esa vela (test).
- [x] El mismo trade da el mismo resultado en el backtest que operado a mano en el replay, con los mismos costes (test).
- [x] Los indicadores que ve una estrategia dan los mismos valores que los del gráfico (test).
- [x] Un error en una estrategia se ve con su archivo y su línea, y la app sigue funcionando (test).
- [x] Filtrar una ejecución por "Nueva York, 2024" devuelve solo esas operaciones y sus métricas se recalculan (test).
- [x] RF-9: 4 años de NQ con la ruptura del rango en menos de 1 minuto con los datos reales.
- [x] Duplicar una estrategia crea un archivo nuevo que sale en la lista; al guardar un cambio en él, la siguiente ejecución usa el código nuevo y el historial marca que el código de las ejecuciones anteriores era otro (test).
- [x] En Chrome, con datos reales (Chrome headless por DevTools y después el usuario): lanzar la ruptura en NQ, ver los resultados, recorrer operaciones en el gráfico con sus SL, TP y el rango dibujado, cambiar un parámetro, relanzar y comparar las dos ejecuciones.

## Dudas

Respondidas por el usuario el 2026-10-16:

- **Diario manual:** le interesa. Va a la fase 6, partiendo del borrador de la spec 007.
- **Primera estrategia:** valen las dos de ejemplo; más adelante dará alguna suya.
- **Quién escribe el código:** las dos cosas. Él explica y Claude la escribe, y después él la retoca a mano para probar cambios (RF-1, RF-18).

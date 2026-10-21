# 012 · Estrategias EMA pullback y Fibonacci (muy parametrizables)

- **Estado:** Implementada el 2026-10-21 (aprobada por el usuario); falta que la pruebe el usuario
- **Fase:** 5 (ampliación del backtest)
- **Creada:** 2026-10-21 · **Actualizada:** 2026-10-21

## Problema

El usuario quiere dos estrategias más para pasar por el backtest: el **pullback a las EMAs** y la de **Fibonacci**. Ninguna de las dos tiene una versión única: cada trader las usa con medias distintas, otro tipo de confirmación, otro stop y otros objetivos. En vez de fijar una versión, el usuario quiere **todas las variantes razonables como opciones** y poder elegir la sesión en la que operan, para compararlas con el historial de ejecuciones (spec 008) y con las reglas de un reto (spec 009).

## Alcance

**Incluye:**
- `estrategias/ema_pullback.py` y `estrategias/fibonacci.py`, con las variantes como parámetros que se cambian en la ventana Backtest.
- Elegir el timeframe al lanzar (RF-1), que hoy es fijo en cada estrategia.
- Elegir las sesiones en las que se opera (RF-2), común a las dos.
- Marcas en el gráfico para ver qué ha detectado la estrategia (EMAs tocadas, swing, niveles de Fibonacci).
- **Herramienta Fibonacci en el gráfico manual** (spec 004), aunque no dependa de las estrategias, y que el Fibonacci que detecta la estrategia se vea después en el modo backtest con esa misma figura.
- Tests con velas sintéticas y una nota en `LEEME.md`.

**No incluye:**
- Optimizar parámetros automáticamente (sigue sin spec).
- Operar varios instrumentos a la vez (una estrategia opera el que se elige al lanzar).
- Patrones de velas complejos (envolventes, estrella de la mañana...). Solo los de la lista de RF-6.

## Requisitos

### Común a las dos

1. **RF-1 · Timeframe elegible.** Una estrategia puede declarar `timeframe` como `Parametro` con `opciones` (1m a 4h) además de como texto fijo. Las existentes siguen funcionando igual. Los timeframes mayores (`velas_de`) se calculan respecto al elegido y, si el filtro de tendencia pide uno menor o igual, se avisa antes de lanzar.
2. **RF-2 · Sesiones.** Tres sí/no (Asia, Londres, Nueva York) que dicen en qué sesiones se **abren** operaciones. Más una **ventana horaria** opcional (`desde`, `hasta`, hora de Nueva York) que, si se rellena, manda sobre las sesiones. Una operación abierta sigue su curso aunque acabe la sesión, salvo que se active "Cerrar al acabar la sesión" **(decidido por Claude)**.
3. **RF-3 · Lados.** `lados`: "ambos", "solo largos" o "solo cortos".
4. **RF-4 · Una operación a la vez.** Máximo de operaciones al día y de seguidas en el mismo sentido (parámetros; por defecto 3 al día). No se abre otra con una posición abierta.
5. **RF-5 · Salidas comunes.** Stop, objetivo y gestión, a elegir en cada estrategia entre las listas de abajo, más: contratos (y micro sí/no), parcial (qué fracción, a cuántas R) y llevar el stop a break-even tras la parcial o tras N R. Cierre forzoso a una hora (por defecto 16:00 ET, desactivable).

### EMA pullback

6. **RF-6 · Medias.** Hasta tres EMAs (rápida, media, lenta) con su periodo; cada una se puede **desactivar** y cambiar a SMA (`tipo_media`). Por defecto 9/20/50.
7. **RF-7 · Tendencia.** Se puede combinar cualquiera de estos filtros (cada uno se activa o no):
   - Medias apiladas (rápida > media > lenta en largos).
   - Precio al lado correcto de la media lenta.
   - Pendiente de una media positiva en los últimos N cierres.
   - Tendencia de un timeframe mayor (el precio sobre su EMA de ese timeframe).
   - Distancia mínima entre media rápida y lenta en ATR (para evitar rangos).
8. **RF-8 · Qué cuenta como pullback.**
   - Media objetivo: la rápida, la media, la lenta o "cualquiera de las dos últimas".
   - Contacto: la vela **toca** la media, **cierra más allá** (sin pasarse más de X ATR) o **entra en una banda** de ± X ATR.
   - Profundidad: mínimo y máximo de velas de retroceso, y que la vela anterior no haya tocado ya la media (para tomar el primer pullback).
   - Hasta cuántas velas puede tardar la confirmación tras el toque.
9. **RF-9 · Entrada.** A elegir:
   - Vela de confirmación a favor que **cierra** por encima de la media rápida o de la objetivo (a mercado).
   - **Ruptura** del máximo de la vela de confirmación (orden stop).
   - **Límite** en la propia media (orden límite que se cancela si pasan N velas).
   - Filtro opcional de la vela de confirmación: cuerpo mínimo en % del rango y que no sea de tamaño exagerado (> X ATR).
10. **RF-10 · Stop.** Mínimo/máximo del pullback, bajo la media lenta, ATR (× factor), o puntos fijos; con margen en ticks. Siempre el más cercano entre los activados, o el más lejano (`stop_modo`).
11. **RF-11 · Objetivo.** R fijo, el último máximo/mínimo del swing anterior, un múltiplo de ATR o ninguno (solo salida por señal). Salida opcional por **cierre al otro lado de la media lenta** o por cruce contrario de las medias.

### Fibonacci

12. **RF-12 · Swing.** Detectado con pivotes: una vela es pivote alto si su máximo es el mayor de N velas a cada lado (`velas_pivote`, por defecto 5; también sobre el timeframe mayor elegido). El **impulso** es el último pivote bajo → pivote alto (largo) o al revés (corto), y tiene que medir al menos X ATR y no más de Y ATR. Opción de reanclar al nuevo máximo si el precio sigue en la dirección antes de entrar.
13. **RF-13 · Niveles.** Niveles de retroceso configurables (por defecto 0,382 · 0,5 · 0,618 · 0,65 · 0,786), de los cuales se elige **cuáles son de entrada** (por defecto la zona 0,618–0,65) y **cuál es el de invalidación** (por defecto 0,786 más margen o, alternativa, el origen del swing).
14. **RF-14 · Entrada.** A elegir:
   - **Límite** en el nivel (0,618 por defecto) o en el borde de la zona.
   - **Rechazo:** el precio entra en la zona y una vela cierra de vuelta a favor (a mercado).
   - **Escalonada:** mitad en un nivel y mitad en otro (por ejemplo 0,5 y 0,618).
   - Confirmación opcional con las EMAs del RF-6 (el precio cierra por encima de la rápida tras tocar la zona) y con RSI (sobrevendido/sobrecomprado a favor).
15. **RF-15 · Stop.** Más allá de un nivel elegido (0,786 por defecto) o del origen del swing, con margen en ticks o en ATR; o por ATR desde la entrada.
16. **RF-16 · Objetivos.** Lista de **extensiones** configurables (por defecto 1,0 y 1,618; también 0,618, 2,0 y 2,618) y qué fracción se cierra en cada una (por defecto mitad y mitad). Modos: (a) objetivo único, (b) tramos con parciales y break-even, (c) tramos con un último trozo con **trailing** (por mínimos/máximos de N velas o por EMA).
17. **RF-17 · Invalidación del swing.** Se olvida el swing, y se cancela lo pendiente, si el precio rompe el origen, si pierde el nivel de invalidación **antes** de entrar, si toca la extensión del 100 % sin haber entrado ("se fue sin nosotros") o si pasan N velas **(por defecto 100)**.
18. **RF-18 · Un swing, una entrada.** Cada swing se opera como mucho una vez, salvo que se active "permitir reentrada".

### Gráfico

19. **RF-19 · Explicarse.** Con `marcar` activado (por defecto sí): en EMA pullback, texto en la vela de toque y de confirmación y línea en el stop; en Fibonacci, el impulso con sus niveles y extensiones, dibujado con la figura del RF-20 (no con líneas sueltas), desde el pivote de origen hasta donde acaba la operación o se invalida el swing.

### Herramienta Fibonacci del gráfico

20. **RF-20 · Herramienta.** Nueva herramienta en la barra de dibujo (atajo `f` **(decidido por Claude)**), de dos puntos: origen y final del impulso. Pinta las líneas de **retroceso** entre ambos (0 · 0,236 · 0,382 · 0,5 · 0,618 · 0,65 · 0,786 · 1), con su porcentaje y su precio en el eje, y las **extensiones** más allá del final (1,272 · 1,618 · 2 · 2,618) cuando se activan. Sirve para impulsos al alza y a la baja según el orden de los puntos. Colores y relleno suaves entre niveles, y la zona 0,618–0,65 resaltada.
21. **RF-21 · Editar.** Como el resto de dibujos (spec 004, RF-3, RF-4, RF-5): seleccionar, arrastrar entera o por un punto, borrar con `Supr`, anclada a tiempo y precio, y por instrumento. Las líneas llegan hasta el último punto del dibujo (decidido por el usuario al probarla el 2026-10-21); una casilla del panel las extiende hasta el final visible. Se puede poner a la derecha de la última vela.
22. **RF-22 · Configurar.** Al seleccionarla, un pequeño panel permite elegir qué niveles se ven, añadir un nivel propio, activar o no las extensiones y mostrar o no el precio y el porcentaje. La configuración se recuerda para las siguientes figuras **(decidido por Claude)**.
23. **RF-23 · Sin ver el futuro.** Como cualquier dibujo, en replay se pone a mano sobre lo que ya se ve; no se calcula nada con velas posteriores al instante. Se borra al empezar un replay nuevo, como los demás dibujos (spec 004, RF-6).
24. **RF-24 · Verla después.** En el modo backtest del gráfico (spec 008), cada operación de la estrategia Fibonacci muestra su figura con los niveles que se usaron. Las figuras de las **estrategias** son solo de lectura y no se mezclan con los dibujos propios (no se pueden mover ni se guardan con ellos). Con un botón "Copiar como dibujo" se pasa una a los dibujos manuales para retocarla o dejarla guardada en el navegador **(decidido por Claude)**.

## Criterios de aceptación

- [x] Una estrategia con `timeframe` como parámetro se lanza con 5m y con 15m; las estrategias que ya existen siguen pasando sus tests (RF-1).
- [x] Con velas sintéticas: con Nueva York activada y Asia desactivada, no se abre ninguna operación con señales a las 22:00 ET; con la ventana 09:30–11:00 solo se abren dentro de ella (RF-2).
- [x] EMA pullback, mercado alcista sintético con un retroceso a la EMA 20 y una vela de confirmación: abre un largo al cierre de esa vela, con el stop bajo el mínimo del pullback y el TP a 2R. El mismo caso con "solo cortos" no abre nada (RF-3, RF-9, RF-10).
- [x] EMA pullback: cada filtro de tendencia, activado, anula un caso que sin él habría entrado (test por filtro, RF-7).
- [x] Fibonacci, swing sintético 100 → 200: la entrada límite en 0,618 queda en 138,2, el stop bajo 0,786 (121,4) con margen y los objetivos en 200 (1,0) y 261,8 (1,618); en el espejo para cortos salen los niveles simétricos (RF-12 a RF-16).
- [x] Fibonacci: si el precio rompe el 0,786 antes de entrar, o llega al 100 % sin entrar, la orden se cancela y no se opera ese swing (RF-17).
- [x] Ambas estrategias corren 4 años de NQ en menos de 30 s con los valores por defecto (el RF-9 de la 008 pide menos de 1 minuto).
- [x] Comprobado con datos reales de NQ (4 años, valores por defecto: EMA pullback 6,4 s y Fibonacci 2,4 s) y en Chrome headless para Fibonacci; falta la revisión del usuario.
- [x] Herramienta: en un gráfico con 100 de origen y 200 de final, las líneas quedan en 138,2 (0,618) y 121,4 (0,786), y en 261,8 la extensión 1,618; con los puntos al revés (200 → 100) quedan en 161,8 y 178,6 (cálculo puro, test en Node).
- [x] Herramienta: se dibuja, se selecciona, se arrastra por un punto y se borra, y sobrevive a una recarga y a un cambio de timeframe (revisión en Chrome).
- [x] Modo backtest: al ver una operación de Fibonacci, el gráfico muestra la figura con los mismos niveles que usó la estrategia; "Copiar como dibujo" la deja editable en los dibujos propios (revisión en Chrome).
- [x] No hay mirada al futuro: los pivotes solo se confirman N velas después de formarse (test: el pivote no se usa hasta que han cerrado N velas más) (RF-12).

## Dudas

Todas con propuesta; si no se dice nada se usa la propuesta.

1. **Cantidad de opciones.** La lista de arriba es larga. ¿Se implementa **todo** en una pasada o se hace por tareas, primero un conjunto base (lo marcado como "por defecto") y las variantes extra después? Propuesta: por tareas, base primero, para que el usuario pruebe pronto.
2. **Pivote y mirada al futuro.** Un pivote de 5 velas se conoce 5 velas tarde. Así es en el trading real y lo que hace el backtest. Propuesta: mantenerlo así.
3. **Fibonacci manual.** El usuario, si lo prefiere, podría dar el swing a mano (precio de origen y final) para probar un caso. Propuesta: no ahora.
4. **"Visualizar después".** Lo he entendido como el RF-24: ver en el modo backtest la figura de cada operación de la estrategia. Si querías decir otra cosa (por ejemplo, que los dibujos manuales se conserven al empezar un replay nuevo, hoy se borran por el RF-6 de la 004), dímelo.
5. **Orden de trabajo.** La herramienta manual no depende de las estrategias. Propuesta: hacerla primero (T1 a T3 del plan), porque la estrategia la reutiliza para dibujar.
6. **Muchas variantes = fácil engañarse.** Con tantos parámetros se puede ajustar hasta que salga bien (aviso de `LEEME.md`). Propuesta: añadir a los resultados un aviso si se ha probado la misma estrategia con más de N combinaciones sin periodo de prueba aparte, cuando exista la optimización. De momento, solo la nota en el `LEEME.md`.

## Decisiones tomadas al implementar

- **(decidido por Claude)** Cada tramo de bajada (o subida) que sigue a un máximo (o mínimo) es a su vez un impulso. La estrategia Fibonacci opera el último impulso; el retroceso de un swing vivo no lo sustituye, y con «solo largos» o «solo cortos» se aísla un sentido.
- **(decidido por Claude)** La entrada escalonada va sin tomas parciales: todo se cierra en el último objetivo.
- **(decidido por Claude)** La edad máxima de un swing se mide en velas del timeframe de los pivotes.
- **Cambio al probarla (usuario):** las líneas de la herramienta llegan hasta el último punto del dibujo, y la casilla «Extender a la derecha» del panel las lleva al final visible.

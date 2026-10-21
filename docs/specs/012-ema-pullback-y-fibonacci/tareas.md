# 012 · Tareas

Referencia: [plan.md](plan.md)

Cada tarea se confirma con el usuario antes de pasar a la siguiente.

**Bloque 1 · Herramienta Fibonacci**
- [x] T1: `fibonacciNiveles` en `calculos.js` y su test en Node (RF-20)
- [x] T2: herramienta `fibonacci` en `dibujo.js`: crear, pintar con extensiones y zona resaltada, seleccionar, arrastrar, borrar, atajo `f`, panel de configuración (RF-20 a RF-23)

**Bloque 2 · Piezas comunes**
- [x] T3: timeframe como parámetro (cargador, ejecutor, formulario) y agrupar parámetros por secciones (RF-1)
- [x] T4: `backtest/comunes.py` (sesiones y ventana horaria, lados, límites, salidas: parcial, break-even, trailing, cierre forzoso) con tests (RF-2 a RF-5)
- [x] T5: `backtest/swings.py` con pivotes sin mirar al futuro y test de ello (RF-12)

**Bloque 3 · Estrategias**
- [x] T6: EMA pullback, versión base (medias 9/20/50, filtros apilado y lado de la lenta, toque, entrada al cierre, stop bajo el pullback, objetivo en R, marcas) con tests (RF-6 a RF-11 y RF-19)
- [x] T7: EMA pullback, variantes (filtros de pendiente, tipo de media, distancia y timeframe mayor; entrada por ruptura y límite; stop y objetivos alternativos; salida por la media) con un test por variante
- [x] T8: `Marca.datos`, `self.fibonacci(...)`, guardado en `backtests.sqlite` y pintado de la figura en el modo backtest con "Copiar como dibujo" (RF-19, RF-24)
- [x] T9: Fibonacci, versión base (pivotes, impulso en ATR, zona 0,618–0,65, entrada límite, stop tras 0,786, objetivos 1,0 y 1,618 con parcial y break-even, invalidación) con tests (RF-12 a RF-18)
- [x] T10: Fibonacci, variantes (rechazo, escalonada, confirmación con EMAs y RSI, trailing, reanclaje, reentrada, otros niveles) con un test por variante

**Cierre**
- [x] T11: rendimiento con 4 años de NQ, datos reales y Chrome headless con las dos estrategias y la herramienta; `LEEME.md`, `CONTEXTO.md` y `FASES.md`

## Notas de implementación

Lo que se descubra al implementar. Si afecta a la spec, actualizarla y anotarlo también en `docs/CONTEXTO.md`.

- **T1/T2, Fibonacci:** `calculos.js` tiene `fibonacciNiveles(origen, final, niveles)` (retrocesos: `final - impulso*r`) y `fibonacciExtensiones(origen, final, niveles)` (`origen + impulso*e`), ambas devuelven `[{valor, precio}]`. En `dibujo.js`: `nivelesFibonacci({origen, final, retrocesos, extensiones})` y `pintarFibonacci(ctx, ancho, p1, p2, config, opciones)` (p1 y p2 en píxeles con `precio`; `opciones.xFin`, `tinta`, `texto`, `grosor`), sin depender de la selección, para reutilizarlas en el modo backtest (T8). La config (`retrocesos`, `extensiones`, `propios`, `conExtensiones`, `precio`, `porcentaje`) sale de `configFibonacci()` y se guarda en `fibonacci.config`.
- **T2, Chrome headless:** comprobado crear con `f` arrastrando, panel, config guardada y borrar con Supr, sin errores de JS.
- **T3:** el timeframe elegible se resuelve en `Estrategia.__init__` (si hay un parámetro `timeframe`, la instancia usa ese) y en `timeframe_de(clase, valores)`, que usan el historial y el cargador. `Parametro` gana `grupo` y el formulario los pinta como `<details>` plegables que recuerdan si estaban abiertos. `TIMEFRAMES` y `ParametroNoValido` se exportan desde `trading_replay.backtest`.
- **T4:** `backtest/comunes.py` con `Operativa` (composición, no herencia). La entrada escalonada va con dos órdenes límite y **sin tomas parciales** (todo al último objetivo), porque las tomas parciales se calculan sobre la posición entera. Con un contrato entra solo en el primer escalón. Las horas «HH:MM» mal escritas o una ventana a medias dan `ParametroNoValido`.
- **T5:** `Pivotes.actualizar` devuelve los pivotes `n` velas después de formarse; el test comprueba que no aparecen antes y que da lo mismo velas a velas que de golpe.
- **T6/T7, EMA pullback:** el cierre de las órdenes «ruptura» y «límite» pasa por `caducar_ordenes` (vida en velas). La entrada límite no admite el stop tras el pullback (aún no existe) y lo dice al empezar. Con un plazo de confirmación mayor que 1, una vela posterior de la rampa también puede confirmar: es lo esperado, y los tests de la vela de confirmación fijan el plazo a 1.
- **T8:** `Marca.datos` (JSON), columna `marcas.datos` migrada sola, `self.fibonacci(...)` devuelve la marca y la estrategia le pone `fin`; el endpoint del tramo convierte los instantes al reloj del gráfico. En `backtest.js` la figura se pinta con `pintarFibonacci`, la misma función de la herramienta manual, y el botón «Copiar Fibonacci como dibujo» solo sale si la operación tiene figura.
- **T9/T10, Fibonacci:** descubierto al probar la entrada por rechazo: el pivote bajo del retroceso se confirma justo en la vela del rebote, y el tramo de bajada hasta él (que también es un impulso) sustituía al swing antes de entrar. Ahora **el retroceso de un swing vivo no lo sustituye**, un swing descartado no vuelve a mirarse, y con reentrada un impulso solo sustituye al swing si lo supera. La edad del swing se cuenta en velas del timeframe de los pivotes, no del de la estrategia.
- **Efecto a tener en cuenta:** cada tramo de bajada tras un máximo es a su vez un impulso bajista y su retroceso puede dar un corto. Con «solo largos» o «solo cortos» se aísla.
- **T11, rendimiento con 4 años de NQ y los valores por defecto:** EMA pullback 2.037 operaciones, 35,1 % de acierto, +10.225 $, 6,4 s; Fibonacci 711 operaciones, 26,6 % de acierto, +45.025 $, 2,4 s. Son solo comprobaciones de que corre y de la velocidad; los resultados no se han estudiado.
- **T2, cambio al probarla el usuario:** las líneas llegan hasta el último punto del dibujo; la casilla «Extender a la derecha» (`extender` en `fibonacci.config`) las lleva al final visible.
- **T11, Chrome headless con datos reales (NQ, marzo de 2024, 15 operaciones de Fibonacci):** la figura sale en su sitio con niveles, % y precio, la zona 0,618–0,65 resaltada, las extensiones y las zonas de SL y TP; el botón «Copiar Fibonacci como dibujo» solo aparece con figura y guarda un dibujo `fibonacci` de dos puntos en `trading-replay.dibujos.NQ`; sin errores de JavaScript. Corregido al probar: el 0 % y la extensión 1,0 coinciden y sus etiquetas se pisaban (ahora se dibuja una sola).
- **Descubierto en esa prueba, anterior a esta spec:** en Chrome headless, tras cambiar de timeframe en el modo backtest, y a veces al entrar en la primera operación, el gráfico acaba con el rango visible al final de los datos (2 velas) aunque `centrarOperacion` se ha llamado con el rango correcto una sola vez y no hay otra llamada del código que lo mueva. Pasa igual con `ruptura_rango` y con el frontend del último commit (probado con `git archive HEAD`), así que no lo causa esta spec. Puede ser propio del navegador sin interfaz (la nota del 2026-10-16 ya dice que ahí `requestAnimationFrame` casi no da cuadros); falta comprobarlo en el Chrome normal. Si ocurre también ahí, la causa estaría en que la librería recoloca el rango al aplicar los datos nuevos, después del `setVisibleLogicalRange`.
- **Pendiente de revisar por el usuario:** ver el dibujo copiado en el gráfico normal (se comprobó que se guarda, no que se vea tras salir del backtest).

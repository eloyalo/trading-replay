# Contexto del proyecto

Este archivo es la memoria del proyecto. Se lee al empezar cada sesión de trabajo y se actualiza al terminarla.

## Estado actual

- **Fases 0 a 3 hechas.** El usuario cerró las fases 2 y 3 el 2026-10-16 (specs 003, 004 y 005 en estado `Hecha`). Si más adelante pide algo sobre ellas, se añade como cambio aparte.
- **Fase 4** implementada y probada en Chrome ([spec 006](specs/006-prop-firm/spec.md)). Falta que el usuario la pruebe.
- **Modo de trabajo desde el 2026-10-16:** el usuario pidió a Claude que siguiera solo, tomando las decisiones sin preguntar, y que él probaría la app después. Las specs escritas así llevan la nota "aprobada por delegación".
- **Siguiente paso (para retomar):**
  1. Cuando el usuario pruebe la fase 4, recoger sus cambios en la spec 006 y cerrarla.
  2. Fase 5: diario y estadísticas (spec nueva). El resumen de cuentas de la 006 ya da beneficio, acierto, mayor ganancia y pérdida y comisiones; la fase 5 añade etiquetas, notas y métricas por estrategia.
- **Recordatorio para el usuario:** reiniciar el servidor tras cada cambio del backend (`./iniciar.sh` no recarga solo). El 405 al borrar cuentas del 2026-10-16 era un servidor arrancado antes de añadir esas rutas.
- **Pendiente menor:** GC 2022-10-20 da 503 siempre en Dukascopy. Se reintenta solo con `datos descargar`.

## Qué hay hecho

- **Fase 0:** esqueleto con FastAPI y frontend estático, Lightweight Charts 5.2.1 incluido en `frontend/vendor/` (spec 001).
- **Fase 4:** retos de prop firm (spec 006): perfiles editables en `perfiles/`, cuentas de reto, reglas vigiladas en cada minuto, ventanas de aprobado (con confeti) y suspendido, intentos y resumen de todas las cuentas.
- **Fase 3:** motor de órdenes en el backend que avanza con el reloj del replay, cuentas persistentes en SQLite y panel de operar con líneas arrastrables (spec 005).
- **Fase 2:** replay con reloj en el backend (spec 003), y dibujo e indicadores en el frontend (spec 004).
- **Fase 1:** histórico de 1m de Dukascopy (desde el 2022-10-16 hasta el 2026-10-14) en `datos/velas/{NQ,ES,GC}.parquet`, consultas por timeframe con DuckDB, API `/api/instrumentos` y `/api/velas`, y gráfico con selector de instrumento y timeframe que carga historia al desplazarse a la izquierda (spec 002).

## Mapa del código

```
backend/trading_replay/
  app.py                  ← FastAPI: estado, instrumentos, velas, replay, cuentas, órdenes, posiciones, operaciones + frontend
  replay.py               ← sesión de replay: reloj, búfer y cursor de minutos por instrumento, momento aleatorio
  operativa/contratos.py  ← contratos mini y micro (multiplicador, tick)
  operativa/motor.py      ← motor de órdenes puro: ejecución con velas de 1m, OCO, posiciones, operaciones
  operativa/bd.py         ← SQLite (datos/cuentas.sqlite): cuentas, órdenes, ejecuciones, posiciones, operaciones, retos, intentos
  operativa/servicio.py   ← motor de la cuenta activa + reloj del replay + base de datos + reglas del reto; resúmenes para la API
  operativa/perfiles.py   ← carga de los perfiles de reto (perfiles/*.json)
  operativa/reto.py       ← reglas de un reto, puras: umbral, nivel y precio de ruptura, días, consistencia, aprobado
  config.py               ← rutas, instrumentos (símbolo, código Dukascopy, cierre diario), FECHA_INICIO
  cli.py                  ← `trading-replay datos descargar|construir|huecos`
  historico/dukascopy.py  ← descarga (keep-alive, 6 hilos, reintentos) y decodificación .bi5
  historico/almacen.py    ← Parquet de 1m, consultar(simbolo, tf, desde, hasta), rango(), minutos(), minuto_aleatorio()
  historico/huecos.py     ← horario de mercado por instrumento e informe de huecos
frontend/                 ← sin compilación; los scripts se cargan en este orden:
  calculos.js             ← funciones puras: cubeta(), indicadores, cálculo incremental, tiempo ↔ índice lógico
  app.js                  ← gráfico, carga de velas, selector de instrumento y timeframe
  indicadores.js          ← series de indicadores, panel de configuración y leyenda
  dibujo.js               ← herramientas de dibujo (primitiva de Lightweight Charts)
  operativa.js            ← panel de operar, líneas de órdenes arrastrables, marcas de ejecuciones, cuentas
  replay.js               ← barra de replay, play, movimiento simulado, modo a ciegas y atajos
  retos.js                ← panel del reto, ventanas de aprobado/suspendido con confeti, resumen de cuentas
perfiles/                 ← reglas de los retos, un JSON por empresa (Topstep, DayTraders)
tests/                    ← pytest; conftest.py crea datos sintéticos en una carpeta temporal
tests/js/                 ← tests de Node de calculos.js, lanzados desde tests/test_frontend.py
datos/                    ← fuera de git: crudo/, velas/, huecos/
```

## Convenciones técnicas a recordar

- Horas: UTC en disco, hora de Nueva York (ET) en la API y en el gráfico. El campo `time` de las velas es la hora ET expresada como si fuera UTC, porque Lightweight Charts muestra siempre UTC.
- El día de trading empieza a las 18:00 ET de la víspera, y las velas de 4h se alinean a las 18:00 ET.
- `almacen.consultar(..., desde, hasta)` devuelve velas que empiezan en [desde, hasta) y agrega desde 1m. Si `hasta` cae a mitad de una vela, esa vela sale parcial. La spec 003 se apoya en esto para la vela en formación.
- Replay: el instante `T` del reloj significa que se ven los minutos que empiezan antes de `T`. Mientras hay sesión, `/api/velas` se recorta a `T`. La sesión es única, vive en memoria y se pierde al reiniciar el servidor.
- El frontend replica en `calculos.js` (`cubeta()`) la alineación de velas de `almacen.consultar`. Si se toca una, hay que tocar la otra.
- Indicadores y dibujos solo usan `estado.velas`, que en replay ya llega recortado al instante: no pueden ver el futuro.
- Los dibujos guardan cada punto como `{t, precio}` (`t` como el `time` de las velas) y se borran al empezar un replay nuevo.
- Lightweight Charts une con una recta los puntos a los dos lados de un hueco. Para cortar una línea, el punto anterior al corte se pinta transparente.
- Preferencias del navegador en `localStorage` con el prefijo `trading-replay.` (velocidad, modo, ciego, indicadores, dibujos.<SÍMBOLO>, boleta, micro, operar).
- Operativa: el motor calcula en ticks enteros. BID = precio del CFD redondeado al tick; ASK = BID + spread. Con velas de 1m, siempre lo peor para el trader (SL antes que TP en el mismo minuto). Detalle en el plan de la 005.
- El avance del reloj y las órdenes van bajo `servicio.cerrojo`; en el frontend, por la misma fila (`enSerie`).
- Al saltar o salir del replay se cierra todo al precio del instante. Si el servidor se reinicia con algo abierto, el replay se retoma en el instante del último evento (`cuentas.instante_replay`).
- Retos: cada salto (sesión de replay) es un día del reto. Los días salen de `operaciones` agrupadas por `sesion`; no hay tabla de días. El día se cierra al saltar o salir (`servicio.terminar_dia`) o, en una cuenta que no está activa, la primera vez que se mira.
- Retos: las reglas se vigilan en `procesar_avance`, minuto a minuto: hora de cierre, órdenes, ruptura con el peor precio del minuto y pico con el mejor. Los eventos van en `cuenta.eventos` y se entregan una vez.
- SQLite en modo WAL: en el disco NTFS, el diario por defecto tardaba 100 ms por transacción.
- NQ y ES (CFD) no tienen datos de 16:15 a 18:00 ET. GC no los tiene de 17:00 a 18:00.
- Dukascopy bloquea temporalmente (429) tras unas 3.700 peticiones seguidas.

## Cómo arrancar

```
./iniciar.sh                           # abre http://127.0.0.1:8000
uv run pytest                          # tests
uv run trading-replay datos descargar  # descarga o actualiza el histórico (reanudable)
uv run trading-replay datos construir  # regenera los Parquet desde datos/crudo
uv run trading-replay datos huecos     # regenera datos/huecos/*.csv
```

## Objetivo

Practicar trading manual sobre histórico de NQ, ES y oro, simulando cuentas demo y retos de prop firm, y medir el rendimiento de cada estrategia. Todo en local, sin depender de Windows.

## Preguntas abiertas

- [x] ¿Qué prop firms modelamos primero? → Topstep y DayTraders (revisar sus reglas vigentes en la fase 4).
- [x] ¿Cuántos años de histórico descargamos? → los últimos 4 años.
- [ ] ¿Basta con 1m o hacen falta ticks para resolver bien SL/TP dentro de la misma vela?
- [x] ¿App web local o ventana de escritorio? → web local (ADR 0001).
- [x] Fase 4: ¿cómo cuentan los "días de trading" de un reto cuando se opera saltando a momentos aleatorios? → cada salto (sesión de replay) es un día del reto, aunque dentro del salto se cruce el cambio de día del mercado (decidido por el usuario el 2026-10-16).

## Bitácora

Entradas nuevas arriba. Anotar lo que se ha hecho, lo que se ha probado y lo que se ha aprendido (problemas, limitaciones, cambios de idea).

### 2026-10-16 (7)
- El usuario aprueba la spec 006 y añade el resumen de cuentas (RF-21): botón "Cuentas" en la barra de arriba, también fuera del replay, con la consistencia explicada con los números de cada cuenta y lo que falta para aprobar.
- El 405 al borrar o reiniciar cuentas venía de su servidor, arrancado antes de añadir esas rutas. Con el código actual funciona (tests y Chrome).
- Spec 006 implementada: plan, tareas, backend, frontend, 90 tests en verde y prueba en Chrome con datos reales (detalle en las notas de `tareas.md`).
- **Corregido en los tests:** el precio de ruptura se redondeaba al revés y liquidaba un tick antes de tiempo.
- **Descubierto:** en la ventana de Chrome de la automatización, `requestAnimationFrame` casi no da cuadros; el confeti se mueve según el tiempo real.

### 2026-10-16 (6)
- El usuario elige que cada salto sea un día del reto. Pregunta abierta cerrada.
- Reglas de Topstep (Trading Combine) y DayTraders (Trail y EOD) revisadas en sus páginas oficiales. **Descubierto:** el límite diario de Topstep es opcional y no suspende (cierra el día); el de DayTraders tampoco suspende. La consistencia es del 55 % en Topstep y del 50 % en DayTraders, y en los dos casos lo que hace es subir el objetivo. DayTraders pide además 2 días con un beneficio mínimo (200 $ en 50K).
- Spec 006 escrita en borrador.
- El usuario pide para la 006: ventana modal con confeti al aprobar un reto (RF-20) y las cuentas Static de DayTraders (añadidas las de 25K, 50K, 100K y 150K de su página oficial; la 50K: objetivo 3.750 $, drawdown estático de 1.000 $, 6 contratos). Sigue pendiente de aprobar.

### 2026-10-16 (5)
- El usuario da por terminadas las fases 2 y 3 y acepta las decisiones marcadas **(decidido por Claude)** en las specs 004 y 005. Specs 003, 004 y 005 en estado `Hecha`.
- Pregunta si se pueden tener varias cuentas y elegir entre ellas. Ya existía (spec 005, RF-3): selector de cuenta activa y "Nueva cuenta" en el panel de operar. Para cambiar de cuenta no puede haber nada abierto.
- A petición suya, añadido a la spec 005: renombrar, reiniciar y borrar la cuenta activa (RF-26 a RF-28), con segundo clic para reiniciar y borrar. Implementado, 70 tests en verde y probado en Chrome. Corregido de paso: el selector de cuentas no actualizaba el balance al operar.
- **Decidido por Claude:** las tres acciones van sobre la cuenta activa; al borrar la activa pasa a serlo la más antigua; no se puede borrar la única cuenta.

### 2026-10-16 (4)
- El usuario probó la app: "todo me ha gustado". Pidió zonas de color para el SL y el TP en el gráfico, poder poner el SL y el TP en dólares además de en puntos, y una vista previa de dónde quedarían antes de confirmar, que se mueva con el precio en play. Añadido a la spec 005 (RF-22 a RF-25), implementado y probado en Chrome.
- **Decidido por Claude:** la boleta pasa a tener selector de lado (Compra o Venta) y un solo botón de confirmar, porque la vista previa necesita saber el lado antes de confirmar. En dólares, el SL se redondea hacia dentro y el TP hacia fuera.
- **Descubierto:** en modo simulado, la orden a mercado salía al cierre real del minuto dibujado y no al precio que se veía (15 puntos de diferencia en una prueba). Ahora se completa la vela al operar a mercado.
- Para probar sin tocar la cuenta del usuario: arrancar el servidor con `TRADING_REPLAY_DATOS` en una carpeta temporal que tenga un enlace a `datos/velas`.

### 2026-10-16 (3)
- Fase 3 empezada por la misma delegación. Spec 005 (órdenes y cuenta simulada) escrita, aprobada por delegación, implementada y probada en Chrome con datos reales.
- **Decidido por Claude:** cuenta "Demo" de 50.000 $; spread 1 tick, deslizamiento 0 y comisiones de 2,50 $ (mini) y 0,75 $ (micro) por lado; límites "al tocar"; SL y TP en puntos desde la entrada; órdenes a mercado en el acto al último precio; al saltar o salir se cierra todo, con un segundo clic de confirmación.
- **Descubierto:** SQLite tardaba unos 100 ms por transacción en el disco NTFS; con WAL, 0,1 ms.
- Criterio de aceptación comprobado con datos reales: 2 NQ con SL 10 y TP 20, TP alcanzado, balance de 50.000 a 50.790 $ (800 − 10 de comisiones).
- 68 tests en verde.
- **Datos de prueba borrados:** al acabar se borró `datos/cuentas.sqlite`, que solo tenía las operaciones de prueba de Claude. El usuario empieza con la cuenta Demo limpia.

### 2026-10-16 (2)
- El usuario pide seguir sin preguntar: Claude toma las decisiones y él probará la app después.
- Spec 004 escrita, aprobada por delegación, implementada y probada en Chrome con datos reales. Indicadores elegidos por Claude: EMA/SMA (3 medias configurables), VWAP diario, volumen, RSI, ATR, niveles del día anterior y niveles overnight. Dibujo: línea horizontal, de tendencia y rectángulo, con selección, arrastre y borrado.
- **Decidido por Claude:** los dibujos se borran al empezar un replay nuevo, porque un nivel dibujado en otra fecha puede delatar el futuro.
- **Descubierto:** Lightweight Charts no corta las líneas con puntos vacíos; se cortan pintando transparente el punto anterior (ver notas de la 004).
- Rendimiento con todos los indicadores: 1,6 ms por minuto de replay en 1m. Sobra margen a 1000x.
- Tests de JavaScript con Node (`node:test`) lanzados desde pytest. 29 tests en verde.

### 2026-10-16
- La extensión de Chrome conecta usando el Chrome del sistema; el de Flatpak no tiene registrado el conector de Claude Code (anotado en `CLAUDE.local.md`).
- Spec 003 probada en Chrome con datos reales: 1000x fluido (200 fps), sin velas futuras al cambiar de timeframe en pleno play, modo simulado que termina siempre en la vela real, modo a ciegas sin fecha en ningún sitio y atajos funcionando. Detalle en las notas de `tareas.md`.
- Corregidos al probar: el reloj en modo simulado y la hora "00:00" en la información de 1D.
- **Descubierto:** Chrome cacheaba el frontend y no veía los cambios. El servidor manda `Cache-Control: no-cache` fuera de `/api/`.

### 2026-10-15 (6)
- Plan y tareas de la spec 003 escritos y aprobados por el usuario.
- Spec 003 implementada (T1 a T7): sesión de replay en el backend con búfer de 7 días en memoria, endpoints `/api/replay`, `/api/velas` recortado al instante, y en el frontend la barra de replay, el play con velocidades, el movimiento simulado, el modo a ciegas y los atajos. 28 tests en verde.
- **Descubierto:** `almacen.rango()` costaba unos 75 ms por llamada con los datos reales. Ahora se cachea por fecha de modificación del Parquet.
- Comprobado que la agregación de velas del frontend da el mismo OHLC que el backend en todos los timeframes, con semanas de cambio de horario. El volumen puede diferir en la cuarta cifra decimal (ver notas de `tareas.md`).
- La extensión de Chrome no estaba conectada: la revisión visual queda pendiente del usuario.

### 2026-10-15 (5)
- Fase 1 cerrada: el usuario confirma que el gráfico "carga increíblemente bien".
- Spec 003 (replay) escrita y aprobada. Decisión de diseño: el reloj del replay vive en el backend, para que el motor de órdenes de la fase 3 avance con él y para que la API nunca dé velas futuras.
- Respuestas del usuario a las dudas de la 003:
  - Dibujo en una spec aparte, y quiere también **indicadores**.
  - Quiere poder **elegir entre movimiento real y simulado** dentro del minuto.
  - Velocidades: 1x, **2x, 3x, 5x**, 10x, 60x, 300x y 1000x.
- Preparado para publicarse en GitHub:
  - Licencia MIT.
  - README con la atribución de Lightweight Charts (LICENSE y NOTICE en `frontend/vendor/`), aviso sobre los datos de Dukascopy, aviso de que no es asesoramiento financiero y aclaración sobre las marcas de prop firms.
  - `iniciar.ps1` para Windows (sin probar).
  - Los detalles del equipo del usuario se han movido a `CLAUDE.local.md`, que está en `.gitignore`.
  - El usuario borró el historial git para empezar limpio. **Claude no hace commits.**
- Fin de la sesión del día. Se retoma con el plan de la spec 003.

### 2026-10-15 (4)
- El usuario aprueba la spec 002 y se implementa: descarga, Parquet, consultas por timeframe, huecos, CLI, API y gráfico con selector. 16 tests en verde.
- **Descubierto:** los CFD de índices de Dukascopy cotizan hasta las 16:15 ET, no hasta las 17:00 como los futuros. El oro sí cierra a las 17:00.
- **Descubierto:** Dukascopy tarda en aceptar conexiones nuevas (saludo TLS de 12 a 60 s). Se descarga reutilizando conexiones (keep-alive), unas 8 veces más rápido.
- Umbral del informe de huecos subido de 5 a 15 minutos para evitar ruido.
- Descarga real hecha: más del 99 % de los días. **Descubierto:** tras unas 3.700 peticiones seguidas, Dukascopy responde 429 a todo durante un tiempo. La descarga ahora es más prudente (6 hilos, esperas largas ante 429/503).
- El bloqueo 429 duró unos 10 minutos. Al reintentar bajaron 11 de los 12 días pendientes. Queda GC 2022-10-20, que da 503 siempre, y después Dukascopy dejó de aceptar conexiones un rato.
- Criterios comprobados con datos reales: consulta en 44 ms, vela diaria verificada a mano, 0 velas en fin de semana y los huecos grandes son festivos.

### 2026-10-15 (3)
- Fase 0 cerrada: el usuario confirmó que ve el gráfico vacío.
- Prueba real contra Dukascopy:
  - URL: `https://datafeed.dukascopy.com/datafeed/{INSTRUMENTO}/{año}/{mes 0-11}/{día}/BID_candles_min_1.bi5`
  - Formato: LZMA con registros de 24 bytes `>5if`, en el orden segundos desde las 00:00 UTC, apertura, cierre, mínimo, máximo (enteros × 0.001) y volumen (float).
  - Los precios cuadran con los niveles reales. Cada petición tarda de 1 a 3,5 s y en paralelo rinde mucho mejor.
- Borrador de la spec 002. Propone descargar solo BID y simular el spread como en los futuros, y que el día de trading empiece a las 18:00 ET como en el CME.

### 2026-10-15 (2)
- ADR 0001 aceptado: 4 años de histórico, y Topstep y DayTraders como primeras prop firms.
- Nueva funcionalidad pedida: botón **"Momento aleatorio"** para saltar a un instante al azar y operar como en tiempo real, con una **cartera persistente** cuyo balance se conserva entre saltos. Añadida a las fases 2 y 3 en `FASES.md`.
- Spec 001 (esqueleto) implementada: FastAPI, página con gráfico vacío de Lightweight Charts 5.2.1 incluida en el proyecto (funciona sin internet), 3 tests en verde y `./iniciar.sh`.

### 2026-10-15
- Creado el proyecto con la estructura de documentación SDD.
- Se descarta NinjaTrader porque solo funciona en Windows. Se construye desde cero.
- Stack propuesto en el ADR 0001, pendiente de aceptar.

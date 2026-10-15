# Contexto del proyecto

Este archivo es la memoria del proyecto. Se lee al empezar cada sesión de trabajo y se actualiza al terminarla.

## Estado actual

- **Fase:** 2 · Gráfico y replay
- **Spec en curso:** [003 · Replay](specs/003-replay/spec.md), **aprobada**, sin empezar a implementar.
- **Siguiente paso (para retomar):**
  1. Escribir `specs/003-replay/plan.md` y `tareas.md` y enseñárselos al usuario.
  2. Implementar la spec 003.
  3. Después, escribir la spec 004 (herramientas de dibujo e indicadores). Antes hay que preguntar al usuario qué indicadores quiere.
- **Pendiente menor:** GC 2022-10-20 da 503 siempre en Dukascopy. Se reintenta solo con `datos descargar`.

## Qué hay hecho

- **Fase 0:** esqueleto con FastAPI y frontend estático, Lightweight Charts 5.2.1 incluido en `frontend/vendor/` (spec 001).
- **Fase 1:** histórico de 1m de Dukascopy (desde el 2022-10-16 hasta el 2026-10-14) en `datos/velas/{NQ,ES,GC}.parquet`, consultas por timeframe con DuckDB, API `/api/instrumentos` y `/api/velas`, y gráfico con selector de instrumento y timeframe que carga historia al desplazarse a la izquierda (spec 002).

## Mapa del código

```
backend/trading_replay/
  app.py                  ← FastAPI: /api/estado, /api/instrumentos, /api/velas + frontend estático
  config.py               ← rutas, instrumentos (símbolo, código Dukascopy, cierre diario), FECHA_INICIO
  cli.py                  ← `trading-replay datos descargar|construir|huecos`
  historico/dukascopy.py  ← descarga (keep-alive, 6 hilos, reintentos) y decodificación .bi5
  historico/almacen.py    ← Parquet de 1m, consultar(simbolo, tf, desde, hasta), rango()
  historico/huecos.py     ← horario de mercado por instrumento e informe de huecos
frontend/                 ← index.html, app.js, estilos.css (sin paso de compilación)
tests/                    ← pytest; conftest.py crea datos sintéticos en una carpeta temporal
datos/                    ← fuera de git: crudo/, velas/, huecos/
```

## Convenciones técnicas a recordar

- Horas: UTC en disco, hora de Nueva York (ET) en la API y en el gráfico. El campo `time` de las velas es la hora ET expresada como si fuera UTC, porque Lightweight Charts muestra siempre UTC.
- El día de trading empieza a las 18:00 ET de la víspera, y las velas de 4h se alinean a las 18:00 ET.
- `almacen.consultar(..., desde, hasta)` devuelve velas que empiezan en [desde, hasta) y agrega desde 1m. Si `hasta` cae a mitad de una vela, esa vela sale parcial. La spec 003 se apoya en esto para la vela en formación.
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
- [ ] Fase 4: ¿cómo cuentan los "días de trading" de un reto cuando se opera saltando a momentos aleatorios?

## Bitácora

Entradas nuevas arriba. Anotar lo que se ha hecho, lo que se ha probado y lo que se ha aprendido (problemas, limitaciones, cambios de idea).

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

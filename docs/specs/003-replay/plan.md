# 003 · Plan técnico

Referencia: [spec.md](spec.md)

## Enfoque

El reloj del replay vive en el backend, en una **sesión única en memoria** (la app es local y de un solo usuario). Mientras hay sesión, todas las consultas de velas se recortan al instante del reloj, así que el futuro nunca sale de la API (RF-1), sin depender de que el frontend se porte bien.

El frontend pide al backend que avance el reloj y recibe solo los minutos nuevos de 1m. Con ellos actualiza la vela en formación del timeframe activo, sin volver a pedir todo el gráfico. Al cambiar de timeframe o de instrumento redibuja con `/api/velas`, que ya devuelve la vela en formación parcial (RF-11, RF-12).

### Qué significa "el instante"

El reloj guarda un instante `T` en hora ET. Se ven los minutos que **empiezan antes de `T`**: a las 10:37 se ve hasta la vela de 1m de las 10:36, y la de 1h de las 10:00 está formada con los minutos de 10:00 a 10:36. Es la misma regla que `almacen.consultar(..., hasta=T)`.

Con esta regla, el criterio del viernes queda así: con el reloj a las 16:15 (la última vela visible es la de las 16:14), "siguiente vela" en 1m pone el reloj en el domingo a las 18:01 y aparece la vela de las 18:00.

### Avance

- **Avanzar minutos (play):** el reloj pasa al final del siguiente minuto **con datos** del instrumento activo. Así se saltan solos la pausa diaria, los fines de semana y los festivos (RF-3), y el play no se queda dos días parado un fin de semana.
- **Siguiente vela (RF-7):** se busca el siguiente minuto con datos y el reloj salta al final de la vela del timeframe activo que lo contiene. Cada pulsación muestra una vela completa nueva.
- **Fin (RF-10):** si no quedan minutos, la respuesta lo indica y el frontend para el play.

Para que el play a 1000x (unos 17 minutos por segundo) vaya fluido, la sesión no consulta el Parquet en cada paso, porque cada consulta tarda de 20 a 60 ms. Guarda en memoria los minutos siguientes al reloj de cada instrumento usado, en bloques de 7 días, y recarga cuando se acaban. Avanzar cuesta entonces microsegundos.

### Play en el frontend

Un bucle con `requestAnimationFrame` calcula cuántos minutos tocan según la velocidad y el tiempo transcurrido, y los pide en una sola llamada. Nunca hay más de una petición en vuelo: si el equipo va lento, los minutos se agrupan en vez de acumular retraso.

### Movimiento simulado dentro del minuto (RF-9)

En modo simulado y a 10x o menos, el frontend pide el minuto **al empezar** ese minuto y lo dibuja poco a poco durante lo que dura: apertura → extremo más cercano → otro extremo → cierre, con pequeñas oscilaciones y unas 4 actualizaciones por segundo. El último fotograma es siempre la vela real.

Consecuencia: durante la animación, el reloj del backend va hasta un minuto por delante de lo dibujado. Para la fase 3 da igual, porque las órdenes se evalúan con los datos reales de 1m (como dice la spec), pero se tendrá en cuenta al diseñar el motor de órdenes.

### Modo a ciegas (RF-14)

Es solo visual: el eje, la etiqueta del cursor, la cabecera y la línea de información muestran el día de la semana y la hora ("Mar 10:37"), sin día, mes ni año. Los datos de la API llevan la fecha igualmente; no se intenta esconderla de quien abra las herramientas del navegador.

## Componentes afectados

| Módulo / archivo | Cambio |
|---|---|
| `trading_replay/replay.py` (nuevo) | Sesión de replay: reloj, búfer de minutos siguientes, avanzar minutos, siguiente vela, fin de cubeta por timeframe y elección del momento aleatorio |
| `trading_replay/historico/almacen.py` | `minutos(simbolo, desde, hasta)` para llenar el búfer y `minuto_aleatorio(simbolo, desde, hasta, sesion)` |
| `trading_replay/app.py` | Endpoints de `/api/replay` y recorte de `/api/velas` al instante del reloj |
| `frontend/index.html`, `estilos.css` | Barra de replay |
| `frontend/replay.js` (nuevo) | Controles, bucle de play, animación simulada, modo a ciegas y atajos |
| `frontend/app.js` | Separar la carga del gráfico para que el replay la reutilice; formateadores de hora para el modo a ciegas |

## API

| Método y ruta | Cuerpo | Respuesta |
|---|---|---|
| `POST /api/replay` | `{simbolo, inicio}` o `{simbolo, aleatorio: true, sesion}` | `{instante}` |
| `GET /api/replay` | — | `{activo, instante}` |
| `POST /api/replay/avanzar` | `{simbolo, minutos}` o `{simbolo, tf}` (siguiente vela) | `{instante, velas: [1m nuevas], fin}` |
| `DELETE /api/replay` | — | `{activo: false}` |

- `sesion` admite `cualquiera`, `asia`, `londres` y `nueva_york`, las mismas sesiones que ya guarda el Parquet.
- `minutos` va de 1 a 500 por llamada.
- `/api/velas` se recorta a `hasta = min(hasta, instante)` mientras haya sesión. Si no se pasa `hasta`, toma el instante.
- Iniciar un replay con otro activo lo sustituye.

## Modelo de datos

Sin cambios en disco. La sesión vive en memoria y se pierde al reiniciar el servidor; guardar y retomar sesiones es de la fase 7.

```
SesionReplay
  instante: datetime (ET sin zona)
  bufer: {simbolo: array de minutos siguientes con OHLCV}
```

Un `threading.Lock` protege la sesión, porque FastAPI atiende los endpoints síncronos en varios hilos.

## Decisiones de detalle

- **Momento aleatorio (RF-5):** se elige un minuto al azar entre los que tienen datos en `[inicio + 1 mes, fin − 7 días]` y la sesión pedida, con un `OFFSET` aleatorio sobre el Parquet. Así siempre cae en un minuto con datos y la probabilidad es uniforme por minuto de mercado. El reloj se pone al inicio de ese minuto: lo primero que aparece al dar a play es justo esa vela.
- **Ir a fecha (RF-4):** se acepta cualquier instante dentro del rango de datos. Si cae en un hueco, el gráfico muestra lo anterior y el primer paso salta a la siguiente vela.
- **Cubetas en el frontend:** para sumar los minutos nuevos a la vela en formación, el frontend replica la regla de `almacen.consultar` (4h y 1D alineados a las 18:00 ET, y la vela diaria etiquetada con la fecha del día de trading). Al cambiar de timeframe se redibuja desde la API, que es la fuente de verdad.
- **Instrumento activo:** el avance se calcula con los minutos del instrumento que se está viendo. El reloj es el mismo para los tres (RF-13); al cambiar de instrumento se ve ese instrumento hasta el mismo instante.
- **Preferencias:** velocidad, modo real/simulado y modo a ciegas se recuerdan en `localStorage`.
- **Atajos (RF-16):** se ignoran mientras el foco está en un campo de texto o fecha.

## Riesgos

- **Dos agregaciones (SQL y JS).** Si divergen, la vela en formación podría verse distinta al cambiar de timeframe. Se mitiga con una prueba manual (avanzar en 1h, cambiar a 1m y volver) y manteniendo la función JS pequeña y comentada junto a la SQL.
- **Fluidez a 1000x.** Si `update` por minuto no basta, se agrupan los minutos de cada fotograma en una sola actualización.
- **Modo a ciegas y escala de precios:** el nivel del precio (NQ a 11.000 o a 21.000) delata la época aproximada. Queda fuera de esta spec.

## Cómo se prueba

Tests automáticos (pytest, con datos sintéticos):
- Con sesión activa, `/api/velas` en todos los timeframes no contiene información de minutos posteriores al instante: el último cierre es el del último minuto anterior y ningún máximo o mínimo procede de minutos futuros.
- En 1h a las 10:37, la última vela coincide con la agregación de 10:00 a 10:36.
- Avanzar 1 minuto, varios minutos y siguiente vela en 1m, 15m y 1h.
- Viernes 16:15 → siguiente vela en 1m → domingo 18:01.
- Momento aleatorio repetido 500 veces: siempre en un minuto con datos, en la sesión pedida y fuera del primer mes y de la última semana.
- Fin de datos, salir del replay (vuelve el histórico completo) y errores de validación.

Pruebas manuales en el navegador con los datos reales: play a 1x, 60x y 1000x, modo simulado, cambio de timeframe e instrumento durante el play, modo a ciegas (revisar eje, cursor y cabecera) y atajos.

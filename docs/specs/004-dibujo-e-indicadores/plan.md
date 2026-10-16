# 004 · Plan técnico

Referencia: [spec.md](spec.md)

## Enfoque

Todo ocurre en el frontend, sin cambios en el backend. Los indicadores y los dibujos solo usan `estado.velas`, que ya viene recortado al instante del replay, así que no pueden ver el futuro (RF-9) sin tener que vigilarlo aparte.

### Indicadores

Cada indicador se define con una función `paso(velas, i, previo)` que calcula el valor en la vela `i` a partir del estado que dejó la vela `i - 1`. Con eso el mismo código sirve para:

- **Calcular todo** al cargar el gráfico o al añadir historia por la izquierda.
- **Actualizar desde un índice** cuando el replay cambia la última vela o añade velas nuevas: solo se recalcula desde la primera vela tocada. Así a 1000x el coste por fotograma es mínimo.
- **Vela provisional** del movimiento simulado: se calcula el valor con la vela dibujada en ese momento, sin guardarla.

Un test comprueba que actualizar paso a paso da exactamente lo mismo que recalcular de cero (criterio 2), y que ningún valor de velas cerradas cambia al añadir velas nuevas.

| Indicador | Cálculo | Serie |
|---|---|---|
| SMA | Suma deslizante de cierres | Línea, panel principal |
| EMA | `α = 2 / (n + 1)`, arranca con la SMA de las `n` primeras | Línea, panel principal |
| VWAP | Σ(precio típico × volumen) / Σ volumen, reinicio al cambiar de día de trading | Línea, panel principal |
| Volumen | Volumen de la vela, verde o rojo según cierre ≥ apertura | Histograma superpuesto en el 20 % inferior del panel principal |
| RSI | Wilder: medias de subidas y bajadas, arranca con la media simple de las `n` primeras | Línea en panel propio, con líneas en 30 y 70 |
| ATR | Wilder sobre el rango verdadero, arranca con la media simple de los `n` primeros | Línea en panel propio |
| Día anterior | Máximo, mínimo y cierre del día de trading anterior con datos | Tres líneas escalonadas |
| Overnight | Máximo y mínimo de 18:00 a 9:30 del día; se dibujan desde las 9:30 | Dos líneas escalonadas |

El día de trading de una vela es `floor((time + 6 h) / 1 día)`, la misma regla que la vela diaria del backend.

Al cambiar la configuración se quitan todas las series de indicadores y se vuelven a crear. Los paneles de RSI y ATR se crean en orden (1 y 2) y la librería borra sola los paneles vacíos.

### Dibujos

Se dibujan con una **primitiva** de Lightweight Charts (`serie.attachPrimitive`), que pinta en el canvas del panel principal y pone la etiqueta de precio de las líneas horizontales en el eje.

**Coordenadas.** Cada punto se guarda como `{t, precio}`, con `t` en segundos (hora ET como si fuera UTC, igual que las velas). Para dibujarlo, `t` se pasa a índice lógico de la escala de tiempo:

- Dentro de los datos: el índice de la vela que contiene `t` (la de su cubeta, o la anterior si `t` cae en un hueco).
- A la derecha de la última vela: `último índice + (t − hora de la última vela) / duración de la vela`. Así se puede dibujar en el futuro del replay (RF-2), y cuando esas velas aparecen el punto cae en la suya.
- A la izquierda de la primera: lo mismo hacia atrás.

Al hacer clic, el índice lógico se redondea a la vela más cercana y se pasa a `t` con la inversa: los puntos se ajustan a las velas, como en TradingView. Al cambiar de timeframe, `t` sigue siendo el mismo instante y cae en la vela del nuevo timeframe que lo contiene (RF-4).

**Ratón.** Se escuchan `mousedown`, `mousemove` y `mouseup` en fase de captura sobre el contenedor del gráfico:

- Con una herramienta activa, el clic pone un punto y no llega al gráfico (no desplaza).
- Sin herramienta, si el clic cae sobre un dibujo o un punto de control (a menos de 6 px), se selecciona y se arrastra, y tampoco llega al gráfico. Si no, se quita la selección y el gráfico se desplaza como siempre.
- Solo en el panel principal: fuera de él (eje de precios, eje de tiempo, paneles de RSI y ATR) no se interviene.

Puntos de control: la línea horizontal tiene uno; la de tendencia, sus dos extremos; el rectángulo, sus cuatro esquinas. Arrastrar el dibujo entero mueve todos los puntos el mismo número de velas y el mismo precio.

**Guardado.** En `localStorage`, por instrumento (`trading-replay.dibujos.NQ`…). `empezar()` del replay los borra todos (RF-6).

### Leyenda (RF-11)

Un bloque HTML encima del gráfico, arriba a la izquierda. Con `subscribeCrosshairMove` se busca la vela bajo el cursor y se enseñan su OHLC y el valor de cada indicador activo. Sin cursor, los de la última vela. No muestra nunca la fecha (modo a ciegas incluido).

## Componentes afectados

| Módulo / archivo | Cambio |
|---|---|
| `frontend/calculos.js` (nuevo) | Funciones puras: `cubeta()` (movida desde `replay.js`), definiciones de indicadores, motor de cálculo incremental y conversión tiempo ↔ índice lógico. Se puede cargar en Node para los tests |
| `frontend/indicadores.js` (nuevo) | Series de la librería, panel de configuración, leyenda y preferencias |
| `frontend/dibujo.js` (nuevo) | Primitiva, herramientas, selección, arrastre, guardado y atajos |
| `frontend/app.js` | Avisar a indicadores tras `setData` (carga e historia anterior) |
| `frontend/replay.js` | Avisar a indicadores en `aplicarMinutos` y en la animación; borrar dibujos al empezar; `Esc` cede ante el dibujo |
| `frontend/index.html`, `estilos.css` | Barra de herramientas vertical, botón y panel de indicadores, leyenda |
| `tests/js/calculos.test.mjs` (nuevo) | Tests de Node (`node:test`) de los cálculos |
| `tests/test_frontend.py` (nuevo) | Lanza los tests de Node desde pytest; se salta si no hay Node |

## Modelo de datos

```
localStorage
  trading-replay.indicadores = {
    medias: [{activa, tipo: "EMA"|"SMA", periodo, color} × 3],
    vwap, volumen, diaAnterior, overnight: {activa},
    rsi, atr: {activa, periodo}
  }
  trading-replay.dibujos.<SIMBOLO> = [
    {id, tipo: "horizontal"|"tendencia"|"rectangulo", puntos: [{t, precio}, ...]}
  ]
```

## Riesgos

- **Rendimiento a 1000x con todo activo.** Se mitiga con el cálculo incremental y actualizando cada serie con `update` solo en las velas tocadas.
- **Líneas escalonadas de niveles.** Entre un día y el siguiente la línea haría un salto vertical. Se corta poniendo un hueco (punto sin valor) en la primera vela de cada día. Esa vela se queda sin nivel dibujado, pero sí sale en la leyenda.
- **Eventos de la librería.** Lightweight Charts escucha eventos de ratón (no de puntero) en sus elementos. Si se cortan en captura en el contenedor, no le llegan. Si una versión futura cambia a eventos de puntero, habrá que revisarlo.
- **Pantallas táctiles:** fuera de alcance.

## Cómo se prueba

Tests automáticos (Node, lanzados desde `uv run pytest`):
- EMA, SMA, RSI, ATR y VWAP contra valores calculados a mano en una serie pequeña.
- Incremental = de cero: se añaden velas una a una (y se modifica la última varias veces, como hace el replay) y se compara con el cálculo completo.
- Niveles del día anterior y overnight en 1m, 15m y 1h con varios días sintéticos, incluido un hueco de fin de semana.
- Conversión tiempo → índice lógico → tiempo, dentro, a la derecha y a la izquierda de los datos, y en huecos.

Pruebas manuales en Chrome con datos reales: dibujar las tres figuras, cambiar de timeframe e instrumento, arrastrar, borrar, recargar, empezar un replay nuevo, play a 1000x con todos los indicadores, modo simulado, modo a ciegas y leyenda.

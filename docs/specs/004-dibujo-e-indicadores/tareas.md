# 004 · Tareas

Referencia: [plan.md](plan.md)

- [x] T1: `calculos.js` con `cubeta()`, indicadores, motor incremental y conversión tiempo ↔ lógico; tests de Node lanzados desde pytest
- [x] T2: `indicadores.js`: series, enganche con la carga y con el replay (incluida la vela provisional del modo simulado)
- [x] T3: Panel de configuración de indicadores y leyenda
- [x] T4: `dibujo.js`: primitiva, herramientas, vista previa al dibujar y guardado por instrumento
- [x] T5: Selección, arrastre, borrar, borrar todo, atajos y borrado al empezar un replay nuevo
- [x] T6: Pruebas manuales en Chrome con datos reales y comprobar los criterios de aceptación (falta que el usuario la pruebe)

## Notas de implementación

- **Lightweight Charts no corta las líneas con puntos vacíos:** une con una recta los puntos de los dos lados del hueco, así que el VWAP y los niveles salían unidos en diagonal de un día a otro. Se comprobó en una prueba aparte que cada tramo toma el color del punto donde empieza. Solución: el punto anterior a un corte se pinta transparente (`punto()` en `indicadores.js`). En replay, cuando llega una vela nueva hay que retocar el punto anterior antes de añadirla, porque la librería solo deja tocar el último punto de una serie.
- **Rendimiento:** con todos los indicadores activos (13 series), sumar un minuto en 1m con 4.500 velas cuesta 1,6 ms de mediana y 3,6 ms como máximo. A 1000x llegan unos 17 minutos por segundo, de uno en uno, así que sobra margen. Cada `update` de una serie cuesta unos 0,05 ms y un `setData` de 4.500 puntos, 2,4 ms. Por eso el replay usa `update` y solo recalcula desde la primera vela tocada.
- **Comprobado con datos reales:** tras un play a 1000x y otro en modo simulado, el resultado incremental de cada indicador es idéntico al de recalcular todo, y ninguna vela cerrada cambió de valor.
- Al cambiar de timeframe, cada punto de un dibujo cae en la vela que lo contiene (comprobado en 1m, 15m y 1h). Un punto puesto en el futuro sigue en su instante al avanzar el replay.
- La EMA 21 era azul, como los dibujos, y la línea de tendencia se confundía con ella. Se cambiaron los colores por defecto de las medias.
- Se añadió un margen de 15 velas a la derecha del gráfico (`rightOffset`), porque sin él no había sitio para dibujar en el futuro.
- Las funciones puras están en `calculos.js` (también `cubeta()`, movida desde `replay.js`) y se testean con Node desde pytest (`tests/test_frontend.py`). Si no hay Node, ese test se salta.
- `Esc` cancela por orden: el panel de indicadores, la herramienta o el dibujo en curso, la selección y, si no hay nada de eso, sale del replay (como en la spec 003). Ojo al probar: si un clic no acierta en un dibujo, el siguiente `Esc` sale del replay.
- 29 tests en verde: los 28 anteriores más el de Node, que agrupa 17 tests de los cálculos.

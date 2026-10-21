# 011 · Tareas

Referencia: [plan.md](plan.md)

- [x] T1: validación de escenas con `widget` en `escena.py` y tests.
- [x] T2: `ejecutar` y `libroEn` en `estudio_calculos.js` y tests en Node.
- [x] T3: dibujo de cotización, libro (con orden y foco) y comparación en `estudio.js`.
- [x] T4: escenas de L1-01 capturadas desde el canal (`tools/studio.py` traduce `visual.source: motion`) y revisión visual.

## Notas de implementación

- **T2:** una orden se puede partir en tramos (uno por nivel) para que cada nivel se consuma cuando lo nombra la voz; los tramos con el mismo `grupo` se muestran como una sola orden (ejecuciones acumuladas, `total` en la flecha y el precio medio solo al acabar el último, `ultimo_del_grupo`).
- **T3:** widgets en `frontend/estudio_widgets.js`; con `widget` el gráfico de velas se oculta y todo se pinta en la capa. En 9:16 el libro ocupa la mitad de arriba y el panel de ejecuciones va debajo.
- **T4:** el canal traduce `visual.source: motion` en `tools/studio.py` (`Canal Trading`). Capturadas las 9 escenas de L1-01 (s06, s07, s08, s10–s14, s18) y los Shorts a2, a3 y c3, sincronizadas con la voz. 156 tests en verde.

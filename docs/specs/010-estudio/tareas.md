# 010 · Tareas

Referencia: [plan.md](plan.md)

- [x] T1: `estudio/acciones.py`: descarga bajo demanda, caché, splits y agregación; tests sin red.
- [x] T2: `estudio/escena.py`: validación y resolución de datos; `POST /api/estudio/preparar`; tests.
- [x] T3: `estudio_calculos.js` (funciones puras) y tests en Node.
- [x] T4: `estudio.html`, `estudio.css` y `estudio.js`: gráfico, tema, cámara, revelar, pasos de dibujo, indicadores y `window.estudio`.
- [x] T5: modo manual: cargar, play, línea de tiempo, pincel con grabación de trazos, exportar la escena y modo limpio (`F`).
- [x] T6: `estudio/captura.py` y `trading-replay estudio validar|capturar`; medir la velocidad; test de determinismo.
- [x] T7: escenas de prueba (vela explicada, NQ real, NVDA en agosto de 2024) en 16:9 y 9:16; revisión visual.

## Notas de implementación

- **T1:** comprobado contra Dukascopy el 2026-10-18 que NVDA y SPY existen con velas de 1m, 1h y 1D. **Descubierto:** el volumen del CFD no cambia con el split (NVDA, junio de 2024: 54 antes y 73 después, en bruto), así que solo se ajustan los precios. En la sesión regular hay 390 minutos con volumen; el resto del día viene plano y con volumen 0, y se quita.
- **T2:** los tiempos de la escena admiten un índice de vela con decimales (lo usan los trazos de pincel, que no caen justo en una vela).
- **T4:** los canvas internos de Lightweight Charts tienen `z-index`; el contenedor del gráfico lleva `z-index: 0` para crear su propio contexto de apilado y que la capa de dibujo quede encima. Un `display: flex` en CSS anulaba el atributo `hidden` del panel JSON.
- **T4:** la cámara incluye en su rango de precio los dibujos anclados dentro de su ventana (etiquetas, marcas, operaciones), para no dejarlos fuera al acercarse.
- **T6:** `websockets` 17 pide usar `connect()` como gestor de contexto. Medido: unos 100 ms por fotograma a 1920×1080 (348 fotogramas en 36 s), así que 600 fotogramas tardan ~1 min.
- **T7:** escenas probadas con datos reales: NVDA diario de agosto de 2024 (resultados y caída del 6,4 %) en 16:9 y 9:16, y NQ 5m del 2024-03-25 (resistencia con 6 toques, ruptura a las 14:05, EMA, volumen, cámara y caja de operación). La fuente Inter se instaló en `~/.local/share/fonts` para el tema del canal. Modo manual probado en Chrome sin interfaz: carga la escena de ejemplo y el pincel graba un trazo de 11 puntos.

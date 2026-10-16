# 003 · Tareas

Referencia: [plan.md](plan.md)

- [x] T1: `almacen.minutos()` y `almacen.minuto_aleatorio()`, con tests
- [x] T2: `replay.py`: sesión, búfer, avanzar minutos, siguiente vela y fin de datos, con tests
- [x] T3: Endpoints `/api/replay` y recorte de `/api/velas` al instante, con tests (incluido "ninguna vela futura" y 1h a las 10:37)
- [x] T4: Frontend: barra de replay, iniciar en fecha o momento aleatorio, siguiente vela y salir
- [x] T5: Frontend: play con velocidades y bucle con una sola petición en vuelo
- [x] T6: Frontend: modo simulado dentro del minuto
- [x] T7: Frontend: modo a ciegas y atajos de teclado
- [x] T8: Pruebas manuales con datos reales y comprobar los criterios de aceptación (falta el visto bueno del usuario)

## Notas de implementación

- **`almacen.rango()` tardaba unos 75 ms** con los datos reales y se llama en cada `/api/velas`. Ahora se guarda en memoria por ruta y fecha de modificación del Parquet: solo se recalcula si se reconstruyen los datos. Acelera también el gráfico normal.
- Rendimiento con datos reales: avanzar un minuto tarda 0,6 ms de mediana (30 ms como máximo, al recargar el búfer de 7 días). Momento aleatorio, unos 95 ms. `/api/velas` en 1m con replay, 35 ms.
- **Agregación del frontend comprobada contra el backend:** se agregaron en JS (con las funciones de `replay.js`, en trozos de 37 minutos como en el play) 6 días de NQ con cambio de horario (marzo de 2024) y 7 de GC (noviembre de 2024), y se compararon con `/api/velas` en todos los timeframes. OHLC idéntico en todos.
- **Volumen:** al sumar minutos ya redondeados a 4 decimales, el volumen de la vela en formación puede diferir del backend en la cuarta cifra decimal (0,003 en una vela diaria). Al cambiar de timeframe se redibuja desde la API y se corrige. Es volumen de ticks y solo orientativo, así que se acepta.
- **Pruebas en Chrome (2026-10-16), con datos reales:**
  - Play a 1000x: 66 minutos en 4 s (67 esperados), unos 200 fotogramas por segundo y el peor fotograma en 5 ms.
  - Play cambiando entre 1m, 1h, 4h y 15m: la última vela del gráfico coincide con la de la API y no aparece nada posterior al reloj. El play cruza solo la pausa de 16:15 a 18:00.
  - Modo simulado a 10x: 24 precios distintos por minuto, siempre dentro del rango real, y cada minuto termina exactamente en la vela real.
  - Modo a ciegas: eje, etiqueta del cursor, reloj e información sin fecha, también en 1D.
  - Atajos: `→`, `Espacio`, `Esc` y `R`. Espacio con el foco en el botón Play no hace doble pulsación.
  - Al recargar la página, el replay se retoma donde estaba.
- **Corregido al probar:** en modo simulado el reloj marcaba el minuto siguiente al que se dibujaba (el backend ya lo ha pasado). Ahora muestra el minuto que se está dibujando.
- **Corregido al probar:** en 1D, la línea de información mostraba "00:00", que no significa nada en una vela diaria.
- **Descubierto:** Chrome guardaba en caché `app.js` y los demás archivos del frontend y no veía los cambios al recargar. El servidor manda ahora `Cache-Control: no-cache` en todo lo que no es `/api/`, así que el navegador revalida (304 si no ha cambiado).
- Al empezar en los primeros meses del histórico, en 1D se ven pocas velas pegadas a la derecha: no hay datos anteriores al 2022-10-16.
- Para la extensión de Chrome hay que usar el Chrome del sistema (`/opt/google/chrome`), no el de Flatpak, que no tiene registrado el conector de Claude Code.
- 28 tests en verde (12 nuevos en `tests/test_replay.py`). El del momento aleatorio hace 500 sorteos y tarda unos 7 s.

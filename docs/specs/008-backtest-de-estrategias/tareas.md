# 008 · Tareas

Referencia: [plan.md](plan.md)

- [x] T1: `backtest/indicadores.py` (los de `calculos.js` en Python) y test de paridad con Node
- [x] T2: `backtest/estrategia.py` (`Estrategia`, `Parametro`, velas cerradas, tiempo, indicadores, órdenes, marcas) y `backtest/cargador.py` (carga, recarga, errores con línea, huella, duplicar); tests
- [x] T3: `backtest/ejecutor.py`: bucle de minutos, velas del timeframe, SL/TP en precio y en R, dudosas en el motor, motivos de salida, fin de datos; tests de velas, sin futuro e igual que a mano. **Medir la rapidez con datos reales aquí** (RF-9)
- [x] T4: `backtest/metricas.py`: métricas, curva, desglose, sesión, día de la semana y filtros; tests con operaciones hechas a mano
- [x] T5: `backtest/almacen_bt.py`, `backtest/trabajos.py` y endpoints en `app.py` (incluidos los 409 con replay); tests de API
- [x] T6: `estrategias/LEEME.md`, ruptura del rango y cruce de medias; test de la ruptura con velas sintéticas
- [x] T7: Frontend: ventana "Backtest" (lanzar, progreso, código, duplicar, resultados con filtros, curva, desglose y lista, historial)
- [x] T8: Frontend: modo backtest del gráfico (barra, ir a una operación, carga a la derecha, marcas, zonas de SL y TP, marcas de la estrategia, atajos)
- [x] T9: Pruebas en Chrome con datos reales y criterios de aceptación

## Notas de implementación

Lo que se descubra al implementar. Si afecta a la spec, actualizarla y anotarlo también en `docs/CONTEXTO.md`.

- **T3, rapidez (RF-9):** 4 años de NQ (1.367.781 minutos, 273.753 velas de 5m) con la ruptura del rango en 3,3 s, más 0,14 s de lectura del Parquet. Sale así porque el bucle va por velas del timeframe y solo baja a minuto a minuto mientras hay órdenes o posición; no ha hecho falta el plan B. Memoria: unos 130 MB por pasada, que se liberan al terminar.
- **T3, SL y TP en precio o en R:** en vez de colocarlos con `Motor.modificar` después de la entrada (el SL se evalúa ya en el minuto de la entrada, antes de poder moverlo), `MotorBacktest` hereda de `Motor` y calcula las distancias en `_crear_sl_tp` con el precio real de ejecución. El ejecutor pone en la orden una distancia provisional de un tick para que el motor sepa que lleva SL o TP.
- **T3, operaciones:** `MotorBacktest._aplicar` apunta qué orden abre y cuál cierra cada operación y el SL y el TP que tenía al cerrar. El motivo de salida es un texto: "SL", "TP", "Cierre" (o el motivo que pase la estrategia a `cerrar`), "Cambio de sentido", "Fin de los datos", "SL rebasado al entrar" o "TP rebasado al entrar".
- **T3, primera pasada real:** ruptura del rango en NQ con los valores por defecto, del 2022-10-17 al 2026-10-14: 1.030 operaciones, 45,0 % de acierto, +113.340 $ netos; 450 por SL, 170 por TP y 410 cerradas a las 16:00; ninguna dudosa.
- `Motor.dudosas` (ids de las órdenes de SL que ganaron a su TP en el mismo minuto) queda también en el motor de las cuentas, donde no se usa; crece solo con esos casos.
- **T5, API:** `desde` y `hasta` del lanzamiento y de los filtros son días de trading (el día D va de las 18:00 ET de la víspera a las 18:00 de D), con `hasta` incluido. En vez de `/marcas`, la ruta es `/api/backtests/{id}/tramo?desde&hasta`, que da a la vez las operaciones y las marcas de un tramo del gráfico. La lista de operaciones va por páginas con `inicio` y `limite` (200 por defecto), y el modo gráfico pide una sola operación con `limite=1`.
- **T5:** la tabla `ejecuciones` guarda también el `timeframe` de la estrategia, que el modo gráfico usa al abrir una ejecución.
- **T6, cruce de medias** con los valores por defecto en NQ, 4 años: 1.061 operaciones, 40,9 % de acierto, +29.110 $ netos, 1 dudosa, 1,7 s.
- **T7/T8, marcas en su vela:** una orden a mercado sale al cierre del minuto anterior a su instante, y un SL o un TP dentro del minuto de su instante. Para que las marcas caigan en la vela correcta, cada operación guarda también `minuto_entrada` y `minuto_salida` (el minuto cuyo precio dio la ejecución), y el gráfico pone las flechas ahí. Las zonas de SL y TP van del instante de entrada al de salida.
- **T8:** la carga hacia la derecha pide otra vez entera la última vela cargada (puede llegar a medias) y, si una ventana entera no trae datos (festivo y fin de semana en 1m), prueba con la siguiente hasta cuatro veces antes de dar por acabado el histórico.
- **T9:** la extensión de Chrome no estaba conectada tras el cierre del PC. Se probó con el Chrome del sistema en modo headless, manejado por el protocolo de DevTools desde un script de Node (WebSocket nativo), contra un servidor en el puerto 8001 con una carpeta de datos temporal enlazada a `datos/velas`. Comprobado con datos reales: lanzar desde la ventana con progreso, resultados con cifras, curva, desglose y lista; filtros (Nueva York, 2024, cortos: 135 operaciones); ver en el gráfico con zonas de SL y TP, rango de la estrategia y marcas; recorrer con → y los botones; cambiar de timeframe recentrando la operación; carga a la derecha en 1m sin velas repetidas; `R` bloqueado y Esc para salir; historial comparando dos ejecuciones con distinto `objetivo_r`; duplicar; una estrategia con error de sintaxis enseña archivo y línea y no deja lanzar; con un replay en marcha, el botón Backtest queda bloqueado y la API responde 409. Ningún error de JavaScript. Corregido al probar: la tabla del historial no cabía y la celda de acciones se salía de la tabla.
- **Criterio de la fase 5:** "¿qué % de acierto tiene la ruptura del rango en NQ durante la sesión de NY en 2024?" → 259 operaciones, 44,4 % de acierto, +33.940 $ netos y profit factor de 1,16, con las operaciones visibles en el gráfico.

## Después de cerrar la spec

- **2026-10-17, para la Danny strategy:** la API de `Estrategia` gana `velas_de(tf)` (velas cerradas de un timeframe mayor, armadas con las de la estrategia por `Agregador`), `tomar_parcial(contratos, precio)` (límite con papel `cierre`, que solo reduce y se cancela sola al quedarse plana la posición), `simbolo` y `tick`. `OrdenNoValida` se exporta desde `trading_replay.backtest`. Documentado en `estrategias/LEEME.md`, con tests en `tests/test_backtest.py`.

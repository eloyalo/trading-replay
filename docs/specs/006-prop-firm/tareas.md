# 006 · Tareas

Referencia: [plan.md](plan.md)

- [x] T1: `perfiles/topstep.json` y `perfiles/daytraders.json`; `operativa/perfiles.py` con tests
- [x] T2: `operativa/reto.py` (lógica pura) con tests
- [x] T3: `bd.py`: tablas `retos` e `intentos`; cuentas de reto al crear; reiniciar guarda el intento
- [x] T4: `servicio.py`: días, vigilancia por minuto, hora de cierre, validación de órdenes, eventos y resumen del reto; tests de API
- [x] T5: Resumen de cuentas (`/api/cuentas/resumen`) con estadísticas, consistencia e intentos; tests
- [x] T6: Frontend: tipo de cuenta al crear, panel del reto, línea de liquidación y eventos
- [x] T7: Frontend: ventana de aprobado con confeti y de suspendido; ventana de resumen de cuentas
- [x] T8: Pruebas en Chrome con datos reales y criterios de aceptación

## Notas de implementación

- Perfiles: `perfiles/topstep.json` (3 cuentas) y `perfiles/daytraders.json` (10: Trail, EOD y Static). Se releen solos si cambia un archivo.
- **Corregido al escribir los tests:** el precio de ruptura se redondeaba al revés. En un largo, el balance llega al umbral en el primer tick por debajo del punto exacto (floor); en un corto, en el de encima (ceil). Con el redondeo contrario se liquidaba un tick antes de romper la regla.
- **Simplificación:** si un SL está más allá de la pérdida máxima, se ejecuta el SL (se pierde lo del SL) y después se suspende, en vez de liquidar justo en el umbral. Es más duro que la realidad, nunca más blando. Anotado en el plan.
- El día de una cuenta de reto que no está activa se cierra la primera vez que se mira después (resumen de cuentas o al activarla), porque solo la activa sigue el reloj.
- Los eventos (aprobado, suspendido, pausa, hora de cierre) viajan dentro del resumen de la cuenta (`cuenta.eventos`) y se entregan una sola vez.
- Ventanas con `<dialog>` y `showModal()`: no bloquean como `alert()`. Con una ventana abierta no funcionan los atajos del gráfico (`hayVentana()` en `app.js`), para que Esc la cierre sin salir del replay.
- **Descubierto al probar en Chrome:** con la ventana de Chrome que maneja la automatización, `requestAnimationFrame` casi no da cuadros (1 en 1,5 s). El confeti calcula la física en pasos de 1/60 s según el tiempo real, así que se mueve igual a 60 o 120 Hz y aunque se pierdan cuadros. Para verlo en la prueba se sustituyó `requestAnimationFrame` por un temporizador de 16 ms.
- **Comprobado en Chrome con datos reales** (servidor aparte con `TRADING_REPLAY_DATOS` temporal): reto Topstep 50K creado desde los ajustes; venta de 5 NQ a 18661,75 con la línea "Límite diario · se cierra todo" a 18671,50; en play a 300x el límite diario cerró al ASK 18671,75 (−1.000 $ y 25 $ de comisiones), paró el play, avisó y bloqueó las órdenes hasta el siguiente salto. Ventanas de aprobado (con confeti) y de suspendido, "Nuevo intento" (intento 2 con el 1 en el historial), resumen de cuentas fuera y dentro del replay y "Usar" otra cuenta.
- El aprobado real (al cerrar el día) se comprobó con tests; en Chrome, la ventana se abrió con un evento de prueba.
- 90 tests de pytest en verde (20 nuevos: 12 de reglas y perfiles y 8 de la API).


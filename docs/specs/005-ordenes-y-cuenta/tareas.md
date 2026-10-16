# 005 · Tareas

Referencia: [plan.md](plan.md)

- [x] T1: `operativa/contratos.py` y `operativa/motor.py` (órdenes, ejecución en ticks, OCO, posiciones, operaciones), con tests
- [x] T2: `SesionReplay`: cursores por instrumento (`minutos_entre`, `ultimo`) e `id` de sesión, sin romper los tests de la 003
- [x] T3: `operativa/bd.py` (SQLite) y `operativa/servicio.py` (motor de la cuenta activa, guardado, resumen, liquidación y restauración)
- [x] T4: Endpoints de cuentas, órdenes, posiciones y operaciones; avance del reloj conectado al motor; tests de API
- [x] T5: Frontend: panel de operar, resumen, posiciones, órdenes e historial; confirmación al saltar con exposición
- [x] T6: Frontend: líneas en el gráfico, arrastre de órdenes y marcas de ejecuciones
- [x] T7: Frontend: gestión de cuentas y costes; modo a ciegas en el historial
- [x] T8: Pruebas manuales en Chrome con datos reales y comprobar los criterios de aceptación (falta que el usuario la pruebe)

- [x] T9: `desde` en las posiciones del resumen; conversiones de puntos y dólares en `calculos.js`, con tests
- [x] T10: Boleta con lado, unidad (puntos o $), equivalencias y botón de confirmar
- [x] T11: Zonas de SL y TP con importe en las etiquetas, también al arrastrar
- [x] T12: Vista previa de entrada, SL y TP que sigue al precio en play y en modo simulado; pruebas en Chrome

- [x] T13: Reiniciar y borrar cuentas en `bd.py`, `servicio.py` y la API, con tests
- [x] T14: Frontend: renombrar, reiniciar y borrar en los ajustes de cuenta, con segundo clic; pruebas en Chrome

## Notas de implementación

- **Cambio respecto al primer borrador de la spec:** las órdenes a mercado se ejecutan en el acto al último precio (cierre del último minuto) si el mercado está abierto. Esperar a la apertura del minuto siguiente dejaba la orden colgada con el replay en pausa. Spec actualizada (RF-7, RF-14, RF-16).
- **SQLite en el disco NTFS:** con el diario por defecto cada transacción tardaba unos 100 ms (medido: 96 ms) y cada orden se notaba. Con `journal_mode = WAL` y `synchronous = NORMAL`, 0,1 ms. WAL funciona sobre ntfs-3g. Un corte de luz podría perder la última transacción, nunca corromper la base de datos.
- Rendimiento con datos reales: enviar o cancelar una orden, unos 3 ms; avanzar un minuto con posición y órdenes abiertas, 3,3 ms de mediana.
- **Comprobado en Chrome con datos reales:** compra de 2 NQ a mercado con SL 10 y TP 20, arrastre del SL a otro precio, play a 300x hasta el TP: +800 $ brutos, −10 $ de comisiones y balance de 50.000 a 50.790 $. Se comprobó con los datos de 1m que el TP se tocó por primera vez en el minuto de la ejecución (03:09) y que el SL nunca se tocó.
- Saltar a un momento aleatorio con un corto abierto pide un segundo clic y lo cierra al precio del instante (−20 $: 1 tick de spread y 10 $ de comisiones). El historial se mantiene y el PnL de este replay vuelve a cero.
- Reiniciar el servidor con una posición y órdenes abiertas retoma el replay en el instante guardado, con todo en su sitio.
- La confirmación de saltar o salir con algo abierto dura 6 s (con 3 s se pasaba de tiempo con facilidad).
- `SesionReplay` lleva ahora un cursor por instrumento (`minutos_entre`, `ultimo`) y un `id`; `avanzar()` devuelve las filas crudas y el endpoint las convierte para el gráfico.
- El módulo de SQLite se llama `operativa/bd.py` (no `almacen.py`) para no confundirlo con `historico/almacen.py`.
- 68 tests en verde: 31 del motor (`tests/test_motor.py`) y 8 de la API (`tests/test_operativa.py`), más los anteriores.
- **Cambios pedidos por el usuario (RF-22 a RF-25), 2026-10-16:**
  - Zonas de SL y TP con una primitiva por debajo de las velas, y el importe en dólares en las etiquetas. Al arrastrar el SL, la zona y la etiqueta le siguen (comprobado: SL de 21312,50 a 21297,75 → −495 $).
  - Boleta con lado, unidad (puntos o $) y un solo botón de confirmar con el resumen ("Vender 2 NQ límite 21337.00").
  - Comprobado: con 2 NQ, SL de 505 $ → 12,5 pts (500 $) y TP de 505 $ → 12,75 pts (510 $); al volver a puntos se conservan.
  - Vista previa comprobada en play a 60x y en modo simulado a 10x: el SL previsto es siempre el precio que se ve, redondeado al tick, más el spread y menos la distancia. En venta límite, la entrada es el precio escrito y el SL queda por encima.
  - **Descubierto al probar:** en modo simulado, una compra a mercado se ejecutó a 21322,50 mientras el gráfico enseñaba unos 21308, porque el backend va un minuto por delante y ejecuta al cierre real de ese minuto (RF-16). Ahora, al operar a mercado en modo simulado, se completa la vela que se está dibujando; comprobado: la vela se cerró en 21327,01 y la compra salió a 21327,25 (ASK). Spec actualizada.
  - Las pruebas en Chrome se hicieron con un servidor aparte (`TRADING_REPLAY_DATOS` apuntando a una carpeta temporal con un enlace a `datos/velas`) para no tocar la cuenta del usuario. Truco útil para probar sin ensuciar sus datos.
  - 68 tests de pytest y 18 de Node en verde.
- **Renombrar, reiniciar y borrar cuentas (RF-26 a RF-28), 2026-10-16:**
  - API nueva: `POST /api/cuentas/{id}/reiniciar` y `DELETE /api/cuentas/{id}` (devuelve las cuentas que quedan). Renombrar ya existía en el `PATCH`. Reiniciar o borrar la activa con algo abierto, o borrar la única cuenta, da 409.
  - Una cuenta que no está activa nunca tiene nada abierto (para cambiar de cuenta hay que cerrar todo), así que se puede borrar aunque la activa tenga una posición.
  - Comprobado en Chrome con un servidor aparte: renombrar con una posición abierta, reiniciar rechazado con la posición abierta y aceptado tras cerrarla (balance a 50.000 $, historial y marcas del gráfico vacíos), crear "Reto" y borrarlo (vuelve a quedar activa la otra), y borrar la única cuenta rechazado con aviso.
  - **Corregido al probar:** el selector de cuentas no actualizaba el balance al operar; solo al abrir los ajustes. Ahora se actualiza con cada resumen de la cuenta.
  - 70 tests de pytest en verde.

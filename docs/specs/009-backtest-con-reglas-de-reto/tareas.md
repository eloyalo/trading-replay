# 009 · Tareas

Referencia: [plan.md](plan.md)

- [x] T1: `operativa/vigilancia.py` con la vigilancia sacada de `servicio.py`, sin cambiar lo que hace; los tests de las specs 005 y 006 siguen pasando
- [x] T2: `backtest/reto_bt.py` e integración en el ejecutor (días, intentos encadenados, vigilancia por minuto y en el acto, órdenes rechazadas, motivos, intento de cada operación); tests con velas sintéticas
- [x] T3: `metricas.resumen_reto`, esquema y migración de `backtests.sqlite`, trabajos y API; tests
- [x] T4: Frontend: selector de reto, sección del reto en los resultados, columna de intento e historial
- [x] T5: Datos reales y Chrome headless (ruptura y Danny con el Topstep 50K); documentación

## Notas de implementación

Lo que se descubra al implementar. Si afecta a la spec, actualizarla y anotarlo también en `docs/CONTEXTO.md`.

- **T1:** la vigilancia salió de `servicio.py` a `operativa/vigilancia.py` sin cambiar nada. Los 130 tests que había siguieron en verde sin tocarlos.
- **T2:** el día del reto se cambia al empezar la primera vela de un día de trading nuevo, antes de sus minutos, para que una posición que cruza las 18:00 ya cuente en el día nuevo. El motivo de lo que cierra el reto se apunta después del evento y antes de recoger las operaciones, porque hasta el evento no se sabe qué regla ha saltado.
- **T2, al probar:** los precios de ruptura esperados del test estaban mal calculados a mano (contaba las dos comisiones; al entrar solo se ha pagado la de entrada). El código daba lo correcto: la misma regla que en la spec 006.
- **T3:** la caché de operaciones de `almacen_bt` no se vaciaba al cambiar de base de datos (solo pasaba en los tests). Arreglado.
- **T3, migración:** probada con un test y con la base de datos real de la carpeta de pruebas, que tenía dos ejecuciones de la 008.
- **T4, al probar:** la columna "Reto" hacía desbordar el historial; el reto va ahora en una segunda línea bajo el nombre de la estrategia.
- **T5, datos reales con el Topstep 50K, 4 años de NQ:**
  - Ruptura del rango: 123 intentos, 27 aprobados y 95 suspendidos (22,1 %), 8,3 días del reto hasta aprobar. 533 operaciones las cierra el límite diario antes que su stop: con 1 NQ, el stop al otro lado del rango suele pasar de 1.000 $.
  - Danny strategy: 86 intentos, 16,5 % aprobados.
  - Todos los suspendidos lo son por pérdida máxima. Muchos con −5 $ tras un día bueno: la pérdida máxima de Topstep sube hasta el balance inicial, y la consistencia del 55 % impide aprobar con un solo día grande.
- **Chrome headless:** lanzar con reto desde la ventana, sección del reto con tarjetas e intentos, pulsar un intento para filtrar sus operaciones, historial con el reto y el modo gráfico con la salida "Límite diario". Sin errores de JavaScript.

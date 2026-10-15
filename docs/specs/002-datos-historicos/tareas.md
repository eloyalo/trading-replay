# 002 · Tareas

Referencia: [plan.md](plan.md)

- [x] T1: Dependencias y `config.py`
- [x] T2: Descarga y decodificación de Dukascopy (`dukascopy.py`), con tests
- [x] T3: Construcción del Parquet con limpieza y sesiones (`almacen.py`), con tests
- [x] T4: Consulta por timeframe con día de trading desde las 18:00 ET, con tests
- [x] T5: Informe de huecos (`huecos.py`), con tests
- [x] T6: CLI `trading-replay datos ...`
- [x] T7: Endpoints `/api/instrumentos` y `/api/velas`, con tests
- [x] T8: Frontend con selector de instrumento y timeframe y carga incremental
- [x] T9: Descarga real de los 4 años y comprobar los criterios de aceptación (falta 1 día de GC, ver spec)

## Notas de implementación

- Todas las velas con volumen 0 de Dukascopy son planas (O=H=L=C): son minutos sin cotizaciones. En el oro coinciden exactamente con la pausa de 17:00 a 18:00 ET. En los índices aparecen además minutos sueltos de madrugada.
- Los CFD de índices cierran a las 16:15 ET (ver la limitación en la spec).
- Primera descarga con `urllib`: unos 4 s por día porque cada petición abría una conexión TLS nueva (de 12 a 60 s de saludo TLS). Con conexiones keep-alive por hilo baja a unos 0,5 s por día con 8 hilos.
- En 1D la etiqueta de la vela (00:00 del día de trading) es posterior a su inicio real (18:00 de la víspera). Al cargar historia hacia atrás puede repetirse la primera vela, así que el frontend filtra las velas que ya tiene.
- Descarga real: 24 min para 3.756 días, con 39 errores 503 sobre todo en la ráfaga inicial. Al relanzar, 12 seguían fallando y después Dukascopy respondió **429** a todo: bloqueo temporal por exceso de peticiones. Ahora se usan 6 hilos, esperas más largas ante 429/503 y se respeta `Retry-After`.
- Tamaño: unos 70 MB de Parquet (1,35 a 1,41 millones de velas de 1m por instrumento), más los crudos.
- Rendimiento: NQ 15m de un mes en 44 ms; 1h de 4 años en 0,4 s; 1D de 4 años en 0,13 s.
- Tests: 16 en verde. Cubren la decodificación, sábados y días ya descargados, la limpieza, las sesiones, el día de trading con cambio de horario, la alineación de 4h, la hora ET para el gráfico, el horario por instrumento, los huecos y la API.

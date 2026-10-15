# 003 · Replay

- **Estado:** Aprobada (2026-10-15, con las respuestas del usuario a las dudas)
- **Fase:** 2
- **Creada:** 2026-10-15 · **Actualizada:** 2026-10-15

## Problema

Para practicar hay que ver el mercado como si fuera en vivo: situarse en un momento del pasado sin conocer lo que vino después y verlo avanzar, tomando decisiones con la información que había en ese instante.

## Alcance

**Incluye:**
- Sesión de replay con un reloj que solo avanza.
- Inicio en una fecha concreta o en un **momento aleatorio**.
- Avance vela a vela, play/pausa con varias velocidades y **modo tiempo real** (1x).
- Cambio de timeframe y de instrumento durante el replay sin ver el futuro.
- Opción de ocultar la fecha.
- Atajos de teclado básicos del replay.

**No incluye:**
- Órdenes ni cartera (fase 3). El diseño de esta spec las tiene en cuenta: el reloj del replay vive en el backend para que el motor de órdenes de la fase 3 avance con él.
- Herramientas de dibujo e indicadores: van en la spec 004, justo después de esta.
- Guardar y retomar sesiones de replay (fase 7).

## Requisitos

### Reloj del replay
1. **RF-1 · Sesión.** Al empezar un replay se crea en el backend una sesión con su **instante actual**. El backend nunca devuelve velas posteriores a ese instante mientras la sesión esté activa.
2. **RF-2 · Solo hacia delante.** El instante solo avanza. Para volver atrás hay que empezar un replay nuevo. Así no hay tentación de "deshacer" lo visto.
3. **RF-3 · Huecos.** Al avanzar se saltan los periodos sin datos (pausa diaria, fines de semana, festivos): el siguiente paso va a la siguiente vela que exista.

### Inicio
4. **RF-4 · Fecha concreta.** Se elige instrumento, fecha y hora de inicio (hora de Nueva York).
5. **RF-5 · Momento aleatorio.** Un botón elige un instante al azar con mercado abierto. Se puede filtrar por sesión: cualquiera, Asia, Londres o Nueva York.
   - Quedan fuera el primer mes del histórico (para que haya contexto previo) y la última semana (para que haya futuro que jugar).
   - El instante elegido tiene datos en ese minuto, no cae en un hueco.
6. **RF-6 · Contexto previo.** Al empezar se ve la historia anterior al instante, igual que en el gráfico normal: se puede desplazar hacia la izquierda sin límite.

### Avance
7. **RF-7 · Paso.** "Siguiente vela" avanza el reloj hasta el cierre de la vela actual del timeframe activo. En 15m, por ejemplo, salta a la siguiente vela de 15m.
8. **RF-8 · Play.** El reloj avanza minuto a minuto y las velas del timeframe activo se van formando. Velocidades:

   | Velocidad | 1 minuto de mercado dura |
   |---|---|
   | Tiempo real (1x) | 60 s |
   | 2x | 30 s |
   | 3x | 20 s |
   | 5x | 12 s |
   | 10x | 6 s |
   | 60x | 1 s |
   | 300x | 0,2 s |
   | 1000x | 0,06 s |

9. **RF-9 · Movimiento dentro del minuto.** Selector con dos modos, que se puede cambiar en cualquier momento:
   - **Real (por defecto):** el precio cambia una vez por minuto, con los datos de 1m tal cual.
   - **Simulado:** a velocidades bajas (de 1x a 10x) la vela del minuto se dibuja progresivamente con un recorrido aproximado: apertura → el extremo más cercano a la apertura → el otro extremo → cierre, con pequeñas oscilaciones. La vela final siempre es la real; solo el camino es inventado. En la interfaz se indica claramente "precio simulado dentro del minuto".
   - A partir de 60x no hay diferencia entre los dos modos (cada minuto dura 1 s o menos).
   - Nota para la fase 3: las órdenes siempre se ejecutan con los datos reales de 1m y el criterio conservador, nunca con el recorrido simulado, para que el modo simulado no cambie los resultados.
10. **RF-10 · Fin.** Al llegar al final de los datos, el replay se para y lo avisa.

### Sin ver el futuro
11. **RF-11 · Vela en formación.** En timeframes mayores que 1m, la última vela se construye solo con los minutos ya transcurridos. Por ejemplo, a las 10:37 la vela de 1h de las 10:00 tiene la apertura de las 10:00 y el máximo, el mínimo y el cierre hasta las 10:37.
12. **RF-12 · Cambiar timeframe.** Se puede cambiar de timeframe en cualquier momento y el gráfico se redibuja hasta el instante actual, con la vela en formación correcta.
13. **RF-13 · Cambiar instrumento.** El reloj es común a los tres instrumentos: si estás en NQ a las 10:37 y cambias a ES, ves ES a las 10:37. Sirve para comparar mercados en el mismo momento.

### Ocultar la fecha
14. **RF-14 · Modo a ciegas.** Opción para no ver la fecha (día, mes y año) ni en el eje del gráfico ni en la cabecera. Sí se ven la hora y el día de la semana, que son útiles para operar (por ejemplo, "Mar 10:37"). Se puede activar antes de empezar y desactivar en cualquier momento. Al desactivarlo se ve la fecha real.

### Controles
15. **RF-15 · Barra de replay.** Botones: Momento aleatorio, Ir a fecha, Siguiente vela, Play/Pausa, selector de velocidad, selector real/simulado, ocultar fecha y Salir del replay. Se ve el instante actual (o solo día de la semana y hora en modo a ciegas).
16. **RF-16 · Atajos.**
    - `→`: siguiente vela.
    - `Espacio`: play/pausa.
    - `R`: momento aleatorio.
    - `Esc`: salir del replay.
17. **RF-17 · Salir.** Al salir del replay se vuelve al gráfico normal con todo el histórico.

## Criterios de aceptación

- [ ] Con un replay en marcha, ninguna petición de la API devuelve una vela posterior al instante actual (comprobado con un test).
- [ ] En 1h, a las 10:37, la última vela coincide con la agregación manual de los minutos de 10:00 a 10:36.
- [ ] Cambiar de 1m a 1h y volver durante el replay no muestra ninguna vela futura.
- [ ] El momento aleatorio cae siempre en un minuto con datos, dentro de la sesión pedida, y nunca en el primer mes ni en la última semana (test con muchas repeticiones).
- [ ] En modo a ciegas no aparece la fecha en ningún sitio de la pantalla.
- [ ] El play a 1000x se ve fluido, sin parpadeos ni saltos del gráfico.
- [ ] Con el reloj un viernes a las 16:14 ET, "siguiente vela" en 1m salta al domingo a las 18:00.
- [ ] En modo simulado, al terminar cada minuto la vela coincide exactamente con la real.

## Dudas resueltas (2026-10-15)

1. **Herramientas de dibujo:** en una spec aparte (004) justo después. El usuario quiere además **indicadores**; también irán en la 004.
2. **Movimiento dentro del minuto:** el usuario quiere poder elegir entre real y simulado (RF-9).
3. **Velocidades:** las propuestas más 2x, 3x y 5x (RF-8).

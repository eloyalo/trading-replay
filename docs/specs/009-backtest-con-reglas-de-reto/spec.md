# 009 · Backtest con las reglas de un reto de prop firm

- **Estado:** En curso: implementada y probada, pendiente de que el usuario la pruebe (aprobada por delegación el 2026-10-17)
- **Fase:** 5 (ampliación del backtest)
- **Creada:** 2026-10-17 · **Actualizada:** 2026-10-17

## Problema

El backtest (spec 008) dice si una estrategia gana dinero a lo largo del histórico, pero no si aprobaría un reto de prop firm. Un reto suspende por la pérdida máxima o lo pausa el límite diario mucho antes de que una estrategia "rentable a 4 años" se recupere. Y la consistencia o los días mínimos pueden impedir aprobar aunque se llegue al objetivo. El usuario quiere saber, con una estrategia concreta: ¿aprobaría el Topstep 50K? ¿Cuántas veces de cada diez? ¿En cuántos días? ¿Por qué regla suspende cuando suspende?

## Alcance

**Incluye:**
- Lanzar un backtest con un perfil de reto de `perfiles/` (spec 006), además de sin reto como hasta ahora.
- Aplicar las reglas del perfil mientras corre la estrategia, minuto a minuto, con el mismo código que el replay.
- Encadenar intentos a lo largo del periodo: cuando uno se aprueba o se suspende, empieza otro.
- Resultados del reto: intentos, % de aprobados, días hasta aprobar, motivos de suspensión y la lista de intentos.

**No incluye:**
- Que la estrategia sepa que está en un reto (su balance, el umbral o lo que le queda), por ejemplo para ajustar el tamaño. Se puede añadir después.
- La cuenta financiada después de aprobar (reglas de pago y de la cuenta funded).
- El coste de los intentos (cuotas de la prop firm).
- Intentos que empiecen cada día y se solapen. Habría que pasar la estrategia una vez por cada día de inicio **(decidido por Claude)**.

## Requisitos

### Lanzar
1. **RF-1 · Elegir reto.** Al lanzar un backtest se puede elegir un perfil de reto, o ninguno. Sin reto, todo funciona como en la spec 008. Con reto, el balance de partida es el del perfil y los costes, los que se elijan al lanzar.

### Reglas
2. **RF-2 · Mismas reglas que en el replay.** Pérdida máxima (estática, trailing al cierre o trailing intradía, con su tope), límite diario (pausa o suspende), consistencia, días mínimos con beneficio mínimo, contratos máximos y hora de cierre se aplican como en la spec 006. Se vigilan en cada minuto con el peor precio y, al romper una regla, se cierra todo al precio de ruptura. Lo que cambia es solo cómo se cuentan los días (RF-3) y que los intentos se encadenan (RF-5). El código de la vigilancia es el mismo para el replay y para el backtest.
3. **RF-3 · Día del reto.** En el backtest no hay saltos: cada día de trading del histórico (de las 18:00 ET de la víspera a las 18:00 ET) es un día del reto. Cuenta como día si tuvo alguna ejecución, como en el replay. Al acabar cada día se aplica el trailing al cierre y se mira si el intento queda aprobado **(decidido por Claude)**.
4. **RF-4 · Órdenes que el reto no admite.** Con el día pausado por el límite diario, fuera del horario del reto o pasándose de los contratos máximos, la orden de la estrategia no se envía. La estrategia sigue como si nada (no es un error). Los resultados dicen cuántas órdenes se rechazaron y por qué **(decidido por Claude)**.

### Intentos
5. **RF-5 · Intentos encadenados.** El primer intento empieza al principio del periodo. Cuando un intento se aprueba o se suspende, se cierra lo que haya abierto y el siguiente empieza el día de trading siguiente, con el balance inicial del perfil y las reglas a cero. El último intento puede quedar sin terminar al acabar los datos **(decidido por Claude)**.
6. **RF-6 · Operaciones del intento.** Cada operación sabe a qué intento pertenece. Las que cierra el reto llevan el motivo: "Pérdida máxima", "Límite diario", "Hora de cierre del reto" o "Fin del intento" (aprobado con algo abierto).

### Resultados
7. **RF-7 · Resumen del reto.** Intentos aprobados, suspendidos y sin terminar. **% de aprobados** (aprobados ÷ terminados). Días del reto y días naturales de media hasta aprobar y hasta suspender. Motivos de suspensión con su cuenta. Beneficio medio de los intentos aprobados y de los suspendidos. Órdenes rechazadas por el reto, por motivo.
8. **RF-8 · Lista de intentos.** Número, primer y último día, resultado, motivo, días del reto, beneficio, mejor día y operaciones. Desde un intento se ven sus operaciones: los filtros de fecha se ponen en su periodo.
9. **RF-9 · Junto a lo demás.** Las métricas, la curva, el desglose y la lista de operaciones de la spec 008 siguen igual, con todas las operaciones de todos los intentos. La lista enseña el intento de cada operación.
10. **RF-10 · Historial.** El historial de ejecuciones dice con qué reto se lanzó cada una y su % de aprobados.

## Criterios de aceptación

- [x] Con velas sintéticas y un perfil de prueba: un intento que llega al objetivo y cumple los días se aprueba al cerrar el día; uno que toca la pérdida máxima se suspende en ese minuto, al precio de ruptura; y el siguiente intento empieza al día de trading siguiente con el balance inicial (test).
- [x] El límite diario con efecto "pausa" cierra todo y rechaza las órdenes del resto del día, y al día siguiente se vuelve a operar (test).
- [x] La consistencia y los días mínimos impiden aprobar aunque se llegue al objetivo, igual que en la spec 006 (test).
- [x] Contratos máximos y hora de cierre: la orden que se pasa no se envía y a la hora de cierre se cierra todo (test).
- [x] Los tests de los retos del replay (spec 006) siguen pasando después de sacar la vigilancia a un módulo común.
- [x] Por la API y en Chrome con datos reales (Chrome headless; falta la revisión del usuario): lanzar la ruptura del rango y la Danny strategy con el Topstep 50K y ver % de aprobados, intentos y sus operaciones.

## Dudas

Ninguna abierta: el usuario delegó las decisiones. Las marcadas **(decidido por Claude)** se pueden cambiar cuando las pruebe.

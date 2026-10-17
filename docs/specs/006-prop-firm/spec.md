# 006 · Simulador de prop firm

- **Estado:** Hecha (aprobada el 2026-10-16; el usuario la probó y la dio por buena el 2026-10-16, con el RF-22 añadido)
- **Fase:** 4
- **Creada:** 2026-10-16 · **Actualizada:** 2026-10-16 (pedido por el usuario: cuentas Static de DayTraders, celebración al aprobar, resumen de cuentas y nueva cuenta desde el resumen)

## Problema

Con la cuenta simulada (spec 005) se ve si una estrategia gana dinero, pero no si pasaría un reto de prop firm. Los retos tienen reglas propias: un objetivo de beneficio, una pérdida máxima que a menudo se mueve con el balance, un límite diario y una regla de consistencia. Una estrategia rentable puede suspender por cualquiera de ellas. El usuario quiere practicar con esas reglas aplicadas en el momento, como en la plataforma real, y quiere tener varias cuentas, cada una con su uso.

## Reglas revisadas (2026-10-16)

Las reglas cambian a menudo. Se han revisado en las páginas oficiales y por eso los perfiles son archivos que se pueden editar (RF-2).

**Topstep, Trading Combine** ([parámetros](https://help.topstep.com/en/articles/8284197-trading-combine-parameters), [pérdida máxima](https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit), [consistencia](https://help.topstep.com/en/articles/8284208-consistency-at-topstep), [límite diario](https://help.topstep.com/en/articles/10490293-daily-loss-limit-in-the-trading-combine-and-express-funded-account)):

| Cuenta | Objetivo | Pérdida máxima (trailing al cierre del día) | Límite diario (opcional) | Contratos |
|---|---|---|---|---|
| 50K | 3.000 $ | 2.000 $ | 1.000 $ | 5 minis o 50 micros |
| 100K | 6.000 $ | 3.000 $ | 2.000 $ | 10 o 100 |
| 150K | 9.000 $ | 4.500 $ | 3.000 $ | 15 o 150 |

- La pérdida máxima sube con el balance al cierre de cada día, nunca baja y se queda fija al llegar al balance inicial. Se vigila en tiempo real, con el PnL abierto incluido: si se toca, se liquida y el reto queda suspendido.
- El límite diario es opcional al comprar el reto. Si se toca, se cierra todo y no se puede operar hasta el día siguiente, pero no se suspende.
- Consistencia: el mejor día no puede pasar del 55 % del beneficio total. Si se pasa, el objetivo sube a mejor día ÷ 0,55.
- Hay que estar sin posiciones a las 15:10 CT (16:10 ET).

**DayTraders** ([tamaños de las evaluaciones](https://daytraders.com/help/articles/10131750-evaluation-account-sizes-fees-and-details), [cuentas EOD](https://daytraders.com/help/articles/14473672-eod-account-rules), [tipos de drawdown](https://daytraders.com/help/articles/9855052-drawdown-threshold-guide-trailing-static-eod), [cómo funcionan](https://daytraders.com/how-futures-funding-evaluations-work)):

| Cuenta | Objetivo | Drawdown | Límite diario | Beneficio mínimo de un día válido | Contratos |
|---|---|---|---|---|---|
| Trail 25K | 1.500 $ | 1.500 $ trailing intradía | no tiene | 100 $ | 6 o 60 |
| Trail 50K | 3.000 $ | 2.500 $ trailing intradía | no tiene | 200 $ | 10 o 100 |
| EOD 25K | 1.500 $ | 1.000 $ trailing al cierre | 800 $ | 100 $ | 6 o 60 |
| EOD 50K | 3.000 $ | 2.000 $ trailing al cierre | 1.250 $ | 200 $ | 10 o 100 |
| EOD 150K | 8.500 $ | 4.000 $ trailing al cierre | 2.000 $ | 300 $ | 12 o 120 |
| EOD 300K | 15.000 $ | 6.500 $ trailing al cierre | 3.250 $ | 400 $ | 40 o 400 |
| Static 25K | 2.500 $ | 750 $ estático | no tiene | 100 $ | 4 o 40 |
| Static 50K | 3.750 $ | 1.000 $ estático | no tiene | 200 $ | 6 o 60 |
| Static 100K | 5.750 $ | 1.500 $ estático | no tiene | 200 $ | 8 o 80 |
| Static 150K | 6.750 $ | 1.750 $ estático | no tiene | 300 $ | 8 o 80 |

- Estático: el umbral se fija el primer día y no se mueve nunca.
- Trailing intradía: sigue el balance en vivo más alto, con el PnL abierto. En la evaluación deja de subir cuando el umbral llega al objetivo.
- El límite diario pausa la cuenta hasta el día siguiente; no suspende.
- Consistencia del 50 %. Hacen falta 2 días válidos: días con al menos ese beneficio mínimo.
- **Sin confirmar:** el beneficio mínimo de las Trail y las Static (se usa el de la EOD del mismo tamaño; para la Static 100K, que no tiene EOD equivalente, el de 50K). Algunas reseñas dan 3 contratos para la Static 50K; se usa el 6 de la página oficial. Tampoco se sabe si hay hora de cierre obligatoria (se deja sin ella) y si hay hora de cierre obligatoria (se deja sin ella). El EOD trailing de DayTraders no dice si deja de subir; se pone el mismo tope que la Trail.

## Alcance

**Incluye:**
- Perfiles de reto en archivos JSON, con los de Topstep y DayTraders (Trail, EOD y Static) de las tablas.
- Cada cuenta tiene un tipo: libre (como la Demo) o reto con un perfil.
- Reglas: objetivo, pérdida máxima (estática, trailing intradía o trailing al cierre del día), límite diario, consistencia, días mínimos, contratos máximos y hora de cierre obligatoria.
- Estado del reto en tiempo real (en curso, aprobado o suspendido, con el motivo) y en el gráfico la línea donde se rompería la pérdida máxima.
- Historial de intentos de cada cuenta de reto.
- Resumen de todas las cuentas, también fuera del replay, con la consistencia explicada y lo que falta para aprobar.
- Ventana con confeti al aprobar.

**No incluye:**
- La fase de cuenta fondeada (Express Funded, Pro): retiradas, reparto de beneficios, escalado de contratos. Se puede añadir como otro perfil más adelante.
- Precios de los retos, cuotas de activación y reinicios de pago.
- Reglas de noticias o de productos permitidos.
- Editar perfiles desde la interfaz: se editan los archivos.

## Requisitos

### Perfiles
1. **RF-1 · Perfil.** Un perfil describe un reto: empresa, nombre, balance inicial, objetivo, pérdida máxima (importe, tipo y hasta dónde sube), límite diario (importe y efecto), consistencia (%), días mínimos y beneficio mínimo de un día válido, contratos máximos (en minis; un micro cuenta como 1/10) y hora de cierre obligatoria. Cada regla es opcional salvo el objetivo y la pérdida máxima.
2. **RF-2 · Archivos.** Los perfiles son archivos JSON en `perfiles/` en la raíz del proyecto, uno por empresa con la lista de sus cuentas, con la fecha de revisión y las fuentes. Se incluyen los de las tablas de arriba. Añadir o corregir un perfil es editar un archivo, sin tocar código **(decidido por Claude)**.

### Cuentas de reto
3. **RF-3 · Tipo de cuenta.** Al crear una cuenta se elige "Libre" (nombre y balance inicial, como ahora) o un perfil de reto. Una cuenta de reto toma el balance inicial del perfil y se llama como él por defecto ("Topstep 50K"). Las cuentas que ya existen son libres. El perfil de una cuenta no se cambia después.
4. **RF-4 · Día del reto.** Cada salto (cada replay nuevo, por momento aleatorio o por fecha) es un día del reto, aunque dentro del salto se cruce el cambio de día del mercado (decidido por el usuario). El día se cierra al saltar o al salir del replay. Un día cuenta como operado si tiene al menos una ejecución.
5. **RF-5 · Varias a la vez.** Puede haber varias cuentas de reto, del mismo perfil o de otros, cada una con su estado. Se opera con la activa, como ahora.

### Reglas
6. **RF-6 · Pérdida máxima.** El umbral empieza en balance inicial − pérdida máxima.
   - **Estática:** no se mueve.
   - **Trailing al cierre del día:** al cerrar cada día sube hasta balance de cierre − pérdida máxima si eso es más alto. Nunca baja.
   - **Trailing intradía:** sube con el balance en vivo más alto (balance + PnL abierto) mientras se opera. Nunca baja.
   - Si el perfil lo indica, el umbral deja de subir al llegar a un tope (el balance inicial en Topstep, el objetivo en DayTraders).
   - Se vigila en cada minuto con el PnL abierto. Con datos de 1m no se sabe el orden de los precios dentro del minuto, así que se usa el criterio conservador de la spec 005: primero se mira si el peor precio del minuto rompe el umbral y después se sube el umbral con el mejor precio **(decidido por Claude)**.
7. **RF-7 · Romper la pérdida máxima.** Si el balance en vivo llega al umbral, se cierra todo como lo haría un stop al precio en que se toca el umbral (con hueco, a la apertura del minuto) y el reto queda **suspendido** con el motivo, el instante y el balance. Una cuenta suspendida no admite órdenes.
8. **RF-8 · Límite diario.** Si la pérdida del día (balance en vivo − balance al empezar el día) llega al límite, se cierra todo igual que en RF-7. Según el perfil:
   - **Pausa** (Topstep, DayTraders): no se puede operar hasta el siguiente salto. El reto sigue en curso.
   - **Suspende:** el reto queda suspendido. Para perfiles de otras empresas que lo usen.
9. **RF-9 · Consistencia.** Con un porcentaje P, el objetivo efectivo es el mayor entre el objetivo del perfil y mejor día ÷ P. El beneficio de cada día es neto, con comisiones **(decidido por Claude)**. Las pérdidas no reducen el mejor día.
10. **RF-10 · Días mínimos.** Hacen falta N días válidos: días con un beneficio neto de al menos el mínimo del perfil (si no hay mínimo, cualquier día operado).
11. **RF-11 · Contratos máximos.** Se rechaza una orden de entrada si, al ejecutarse, la suma de todas las posiciones (en minis, todos los instrumentos juntos) pasaría del máximo. Para no esquivarlo con órdenes pendientes, también se cuentan las órdenes de entrada pendientes del mismo lado **(decidido por Claude)**.
12. **RF-12 · Hora de cierre.** Si el perfil la tiene, a esa hora (ET) se cierra todo y se cancelan las órdenes. No se puede operar hasta la reapertura de las 18:00 ET. No suspende.
13. **RF-13 · Aprobar.** Al cerrar un día, si el beneficio total neto llega al objetivo efectivo (RF-9) y hay los días válidos que pide el perfil (RF-10), el reto queda **aprobado**. Una cuenta aprobada ya no admite órdenes. Se comprueba al cerrar el día y no al tocar el objetivo, porque en los retos reales el objetivo hay que mantenerlo hasta el cierre **(decidido por Claude)**.

### Intentos
14. **RF-14 · Reiniciar un reto.** Reiniciar una cuenta de reto (RF-27 de la spec 005) empieza un intento nuevo. El intento anterior se guarda en el historial con su resultado (aprobado, suspendido o abandonado si se reinicia en curso), el motivo, los días, el beneficio y el mejor día. Las operaciones del intento anterior se borran, como en las cuentas libres.

### Interfaz
15. **RF-15 · Panel del reto.** Con una cuenta de reto activa, el panel de operar enseña:
    - Estado: en curso, aprobado o suspendido, con el motivo.
    - Progreso hacia el objetivo efectivo, y el objetivo del perfil si la consistencia lo ha subido.
    - Distancia a la pérdida máxima (balance en vivo − umbral) y el umbral.
    - Pérdida del día y lo que queda hasta el límite diario.
    - Día del reto, días válidos y mejor día.
    - Contratos en uso y el máximo.
16. **RF-16 · En el gráfico.** Con una posición abierta en una cuenta de reto, una línea discontinua roja marca el precio al que se cerraría todo: el de la pérdida máxima o el del límite diario, el que esté más cerca, con su nombre en la etiqueta **(decidido por Claude)**.
17. **RF-17 · Avisos.** Al pausar por límite diario o cerrar por la hora obligatoria, se para el play y sale un aviso con el motivo. Al aprobar o suspender, la ventana de RF-20.
18. **RF-18 · Historial de intentos.** En los ajustes de la cuenta, la lista de intentos anteriores con su resultado.
19. **RF-19 · Modo a ciegas.** El panel del reto no enseña fechas.
20. **RF-20 · Celebración al aprobar** (pedido por el usuario). Al aprobar un reto se para el play, cae confeti por toda la pantalla y sale una ventana modal propia de la app (no una alerta del navegador) que celebra el aprobado: perfil, beneficio total, días y mejor día. Tiene dos botones: "Nuevo intento", que reinicia la cuenta (RF-14), y "Cerrar". El confeti se hace sin librerías externas **(decidido por Claude)** y dura unos segundos. Al suspender sale una ventana igual, sin confeti, con el motivo.
21. **RF-21 · Resumen de cuentas** (pedido por el usuario). Un botón "Cuentas" en la barra de arriba, visible siempre (también antes de empezar un replay), abre una ventana con una tarjeta por cuenta y un botón para usarla:
    - **Todas:** balance inicial y actual, beneficio neto (en $ y %), operaciones, % de acierto, mayor ganancia, mayor pérdida, comisiones pagadas y días operados.
    - **Retos**, además: empresa y cuenta, estado (con el motivo), día del reto, objetivo y cuánto falta, distancia a la pérdida máxima y umbral actual, límite diario, días válidos (con el beneficio mínimo) y la lista de días con su resultado.
    - **Consistencia explicada con los números de la cuenta**, con ganancias y pérdidas: mejor día y qué % es del beneficio total, el máximo que permite la regla, el beneficio total que hace falta con ese mejor día y cuánto falta, que tiene que salir de otros días. Por ejemplo: "Mejor día +1.800 $ = 72 % de tu beneficio (+2.500 $). Con la regla del 55 % necesitas +3.272,73 $ en total: te faltan +772,73 $, en días distintos del mejor."
    - **Qué falta para aprobar,** en una línea: "Te faltan 772,73 $ y 1 día válido".
    - Los intentos anteriores de cada reto.
    - En modo a ciegas no se ven fechas: los días van numerados.
22. **RF-22 · Nueva cuenta desde el resumen** (pedido por el usuario al probar la fase). La ventana de "Cuentas" tiene un botón "Nueva cuenta" que despliega el mismo formulario que el panel de operar (tipo, nombre y balance inicial) y crea la cuenta y la deja activa, también fuera del replay. Si hay algo abierto en la cuenta activa, se explica en la ventana que no se puede, como al usar otra cuenta.

## Criterios de aceptación

- [x] Topstep 50K: con una posición abierta cuyo PnL abierto lleva el balance a 48.000 $, el reto queda suspendido en ese minuto con el motivo "Pérdida máxima" (test).
- [x] Trailing al cierre del día: si un día cierra en 50.500 $, el umbral pasa de 48.000 a 48.500 $ y no baja si el día siguiente pierde; al cerrar un día en 52.500 $ se queda en 50.000 $ (test).
- [x] Trailing intradía: un pico de 52.000 $ en vivo sube el umbral a 49.500 $ aunque la operación se cierre después en 51.000 $; el peor precio de un minuto se mira antes que el mejor (test).
- [x] Límite diario con pausa: al tocarlo se cierra todo, se rechazan las órdenes hasta el siguiente salto y el reto sigue en curso (test).
- [x] Consistencia: en Topstep 50K, un mejor día de 2.200 $ sube el objetivo a 4.000 $ (test).
- [x] Días mínimos: en DayTraders 50K, 3.000 $ en un día y 150 $ en otro no aprueban; con un tercer día de 200 $ o más, sí (y cumpliendo la consistencia) (test).
- [x] Contratos máximos: en Topstep 50K se rechaza una orden que llevaría a 6 minis, o a 4 NQ más 11 MES (test).
- [x] Hora de cierre: en Topstep, una posición abierta a las 16:09 ET se cierra en el minuto de las 16:10 ET (test).
- [x] Aprobar: al llegar al objetivo con los días necesarios, el reto se aprueba al saltar y ya no admite órdenes (test).
- [x] En Chrome: al aprobar un reto sale la ventana con confeti, y "Nuevo intento" deja la cuenta como nueva.
- [x] DayTraders Static 50K: el umbral se queda en 49.000 $ aunque el balance suba (test).
- [x] El resumen de cuentas calcula bien beneficio, % de acierto, objetivo efectivo, lo que falta por consistencia y los días válidos de una cuenta con días ganadores y perdedores (test).
- [x] En Chrome: el botón "Cuentas" funciona fuera del replay y la consistencia se explica con los números de la cuenta.
- [x] En Chrome: desde la ventana de "Cuentas", fuera del replay, se crea un reto Topstep 50K y queda activo, con su tarjeta en la lista.
- [x] Reiniciar un reto suspendido guarda el intento en el historial y deja la cuenta como nueva (test).
- [x] En Chrome, con datos reales: crear un reto Topstep 50K, ver el panel, la línea de pérdida máxima, y suspenderlo a propósito con una posición grande.

## Dudas

- La cuenta aprobada se queda bloqueada y se reinicia con "Nuevo intento" **(decidido por Claude, a falta de que el usuario diga otra cosa)**. La fase de fondeada queda fuera de esta spec.

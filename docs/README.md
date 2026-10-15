# Documentación

## Estructura

```
docs/
├── README.md            ← este archivo: cómo se organiza todo
├── FASES.md             ← hoja de ruta por fases
├── CONTEXTO.md          ← estado actual, preguntas abiertas y bitácora
├── specs/               ← una carpeta por funcionalidad
│   ├── _plantilla/      ← copiar para crear una spec nueva
│   └── NNN-nombre/
│       ├── spec.md      ← QUÉ y POR QUÉ (requisitos, criterios de aceptación)
│       ├── plan.md      ← CÓMO (diseño técnico, módulos, datos)
│       └── tareas.md    ← pasos concretos con checkbox
└── decisiones/          ← ADRs: decisiones técnicas y su motivo
    ├── _plantilla.md
    └── NNNN-titulo.md
```

## Flujo SDD

1. **Spec.** Antes de programar una funcionalidad se escribe `spec.md`: qué tiene que hacer, qué queda fuera y cómo sabremos que funciona. El usuario la revisa y la aprueba.
2. **Plan.** Con la spec aprobada, `plan.md` describe la solución técnica. Si implica una decisión con alternativas reales, se registra un ADR en `decisiones/`.
3. **Tareas.** `tareas.md` divide el plan en pasos pequeños que se puedan probar por separado.
4. **Implementación.** Se marcan las tareas al completarlas. Lo que se descubra por el camino (limitaciones, bugs, cambios de idea) se anota en la bitácora de `CONTEXTO.md` y, si cambia la spec, se actualiza la spec.
5. **Cierre.** Se comprueban los criterios de aceptación y la spec pasa a estado `Hecha`.

## Convenciones

- Numeración de specs: `001`, `002`... en el orden en que se crean, no por fase.
- Estados de una spec: `Borrador` → `Aprobada` → `En curso` → `Hecha` (o `Descartada`).
- Fechas en formato `AAAA-MM-DD`.
- Los ADR no se borran: si una decisión cambia, se crea un ADR nuevo que sustituye al anterior y se indica en ambos.

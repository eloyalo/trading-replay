# Instrucciones para Claude

- Responder siempre en español.
- Antes de tocar nada, leer `docs/CONTEXTO.md` (estado actual, siguiente paso, mapa del código y convenciones) y `docs/FASES.md` (hoja de ruta).
- El proyecto sigue SDD (Spec-Driven Development), explicado en `docs/README.md`: no se escribe código de una funcionalidad sin su `spec.md` aprobado por el usuario.
- Se avanza paso a paso: una fase o tarea cada vez, y se confirma con el usuario antes de pasar a la siguiente.
- Al terminar una sesión de trabajo, o cuando se descubra algo relevante (un fallo, una limitación de los datos, una decisión), actualizar `docs/CONTEXTO.md` y, si toca, crear un ADR en `docs/decisiones/`.
- **No hacer commits ni push.** El usuario gestiona git personalmente.

## Entorno

- Python gestionado con `uv` (`uv sync`, `uv run ...`). Tests: `uv run pytest`.
- Para parar un servidor o proceso, hacerlo por su PID, nunca con `pkill -f` y un patrón genérico.
- No lanzar descargas masivas a Dukascopy sin necesidad: bloquea temporalmente (HTTP 429).
- Si existe `CLAUDE.local.md`, contiene notas del equipo local del usuario (no se publica).

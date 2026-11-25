# Checkpoint

Guía para trabajar en este repositorio con Claude Code. Desarrollo, pruebas y lint: `docs/development.md`; mapa del código: `docs/structure.md`.

## Modelos por tarea

Patrón «líder + Haiku lee + Sonnet escribe». El líder es el modelo de la sesión: lo elige el usuario con `/model`. Mensaje para el líder:

> Vas a ser el líder del proyecto. Tú piensas, decides, cuestionas y apruebas el plan antes de que se ejecute; cuidas la calidad, las buenas prácticas y la seguridad. Para escribir código usa el agente implementer (Sonnet); para leer y explorar, Explore (Haiku). Solo te metes si implementer se queda dando vueltas y no puede pasar una barrera. Despliega los agentes que necesites. Pásales el contexto necesario en el prompt: no heredan tu conversación.

- Los agentes están en `.claude/agents/` (`Explore.md`, `implementer.md`). El fichero de Haiku debe llamarse exactamente `Explore` (`name: Explore`) para sustituir al integrado.
- Son de desarrollo: NO van en la imagen Docker (`.dockerignore` excluye `.claude`) ni en los paquetes del producto (el instalador de Windows y el zip del plugin de la Deck copian solo rutas explícitas).

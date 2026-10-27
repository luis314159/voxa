"""«Agrega llamar al plomero a mis pendientes», «¿qué pendientes tengo?», «ya hice la tarea de mate»."""

from __future__ import annotations

from voxa.core.people import speaker
from voxa.core.phrases import capitalize, join_words
from voxa.core.types import Intent, Response
from voxa.state.tasks import TaskList


def _count(n: int) -> str:
    return "un pendiente" if n == 1 else f"{n} pendientes"


class TasksSkill:
    def __init__(self, tasks: TaskList) -> None:
        self.tasks = tasks

    async def handle(self, intent: Intent) -> Response:
        named = (intent.slots.get("person") or "").strip().title() or None
        mine = intent.slots.get("whose") == "mine"
        # «mis pendientes»: los de quien habla, si VOXA reconoce su voz; si no, los de la casa.
        person = named or (speaker() if mine else None)
        match intent.name:
            case "tasks.add":
                task = self.tasks.add(intent.slots.get("query", ""), person)
                if task is None:
                    return Response("Eso ya estaba en los pendientes.")
                whose = f"los pendientes de {person}" if named else "tus pendientes" if person else "los pendientes de la casa"
                return Response(f"Anotado en {whose}: {task.text}.")
            case "tasks.list":
                return Response(self._list(person, named is not None))
            case "tasks.done":
                done = self.tasks.done(intent.slots.get("query", ""), person)
                if done is None:
                    return Response(f"No encontré «{intent.slots.get('query', '')}» en los pendientes.", sound="error")
                left = len(self.tasks.of(done.person))
                return Response(f"Listo, taché {done.text}." + (f" Quedan {_count(left)}." if left else " ¡Ya no hay pendientes!"))
        return Response("Todavía no sé hacer eso con los pendientes.", sound="error")

    def _list(self, person: str | None, named: bool) -> str:
        own = [t.text for t in self.tasks.of(person)] if person else []
        house = [t.text for t in self.tasks.of(None)]
        parts = []
        if person:
            who = f"{person} tiene" if named else "Tienes"
            parts.append(f"{who} {_count(len(own))}: {join_words(own)}." if own else
                         f"{'No tienes' if not named else person + ' no tiene'} pendientes.")
        if house and not named:
            parts.append(capitalize(f"de la casa: {join_words(house)}."))
        if not parts:
            return "No hay pendientes."
        return " ".join(parts)

    def morning(self, person: str | None) -> str:
        """Para «buenos días»: cuántos pendientes tiene quien saludó (vacío si ninguno)."""
        own = self.tasks.of(person) if person else []
        return f"Tienes {_count(len(own))}: {join_words([t.text for t in own])}." if own else ""

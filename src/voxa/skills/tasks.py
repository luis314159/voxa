"""«Agrega llamar al plomero a mis pendientes», «¿qué pendientes tengo?», «ya hice la tarea de mate»."""

from __future__ import annotations

from voxa.core.people import speaker
from voxa.core.phrases import capitalize, join_words
from voxa.core.types import Intent, Response
from voxa.i18n import tr
from voxa.state.tasks import TaskList


def _count(n: int) -> str:
    return tr("un pendiente") if n == 1 else tr("{count} pendientes", count=n)


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
                whose = (tr("los pendientes de {person}", person=person) if named else tr("tus pendientes") if person
                         else tr("los pendientes de la casa"))
                return Response(tr("Anotado en {whose}: {task}.", whose=whose, task=task.text))
            case "tasks.list":
                return Response(self._list(person, named is not None))
            case "tasks.done":
                done = self.tasks.done(intent.slots.get("query", ""), person)
                if done is None:
                    return Response(tr("No encontré «{task}» en los pendientes.", task=intent.slots.get("query", "")),
                                    sound="error")
                left = len(self.tasks.of(done.person))
                rest = tr(" Quedan {count}.", count=_count(left)) if left else tr(" ¡Ya no hay pendientes!")
                return Response(tr("Listo, taché {task}.", task=done.text) + rest)
        return Response("Todavía no sé hacer eso con los pendientes.", sound="error")

    def _list(self, person: str | None, named: bool) -> str:
        own = [t.text for t in self.tasks.of(person)] if person else []
        house = [t.text for t in self.tasks.of(None)]
        parts = []
        if person:
            if own:
                who = tr("{person} tiene", person=person) if named else tr("Tienes")
                parts.append(tr("{who} {count}: {items}.", who=who, count=_count(len(own)), items=join_words(own)))
            else:
                parts.append(tr("{person} no tiene pendientes.", person=person) if named else tr("No tienes pendientes."))
        if house and not named:
            parts.append(capitalize(tr("de la casa: {items}.", items=join_words(house))))
        if not parts:
            return "No hay pendientes."
        return " ".join(parts)

    def morning(self, person: str | None) -> str:
        """Para «buenos días»: cuántos pendientes tiene quien saludó (vacío si ninguno)."""
        own = self.tasks.of(person) if person else []
        if not own:
            return ""
        return tr("{who} {count}: {items}.", who=tr("Tienes"), count=_count(len(own)), items=join_words([t.text for t in own]))

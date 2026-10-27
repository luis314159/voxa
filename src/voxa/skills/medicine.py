"""«Ya me la tomé», «todavía no» y «¿ya se tomó Ana la medicina?»."""

from __future__ import annotations

from datetime import datetime

from voxa.core.people import speaker
from voxa.core.phrases import format_duration
from voxa.core.types import Intent, Response
from voxa.i18n import tr
from voxa.medicine import MedicineTracker, what


def _hour(ts: float) -> str:
    at = datetime.fromtimestamp(ts)
    return f"{at.hour}:{at.minute:02d}"


class MedicineSkill:
    def __init__(self, tracker: MedicineTracker) -> None:
        self._tracker = tracker

    async def handle(self, intent: Intent) -> Response:
        tracker = self._tracker
        ringing = tracker.ringing()
        if intent.name == "medicine.later":
            if not ringing:
                return Response("No hay ninguna medicina pendiente ahorita.")
            minutes = tracker.config.ask_every_minutes
            for timer in ringing:
                tracker.timers.snooze(timer, minutes * 60)
            return Response(tr("Va, te pregunto otra vez en {duration}.", duration=format_duration(minutes * 60)))
        if intent.name != "medicine.taken":
            return Response("Todavía no sé hacer eso.", sound="error")
        if ringing:  # contesta a la pregunta: se anota y deja de sonar
            people = {t.person for t in ringing if t.person}
            tracker.timers.stop_ringing()
            who = speaker() or (people.pop() if len(people) == 1 else None)
            if who:
                return Response(tr("¡Muy bien, {person}! Lo anoté.", person=who))
            return Response("¡Muy bien! Lo anoté.")
        # Sin alarma sonando es una pregunta: nunca se anota sola (podría no habérsela tomado).
        person = intent.slots.get("person") or speaker()
        dose = tracker.log.last_for(person)
        if dose is None:
            return Response("Hoy no tengo medicinas anotadas.")
        if dose.taken is not None:
            return Response(tr("Sí: {label}, a las {hour}.", label=what(dose.label), hour=_hour(dose.taken)))
        return Response(tr("No está confirmada: la de las {hour} ({label}). Se puede marcar desde el celular.",
                           hour=_hour(dose.due), label=what(dose.label)))

"""«Déjale una nota a papá: que compre tortillas», «¿tengo recados?», «ya leí mis recados»."""

from __future__ import annotations

from typing import Callable

from voxa.core.people import resolve, speaker
from voxa.core.phrases import join_words
from voxa.core.types import Intent, Response
from voxa.i18n import tr
from voxa.state.notes import Note, NoteBoard

_EVERYONE = {"todos", "todas", "la familia", "la casa", "everyone", "everybody", "the family", "all"}


def _sentence(text: str) -> str:
    text = text.strip().removeprefix("que ").strip()
    return text[:1].upper() + text[1:] if text else text


def _said(note: Note) -> str:
    if note.author:
        return tr("{author} te dejó un recado: {text}", author=note.author, text=_sentence(note.text))
    return tr("Te dejaron un recado: {text}", text=_sentence(note.text))


class NotesSkill:
    def __init__(self, board: NoteBoard, aliases: Callable[[], dict[str, str]] = dict) -> None:
        self.board = board
        self._aliases = aliases

    async def handle(self, intent: Intent) -> Response:
        board = self.board
        match intent.name:
            case "notes.add":
                text = (intent.slots.get("query") or "").strip(" :,.")
                if not text:
                    return Response("¿Qué le digo?", sound="error")
                to = (intent.slots.get("person") or "").strip()
                if not to or to.lower() in _EVERYONE:
                    board.add(text, None, speaker())
                    return Response("Listo, dejé la nota en la pantalla.")
                person = resolve(to, self._aliases())
                board.add(text, person, speaker())
                return Response(tr("Listo, le dejo la nota a {person}: se la digo cuando lo oiga.", person=person))
            case "notes.read":
                person = speaker()
                if person is None:
                    notes = board.notes
                    if not notes:
                        return Response("No hay notas.")
                    return Response(join_words([self._summary(n) for n in notes]) + ".")
                mine = board.for_person(person)
                if not mine:
                    return Response("No tienes recados.")
                board.mark_told(mine)
                return Response(" ".join(_said(n) + "." for n in mine))
            case "notes.clear":
                removed = board.clear(speaker())
                return Response("Listo, quité los recados." if removed else "No había recados.")
        return Response("Todavía no sé hacer eso con las notas.", sound="error")

    @staticmethod
    def _summary(note: Note) -> str:
        if note.to:
            return tr("para {person}: {text}", person=note.to, text=note.text)
        return tr("para todos: {text}", text=note.text)

    def postscript(self) -> str | None:
        """Al terminar de contestarle a alguien que VOXA reconoce, sus recados nuevos (una sola vez)."""
        person = speaker()
        if person is None:
            return None
        new = self.board.untold(person)
        if not new:
            return None
        self.board.mark_told(new)
        said = " ".join(_said(n) + "." for n in new)
        return tr("Por cierto, {person}: {notes}", person=person, notes=said)

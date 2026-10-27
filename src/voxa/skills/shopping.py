from __future__ import annotations

import re

from voxa.core.phrases import join_words
from voxa.core.types import Intent, Response
from voxa.i18n import tr
from voxa.nlu.normalize import strip_accents
from voxa.state.shopping import ShoppingList

# «leche, huevos y tortillas» → tres cosas; «pan dulce» es una.
_SPLIT = re.compile(r"\s*,\s*|\s+y\s+|\s+e\s+|\s+and\s+")
_TRAILING = re.compile(r"\s+(a|en|de)\s+la\s+lista.*$")


def with_commas(query: str, raw: str) -> str:
    """El slot viene sin signos; las comas del texto original («leche, huevos y pan») separan cosas."""
    tokens = re.findall(r"(\w+)(\W*)", raw.lower())
    keys = [strip_accents(word) for word, _ in tokens]
    target = [strip_accents(word) for word in query.lower().split()]
    for i in range(len(tokens) - len(target) + 1):
        if keys[i : i + len(target)] == target:
            words = tokens[i : i + len(target)]
            return "".join(w + (", " if "," in sep and n < len(words) - 1 else " ") for n, (w, sep) in enumerate(words)).strip()
    return query


def split_items(text: str) -> list[str]:
    text = _TRAILING.sub("", text.strip())
    return [part.strip() for part in _SPLIT.split(text) if part.strip()]


class ShoppingSkill:
    def __init__(self, shopping: ShoppingList) -> None:
        self.shopping = shopping

    async def handle(self, intent: Intent) -> Response:
        match intent.name:
            case "shopping.add":
                added, present = self.shopping.add(split_items(with_commas(intent.slots["query"], intent.raw)))
                if not added and present:
                    items = join_words(present).capitalize()
                    if len(present) == 1:
                        return Response(tr("{items} ya estaba en la lista.", items=items))
                    return Response(tr("{items} ya estaban en la lista.", items=items))
                if not added:
                    return Response("¿Qué agrego a la lista?", sound="error")
                return Response(tr("Agregué {items} a la lista.", items=join_words(added)))
            case "shopping.remove":
                items = split_items(with_commas(intent.slots["query"], intent.raw))
                removed = [r for r in (self.shopping.remove(i) for i in items) if r]
                if not removed:
                    return Response(tr("No encontré {items} en la lista.", items=intent.slots["query"]))
                return Response(tr("Quité {items} de la lista.", items=join_words(removed)))
            case "shopping.list":
                items = self.shopping.items
                if not items:
                    return Response("La lista del súper está vacía.")
                if len(items) == 1:
                    return Response(tr("En la lista hay una cosa: {items}.", items=join_words(items)))
                return Response(tr("En la lista hay {count} cosas: {items}.", count=len(items), items=join_words(items)))
            case "shopping.clear":
                count = self.shopping.clear()
                return Response("Borré la lista del súper." if count else "La lista ya estaba vacía.")
        return Response("Todavía no sé hacer eso con la lista.", sound="error")

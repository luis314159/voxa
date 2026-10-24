from __future__ import annotations

import re

from voxa.core.phrases import join_words
from voxa.core.types import Intent, Response
from voxa.nlu.normalize import strip_accents
from voxa.state.shopping import ShoppingList

# «leche, huevos y tortillas» → tres cosas; «pan dulce» es una.
_SPLIT = re.compile(r"\s*,\s*|\s+y\s+|\s+e\s+")
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
                    return Response(f"{join_words(present).capitalize()} ya {'estaba' if len(present) == 1 else 'estaban'} en la lista.")
                if not added:
                    return Response("¿Qué agrego a la lista?", sound="error")
                return Response(f"Agregué {join_words(added)} a la lista.")
            case "shopping.remove":
                items = split_items(with_commas(intent.slots["query"], intent.raw))
                removed = [r for r in (self.shopping.remove(i) for i in items) if r]
                if not removed:
                    return Response(f"No encontré {intent.slots['query']} en la lista.")
                return Response(f"Quité {join_words(removed)} de la lista.")
            case "shopping.list":
                items = self.shopping.items
                if not items:
                    return Response("La lista del súper está vacía.")
                return Response(f"En la lista hay {len(items)} {'cosa' if len(items) == 1 else 'cosas'}: {join_words(items)}.")
            case "shopping.clear":
                count = self.shopping.clear()
                return Response("Borré la lista del súper." if count else "La lista ya estaba vacía.")
        return Response("Todavía no sé hacer eso con la lista.", sound="error")

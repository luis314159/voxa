"""Conversiones de cocina sin internet: tazas, cucharadas, gramos y grados del horno.

Las tazas son las de 240 ml (8 onzas), las de los juegos de medidas que se venden en México;
los gramos por taza son valores típicos de recetario (harina sin compactar, azúcar al ras…),
así que las respuestas dicen «unos».
"""

from __future__ import annotations

import re

from voxa.core.types import Intent, Response
from voxa.i18n import english, tr
from voxa.nlu.normalize import strip_accents
from voxa.skills import kitchen_en
from voxa.nlu.numbers import parse_number_at

# Volumen en mililitros y peso en gramos de cada unidad (singular y plural).
_VOLUME = {
    "taza": 240.0, "tazas": 240.0, "cucharada": 15.0, "cucharadas": 15.0, "cucharadita": 5.0,
    "cucharaditas": 5.0, "mililitro": 1.0, "mililitros": 1.0, "ml": 1.0, "litro": 1000.0, "litros": 1000.0,
    "onza liquida": 29.6, "onzas liquidas": 29.6, "vaso": 240.0, "vasos": 240.0,
}
_WEIGHT = {
    "gramo": 1.0, "gramos": 1.0, "g": 1.0, "kilo": 1000.0, "kilos": 1000.0, "kilogramo": 1000.0,
    "kilogramos": 1000.0, "libra": 453.6, "libras": 453.6, "onza": 28.35, "onzas": 28.35,
}
_UNIT_NAMES = {  # para decirlo: (singular, plural, femenino)
    "taza": ("taza", "tazas", True), "cucharada": ("cucharada", "cucharadas", True),
    "cucharadita": ("cucharadita", "cucharaditas", True), "mililitro": ("mililitro", "mililitros", False),
    "litro": ("litro", "litros", False), "gramo": ("gramo", "gramos", False), "kilo": ("kilo", "kilos", False),
    "libra": ("libra", "libras", True), "onza": ("onza", "onzas", True),
}
# Gramos por taza de 240 ml.
_GRAMS_PER_CUP = {
    "harina": 125, "harina de trigo": 125, "harina de maiz": 115, "maseca": 115, "maicena": 128,
    "fecula de maiz": 128, "azucar": 200, "azucar morena": 220, "azucar glass": 120, "azucar glas": 120,
    "azucar mascabado": 220, "mantequilla": 227, "margarina": 227, "manteca": 205, "aceite": 218,
    "agua": 240, "leche": 245, "crema": 240, "miel": 340, "arroz": 185, "avena": 90, "cacao": 100,
    "cocoa": 100, "chocolate en polvo": 100, "sal": 290, "frijol": 190, "frijoles": 190, "lenteja": 190,
    "lentejas": 190, "queso rallado": 100, "nuez": 120, "nueces": 120, "almendra": 140, "almendras": 140,
    "pasas": 150, "coco rallado": 85, "pan molido": 110, "yogur": 245, "yogurt": 245,
}
_FRACTIONS = [
    (r"^(?:un |una )?cuarto de ", 0.25), (r"^tres cuartos de ", 0.75), (r"^(?:un |una )?tercio de ", 1 / 3),
    (r"^dos tercios de ", 2 / 3), (r"^(?:media|medio) ", 0.5),
]


def _canonical(unit: str) -> str:
    for key in _UNIT_NAMES:
        if unit == key or unit == _UNIT_NAMES[key][1]:
            return key
    return {"kilogramo": "kilo", "kilogramos": "kilo", "ml": "mililitro", "g": "gramo", "vaso": "taza",
            "vasos": "taza", "onza liquida": "taza", "onzas liquidas": "taza"}.get(unit, unit)


def parse_amount(text: str) -> tuple[float, str, str | None] | None:
    """«un cuarto de taza de harina» → (0.25, "taza", "harina"); «2 tazas y media» → (2.5, "taza", None).

    El ingrediente se devuelve como se dijo (con sus acentos: «azúcar»).
    """
    original = text.lower().split()
    text = strip_accents(text.lower()).strip()
    text = re.sub(r"^(?:el|la|los|las)\s+", "", text)
    amount = 1.0
    for pattern, value in _FRACTIONS:
        if re.match(pattern, text):
            amount, text = value, re.sub(pattern, "", text)
            break
    else:
        tokens = text.split()
        parsed = parse_number_at(tokens, 0)
        if parsed is not None:
            amount, text = parsed[0], " ".join(tokens[parsed[1] :])
    units = sorted({*_VOLUME, *_WEIGHT}, key=len, reverse=True)
    match = re.match(rf"^({'|'.join(re.escape(u) for u in units)})\b\s*(.*)$", text)
    if match is None:
        return None
    unit, rest = match.group(1), match.group(2)
    if rest.startswith(("y media", "y medio")):
        amount += 0.5
        rest = rest.split(" ", 2)[2] if rest.count(" ") >= 2 else ""
    rest = re.sub(r"^de\s+", "", rest).strip()
    if rest:  # mismas palabras, pero con acentos
        rest = " ".join(original[len(original) - len(rest.split()) :])
    return amount, unit, rest or None


def _ingredient(text: str | None) -> tuple[str, int] | None:
    if not text:
        return None
    key = re.sub(r"^(?:el|la|los|las)\s+", "", strip_accents(text))
    for name in sorted(_GRAMS_PER_CUP, key=len, reverse=True):
        if key == name or key.startswith(name + " "):
            return name, _GRAMS_PER_CUP[name]
    return None


def _round(value: float) -> float:
    """Redondeo de cocina: medios para lo pequeño, de 5 en 5 para los gramos."""
    if value < 10:
        return round(value * 2) / 2
    if value < 100:
        return float(round(value))
    return float(round(value / 5) * 5)


_SPOKEN_FRACTIONS = [(0.25, "un cuarto de"), (1 / 3, "un tercio de"), (2 / 3, "dos tercios de"), (0.75, "tres cuartos de")]


def say_quantity(value: float, unit: str) -> str:
    """«1 taza», «2 tazas y media», «media cucharadita», «un cuarto de taza», «125 gramos»."""
    singular, plural, feminine = _UNIT_NAMES[unit]
    for fraction, words in _SPOKEN_FRACTIONS:
        if abs(value - fraction) < 0.04:
            return f"{words} {singular}"
    value = _round(value)
    if value == 1:
        return f"{'una' if feminine else 'un'} {singular}"
    if value == 0.5:
        return f"{'media' if feminine else 'medio'} {singular}"
    if not value.is_integer():
        whole = int(value)
        if whole == 1:
            return f"{'una' if feminine else 'un'} {singular} y {'media' if feminine else 'medio'}"
        return f"{whole} {plural} y {'media' if feminine else 'medio'}"
    return f"{int(value)} {plural}"


def convert(amount: float, unit: str, target: str, ingredient: str | None) -> tuple[float, str | None] | str:
    """Devuelve (cantidad en ``target``, ingrediente usado) o un mensaje de por qué no se puede."""
    src_volume, src_weight = _VOLUME.get(unit), _WEIGHT.get(unit)
    dst_volume, dst_weight = _VOLUME.get(target), _WEIGHT.get(target)
    if src_volume and dst_volume:
        return amount * src_volume / dst_volume, None
    if src_weight and dst_weight:
        return amount * src_weight / dst_weight, None
    found = _ingredient(ingredient)
    if found is None:
        what = f"de {ingredient}" if ingredient else "sin saber de qué ingrediente"
        return f"No sé cuánto pesa una taza {what}. Prueba con harina, azúcar, arroz o mantequilla."
    name, grams_per_cup = found
    grams_per_ml = grams_per_cup / 240.0
    if src_volume and dst_weight:
        return amount * src_volume * grams_per_ml / dst_weight, name
    return amount * src_weight / grams_per_ml / dst_volume, name


class KitchenSkill:
    async def handle(self, intent: Intent) -> Response:
        if intent.name == "kitchen.temperature":
            return self._temperature(intent.slots["number"], intent.slots["from"])
        return self._convert(intent.slots["unit"], intent.slots.get("query", ""))

    def _convert(self, target: str, query: str) -> Response:
        if english():
            return self._convert_en(target, query)
        parsed = parse_amount(query)
        if parsed is None:
            return Response("No entendí la cantidad. Prueba con «¿cuántos gramos es una taza de harina?».", sound="error")
        amount, unit, ingredient = parsed
        result = convert(amount, unit, target, ingredient)
        if isinstance(result, str):
            return Response(result, sound="error")
        value, used = result
        source = say_quantity(amount, _canonical(unit)) + (f" de {ingredient}" if ingredient else "")
        answer = say_quantity(value, _canonical(target))
        if used and answer[0].isdigit():  # depende del ingrediente: es aproximado
            answer = ("unas " if _UNIT_NAMES[_canonical(target)][2] else "unos ") + answer
        verb = "son" if amount > 1 or _round(value) > 1 else "es"
        return Response(f"{source[:1].upper()}{source[1:]} {verb} {answer}.")

    def _convert_en(self, target: str, query: str) -> Response:
        parsed = kitchen_en.parse_amount(query)
        if parsed is None:
            return Response("I didn't get the amount. Try «how many grams is a cup of flour».", sound="error")
        amount, unit, ingredient = parsed
        key = kitchen_en.ingredient_key(ingredient)
        result = convert(amount, unit, target, key)
        if isinstance(result, str):
            if ingredient:
                return Response(f"I don't know how much a cup of {ingredient} weighs. Try flour, sugar, rice or butter.",
                                sound="error")
            return Response("Which ingredient? Try «how many grams is a cup of flour».", sound="error")
        value, used = result
        target = _canonical(target)
        source = kitchen_en.say_quantity(amount, unit, _round(amount)) + (f" of {ingredient}" if ingredient else "")
        answer = kitchen_en.say_quantity(value, target, _round(value))
        about = "about " if used else ""  # depende del ingrediente: es aproximado
        return Response(f"{source[:1].upper()}{source[1:]} is {about}{answer}.")

    def _temperature(self, degrees: int, source: str) -> Response:
        if source == "f":
            celsius = round((degrees - 32) * 5 / 9)
            return Response(tr("{degrees} grados Fahrenheit son {celsius} grados centígrados.", degrees=degrees,
                               celsius=celsius))
        fahrenheit = round(degrees * 9 / 5 + 32)
        return Response(tr("{degrees} grados centígrados son {fahrenheit} grados Fahrenheit.", degrees=degrees,
                           fahrenheit=fahrenheit))

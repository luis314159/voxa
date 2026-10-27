"""Kitchen conversions said in English («how many grams is a cup of flour»).

The math is the same as in Spanish (``voxa.skills.kitchen``): English units and ingredients map to the
Spanish keys of its tables, and the answer is said with English units («a cup and a half»).
"""

from __future__ import annotations

import re

from voxa.nlu.numbers_en import parse_number_at
from voxa.nlu.normalize import strip_accents

# English unit → the Spanish key of ``kitchen._VOLUME`` / ``kitchen._WEIGHT``.
UNITS = {
    "cup": "taza", "cups": "taza", "tablespoon": "cucharada", "tablespoons": "cucharada", "tbsp": "cucharada",
    "teaspoon": "cucharadita", "teaspoons": "cucharadita", "tsp": "cucharadita",
    "milliliter": "mililitro", "milliliters": "mililitro", "millilitre": "mililitro", "millilitres": "mililitro",
    "ml": "mililitro", "liter": "litro", "liters": "litro", "litre": "litro", "litres": "litro",
    "fluid ounce": "onza liquida", "fluid ounces": "onza liquida", "fl oz": "onza liquida",
    "gram": "gramo", "grams": "gramo", "g": "gramo", "kilo": "kilo", "kilos": "kilo", "kilogram": "kilo",
    "kilograms": "kilo", "kg": "kilo", "pound": "libra", "pounds": "libra", "lb": "libra", "lbs": "libra",
    "ounce": "onza", "ounces": "onza", "oz": "onza",
}
# How to say each Spanish key in English: (singular, plural).
_NAMES = {
    "taza": ("cup", "cups"), "cucharada": ("tablespoon", "tablespoons"), "cucharadita": ("teaspoon", "teaspoons"),
    "mililitro": ("milliliter", "milliliters"), "litro": ("liter", "liters"), "gramo": ("gram", "grams"),
    "kilo": ("kilo", "kilos"), "libra": ("pound", "pounds"), "onza": ("ounce", "ounces"),
    "onza liquida": ("fluid ounce", "fluid ounces"),
}
# English ingredient → the Spanish key of ``kitchen._GRAMS_PER_CUP``.
INGREDIENTS = {
    "flour": "harina", "all purpose flour": "harina", "wheat flour": "harina", "corn flour": "harina de maiz",
    "masa harina": "harina de maiz", "cornmeal": "harina de maiz", "cornstarch": "maicena", "corn starch": "maicena",
    "sugar": "azucar", "white sugar": "azucar", "granulated sugar": "azucar", "brown sugar": "azucar morena",
    "powdered sugar": "azucar glass", "icing sugar": "azucar glass", "confectioners sugar": "azucar glass",
    "butter": "mantequilla", "margarine": "margarina", "lard": "manteca", "oil": "aceite",
    "vegetable oil": "aceite", "olive oil": "aceite", "water": "agua", "milk": "leche", "cream": "crema",
    "heavy cream": "crema", "honey": "miel", "rice": "arroz", "oats": "avena", "rolled oats": "avena",
    "oatmeal": "avena", "cocoa": "cacao", "cocoa powder": "cacao", "salt": "sal", "beans": "frijol",
    "lentils": "lenteja", "grated cheese": "queso rallado", "shredded cheese": "queso rallado", "nuts": "nuez",
    "walnuts": "nuez", "pecans": "nuez", "almonds": "almendra", "raisins": "pasas", "coconut": "coco rallado",
    "shredded coconut": "coco rallado", "breadcrumbs": "pan molido", "bread crumbs": "pan molido",
    "yogurt": "yogur", "yoghurt": "yogur",
}
_FRACTIONS = [
    (r"^(?:a |one )?quarter (?:of )?(?:an? )?", 0.25), (r"^three quarters (?:of )?(?:an? )?", 0.75),
    (r"^(?:a |one )?third (?:of )?(?:an? )?", 1 / 3), (r"^two thirds (?:of )?(?:an? )?", 2 / 3),
    (r"^half (?:of )?(?:an? )?", 0.5), (r"^(?:a |one )half (?:of )?(?:an? )?", 0.5),
]


def parse_amount(text: str) -> tuple[float, str, str | None] | None:
    """«a quarter cup of sugar» → (0.25, "taza", "sugar"); «2 and a half cups» → (2.5, "taza", None).

    The unit comes back as the Spanish key (for ``kitchen.convert``); the ingredient as it was said.
    """
    text = strip_accents(text.lower()).replace("-", " ").strip()
    text = re.sub(r"\s+(?:weigh|weighs|make|makes)$", "", text)
    text = re.sub(r"^(?:the)\s+", "", text)
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
        if re.match(r"^and (?:a )?half ", text):  # «two and a half cups»
            amount += 0.5
            text = re.sub(r"^and (?:a )?half ", "", text)
    match = re.match(rf"^({'|'.join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))})\b\s*(.*)$", text)
    if match is None:
        return None
    unit, rest = UNITS[match.group(1)], match.group(2)
    if re.match(r"^and a half\b", rest):  # «a cup and a half of rice»
        amount += 0.5
        rest = re.sub(r"^and a half\s*", "", rest)
    rest = re.sub(r"^of\s+", "", rest).strip()
    return amount, unit, rest or None


def ingredient_key(text: str | None) -> str | None:
    """«all purpose flour» → «harina»; ``None`` if VOXA doesn't know how much a cup of it weighs."""
    if not text:
        return None
    key = re.sub(r"^(?:the|some)\s+", "", strip_accents(text.lower()))
    for name in sorted(INGREDIENTS, key=len, reverse=True):
        if key == name or key.startswith(name + " "):
            return INGREDIENTS[name]
    return None


def _article(word: str) -> str:
    return "an" if word[0] in "aeiou" else "a"


_SPOKEN_FRACTIONS = [(0.25, "a quarter {one}"), (1 / 3, "a third of {a} {one}"), (2 / 3, "two thirds of {a} {one}"),
                     (0.75, "three quarters of {a} {one}"), (0.5, "half {a} {one}")]


def say_quantity(value: float, unit: str, rounded: float) -> str:
    """«a cup», «a cup and a half», «2 and a half cups», «half a teaspoon», «125 grams».

    ``rounded`` is the kitchen rounding of ``value`` (``kitchen._round``).
    """
    one, many = _NAMES[unit]
    for fraction, words in _SPOKEN_FRACTIONS:
        if abs(value - fraction) < 0.04:
            return words.format(a=_article(one), one=one)
    if rounded == 1:
        return f"{_article(one)} {one}"
    if not rounded.is_integer():
        whole = int(rounded)
        return f"{_article(one)} {one} and a half" if whole == 1 else f"{whole} and a half {many}"
    return f"{int(rounded)} {many}"

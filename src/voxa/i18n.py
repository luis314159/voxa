"""El idioma de la casa: español (el de siempre) o inglés.

- ``tr("Agregué {items} a la lista.", items=…)``: frases con datos; la plantilla en español es la llave
  del catálogo (``voxa.i18n_en``) y en inglés se usa su traducción con los mismos datos.
- ``localize(texto)``: frases fijas («No hay temporizadores.»), traducidas al final, sin tocar cada
  habilidad. Lo que todavía no está en el catálogo se queda en español.
- ``in_language(código)``: en una casa bilingüe, el idioma de una frase, solo mientras se contesta.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

LANGUAGES = ("es", "en")
_language = "es"
_this_turn: ContextVar[str | None] = ContextVar("voxa_language", default=None)


def set_language(code: str) -> None:
    global _language
    _language = code if code in LANGUAGES else "es"


def language() -> str:
    return _this_turn.get() or _language


def home_language() -> str:
    return _language


def other_language(code: str | None = None) -> str:
    return "en" if (code or _language) == "es" else "es"


@contextmanager
def in_language(code: str | None) -> Iterator[None]:
    """En una casa bilingüe, una frase en el otro idioma se contesta en ese idioma (solo en esta tarea)."""
    token = _this_turn.set(code if code in LANGUAGES else None)
    try:
        yield
    finally:
        _this_turn.reset(token)


def english() -> bool:
    return language() == "en"


_ENGLISH_WORDS = frozenset(
    "the an is are what how why when where who which do does did can could would should will i you we my "
    "your our it this that to of for and with on in at please thanks thank play set add remind tell turn "
    "much many long time there have has get give make".split()
)
_SPANISH_WORDS = frozenset(
    "el la los las un una es son que como por para con de del al en y mi mis tu me te se lo le nos cuanto "
    "cuantos cuanta cuantas donde quien cual cuando hay pon ponme dime dame quiero puedes gracias favor "
    "agrega recuerdame avisa sube baja muy mas".split()
)


def guess_language(text: str) -> str:
    """El idioma de una frase escrita (sin STT que lo diga): por sus palabras más comunes."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    words = "".join(c if c.isalpha() else " " for c in plain).split()
    english_score = sum(w in _ENGLISH_WORDS for w in words)
    spanish_score = sum(w in _SPANISH_WORDS for w in words) + 2 * any(c in text.lower() for c in "ñ¿¡áéíóú")
    if english_score == spanish_score:
        return _language
    return "en" if english_score > spanish_score else "es"


def _catalog() -> dict[str, str]:
    from voxa.i18n_en import EN

    return EN


def tr(spanish: str, **values: object) -> str:
    template = _catalog().get(spanish, spanish) if english() else spanish
    return template.format(**values) if values else template


def localize(text: str | None) -> str | None:
    if not text or not english():
        return text
    return _catalog().get(text, text)

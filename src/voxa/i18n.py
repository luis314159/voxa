"""El idioma de la casa: español (el de siempre) o inglés.

- ``tr("Agregué {items} a la lista.", items=…)``: frases con datos; la plantilla en español es la llave
  del catálogo (``voxa.i18n_en``) y en inglés se usa su traducción con los mismos datos.
- ``localize(texto)``: frases fijas («No hay temporizadores.»), traducidas al final, sin tocar cada
  habilidad. Lo que todavía no está en el catálogo se queda en español.
"""

from __future__ import annotations

LANGUAGES = ("es", "en")
_language = "es"


def set_language(code: str) -> None:
    global _language
    _language = code if code in LANGUAGES else "es"


def language() -> str:
    return _language


def english() -> bool:
    return _language == "en"


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

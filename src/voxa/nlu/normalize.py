"""Normaliza lo que entrega el STT antes de buscar la intención.

Deja el texto en minúsculas, sin acentos ni signos, y quita la palabra de
activación, muletillas y cortesías que no cambian el significado.
"""

from __future__ import annotations

import re
import unicodedata

# Variantes con las que el STT suele escribir «Hey Voxa».
_WAKE = re.compile(r"^(?:(?:hey|hei|ey|ei|oye|ok|okay)\s+)?(?:voxa|boxa|voksa|vocsa|vox a|box a)\b\s*")
_LEADING_FILLERS = ("oye", "este", "eh", "em", "mmm", "mm", "a ver", "haber", "bueno", "porfa", "por favor")
_COURTESY = re.compile(r"\b(?:por favor|porfa|porfis)\b")
_DECIMAL = re.compile(r"(\d)[.,](\d)")
_NON_WORD = re.compile(r"[^a-z0-9.\s]")
_SPACES = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize(text: str) -> str:
    text = strip_accents(text.lower())
    text = _DECIMAL.sub(r"\1.\2", text)
    text = _NON_WORD.sub(" ", text)
    # Un punto solo sobrevive entre dígitos («1.5»).
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)
    text = _SPACES.sub(" ", text).strip()

    text = _WAKE.sub("", text)
    text = _COURTESY.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()

    changed = True
    while changed:
        changed = False
        for filler in _LEADING_FILLERS:
            if text == filler:
                return ""
            if text.startswith(filler + " "):
                text = text[len(filler) + 1 :]
                changed = True
    return text

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

# Errores típicos del STT al partir o pegar palabras (vistos con Vosk y Whisper).
_STT_FIXES = [
    (re.compile(r"\btemporizador es\b"), "temporizadores"),
    (re.compile(r"\b(sube|baja|adelanta|atrasa|regresa|dale) (le|lo)\b"), r"\1\2"),
    (re.compile(r"\bcancel a\b"), "cancela"),
    (re.compile(r"\byou tube\b"), "youtube"),
    (re.compile(r"\bporciento\b"), "por ciento"),
    (re.compile(r"\b(de|a) el\b"), lambda m: "del" if m.group(1) == "de" else "al"),
    # Ninguna orden empieza con «con», «por» o «pone»: es «pon» mal reconocido.
    (re.compile(r"^(?:con|por|pone|poner|ponga|pongan)\b"), "pon"),
]


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def restore_original(value: str, raw: str) -> str:
    """El fragmento de ``raw`` que corresponde a ``value`` (ya normalizado), con sus acentos y eñes.

    «pon a José José» → slot «jose jose» → «josé josé»: para que VOXA lo diga con el acento en su lugar
    y Spotify lo busque tal cual. Si el STT cambió las palabras, se queda el valor normalizado.
    """
    words = re.findall(r"\w+", raw.lower())
    target = value.split()
    keys = [strip_accents(w) for w in words]
    for i in range(len(words) - len(target) + 1):
        if keys[i : i + len(target)] == target:
            return " ".join(words[i : i + len(target)])
    return value


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

    for pattern, replacement in _STT_FIXES:
        text = pattern.sub(replacement, text)
    return text


def phonetic_key(word: str) -> str:
    """Clave fonética del español: b/v, s/z/c(e,i), y/ll y la h muda suenan igual.

    Sirve para corregir palabras mal escritas por el STT («abizame» ≈ «avisame»).
    """
    key = word.replace("ch", "\0").replace("h", "").replace("\0", "ch")
    key = key.replace("v", "b").replace("z", "s").replace("ll", "y").replace("qu", "k")
    key = re.sub(r"c([ei])", r"s\1", key)
    return re.sub(r"c(?!h)", "k", key)

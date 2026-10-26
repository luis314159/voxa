"""«Pon algo tranquilo para cocinar»: música por ambiente, actividad, género o época → una playlist.

Solo cuando TODAS las palabras son de ambiente, género o época («salsa», «los 80», «algo para
bailar»); así «Mariachi Vargas» o «La Sonora Dinamita» siguen buscándose como artistas.
"""

from __future__ import annotations

import re

from voxa.nlu.normalize import strip_accents

_FILLER = frozenset(
    "algo musica canciones cancion rolas rola unas unos una un de del la las el los para pa que sea bien muy "
    "mas poco y o en con tipo estilo onda buena buenas puras puro solo".split()
)
_MOODS = frozenset(
    "tranquila tranquilo tranquilas tranquilos relajante relajantes relajada relajado suave suaves alegre alegres "
    "feliz felices animada animado animadas animados romantica romantico romanticas romanticos triste tristes "
    "movida movidas movido prendida prendidas bailable bailables bailar energetica energia fiesta fiestera "
    "chill lofi instrumental instrumentales clasica clasicas fondo concentrarme concentrarse estudiar trabajar "
    "cocinar cocinando comer cenar desayunar cena comida desayuno limpiar limpiando limpieza ejercicio domingo "
    "sabado manana tarde noche lluvia navidad navidena navidenas posada infantil infantiles ninos dormir "
    "descansar relajarse relajarme viejitas viejitos viejita oldies clasicos exitos nostalgica nostalgicas "
    "ochentas noventas setentas sesentas epoca mexicana mexicanas mexicano latina latinas latino ingles espanol "
    "acustica acustico acusticas".split()
)
_GENRES = frozenset(
    "jazz bossa nova salsa cumbia cumbias bachata bachatas merengue merengues bolero boleros banda nortena "
    "nortenas ranchera rancheras mariachi regional rock pop reggaeton trova baladas balada electronica house "
    "hip hop rap blues country reggae tropical tropicales ska indie alternativa metal punk funk soul disco "
    "gospel flamenco tango folk opera sonidera sonideras corridos huapangos huapango danzon jarocho grupera "
    "gruperas rumba kpop".split()
)
_DECADE = re.compile(r"^(19|20)?\d0s?$")


def mood_search(query: str, *, forced: bool = False) -> str | None:
    """Lo que hay que buscar como playlist, o ``None`` si parece un artista, canción o álbum.

    ``forced``: la frase ya dijo que es un ambiente («música para…»): se busca tal cual.
    """
    words = strip_accents(query.lower()).replace("-", "").split()
    meaningful = [w for w in words if w not in _FILLER]
    known = all(w in _MOODS or w in _GENRES or _DECADE.match(w) for w in meaningful)
    if not meaningful or not (known or forced):
        return None
    # Sin muletillas al principio («algo», «unas»), y «música» si no dice el género.
    original = query.split()
    while original and strip_accents(original[0].lower()) in {"algo", "unas", "unos", "un", "una", "poco", "de"}:
        original.pop(0)
    text = " ".join(original)
    if any(w in _GENRES for w in meaningful) or strip_accents(text.lower()).startswith("musica"):
        return text
    if any(_DECADE.match(w) for w in meaningful) and not strip_accents(text.lower()).startswith(("de ", "para ")):
        return f"música de {text}"
    return f"música {text}"

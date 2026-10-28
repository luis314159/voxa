"""La página del celular tiene traducción al inglés para todo su texto fijo."""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

PAGINA = Path(__file__).resolve().parents[1] / "src" / "voxa" / "telefono.html"

# Textos que se quedan igual en inglés: marcas, direcciones, números.
SIN_TRADUCIR = {
    "VOXA",
    "Manual",
    "Spotify",
    "Playlists",
    "Client ID",
    "English",
    "Español",
    "Idioma de VOXA / VOXA's language",
    "Claude (Anthropic)",
    "OpenAI",
    "Azure OpenAI",
    "Normal (base)",
    "Normal",
    "console.cloud.google.com",
    "http://127.0.0.1:8767/?code=…",
    "No",
    "developer.spotify.com/dashboard",
    "3 min",
    "5 min",
    "10 min",
    "15 min",
    "http://127.0.0.1:8765/callback?code=…",
    "https://calendar.google.com/…/basic.ics",
    "http://192.168.…:8770/?k=…",
}


class _Textos(HTMLParser):
    def __init__(self):
        super().__init__()
        self.textos, self.script, self.dentro = [], [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.dentro = tag
        for nombre, valor in attrs:
            if nombre in ("placeholder", "title", "aria-label", "alt") and valor:
                self.textos.append(" ".join(valor.split()))

    def handle_endtag(self, tag):
        if tag == self.dentro:
            self.dentro = None

    def handle_data(self, data):
        if self.dentro == "script":
            self.script.append(data)
        elif self.dentro is None and data.strip():
            self.textos.append(" ".join(data.split()))


def _leer():
    p = _Textos()
    p.feed(PAGINA.read_text(encoding="utf-8"))
    return p.textos, "".join(p.script)


def _diccionario(script):
    m = re.search(r"const EN = (\{.*?\n\});", script, re.S)
    assert m, "no encontré «const EN = { … };» en el script"
    sin_comentarios = re.sub(r"^\s*//.*\n", "", m.group(1), flags=re.M)
    return json.loads(sin_comentarios)


def test_todo_el_texto_fijo_tiene_ingles():
    textos, script = _leer()
    en = _diccionario(script)
    faltan = sorted({t for t in textos if re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñü]", t)} - set(en) - SIN_TRADUCIR)
    assert not faltan, f"sin traducción: {faltan}"


def test_las_traducciones_no_estan_vacias_ni_iguales():
    _, script = _leer()
    en = _diccionario(script)
    assert len(en) > 150
    malas = [k for k, v in en.items() if not v.strip() or (v == k and k not in SIN_TRADUCIR)]
    assert not malas, f"traducciones vacías o iguales: {malas}"


def test_los_huecos_coinciden():
    _, script = _leer()
    for k, v in _diccionario(script).items():
        assert sorted(re.findall(r"\{\w+\}", k)) == sorted(re.findall(r"\{\w+\}", v)), k


def test_tr_usa_las_llaves_del_script():
    """Cada tr("…") del script con texto literal tiene su entrada en EN."""
    _, script = _leer()
    en = _diccionario(script)
    usados = set(re.findall(r'\btr\("((?:[^"\\]|\\.)*)"', script))
    faltan = sorted(usados - set(en))
    assert not faltan, f"tr() sin traducción: {faltan}"

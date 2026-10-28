"""El manual para la familia: la página que sirve VOXA está al día, sus capturas existen y sus frases se entienden."""

import importlib.util
import re
from pathlib import Path

from voxa.app import build_app
from voxa.config import Config

from test_web import KEY, http, logged_in, phone  # noqa: F401 - phone es un fixture

REPO = Path(__file__).resolve().parents[1]
MANUAL = REPO / "docs" / "manual.md"
IMAGES = REPO / "src" / "voxa" / "manual" / "img"

# Citas de «Qué le puedes pedir» que no son órdenes: lo que pregunta VOXA, un interruptor, el inglés.
NOT_COMMANDS = {"¿ya te la tomaste?", "Hey Voxa", "Casa bilingüe", "what's the weather like?"}


def _converter():
    spec = importlib.util.spec_from_file_location("convertir", REPO / "scripts" / "manual" / "convertir.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_page_is_up_to_date_with_the_markdown():
    convertir = _converter()
    expected = convertir.render(MANUAL.read_text(encoding="utf-8"), convertir.TEMPLATE.read_text(encoding="utf-8"))
    assert convertir.PAGE.read_text(encoding="utf-8") == expected, "corre: python scripts/manual/convertir.py"


def test_every_screenshot_exists_and_is_used():
    used = {Path(p).name for p in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", MANUAL.read_text(encoding="utf-8"))}
    assert used == {p.name for p in IMAGES.iterdir()}


def test_every_example_phrase_is_understood():
    text = MANUAL.read_text(encoding="utf-8")
    examples = text[text.index("## 5."):text.index("## 6.")]
    assistant = build_app(Config(), simulated=True).assistant
    phrases = set(re.findall(r"«([^»]+)»", examples)) - NOT_COMMANDS
    assert len(phrases) > 80
    assert not [p for p in sorted(phrases) if not assistant.understands(p)]


async def test_voxa_serves_the_manual_behind_its_key(phone):  # noqa: F811
    server, _, _ = phone
    assert (await http(server.port, "GET", "/manual"))[0] == 403
    status, headers, _ = await http(server.port, "GET", f"/manual?k={KEY}")
    assert status == 303 and headers["Location"] == "/manual"  # desde el menú de la PC: guarda la clave

    status, headers, body = await http(server.port, "GET", "/manual", headers=logged_in())
    assert status == 200 and headers["Content-Type"].startswith("text/html") and b"Manual de VOXA" in body
    status, headers, body = await http(server.port, "GET", "/manual/img/celular-ia.png", headers=logged_in())
    assert status == 200 and headers["Content-Type"] == "image/png" and body.startswith(b"\x89PNG")
    status, headers, _ = await http(server.port, "GET", "/manual/img/pantalla-cocina.jpg", headers=logged_in())
    assert status == 200 and headers["Content-Type"] == "image/jpeg"
    for path in ("/manual/img/../index.html", "/manual/img/no-existe.png", "/manual/otra"):
        assert (await http(server.port, "GET", path, headers=logged_in()))[0] == 404

import pytest

from voxa.app import build_app
from voxa.config import Config
from voxa.skills.kitchen import convert, parse_amount, say_quantity


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("una taza de harina", (1.0, "taza", "harina")),
        ("un cuarto de taza", (0.25, "taza", None)),
        ("tres cuartos de taza de azúcar", (0.75, "taza", "azúcar")),
        ("media cucharadita de sal", (0.5, "cucharadita", "sal")),
        ("2 tazas y media de arroz", (2.5, "tazas", "arroz")),
        ("doscientos gramos de mantequilla", (200.0, "gramos", "mantequilla")),
        ("una tonelada", None),
    ],
)
def test_parse_amount(said, expected):
    assert parse_amount(said) == expected


def test_convert_between_volumes_weights_and_with_density():
    assert convert(1, "taza", "cucharadas", None) == (16.0, None)
    assert convert(1, "kilo", "libras", None)[0] == pytest.approx(2.2046, rel=1e-3)
    grams, used = convert(1, "taza", "gramos", "harina")
    assert grams == pytest.approx(125.0) and used == "harina"
    cups, _ = convert(200, "gramos", "tazas", "azúcar")
    assert cups == pytest.approx(1.0)
    assert "tierra" in convert(1, "taza", "gramos", "tierra")


def test_say_quantity():
    assert say_quantity(1, "taza") == "una taza"
    assert say_quantity(0.5, "cucharadita") == "media cucharadita"
    assert say_quantity(0.25, "taza") == "un cuarto de taza"
    assert say_quantity(2.5, "taza") == "2 tazas y media"
    assert say_quantity(1.5, "kilo") == "un kilo y medio"
    assert say_quantity(123, "gramo") == "125 gramos"


@pytest.mark.parametrize(
    ("said", "answer"),
    [
        ("¿Cuántos gramos es una taza de harina?", "Una taza de harina son unos 125 gramos."),
        ("cuántas cucharadas son un cuarto de taza", "Un cuarto de taza son 4 cucharadas."),
        ("200 gramos de mantequilla en tazas", "200 gramos de mantequilla son una taza."),
        ("350 grados Fahrenheit en centígrados", "350 grados Fahrenheit son 177 grados centígrados."),
        ("180 grados a Fahrenheit", "180 grados centígrados son 356 grados Fahrenheit."),
    ],
)
async def test_conversions_by_voice(said, answer):
    app = build_app(Config(), simulated=True)
    assert (await app.assistant.handle_text(said)).speech == answer

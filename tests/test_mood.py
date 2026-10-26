import pytest

from voxa.app import build_app
from voxa.config import Config
from voxa.skills.mood import mood_search


@pytest.mark.parametrize("query, search", [
    ("algo tranquilo para cocinar", "música tranquilo para cocinar"),
    ("los 80", "música de los 80"),
    ("salsa", "salsa"),
    ("unas cumbias", "cumbias"),
    ("rock en español", "rock en español"),
    ("música romántica", "música romántica"),
    ("lo-fi", "música lo-fi"),
])
def test_moods_genres_and_decades_become_playlist_searches(query, search):
    assert mood_search(query) == search


@pytest.mark.parametrize("query", ["Soda Stereo", "Mariachi Vargas", "La Sonora Dinamita", "Banda MS", "persiana americana"])
def test_artists_and_songs_are_left_alone(query):
    assert mood_search(query) is None


async def test_mood_requests_play_a_playlist():
    app = build_app(Config(), simulated=True)
    music = app.assistant.skill("music")._backend
    expected = {
        "pon algo tranquilo para cocinar": "música tranquilo para cocinar",
        "pon música para cocinar": "música para cocinar",
        "pon música para la fiesta de mi hermana": "música para la fiesta de mi hermana",
        "pon música de los 80": "música de los 80",
        "pon salsa": "salsa",
        "pon a Juan Gabriel": "juan gabriel",
    }
    for said, query in expected.items():
        response = await app.assistant.handle_text(said)
        assert music.calls[-1] == f"play:{query}", said
        if said != "pon a Juan Gabriel":
            assert response.speech.startswith("La playlist"), said
    assert (await app.assistant.handle_text("pon la música en la sala")).speech == "Pasando la música a Sala."

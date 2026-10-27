"""Notas y recados: en la pantalla, y dichos a quien van cuando VOXA reconoce su voz."""

from voxa.app import build_app
from voxa.config import Config, FamilyConfig
from voxa.core.people import resolve, speaking
from voxa.state.notes import NoteBoard


def test_nicknames():
    aliases = {"Luis": "papá, pa", "Ana": "mamá"}
    assert resolve("papá", aliases) == "Luis" and resolve("mi mamá", aliases) == "Ana"
    assert resolve("la tía rosa", aliases) == "Tía Rosa"


def family_app(tmp_path):
    return build_app(Config(family=FamilyConfig(aliases={"Luis": "papá"}), state_dir=tmp_path), simulated=True)


async def test_a_note_for_dad_is_told_when_he_talks(tmp_path):
    app = family_app(tmp_path)
    say = app.assistant.handle_text
    with speaking("Ana"):
        said = await say("déjale una nota a papá que compre tortillas")
    assert said.speech == "Listo, le dejo la nota a Luis: se la digo cuando lo oiga."
    assert app.notes.snapshot() == [{"id": 1, "text": "compre tortillas", "to": "Luis", "from": "Ana"}]
    with speaking("Luis"):
        said = await say("¿qué hora es?")
    assert said.speech.endswith("Por cierto, Luis: Ana te dejó un recado: Compre tortillas.")
    with speaking("Luis"):
        assert "recado" not in (await say("¿qué hora es?")).speech  # una sola vez
        assert (await say("¿tengo recados?")).speech == "Ana te dejó un recado: Compre tortillas."
        assert (await say("ya leí mis recados")).speech == "Listo, quité los recados."
    assert app.notes.snapshot() == []


async def test_a_note_for_everyone_stays_on_the_screen(tmp_path):
    app = family_app(tmp_path)
    said = await app.assistant.handle_text("pon una nota que diga no hay agua caliente")
    assert said.speech == "Listo, dejé la nota en la pantalla."
    assert app.notes.snapshot()[0]["to"] is None
    with speaking("Luis"):
        assert "Por cierto" not in (await app.assistant.handle_text("qué hora es")).speech
    assert (await app.assistant.handle_text("hay notas")).speech == "para todos: no hay agua caliente."


def test_notes_survive_a_restart_and_expire(tmp_path):
    now = [1_800_000_000.0]
    board = NoteBoard(tmp_path / "notas.json", clock=lambda: now[0])
    board.add("compra pan", "Ana", None)
    assert NoteBoard(tmp_path / "notas.json", clock=lambda: now[0]).for_person("ana")
    now[0] += 4 * 86400
    assert NoteBoard(tmp_path / "notas.json", clock=lambda: now[0]).snapshot() == []


async def test_notes_in_english(tmp_path):
    from voxa.config import VoiceConfig

    app = build_app(Config(voice=VoiceConfig(language="en"), family=FamilyConfig(aliases={"Luis": "dad"}),
                           state_dir=tmp_path), simulated=True)
    said = await app.assistant.handle_text("leave a note for dad saying buy tortillas")
    assert said.speech == "Done, I'll give Luis the note when I hear them."
    with speaking("Luis"):
        said = await app.assistant.handle_text("thanks")
    assert said.speech == "You're welcome! By the way, Luis: Someone left you a message: Buy tortillas."


async def test_nicknames_work_everywhere(tmp_path):
    """«Los pendientes de papá» y «recuérdale a mamá…» llegan a la persona correcta."""
    app = build_app(Config(family=FamilyConfig(aliases={"Luis": "papá", "Ana": "mamá, ma"}), state_dir=tmp_path),
                    simulated=True)
    say = app.assistant.handle_text
    assert (await say("agrega llamar al plomero a los pendientes de papá")).speech.endswith("llamar al plomero.")
    assert [t.text for t in app.tasks.of("Luis")] == ["llamar al plomero"]
    await say("recuérdale a mamá que saque la basura a las 9 de la noche")
    assert app.timers.active[0].person == "Ana"

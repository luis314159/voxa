import pytest

from voxa.core.types import Intent
from voxa.services.mpris import PlayerctlBackend
from voxa.services.music_backend import (
    AuthRequired,
    BackendUnavailable,
    LayeredMusicBackend,
    NothingFound,
    NotSupported,
    PlayResult,
)
from voxa.services.process import CommandNotFound, CommandResult
from voxa.services.simulated import SimulatedMusic
from voxa.services.spotifast_cli import SpotifastCli
from voxa.skills.music import MusicSkill


class FakeRunner:
    def __init__(self, *results: CommandResult | Exception) -> None:
        self.results = list(results)
        self.calls: list[list[str]] = []

    async def __call__(self, args, timeout=5.0):
        self.calls.append(list(args))
        result = self.results.pop(0) if self.results else CommandResult(0, "")
        if isinstance(result, Exception):
            raise result
        return result


async def test_spotifast_play_search_with_kind():
    run = FakeRunner()
    result = await SpotifastCli(run=run).play("soda stereo", "artist")
    assert run.calls == [["spotifast", "play-search", "--kind", "artist", "soda", "stereo"]]
    assert result == PlayResult("soda stereo", kind="artist")


async def test_spotifast_track_search_has_no_kind_flag():
    run = FakeRunner()
    await SpotifastCli(run=run).play("bohemian rhapsody", "track")
    assert run.calls == [["spotifast", "play-search", "bohemian", "rhapsody"]]


async def test_spotifast_flatpak_command_and_seek_backwards():
    run = FakeRunner()
    await SpotifastCli(["flatpak", "run", "rocks.spotifast.Spotifast"], run=run).seek(-15)
    assert run.calls == [["flatpak", "run", "rocks.spotifast.Spotifast", "seek", "--", "-15"]]


async def test_spotifast_now_playing_raw():
    raw = "playing\tPersiana americana\tSoda Stereo\tSignos\t1000\t290000\t70\toff\toff\turl\tno\tVOXA Cocina\n"
    np = await SpotifastCli(run=FakeRunner(CommandResult(0, raw))).now_playing()
    assert (np.title, np.artist, np.playing) == ("Persiana americana", "Soda Stereo", True)


async def test_spotifast_not_running_or_missing():
    with pytest.raises(BackendUnavailable):
        await SpotifastCli(run=FakeRunner(CommandResult(1, "", "not running"))).pause()
    with pytest.raises(BackendUnavailable):
        await SpotifastCli(run=FakeRunner(CommandNotFound("spotifast"))).pause()


async def test_playerctl_commands():
    run = FakeRunner(CommandResult(0, ""), CommandResult(0, "Paused\tDe música ligera\tSoda Stereo\n"))
    backend = PlayerctlBackend("spotifast", run=run)
    await backend.seek(-10)
    np = await backend.now_playing()
    assert run.calls[0] == ["playerctl", "--player=spotifast", "position", "10-"]
    assert np.title == "De música ligera" and not np.playing


class Failing:
    def __init__(self, name, exc):
        self.name = name
        self.exc = exc
        self.calls = 0

    async def pause(self):
        self.calls += 1
        raise self.exc

    async def play(self, query, kind=None):
        self.calls += 1
        raise self.exc


async def test_layered_falls_through_to_next_layer():
    mpris = Failing("mpris", BackendUnavailable("sin reproductor"))
    sim = SimulatedMusic()
    layered = LayeredMusicBackend(search_order=[sim], control_order=[mpris, sim])
    await layered.pause()
    assert mpris.calls == 1 and sim.calls == ["pause"]


async def test_layered_stops_on_nothing_found():
    web = Failing("web", NothingFound("xyz"))
    sim = SimulatedMusic()
    with pytest.raises(NothingFound):
        await LayeredMusicBackend([web, sim], [sim]).play("xyz")
    assert sim.calls == []


async def test_layered_reports_auth_problem_when_all_layers_fail():
    web = Failing("web", AuthRequired("token"))
    cli = Failing("cli", BackendUnavailable("cerrado"))
    with pytest.raises(AuthRequired):
        await LayeredMusicBackend([web, cli], [cli]).play("x")


async def test_layered_skips_not_supported_silently():
    mpris = Failing("mpris", NotSupported("no busca"))
    sim = SimulatedMusic()
    assert (await LayeredMusicBackend([mpris, sim], [sim]).play("queen")).title == "Queen"


async def test_music_skill_messages():
    sim = SimulatedMusic()
    skill = MusicSkill(sim)
    said = await skill.handle(Intent("music.transfer", {"device": "patio"}))
    assert said.speech == "No encontré ese dispositivo: «patio»."
    said = await skill.handle(Intent("music.transfer", {"device": "sala"}))
    assert said.speech == "Pasando la música a Sala."
    broken = MusicSkill(LayeredMusicBackend([Failing("w", AuthRequired("t"))], []))
    said = await broken.handle(Intent("music.play", {"query": "queen"}))
    assert "autorizar" in said.speech and said.sound == "error"

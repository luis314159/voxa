import asyncio

from voxa.health import Health, Problem, internet_check, player_check, spotify_check
from voxa.services.music_backend import BackendUnavailable


async def test_problems_are_sorted_and_reported_changes_notify():
    changes = []
    no_internet = Problem("internet", "Sin internet")

    async def offline():
        return no_internet

    async def broken():
        raise RuntimeError("revisión rota")

    health = Health([offline, broken], on_change=lambda: changes.append(1))
    await health.check()
    health.report(Problem("microfono", "No encuentro el micrófono"))
    health.report(Problem("microfono", "No encuentro el micrófono"))  # igual: no avisa de nuevo
    assert [p.id for p in health.problems] == ["microfono", "internet"]
    assert len(changes) == 2

    await health.check()  # nada cambió
    health.clear("microfono")
    health.clear("microfono")
    assert health.problems == [no_internet]
    assert len(changes) == 3


async def test_internet_check_connects_without_sending():
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        assert await internet_check("127.0.0.1", port)() is None
    finally:
        server.close()
        await server.wait_closed()
    problem = await internet_check("127.0.0.1", port, timeout=1.0)()
    assert problem.id == "internet" and problem.text == "Sin internet"


async def test_spotify_and_player_checks(tmp_path):
    token = tmp_path / "spotify_token.json"
    assert (await spotify_check("", token)()).text == "Falta conectar Spotify"
    assert "spotify-login" in (await spotify_check("abc", token)()).detail
    token.write_text("{}")
    assert await spotify_check("abc", token)() is None

    async def missing():
        raise BackendUnavailable("No players found")

    async def playing():
        return None

    assert (await player_check(missing, "spotifast")()).id == "musica"
    assert await player_check(playing, "spotifast")() is None

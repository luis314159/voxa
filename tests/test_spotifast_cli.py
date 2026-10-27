"""La CLI de Spotifast, con la salida real de «now-playing --raw» (Spotifast 0.14)."""

from voxa.services.process import CommandResult
from voxa.services.spotifast_cli import SpotifastCli

RAW = ("paused\tYou Make My Dreams (Come True)\tDaryl Hall & John Oates\tVoices\t42283\t190626\t97\ton\toff\t"
       "https://i.scdn.co/image/abc\t{saved}\tSpotifast\r\n")


def cli(saved="no"):
    calls = []

    async def run(args, timeout=5.0):
        calls.append(args[1:])
        out = RAW.format(saved=saved) if args[1] == "now-playing" else ""
        return CommandResult(0, out, "")

    return SpotifastCli(("spotifast",), run), calls


async def test_now_playing_reads_every_field():
    spotifast, calls = cli()
    current = await spotifast.now_playing()
    assert calls == [["now-playing", "--raw"]]
    assert (current.title, current.artist, current.album, current.playing) == (
        "You Make My Dreams (Come True)", "Daryl Hall & John Oates", "Voices", False)
    assert current.position == 42.283 and current.length == 190.626 and current.art_url.endswith("/abc")


async def test_like_never_takes_a_song_out():
    """«like» alterna: con la canción ya en tus Me gusta, no se vuelve a llamar."""
    spotifast, calls = cli(saved="yes")
    await spotifast.like()
    assert ["like"] not in calls
    spotifast, calls = cli(saved="no")
    await spotifast.like()
    assert calls[-1] == ["like"]


async def test_search_uses_its_kind():
    spotifast, calls = cli()
    await spotifast.play("soda stereo", "artist")
    assert calls == [["play-search", "--kind", "artist", "soda", "stereo"]]

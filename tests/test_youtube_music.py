import sys

import pytest

from voxa.services.music_backend import AuthRequired, MusicRouter, NotSupported, NothingFound, PlayResult
from voxa.services.process import CommandResult
from voxa.services.simulated import SimulatedMusic
from voxa.services.youtube_music import YouTubeMusic, search_text, songs

RESULTS = "\n".join([
    "aaaaaaaaaaa\tSoda Stereo - Persiana Americana\t287\tSoda Stereo\tnot_live",
    "bbbbbbbbbbb\tSoda Stereo en vivo 24/7\tNA\tRadio\tis_live",
    "ccccccccccc\tSoda Stereo - De Música Ligera\t212\tSoda Stereo\tnot_live",
    "ddddddddddd\tSoda Stereo concierto completo\t7200\tCanal\tnot_live",
])
SLEEPER = (sys.executable, "-c", "import time; time.sleep(30)")  # hace de mpv


def youtube(stdout=RESULTS, code=0):
    calls = []

    async def run(args, timeout=5.0):
        calls.append(list(args))
        return CommandResult(code, stdout, "ERROR: sin red" if code else "")

    return YouTubeMusic(mpv=SLEEPER, run=run), calls


def test_songs_skip_live_streams_and_long_concerts():
    assert [v.id for v in songs(RESULTS)] == ["aaaaaaaaaaa", "ccccccccccc"]
    assert search_text("soda stereo", "artist") == "soda stereo canciones"


async def test_plays_a_queue_of_songs_audio_only():
    music, calls = youtube()
    try:
        result = await music.play("soda stereo", "artist")
        assert result.describe() == "soda stereo" and music.active
        assert calls[0][-1] == "ytsearch12:soda stereo canciones"
        args = music.arguments(music._queue)
        assert "--no-video" in args and args[-2:] == [
            "https://www.youtube.com/watch?v=aaaaaaaaaaa", "https://www.youtube.com/watch?v=ccccccccccc"]
        with pytest.raises(NotSupported):
            await music.like()
    finally:
        await music.stop()
    assert not music.active


async def test_nothing_found_and_errors():
    music, _ = youtube(stdout="")
    with pytest.raises(NothingFound):
        await music.play("xyzzy")


class BrokenSpotify(SimulatedMusic):
    name = "spotify"

    async def play(self, query, kind=None):
        raise AuthRequired("sin conectar")


async def test_router_falls_back_to_youtube_and_controls_whats_playing():
    yt, spotify = SimulatedMusic(), BrokenSpotify()
    yt.name = "youtube"
    router = MusicRouter(spotify, yt)
    assert (await router.play("salsa")).describe() == "Salsa"
    assert router.active is yt
    await router.pause()
    assert yt.calls[-1] == "pause"
    assert spotify.calls == ["pause"]  # al pasar a YouTube, Spotify se pausó una vez; la pausa fue a YouTube


async def test_router_switches_back_to_spotify_and_stops_youtube():
    yt, spotify = SimulatedMusic(), SimulatedMusic()
    stopped = []

    async def stop():
        stopped.append(True)

    yt.stop = stop
    router = MusicRouter(spotify, yt)
    router.active = yt
    await router.play("cumbia")
    assert router.active is spotify and stopped


async def test_account_features_need_spotify():
    router = MusicRouter(None, SimulatedMusic())
    with pytest.raises(NotSupported):
        await router.play_liked()
    with pytest.raises(NotSupported):
        await router.like()


async def test_nothing_anywhere_says_nothing_found():
    class Empty(SimulatedMusic):
        async def play(self, query, kind=None):
            raise NothingFound(query)

    router = MusicRouter(Empty(), Empty())
    with pytest.raises(NothingFound):
        await router.play("xyzzy")


def test_play_result_for_youtube_track():
    assert PlayResult("Persiana Americana", "Soda Stereo", "track").describe() == "Persiana Americana, de Soda Stereo"

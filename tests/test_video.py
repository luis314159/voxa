import asyncio
import json
import sys

import pytest

from voxa.app import build_app
from voxa.config import Config
from voxa.services.process import CommandNotFound, CommandResult
from voxa.services.video import MpvPlayer, Video, VideoNotFound, VideoUnavailable, YtDlpSearch, pick
from voxa.skills.video import speakable_title

RESULTS = "\n".join(
    [
        "liveLIVE001\tPozole EN VIVO\tNA\tCanal\tis_live",
        "shortSHORT1\tPozole en 30 segundos #shorts\t35\tCanal\tnot_live",
        "--exec=rm\tNo es un id de YouTube\t600\tNA\tnot_live",
        "goodGOOD001\tPozole rojo tradicional\t720\tCocina de la abuela\tnot_live",
        "goodGOOD002\tOtro pozole\t900\tNA\tnot_live",
    ]
)


def test_pick_prefers_complete_videos_and_skips_live():
    assert pick(RESULTS) == Video("goodGOOD001", "Pozole rojo tradicional", 720.0, "Cocina de la abuela")
    only_short = "shortSHORT1\tPozole en 30 segundos\t35\tNA\tnot_live"
    assert pick(only_short).id == "shortSHORT1"  # mejor algo que nada
    assert pick("liveLIVE001\tEn vivo\tNA\tNA\tis_live\n") is None
    assert pick("") is None


class FakeRunner:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    async def __call__(self, args, timeout=5.0):
        self.calls.append(list(args))
        if self.error:
            raise self.error
        return self.result


async def test_ytdlp_search_builds_a_safe_command():
    runner = FakeRunner(CommandResult(0, RESULTS))
    video = await YtDlpSearch(("yt-dlp",), runner).search("cómo hacer pozole")
    assert video.url == "https://www.youtube.com/watch?v=goodGOOD001"
    args = runner.calls[0]
    assert args[0] == "yt-dlp" and args[-1] == "ytsearch5:cómo hacer pozole"
    assert "--ignore-config" in args  # la configuración de otro usuario no cambia la búsqueda


async def test_ytdlp_search_errors():
    with pytest.raises(VideoUnavailable, match="no está instalado"):
        await YtDlpSearch(run=FakeRunner(error=CommandNotFound("yt-dlp"))).search("x")
    with pytest.raises(VideoUnavailable, match="Sign in"):
        await YtDlpSearch(run=FakeRunner(CommandResult(1, "", "WARNING: algo\nERROR: Sign in to confirm"))).search("x")
    with pytest.raises(VideoNotFound):
        await YtDlpSearch(run=FakeRunner(CommandResult(0, ""))).search("x")


@pytest.mark.parametrize(
    ("title", "spoken"),
    [
        ("POZOLE ROJO DE CERDO | Receta fácil 🔥 #shorts", "Pozole rojo de cerdo"),
        ("Pan de elote (muy fácil) - Cocina con Ana", "Pan de elote"),
        ("Cómo hacer tamales verdes: paso a paso", "Cómo hacer tamales verdes"),
        ("🔥🔥🔥", "El video"),
        ("Receta de chiles en nogada de la abuela con todos los secretos para que queden", "Receta de chiles en nogada de la abuela con todos"),
    ],
)
def test_speakable_title(title, spoken):
    assert speakable_title(title) == spoken


def test_mpv_arguments_limit_quality_and_enable_ipc(tmp_path):
    player = MpvPlayer(("mpv",), "yt-dlp", 480, socket_path=tmp_path / "mpv.sock")
    args = player.arguments(Video("abc", "Pozole"), tmp_path / "input.conf")
    assert args[0] == "mpv" and args[-1] == "https://www.youtube.com/watch?v=abc"
    assert "--fullscreen" in args
    assert "--ytdl-format=bestvideo[height<=480]+bestaudio/best[height<=480]/best" in args
    assert f"--input-ipc-server={tmp_path / 'mpv.sock'}" in args


@pytest.mark.skipif(sys.platform == "win32", reason="el IPC de mpv usa un socket Unix")
async def test_mpv_ipc_sends_commands_and_waits_for_the_reply(tmp_path):
    received = []

    async def fake_mpv(reader, writer):
        request = json.loads(await reader.readline())
        received.append(request["command"])
        writer.write(b'{"event": "pause"}\n')  # mpv intercala eventos
        writer.write(json.dumps({"request_id": request["request_id"], "error": "success"}).encode() + b"\n")
        await writer.drain()
        writer.close()

    socket_path = tmp_path / "mpv.sock"
    server = await asyncio.start_unix_server(fake_mpv, str(socket_path))
    player = MpvPlayer(socket_path=socket_path)
    player._proc = object()  # «hay un mpv corriendo»
    try:
        await player.pause()
        await player.seek(-10)
        await player.show_text("Te escucho…", 2.0)
    finally:
        player._proc = None
        server.close()
    assert received == [["set_property", "pause", True], ["seek", -10, "relative"], ["show-text", "Te escucho…", 2000]]


def simulated():
    app = build_app(Config(), simulated=True)
    music = app.now_playing.__self__
    return app, app.assistant, app.video, music


async def test_video_play_pauses_music_and_takes_over_media_controls():
    app, assistant, player, music = simulated()
    await assistant.handle_text("pon soda stereo")
    said = await assistant.handle_text("pon un video de cómo hacer pan de elote")
    assert said.speech == "Poniendo: Cómo hacer pan de elote."
    assert music.current.playing is False
    assert assistant.active_media == "video"

    await assistant.handle_text("pausa")
    await assistant.handle_text("adelanta 30 segundos")
    await assistant.handle_text("sigue")
    assert player.calls[-3:] == ["pause", "seek:30", "resume"]
    assert (await assistant.handle_text("qué canción es esta")).speech == "Es «Cómo hacer pan de elote»."

    await assistant.handle_text("cierra el video")
    assert player.current is None and assistant.active_media == "music"
    await assistant.handle_text("sigue")
    assert music.calls[-1] == "resume"


async def test_recipe_phrases_search_for_a_recipe():
    app, assistant, player, _ = simulated()
    search = app.assistant._skills["video"]._search
    await assistant.handle_text("cómo se hace el pozole")
    await assistant.handle_text("receta de chiles en nogada")
    await assistant.handle_text("busca en youtube tamales oaxaqueños")
    assert search.queries == ["receta de pozole", "receta de chiles en nogada", "tamales oaxaqueños"]


async def test_music_request_closes_the_video_and_video_ending_returns_controls():
    app, assistant, player, music = simulated()
    await assistant.handle_text("pon un video de gatitos")
    await assistant.handle_text("pon soda stereo")
    assert player.current is None and music.current.title == "Soda Stereo"

    await assistant.handle_text("pon un video de gatitos")
    player.finish()
    assert assistant.active_media == "music"


async def test_video_errors_are_spoken():
    _, assistant, _, _ = simulated()
    said = await assistant.handle_text("pon un video de algo que no existe")
    assert said.sound == "error" and "No encontré" in said.speech
    assert (await assistant.handle_text("cierra el video")).sound == "ok"

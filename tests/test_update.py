import pytest

from voxa import update
from voxa.main import main
from voxa.services.http import HttpError, HttpResponse


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.urls = []

    async def request(self, method, url, **kwargs):
        self.urls.append(url)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_versions_compare_as_numbers():
    assert update.is_newer("0.10.0", "0.9.3")
    assert update.is_newer("v1.0.0", "0.9.9")
    assert not update.is_newer("0.1.0", "0.1.0")
    assert not update.is_newer("0.1.0-beta.1", "0.1.0")


async def test_latest_release_from_github():
    http = FakeHttp(HttpResponse(200, {"tag_name": "v0.2.0"}))
    assert await update.latest_version(http) == "0.2.0"
    assert http.urls == ["https://api.github.com/repos/luis314159/voxa/releases/latest"]
    assert await update.latest_version(FakeHttp(HttpError("sin red"))) is None
    with pytest.raises(update.NoReleases):
        await update.latest_version(FakeHttp(HttpResponse(404, {"message": "Not Found"})))


def test_installer_comes_from_the_release():
    assert update.installer_url(None) == "https://github.com/luis314159/voxa/releases/latest/download/instalar-voxa.sh"
    assert update.installer_url("v0.2.0") == "https://github.com/luis314159/voxa/releases/download/v0.2.0/instalar-voxa.sh"


def test_update_command(monkeypatch, capsys):
    async def latest(http):
        return "9.0.0"

    ran = []
    monkeypatch.setattr(update, "latest_version", latest)
    monkeypatch.setattr(update, "run_installer", lambda version: ran.append(version) or 0)
    assert main(["actualizar", "--revisar"]) == 0
    assert "la más reciente es la 9.0.0" in capsys.readouterr().out and ran == []
    assert main(["actualizar"]) == 0
    assert ran == [None]
    assert main(["actualizar", "--version", "0.1.0"]) == 0
    assert ran == [None, "0.1.0"]


def test_up_to_date(monkeypatch, capsys):
    async def latest(http):
        return "0.0.1"

    monkeypatch.setattr(update, "latest_version", latest)
    monkeypatch.setattr(update, "run_installer", lambda version: pytest.fail("no debía instalar"))
    assert main(["actualizar"]) == 0
    assert "Ya tienes la versión más reciente" in capsys.readouterr().out


class Releases:
    def __init__(self, tag):
        self.tag = tag

    async def request(self, method, url, **kwargs):
        return HttpResponse(200, {"tag_name": self.tag})


async def test_updater_notices_and_installs_by_voice(tmp_path):
    from voxa.core.types import Intent
    from voxa.skills.updates import UpdateSkill

    launched = []
    updater = update.Updater(Releases("v0.2.0"), tmp_path, current="0.1.0",
                             launch=lambda version, folder: launched.append(version) or True)
    skill = UpdateSkill(updater)
    said = await skill.handle(Intent("update.check"))
    assert said.speech == "Sí: hay la versión 0.2.0; tienes la 0.1.0. Di «actualízate» para instalarla."
    said = await skill.handle(Intent("update.install"))
    assert said.speech == "Me actualizo a la versión 0.2.0. En unos minutos vuelvo." and launched == ["0.2.0"]
    assert (await skill.handle(Intent("update.install"))).speech == "Ya me estoy actualizando."

    current = update.Updater(Releases("v0.1.0"), tmp_path, current="0.1.0", launch=lambda *a: pytest.fail("no"))
    assert (await UpdateSkill(current).handle(Intent("update.check"))).speech == "Estoy al día: tengo la versión 0.1.0."


async def test_automatic_update_waits_for_the_night_and_a_quiet_kitchen(tmp_path):
    import asyncio
    from datetime import datetime

    launched = []
    hour = {"now": datetime(2026, 10, 25, 14, 0)}
    updater = update.Updater(Releases("v0.2.0"), tmp_path, automatic=True, current="0.1.0",
                             launch=lambda version, folder: launched.append(version) or True, now=lambda: hour["now"])
    quiet = {"idle": False}
    task = asyncio.ensure_future(updater.run(lambda: quiet["idle"], nap=0.01))
    await asyncio.sleep(0.05)
    assert updater.available == "0.2.0" and launched == []  # de día no
    hour["now"] = datetime(2026, 10, 26, 3, 30)
    await asyncio.sleep(0.05)
    assert launched == []  # de madrugada, pero hay un temporizador
    quiet["idle"] = True
    await asyncio.sleep(0.05)
    task.cancel()
    assert launched == ["0.2.0"]

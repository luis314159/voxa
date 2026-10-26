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

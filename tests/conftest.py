import pytest


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Ninguna prueba toca la configuración ni el estado reales de quien las corre."""
    for var, folder in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"),
                        ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache")):
        monkeypatch.setenv(var, str(tmp_path / "xdg" / folder))
    monkeypatch.delenv("VOXA_CONFIG", raising=False)


@pytest.fixture(autouse=True)
def spanish_by_default():
    """El idioma de la casa es global (se elige al armar la app): cada prueba empieza y termina en español."""
    from voxa.i18n import set_language

    set_language("es")
    yield
    set_language("es")

import pytest


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Ninguna prueba toca la configuración ni el estado reales de quien las corre."""
    for var, folder in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"),
                        ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache")):
        monkeypatch.setenv(var, str(tmp_path / "xdg" / folder))
    monkeypatch.delenv("VOXA_CONFIG", raising=False)

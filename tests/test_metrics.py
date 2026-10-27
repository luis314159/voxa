"""Cómo va VOXA: mediciones del uso real, solo en la PC."""

import json

from voxa.app import build_app
from voxa.config import Config
from voxa.state.metrics import UsageMetrics, report


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def test_summary_of_a_week(tmp_path):
    clock = Clock()
    metrics = UsageMetrics(tmp_path / "metricas.json", clock)
    for seconds in (0.8, 1.0, 1.2, 3.5):
        metrics.turn("pon salsa", "reglas", seconds=seconds, person="Ana", voices=True)
    metrics.turn("con qué sustituyo el huevo", "ia", seconds=2.0, voices=True)
    metrics.turn("blablá", "no", seconds=1.1, voices=True)
    for _ in range(3):
        metrics.wake()
    metrics.no_command()
    metrics.listening(2 * 3600)
    summary = UsageMetrics(tmp_path / "metricas.json", clock).summary()  # sobrevive a un reinicio
    assert summary["ordenes"] == 6 and summary["entendidas"] == 83 and summary["con_ia"] == 1
    assert summary["no_entendidas"] == 1 and summary["frases"][0]["texto"] == "blablá"
    assert summary["falsas_por_hora"] == 0.5 and summary["activaciones"] == 3
    assert summary["respuesta_s"] == 1.15 and summary["respuesta_lenta_s"] == 2.0
    assert summary["reconocidas"] == 67
    text = report(summary)
    assert "entendidas: 83 %" in text and "«blablá»" in text


def test_old_days_are_left_out(tmp_path):
    clock = Clock()
    metrics = UsageMetrics(tmp_path / "metricas.json", clock)
    metrics.turn("pon salsa", "reglas")
    clock.now += 10 * 86400
    metrics.turn("qué hora es", "reglas")
    assert metrics.summary(7)["ordenes"] == 1 and metrics.summary(30)["ordenes"] == 2
    clock.now += 40 * 86400
    metrics.turn("hola", "reglas")
    assert len(json.loads((tmp_path / "metricas.json").read_text(encoding="utf-8"))["dias"]) == 1


def test_without_data_nothing_is_invented():
    summary = UsageMetrics().summary()
    assert summary["entendidas"] is None and summary["respuesta_s"] is None and summary["falsas_por_hora"] is None
    assert "sin datos" in report(summary)


async def test_the_assistant_says_how_it_understood():
    app = build_app(Config(), simulated=True)
    await app.assistant.handle_text("pon un temporizador de cinco minutos")
    assert app.assistant.last_outcome == "reglas"
    await app.assistant.handle_text("qué onda con todo esto")
    assert app.assistant.last_outcome == "no"

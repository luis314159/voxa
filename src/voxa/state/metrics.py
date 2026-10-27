"""Cómo va VOXA: mediciones del uso real, solo en esta PC (``metricas.json``), de los últimos 30 días.

- cuántas órdenes entendió (por sus reglas o con la IA) y cuáles no, con las últimas frases;
- cuántas veces se activó «Hey Voxa» sin que nadie diera una orden (activaciones falsas), por hora
  de escucha;
- cuánto tardó en contestar (desde que terminaste de hablar hasta que empieza a sonar la respuesta);
- en cuántas órdenes reconoció a quien hablaba.

Nada de esto sale de la PC: se ve en el celular (con la clave) y con ``voxa como-va``.
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

KEEP_DAYS = 30
MAX_PHRASES = 50
MAX_TIMES = 400
_SAVE_EVERY_SECONDS = 300.0

_EMPTY_DAY = {
    "ordenes": 0, "reglas": 0, "ia": 0, "no_entendidas": 0, "activaciones": 0, "sin_orden": 0,
    "escuchando_s": 0.0, "con_persona": 0, "sin_persona": 0, "tiempos": [],
}


class UsageMetrics:
    def __init__(self, store: Path | None = None, clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._clock = clock
        self.days: dict[str, dict] = {}
        self.missed: list[dict] = []
        """Las últimas frases que no entendió: {"texto", "hora"}."""
        self._unsaved_listening = 0.0
        self._load()

    # --- lo que pasa ------------------------------------------------------------------------
    def turn(self, heard: str, outcome: str, *, seconds: float | None = None, person: str | None = None,
             voices: bool = False) -> None:
        """Una orden: ``outcome`` es «reglas», «ia» o «no» (no la entendió).

        ``seconds``: lo que tardó en contestar (solo en las de voz). ``voices``: si hay voces grabadas
        (si no, no tiene caso contar a quién reconoció).
        """
        day = self._today()
        day["ordenes"] += 1
        day[{"reglas": "reglas", "ia": "ia"}.get(outcome, "no_entendidas")] += 1
        if outcome == "no" and heard.strip():
            self.missed = [*self.missed, {"texto": heard.strip()[:200], "hora": self._clock()}][-MAX_PHRASES:]
        if seconds is not None:
            day["tiempos"] = [*day["tiempos"], round(seconds, 2)][-MAX_TIMES:]
        if voices:
            day["con_persona" if person else "sin_persona"] += 1
        self._save()

    def wake(self) -> None:
        self._today()["activaciones"] += 1
        self._save()

    def no_command(self) -> None:
        """Se activó «Hey Voxa» y nadie dijo nada (o no se oyó nada): casi siempre, una activación falsa."""
        self._today()["sin_orden"] += 1
        self._save()

    def listening(self, seconds: float) -> None:
        """Tiempo escuchando «Hey Voxa» (para contar las activaciones falsas por hora)."""
        self._today()["escuchando_s"] += seconds
        self._unsaved_listening += seconds
        if self._unsaved_listening >= _SAVE_EVERY_SECONDS:
            self._save()

    def forget(self) -> None:
        self.days, self.missed = {}, []
        self._save()

    # --- el resumen -------------------------------------------------------------------------
    def summary(self, days: int = 7) -> dict:
        since = (datetime.fromtimestamp(self._clock()) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        chosen = [d for key, d in self.days.items() if key >= since]
        total = {k: sum(d.get(k, 0) for d in chosen) for k in _EMPTY_DAY if k != "tiempos"}
        times = sorted(t for d in chosen for t in d.get("tiempos", []))
        hours = total["escuchando_s"] / 3600
        heard = total["con_persona"] + total["sin_persona"]
        return {
            "dias": days,
            "ordenes": total["ordenes"],
            "entendidas": _percent(total["reglas"] + total["ia"], total["ordenes"]),
            "con_ia": total["ia"],
            "no_entendidas": total["no_entendidas"],
            "activaciones": total["activaciones"],
            "falsas_por_hora": round(total["sin_orden"] / hours, 2) if hours >= 1 else None,
            "horas_escuchando": round(hours, 1),
            "respuesta_s": round(statistics.median(times), 2) if times else None,
            "respuesta_lenta_s": round(times[int(0.9 * (len(times) - 1))], 2) if times else None,
            "reconocidas": _percent(total["con_persona"], heard),
            "frases": list(reversed(self.missed))[:20],
        }

    # --- el día y el archivo --------------------------------------------------------------------
    def _today(self) -> dict:
        key = datetime.fromtimestamp(self._clock()).strftime("%Y-%m-%d")
        if key not in self.days:
            self.days[key] = {k: (list(v) if isinstance(v, list) else v) for k, v in _EMPTY_DAY.items()}
            cutoff = (datetime.fromtimestamp(self._clock()) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
            self.days = {k: v for k, v in self.days.items() if k > cutoff}
        return self.days[key]

    def _load(self) -> None:
        if not self._store or not self._store.exists():
            return
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            self.days = {k: {**_EMPTY_DAY, **v} for k, v in data.get("dias", {}).items() if isinstance(v, dict)}
            self.missed = [m for m in data.get("no_entendidas", []) if isinstance(m, dict)][-MAX_PHRASES:]
        except (OSError, ValueError, AttributeError) as exc:
            log.warning("No pude leer las mediciones: %s", exc)

    def _save(self) -> None:
        self._unsaved_listening = 0.0
        if not self._store:
            return
        try:
            self._store.parent.mkdir(parents=True, exist_ok=True)
            data = {"dias": self.days, "no_entendidas": self.missed}
            self._store.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("No pude guardar las mediciones: %s", exc)


def _percent(part: int, whole: int) -> int | None:
    return round(100 * part / whole) if whole else None


def report(summary: dict) -> str:
    """El resumen en texto, para la terminal o para mandarlo («voxa como-va»)."""
    def value(v, unit="") -> str:
        return "sin datos" if v is None else f"{v}{unit}"

    lines = [
        f"Cómo va VOXA (últimos {summary['dias']} días)",
        f"- Órdenes: {summary['ordenes']}; entendidas: {value(summary['entendidas'], ' %')} "
        f"({summary['con_ia']} con la IA); no entendidas: {summary['no_entendidas']}",
        f"- «Hey Voxa»: {summary['activaciones']} activaciones; sin orden (falsas): "
        f"{value(summary['falsas_por_hora'], ' por hora')} en {summary['horas_escuchando']} h escuchando",
        f"- Tiempo de respuesta: {value(summary['respuesta_s'], ' s')} de costumbre, "
        f"{value(summary['respuesta_lenta_s'], ' s')} en las más lentas",
        f"- Reconoció a quien hablaba: {value(summary['reconocidas'], ' %')}",
    ]
    if summary["frases"]:
        lines.append("- Lo último que no entendió:")
        lines += [f"  «{f['texto']}»" for f in summary["frases"][:10]]
    return "\n".join(lines)

"""Cuánto se ha gastado en IA: límite mensual en dólares y tope de preguntas por día."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


class AiUsage:
    def __init__(self, store: Path | None, monthly_budget_usd: float, daily_questions: int) -> None:
        self._store = store
        self.monthly_budget_usd = monthly_budget_usd
        self.daily_questions = daily_questions
        self.month = ""
        self.month_usd = 0.0
        self.month_questions = 0
        self.day = ""
        self.day_questions = 0
        self._load()

    def _roll(self, now: datetime) -> None:
        month, day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
        if month != self.month:
            self.month, self.month_usd, self.month_questions = month, 0.0, 0
        if day != self.day:
            self.day, self.day_questions = day, 0

    def blocked(self, now: datetime) -> str | None:
        """Por qué ya no se puede preguntar («month» o «day»), o ``None``."""
        self._roll(now)
        if self.monthly_budget_usd > 0 and self.month_usd >= self.monthly_budget_usd:
            return "month"
        if self.daily_questions > 0 and self.day_questions >= self.daily_questions:
            return "day"
        return None

    def record(self, usd: float, now: datetime) -> None:
        self._roll(now)
        self.month_usd += usd
        self.month_questions += 1
        self.day_questions += 1
        self._save()

    def summary(self) -> str:
        budget = f" de {self.monthly_budget_usd:.2f}" if self.monthly_budget_usd > 0 else ""
        return f"{self.month_usd:.2f} USD{budget} este mes · {self.month_questions} preguntas"

    def _load(self) -> None:
        if not self._store or not self._store.exists():
            return
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            self.month = str(data.get("month", ""))
            self.month_usd = float(data.get("month_usd", 0.0))
            self.month_questions = int(data.get("month_questions", 0))
            self.day = str(data.get("day", ""))
            self.day_questions = int(data.get("day_questions", 0))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            log.warning("No pude leer el gasto de IA: %s", exc)

    def _save(self) -> None:
        if not self._store:
            return
        data = {
            "month": self.month, "month_usd": round(self.month_usd, 6), "month_questions": self.month_questions,
            "day": self.day, "day_questions": self.day_questions,
        }
        try:
            self._store.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self._store)
        except OSError as exc:
            log.warning("No pude guardar el gasto de IA: %s", exc)

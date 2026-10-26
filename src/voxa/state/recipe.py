"""La receta en curso: ingredientes, pasos y en cuál va la cocina (sobrevive a un reinicio)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MAX_STEPS = 20
MAX_INGREDIENTS = 30


@dataclass(frozen=True)
class Ingredient:
    text: str
    """Como se dice: «1 kilo de maíz pozolero»."""
    name: str
    """Lo que se compra: «maíz pozolero»."""


@dataclass(frozen=True)
class Step:
    text: str
    minutes: int = 0
    """Espera o cocción del paso (para ofrecer un temporizador); 0 si no hay."""


@dataclass(frozen=True)
class Recipe:
    title: str
    servings: int
    ingredients: tuple[Ingredient, ...]
    steps: tuple[Step, ...]

    @classmethod
    def from_tool(cls, args: dict[str, Any]) -> Recipe | None:
        """Lo que mandó la IA (herramienta ``mostrar_receta``), validado; ``None`` si no sirve."""
        def text(value: Any) -> str:
            return " ".join(str(value).split()) if isinstance(value, (str, int, float)) else ""

        title = text(args.get("titulo"))
        ingredients = []
        for item in args.get("ingredientes") or []:
            if isinstance(item, dict) and (said := text(item.get("texto"))):
                ingredients.append(Ingredient(said, text(item.get("nombre")) or said))
        steps = []
        for item in args.get("pasos") or []:
            if isinstance(item, dict) and (said := text(item.get("texto"))):
                minutes = item.get("minutos")
                minutes = int(minutes) if isinstance(minutes, (int, float)) and 0 < minutes <= 24 * 60 else 0
                steps.append(Step(said, minutes))
        if not title or not steps:
            return None
        servings = args.get("porciones")
        servings = int(servings) if isinstance(servings, (int, float)) and 0 < servings <= 100 else 4
        return cls(title, servings, tuple(ingredients[:MAX_INGREDIENTS]), tuple(steps[:MAX_STEPS]))


class RecipeSession:
    def __init__(self, store: Path | None = None) -> None:
        self._store = store
        self.recipe: Recipe | None = None
        self.current = -1
        """Paso actual (desde 0); -1 = todavía no se empieza (se ven los ingredientes)."""
        self._load()

    @property
    def active(self) -> bool:
        return self.recipe is not None

    @property
    def step(self) -> Step | None:
        if self.recipe is None or not 0 <= self.current < len(self.recipe.steps):
            return None
        return self.recipe.steps[self.current]

    def start(self, recipe: Recipe) -> None:
        self.recipe, self.current = recipe, -1
        self._save()

    def go(self, index: int) -> Step | None:
        if self.recipe is None:
            return None
        self.current = max(-1, min(index, len(self.recipe.steps) - 1))
        self._save()
        return self.step

    def close(self) -> Recipe | None:
        recipe, self.recipe, self.current = self.recipe, None, -1
        self._save()
        return recipe

    def summary(self) -> str:
        """Para la IA: así puede responder «¿cuánto chile le pongo?» sobre esta receta."""
        if self.recipe is None:
            return ""
        r = self.recipe
        where = f"vamos en el paso {self.current + 1} de {len(r.steps)}: {r.steps[self.current].text}" if self.step else "aún no empiezan"
        ingredients = "; ".join(i.text for i in r.ingredients)
        return f"Receta en curso: {r.title}, para {r.servings} porciones. Ingredientes: {ingredients}. Ahora {where}"

    def snapshot(self) -> dict | None:
        if self.recipe is None:
            return None
        r = self.recipe
        return {
            "title": r.title,
            "servings": r.servings,
            "ingredients": [i.text for i in r.ingredients],
            "steps": [{"text": s.text, "minutes": s.minutes} for s in r.steps],
            "current": self.current,
        }

    def _load(self) -> None:
        if not self._store or not self._store.exists():
            return
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
            if data:
                self.recipe = Recipe(
                    data["title"], int(data["servings"]),
                    tuple(Ingredient(**i) for i in data["ingredients"]),
                    tuple(Step(**s) for s in data["steps"]),
                )
                self.current = max(-1, min(int(data.get("current", -1)), len(self.recipe.steps) - 1))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            log.warning("No pude leer la receta guardada: %s", exc)

    def _save(self) -> None:
        if not self._store:
            return
        data = {**asdict(self.recipe), "current": self.current} if self.recipe else None
        try:
            self._store.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._store)
        except OSError as exc:
            log.warning("No pude guardar la receta: %s", exc)

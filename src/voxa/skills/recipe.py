"""Recetas paso a paso: «dame la receta de pozole» → ingredientes, pasos y temporizadores por voz.

La receta la arma la IA (si está activada); sin IA, «receta de pozole» pone un video, como antes.
Se navega con «siguiente paso», «paso anterior», «repite el paso», «ve al paso 4», y en cada paso
con espera, «pon el tiempo» cuenta los minutos de ese paso.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from voxa.core.phrases import capitalize, format_duration, join_words
from voxa.core.types import Intent, Response, Skill
from voxa.state.recipe import Recipe, RecipeSession
from voxa.state.shopping import ShoppingList
from voxa.state.timers import TimerManager

MakeRecipe = Callable[[str], Awaitable["Recipe | Response"]]

NO_RECIPE = Response("No hay ninguna receta abierta. Pídeme una, por ejemplo: «dame la receta de arroz rojo».")
NEEDS_DURATION = Response("¿De cuánto? Di, por ejemplo, «temporizador de 10 minutos».")


class RecipeSkill:
    def __init__(
        self,
        session: RecipeSession,
        timers: TimerManager,
        shopping: ShoppingList,
        *,
        make: MakeRecipe | None = None,
        video: Skill | None = None,
    ) -> None:
        self.session = session
        self._timers = timers
        self._shopping = shopping
        self.make = make
        """Lo pone la app cuando hay IA: arma la receta de un platillo."""
        self._video = video
        self.on_wait: Callable[[str], Awaitable[None]] | None = None
        """Lo pone el servicio: dice algo en voz alta mientras la IA arma la receta (tarda unos segundos)."""

    async def handle(self, intent: Intent) -> Response:
        if intent.name == "recipe.start":
            return await self._start(intent)
        if intent.name == "recipe.timer" and not self.session.active:
            return NEEDS_DURATION
        recipe = self.session.recipe
        if recipe is None:
            return NO_RECIPE
        total = len(recipe.steps)
        match intent.name:
            case "recipe.ingredients":
                if not recipe.ingredients:
                    return Response("Esta receta no trae lista de ingredientes.")
                return Response(f"Para {recipe.title.lower()} necesitas: {join_words([i.text for i in recipe.ingredients])}.")
            case "recipe.next":
                if self.session.current >= total - 1:
                    return Response("Ese era el último paso. ¡Buen provecho! Di «termina la receta» para cerrarla.")
                return self._say_step(self.session.current + 1)
            case "recipe.previous":
                if self.session.current <= 0:
                    return self._say_step(0)
                return self._say_step(self.session.current - 1)
            case "recipe.repeat":
                if self.session.current < 0:
                    return Response(f"Todavía no empezamos {recipe.title.lower()}. Di «siguiente paso» para empezar.")
                return self._say_step(self.session.current)
            case "recipe.goto":
                number = int(intent.slots.get("number", 0))
                if not 1 <= number <= total:
                    return Response(f"La receta tiene {total} pasos.", sound="error")
                return self._say_step(number - 1)
            case "recipe.to_list":
                added, present = self._shopping.add([i.name for i in recipe.ingredients])
                if not added:
                    return Response("Todo eso ya estaba en la lista." if present else "Esta receta no trae ingredientes.")
                extra = f" {len(present)} ya {'estaba' if len(present) == 1 else 'estaban'}." if present else ""
                return Response(f"Agregué {len(added)} {'cosa' if len(added) == 1 else 'cosas'} a la lista.{extra}")
            case "recipe.timer":
                return self._timer()
            case "recipe.close":
                self.session.close()
                return Response(f"Cerré la receta de {recipe.title.lower()}.")
        return Response("Todavía no sé hacer eso con la receta.", sound="error")

    async def _start(self, intent: Intent) -> Response:
        dish = intent.slots.get("query", "").strip()
        if self.make is None:
            if self._video is not None:  # sin IA: un video de la receta, como siempre
                return await self._video.handle(Intent("video.play", {"query": dish, "kind": "recipe"}, intent.text, intent.raw))
            return Response("Para recetas paso a paso hay que activar la IA en la configuración.", sound="error")
        if self.on_wait is not None:
            await self.on_wait(f"Déjame ver la receta de {dish}…")
        result = await self.make(dish)
        if isinstance(result, Response):
            return result
        return await self.open(result)

    async def open(self, recipe: Recipe) -> Response:
        """Abre una receta (también la que manda la IA desde una pregunta libre) y la presenta."""
        self.session.start(recipe)
        steps = len(recipe.steps)
        count = f"{len(recipe.ingredients)} ingredientes y {steps} pasos" if recipe.ingredients else f"{steps} pasos"
        return Response(
            f"{capitalize(recipe.title)}, para {recipe.servings} porciones: son {count}. "
            "Di «los ingredientes» para que te los lea, o «siguiente paso» para empezar."
        )

    def _say_step(self, index: int) -> Response:
        step = self.session.go(index)
        assert step is not None and self.session.recipe is not None
        total = len(self.session.recipe.steps)
        text = f"Paso {index + 1} de {total}: {step.text}"
        if not text.endswith((".", "!", "?")):
            text += "."
        if step.minutes:
            text += f" Si quieres, di «pon el tiempo» y cuento {format_duration(step.minutes * 60)}."
        return Response(text)

    def _timer(self) -> Response:
        step = self.session.step
        if step is None or not step.minutes:
            return NEEDS_DURATION
        label = f"el paso {self.session.current + 1} de la receta"
        self._timers.add(step.minutes * 60, label)
        return Response(f"Listo: {format_duration(step.minutes * 60)} para {label}.")

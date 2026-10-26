import pytest

import voxa.app
from voxa.app import build_app
from voxa.config import AiConfig, Config
from voxa.service import Service
from voxa.services.ai import AiAnswer
from voxa.skills.recipe import NEEDS_DURATION, NO_RECIPE
from voxa.state.recipe import Recipe, RecipeSession

POZOLE = {
    "titulo": "Pozole rojo",
    "porciones": 6,
    "ingredientes": [
        {"texto": "1 kilo de maíz pozolero", "nombre": "maíz pozolero"},
        {"texto": "1 kilo de carne de cerdo", "nombre": "carne de cerdo"},
        {"texto": "5 chiles guajillo", "nombre": "chile guajillo"},
    ],
    "pasos": [
        {"texto": "Cuece la carne con ajo y cebolla", "minutos": 60},
        {"texto": "Licúa los chiles con un poco de caldo.", "minutos": 0},
        {"texto": "Junta todo y deja hervir.", "minutos": 20},
    ],
}


class FakeChat:
    name = "Prueba · modelo"
    model = "claude-haiku-5-5"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    async def ask(self, system, messages, tools=(), *, max_tokens=2048):
        self.asked.append({"system": system, "messages": messages, "tools": [t.name for t in tools]})
        return self.answers.pop(0)


@pytest.fixture
def kitchen(tmp_path, monkeypatch):
    """Una app simulada con la IA «activada» (FakeChat) y conectada como en la PC de la cocina."""
    def make(*answers):
        chat = FakeChat(*answers)
        monkeypatch.setattr(voxa.app, "read_key", lambda config, path: "k")
        monkeypatch.setattr(voxa.app, "build_chat", lambda config, key: chat)
        app = build_app(Config(ai=AiConfig(enabled=True), state_dir=tmp_path, config_dir=tmp_path), simulated=True)
        return Service.create(app), chat

    return make


def test_recipe_from_the_ai_is_validated():
    recipe = Recipe.from_tool(POZOLE)
    assert recipe.title == "Pozole rojo" and recipe.servings == 6
    assert [s.minutes for s in recipe.steps] == [60, 0, 20]
    assert recipe.ingredients[2].name == "chile guajillo"
    odd = Recipe.from_tool({"titulo": " Arroz  rojo ", "porciones": "muchas", "ingredientes": ["arroz"],
                            "pasos": [{"texto": "Fríe el arroz", "minutos": -3}, {"texto": ""}, "lava"]})
    assert odd.title == "Arroz rojo" and odd.servings == 4 and odd.ingredients == ()
    assert [(s.text, s.minutes) for s in odd.steps] == [("Fríe el arroz", 0)]
    assert Recipe.from_tool({"titulo": "Nada", "pasos": []}) is None


def test_recipe_survives_a_restart(tmp_path):
    store = tmp_path / "receta.json"
    session = RecipeSession(store)
    session.start(Recipe.from_tool(POZOLE))
    session.go(1)
    again = RecipeSession(store)
    assert again.recipe == session.recipe and again.current == 1
    again.close()
    assert RecipeSession(store).recipe is None


async def test_cooking_pozole_step_by_step(kitchen):
    service, chat = kitchen(AiAnswer(calls=[("mostrar_receta", POZOLE)]))
    waits = []

    async def wait(text):
        waits.append(text)

    service.app.assistant.skill("recipe").on_wait = wait
    said = await service.handle_text("dame la receta de pozole")
    assert said.speech == ("Pozole rojo, para 6 porciones: son 3 ingredientes y 3 pasos. "
                           "Di «los ingredientes» para que te los lea, o «siguiente paso» para empezar.")
    assert waits == ["Déjame ver la receta de pozole…"]
    assert chat.asked[0]["tools"] == ["mostrar_receta"]
    assert chat.asked[0]["messages"][-1]["content"].endswith("La receta de: pozole")

    said = await service.handle_text("qué ingredientes lleva")
    assert said.speech == ("Para pozole rojo necesitas: 1 kilo de maíz pozolero, 1 kilo de carne de cerdo "
                           "y 5 chiles guajillo.")
    said = await service.handle_text("empezamos")
    assert said.speech == ("Paso 1 de 3: Cuece la carne con ajo y cebolla. "
                           "Si quieres, di «pon el tiempo» y cuento una hora.")
    said = await service.handle_text("pon el tiempo")
    assert said.speech == "Listo: una hora para el paso 1 de la receta."
    assert [t.duration for t in service.app.timers.active] == [3600]

    assert (await service.handle_text("siguiente paso")).speech == "Paso 2 de 3: Licúa los chiles con un poco de caldo."
    assert await service.handle_text("pon el tiempo") == NEEDS_DURATION  # este paso no tiene espera
    assert (await service.handle_text("paso anterior")).speech.startswith("Paso 1 de 3")
    assert (await service.handle_text("ve al paso 3")).speech.startswith("Paso 3 de 3: Junta todo")
    assert (await service.handle_text("en qué paso voy")).speech.startswith("Paso 3 de 3")
    assert (await service.handle_text("ve al paso 9")).speech == "La receta tiene 3 pasos."
    said = await service.handle_text("qué sigue")
    assert said.speech.startswith("Ese era el último paso.")

    snapshot = service.display.snapshot()["recipe"]
    assert snapshot["title"] == "Pozole rojo" and snapshot["current"] == 2
    assert snapshot["steps"][0] == {"text": "Cuece la carne con ajo y cebolla", "minutes": 60}

    service.app.shopping.add(["chile guajillo"])
    said = await service.handle_text("agrega los ingredientes a la lista")
    assert said.speech == "Agregué 2 cosas a la lista. 1 ya estaba."
    assert (await service.handle_text("termina la receta")).speech == "Cerré la receta de pozole rojo."
    assert service.display.snapshot()["recipe"] is None


async def test_follow_up_questions_know_the_recipe(kitchen):
    service, chat = kitchen(AiAnswer(calls=[("mostrar_receta", POZOLE)]), AiAnswer("Unos 5 chiles, o 7 si les gusta picoso."))
    await service.handle_text("cómo se hace el pozole")
    await service.handle_text("siguiente paso")
    said = await service.handle_text("cuánto chile le pongo")
    assert said.speech == "Unos 5 chiles, o 7 si les gusta picoso."
    question = chat.asked[1]["messages"][-1]["content"]
    assert "Receta en curso: Pozole rojo, para 6 porciones" in question
    assert "paso 1 de 3: Cuece la carne" in question
    assert chat.asked[1]["tools"] == ["orden_voxa", "mostrar_receta"]


async def test_a_free_question_can_open_a_recipe(kitchen):
    service, _ = kitchen(AiAnswer(calls=[("mostrar_receta", POZOLE)]))
    said = await service.handle_text("se me antojó algo calientito con maíz para la cena")
    assert said.speech.startswith("Pozole rojo, para 6 porciones")
    assert service.app.recipe.active


async def test_a_dish_the_ai_will_not_cook(kitchen):
    service, _ = kitchen(AiAnswer("Eso no se cocina, pero te puedo dar ideas para la cena."))
    said = await service.handle_text("dame la receta de un coche")
    assert said.speech == "Eso no se cocina, pero te puedo dar ideas para la cena."
    assert not service.app.recipe.active


async def test_without_ai_recipes_are_videos_and_steps_need_a_recipe():
    service = Service.create(build_app(Config(), simulated=True))
    assert await service.handle_text("siguiente paso") == NO_RECIPE
    assert await service.handle_text("pon el temporizador") == NEEDS_DURATION
    said = await service.handle_text("receta de chiles en nogada")
    assert said.speech.startswith("Poniendo")  # el video de la receta, como antes de la IA

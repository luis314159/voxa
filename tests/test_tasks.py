import json

from voxa.core.people import speaking
from voxa.nlu import load_matcher
from voxa.skills.tasks import TasksSkill
from voxa.state.tasks import TaskList

MATCHER = load_matcher()


async def say(skill, text):
    return (await skill.handle(MATCHER.match(text))).speech


async def test_my_tasks_are_mine(tmp_path):
    skill = TasksSkill(TaskList(tmp_path / "p.json"))
    with speaking("Ana"):
        assert await say(skill, "agrega llamar al plomero a mis pendientes") == "Anotado en tus pendientes: llamar al plomero."
        assert await say(skill, "agrega llamar al plomero a mis pendientes") == "Eso ya estaba en los pendientes."
    assert await say(skill, "agrega la tarea de mate a los pendientes de Luis") == "Anotado en los pendientes de Luis: tarea de mate."
    assert await say(skill, "agrega pagar la luz a los pendientes") == "Anotado en los pendientes de la casa: pagar la luz."
    with speaking("Ana"):
        assert await say(skill, "qué pendientes tengo") == "Tienes un pendiente: llamar al plomero. De la casa: pagar la luz."
    assert await say(skill, "qué pendientes tiene Luis") == "Luis tiene un pendiente: tarea de mate."
    with speaking("Luis"):
        assert await say(skill, "ya hice la tarea de mate") == "Listo, taché tarea de mate. ¡Ya no hay pendientes!"
    assert (await say(skill, "ya hice algo que no existe")).startswith("No encontré")


async def test_without_knowing_who_talks_mine_means_the_house(tmp_path):
    skill = TasksSkill(TaskList(tmp_path / "p.json"))
    assert await say(skill, "agrega comprar focos a mis pendientes") == "Anotado en los pendientes de la casa: comprar focos."


def test_tasks_persist(tmp_path):
    tasks = TaskList(tmp_path / "p.json")
    tasks.add("llamar al plomero", "Ana")
    again = TaskList(tmp_path / "p.json")
    assert [(t.text, t.person) for t in again.tasks] == [("llamar al plomero", "Ana")]
    assert again.add("otra cosa").id == 2


def test_good_morning_mentions_my_tasks(tmp_path):
    tasks = TaskList(tmp_path / "p.json")
    tasks.add("llamar al plomero", "Ana")
    assert TasksSkill(tasks).morning("Ana") == "Tienes un pendiente: llamar al plomero."
    assert TasksSkill(tasks).morning(None) == ""


async def test_phone_tasks(tmp_path):
    from test_web import KEY, as_json, http
    from voxa.app import build_app
    from voxa.config import Config
    from voxa.service import Service
    from voxa.web import WebServer

    service = Service.create(build_app(Config(), simulated=True))
    server = WebServer(service, KEY, tmp_path / "fondos", host="127.0.0.1", port=0)
    await server.start()
    try:
        status, _, body = await http(server.port, "POST", "/api/tareas", **as_json({"agregar": "pagar la luz", "persona": "Ana"}))
        data = json.loads(body)
        assert status == 200 and data["tareas"][0] == {"id": 1, "texto": "pagar la luz", "persona": "Ana"}
        status, _, body = await http(server.port, "POST", "/api/tareas", **as_json({"hecha": 1}))
        assert json.loads(body)["tareas"] == []
    finally:
        await server.close()

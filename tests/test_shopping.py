from voxa.app import build_app
from voxa.config import Config
from voxa.service import Service
from voxa.skills.shopping import split_items, with_commas
from voxa.state.shopping import ShoppingList, item_key


def test_items_are_split_by_commas_and_y():
    assert split_items("leche, huevos y tortillas") == ["leche", "huevos", "tortillas"]
    assert split_items("pan dulce") == ["pan dulce"]
    assert split_items("arroz e higos") == ["arroz", "higos"]
    assert with_commas("leche huevos y tortillas", "Agrega leche, huevos y tortillas a la lista") == "leche, huevos y tortillas"


def test_no_duplicates_ignoring_articles_accents_and_plurals():
    assert item_key("los huevos") == item_key("Huevo") == "huevo"
    shopping = ShoppingList()
    assert shopping.add(["la leche", "café"]) == (["leche", "café"], [])
    assert shopping.add(["Leche", "cafe", "pan"]) == (["pan"], ["Leche".lower(), "cafe"])
    assert shopping.remove("el pan") == "pan"
    assert shopping.remove("pan") is None


def test_list_survives_restart(tmp_path):
    store = tmp_path / "lista.json"
    ShoppingList(store).add(["tortillas", "jabón para trastes"])
    assert ShoppingList(store).items == ["tortillas", "jabón para trastes"]


async def test_shopping_by_voice_and_on_screen():
    service = Service.create(build_app(Config(), simulated=True))
    said = await service.handle_text("agrega leche, huevos y tortillas a la lista")
    assert said.speech == "Agregué leche, huevos y tortillas a la lista."
    assert (await service.handle_text("se acabó el café")).speech == "Agregué café a la lista."
    assert (await service.handle_text("agrega la leche a la lista")).speech == "Leche ya estaba en la lista."
    assert (await service.handle_text("quita los huevos de la lista")).speech == "Quité huevos de la lista."
    assert service.display.snapshot()["shopping"] == ["leche", "tortillas", "café"]
    said = await service.handle_text("qué hay que comprar")
    assert said.speech == "En la lista hay 3 cosas: leche, tortillas y café."
    assert (await service.handle_text("borra la lista")).speech == "Borré la lista del súper."
    assert service.display.snapshot()["shopping"] == []

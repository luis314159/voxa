import asyncio
import json

import pytest

from voxa.nlu import load_matcher
from voxa.services.http import HttpError, HttpResponse, UrllibHttp
from voxa.state.shopping import ShoppingList
from voxa.telegram import NOT_LINKED, Chats, ShoppingBot, TelegramApi, TelegramError, link_chat

TOKEN = "123456:ABC-secreto"
FAMILY = 1001
STRANGER = 666


class FakeTelegram:
    """Contesta como la API de bots; guarda cada llamada (método y datos)."""

    def __init__(self, updates=()):
        self.updates = list(updates)
        self.calls = []
        self.fail = None

    async def request(self, method, url, *, params=None, headers=None, json_body=None, form=None, timeout=8.0):
        assert url.startswith(f"https://api.telegram.org/bot{TOKEN}/")
        name = url.rsplit("/", 1)[1]
        self.calls.append((name, json_body))
        await asyncio.sleep(0)  # como la red: deja correr a los demás
        if self.fail:
            raise self.fail
        if name == "getMe":
            return HttpResponse(200, {"ok": True, "result": {"username": "cocina_bot"}})
        if name == "getUpdates":
            offset = (json_body or {}).get("offset") or 0
            pending = [u for u in self.updates if u["update_id"] >= offset]
            return HttpResponse(200, {"ok": True, "result": pending})
        return HttpResponse(200, {"ok": True, "result": {}})

    def sent(self):
        return [body for name, body in self.calls if name in ("sendMessage", "editMessageText")]


def message(text, chat=FAMILY, update_id=1, name="Ana"):
    return {"update_id": update_id, "message": {"chat": {"id": chat, "first_name": name}, "text": text}}


def button(data, chat=FAMILY, update_id=1):
    return {"update_id": update_id,
            "callback_query": {"id": "q1", "data": data, "message": {"message_id": 7, "chat": {"id": chat}}}}


@pytest.fixture
def kitchen(tmp_path):
    http = FakeTelegram()
    shopping = ShoppingList(tmp_path / "lista.json")
    chats = Chats(tmp_path / "chats.json", tmp_path / "codigo.json")
    chats.add(FAMILY, "Ana")
    changes = []
    bot = ShoppingBot(TelegramApi(TOKEN, http), shopping, chats, load_matcher(), on_change=lambda: changes.append(1))
    return bot, http, shopping, chats, changes


async def test_plain_text_is_added_to_the_list(kitchen):
    bot, http, shopping, _, changes = kitchen
    await bot.handle(message("leche, huevos y tortillas"))
    assert shopping.items == ["leche", "huevos", "tortillas"]
    assert http.sent()[-1]["text"] == "Agregué leche, huevos y tortillas."
    assert changes  # la pantalla de la cocina se actualiza

    await bot.handle(message("- pan\n- Leche"))
    assert shopping.items == ["leche", "huevos", "tortillas", "pan"]
    assert http.sent()[-1]["text"] == "Agregué pan. Leche ya estaba."


async def test_voxa_phrases_work_too(kitchen):
    bot, http, shopping, _, _ = kitchen
    shopping.add(["leche", "café"])
    await bot.handle(message("quita la leche"))
    assert shopping.items == ["café"]
    assert "Quité" in http.sent()[-1]["text"]
    await bot.handle(message("borra la lista"))
    assert shopping.items == []


async def test_the_list_comes_with_a_button_per_item(kitchen):
    bot, http, shopping, _, changes = kitchen
    shopping.add(["leche", "jabón para trastes"])
    await bot.handle(message("/lista"))
    keyboard = http.sent()[-1]["reply_markup"]["inline_keyboard"]
    assert [row[0]["text"] for row in keyboard] == ["✓ leche", "✓ jabón para trastes", "Vaciar la lista"]

    await bot.handle(button(keyboard[1][0]["callback_data"]))
    assert shopping.items == ["leche"]
    edited = http.sent()[-1]
    assert edited["message_id"] == 7 and [r[0]["text"] for r in edited["reply_markup"]["inline_keyboard"]] == ["✓ leche", "Vaciar la lista"]
    assert ("answerCallbackQuery", {"callback_query_id": "q1", "text": "Quité jabón para trastes"}) in http.calls
    assert changes


async def test_emptying_the_list_asks_first(kitchen):
    bot, http, shopping, _, _ = kitchen
    shopping.add(["leche"])
    await bot.handle(button("vaciar"))
    assert shopping.items == ["leche"]
    assert http.sent()[-1]["text"] == "¿Vaciar toda la lista?"
    await bot.handle(button("vaciar:si"))
    assert shopping.items == []
    assert http.sent()[-1]["text"] == "La lista del súper está vacía."


async def test_strangers_get_nothing(kitchen):
    bot, http, shopping, _, _ = kitchen
    shopping.add(["leche"])
    await bot.handle(message("cerveza", chat=STRANGER))
    await bot.handle(message("/lista", chat=STRANGER))
    await bot.handle(button("vaciar:si", chat=STRANGER))
    assert shopping.items == ["leche"]
    assert [b["text"] for b in http.sent()] == [NOT_LINKED, NOT_LINKED]
    assert "leche" not in json.dumps(http.calls, ensure_ascii=False)


async def test_pairing_code_links_a_chat_once(tmp_path):
    now = [1000.0]
    chats = Chats(tmp_path / "chats.json", tmp_path / "codigo.json", clock=lambda: now[0])
    code = chats.new_code()
    assert len(code) == 6 and code.isdigit()
    assert not chats.try_pair(STRANGER, "X", "000000" if code != "000000" else "111111")
    assert chats.try_pair(FAMILY, "Ana", f" {code} ")
    assert chats.all() == {FAMILY: "Ana"}
    assert not chats.try_pair(STRANGER, "X", code)  # el código se usa una vez

    code = chats.new_code()
    now[0] += 11 * 60
    assert not chats.try_pair(STRANGER, "X", code)  # vencido


def test_secret_files_are_private(tmp_path):
    import os
    import stat
    import sys

    chats = Chats(tmp_path / "chats.json", tmp_path / "codigo.json")
    chats.add(FAMILY, "Ana")
    chats.new_code()
    if sys.platform != "win32":
        for path in (chats.path, chats.code_path):
            assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


async def test_service_pairs_a_chat_that_sends_the_code(kitchen):
    bot, http, _, chats, _ = kitchen
    code = chats.new_code()
    await bot.handle(message(code, chat=2002, name="Luis"))
    assert chats.allowed(2002)
    assert http.sent()[-1]["text"].startswith("¡Listo!")


async def test_link_command_pairs_the_first_chat_with_the_code(tmp_path):
    chats = Chats(tmp_path / "chats.json", tmp_path / "codigo.json")
    http = FakeTelegram()
    api = TelegramApi(TOKEN, http)
    said = []

    async def family_writes():
        while not said:
            await asyncio.sleep(0)
        code = said[0].rsplit(" ", 1)[1]
        http.updates += [message("hola", chat=STRANGER, update_id=5), message(code, chat=FAMILY, update_id=6)]

    writer = asyncio.create_task(family_writes())
    assert await link_chat(api, chats, say=said.append, minutes=1)
    await writer
    assert chats.all() == {FAMILY: "Ana"}
    assert "@cocina_bot" in said[0]


async def test_the_token_never_shows_up_in_errors(kitchen):
    bot, http, _, _, _ = kitchen
    http.fail = HttpError(f"falló https://api.telegram.org/bot{TOKEN}/getUpdates")
    with pytest.raises(TelegramError) as caught:
        await bot.api.call("getUpdates")
    assert TOKEN not in str(caught.value)


async def test_daemon_http_returns_like_the_normal_one(monkeypatch):
    monkeypatch.setattr(UrllibHttp, "_request", staticmethod(lambda *args: HttpResponse(200, {"ok": True})))
    assert (await UrllibHttp(daemon=True).request("GET", "http://x")).data == {"ok": True}

    def boom(*args):
        raise HttpError("sin red")

    monkeypatch.setattr(UrllibHttp, "_request", staticmethod(boom))
    with pytest.raises(HttpError):
        await UrllibHttp(daemon=True).request("GET", "http://x")

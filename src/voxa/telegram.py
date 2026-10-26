"""La lista del súper desde Telegram: un bot privado de la casa (opcional, ``[telegram]``).

Se le escribe «leche, huevos y tortillas» y lo agrega; «/lista» manda la lista con un botón por
cosa para ir palomeando en la tienda. Solo atiende los chats vinculados con
``voxa telegram-vincular`` (un código de 6 dígitos que se le manda al bot); a los demás les dice
que es privado y nada más. El token se guarda en ``~/.config/voxa/telegram_token`` (600) y nunca
se escribe en el registro.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Callable

from voxa.core.phrases import join_words
from voxa.nlu.matcher import Matcher
from voxa.services.http import Http, HttpError
from voxa.skills.shopping import ShoppingSkill, split_items
from voxa.state.shopping import ShoppingList, item_key

log = logging.getLogger(__name__)

API = "https://api.telegram.org"
TOKEN_ENV = "VOXA_TELEGRAM_TOKEN"
POLL_SECONDS = 30
CODE_MINUTES = 10

HELP = (
    "Escríbeme lo que falta y lo agrego a la lista del súper de la cocina: «leche, huevos y tortillas».\n"
    "/lista — la lista; toca lo que ya compraste para quitarlo.\n"
    "«quita la leche», «borra la lista» también funcionan."
)
NOT_LINKED = "Este bot es privado. Para usarlo, en la PC de la cocina corre: voxa telegram-vincular"


_REMOVE = re.compile(r"^\s*(quita|quitale|borra|elimina|saca|tacha)\b", re.IGNORECASE)


class TelegramError(Exception):
    pass


def read_token(path: Path) -> str | None:
    """El token: de ``VOXA_TELEGRAM_TOKEN`` si está, si no del archivo de ``voxa telegram-vincular``."""
    if os.environ.get(TOKEN_ENV, "").strip():
        return os.environ[TOKEN_ENV].strip()
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


class TelegramApi:
    def __init__(self, token: str, http: Http) -> None:
        self._token = token
        self._http = http

    async def call(self, method: str, payload: dict[str, Any] | None = None, *, timeout: float = 10.0) -> Any:
        try:
            response = await self._http.request(
                "POST", f"{API}/bot{self._token}/{method}", json_body=payload or {}, timeout=timeout
            )
        except HttpError as exc:
            raise TelegramError(self._hide(str(exc))) from None
        data = response.data
        if not isinstance(data, dict) or not data.get("ok"):
            detail = data.get("description") if isinstance(data, dict) else f"HTTP {response.status}"
            raise TelegramError(self._hide(f"{detail} ({response.status})"))
        return data.get("result")

    def _hide(self, text: str) -> str:
        return text.replace(self._token, "***")


# --- chats vinculados ---------------------------------------------------------------------
class Chats:
    """Los chats que pueden usar el bot (``telegram_chats.json``, 600) y el código pendiente."""

    def __init__(self, path: Path, code_path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self.code_path = code_path
        self._clock = clock

    def all(self) -> dict[int, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {int(c["id"]): str(c.get("name", "")) for c in data}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def allowed(self, chat: int) -> bool:
        return chat in self.all()

    def add(self, chat: int, name: str) -> None:
        chats = self.all() | {chat: name}
        _write_private(self.path, json.dumps([{"id": c, "name": n} for c, n in chats.items()], ensure_ascii=False))

    def new_code(self) -> str:
        code = f"{secrets.randbelow(1_000_000):06d}"
        _write_private(self.code_path, json.dumps({"code": code, "until": self._clock() + CODE_MINUTES * 60}))
        return code

    def try_pair(self, chat: int, name: str, text: str) -> bool:
        """True si ``text`` es el código pendiente (y no ha vencido): el chat queda vinculado."""
        try:
            pending = json.loads(self.code_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if self._clock() > float(pending.get("until", 0)):
            self.code_path.unlink(missing_ok=True)
            return False
        if not secrets.compare_digest(text.strip(), str(pending.get("code", ""))):
            return False
        self.add(chat, name)
        self.code_path.unlink(missing_ok=True)
        return True


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def chat_name(chat: dict[str, Any]) -> str:
    return str(chat.get("title") or " ".join(filter(None, (chat.get("first_name"), chat.get("last_name")))) or chat.get("id"))


# --- el bot ---------------------------------------------------------------------------------
class ShoppingBot:
    def __init__(
        self,
        api: TelegramApi,
        shopping: ShoppingList,
        chats: Chats,
        matcher: Matcher,
        on_change: Callable[[], None] = lambda: None,
    ) -> None:
        self.api = api
        self.shopping = shopping
        self.chats = chats
        self._matcher = matcher
        self._skill = ShoppingSkill(shopping)
        self._on_change = on_change

    async def run(self) -> None:
        """Escucha a Telegram (long polling) hasta que se cancele; sin red, reintenta con calma."""
        offset, wait = None, 5.0
        while True:
            try:
                updates = await self.api.call(
                    "getUpdates",
                    {"timeout": POLL_SECONDS, "offset": offset, "allowed_updates": ["message", "callback_query"]},
                    timeout=POLL_SECONDS + 10,
                )
                wait = 5.0
            except TelegramError as exc:
                log.warning("Telegram: %s (reintento en %.0f s)", exc, wait)
                await asyncio.sleep(wait)
                wait = min(wait * 2, 300.0)
                continue
            for update in updates or []:
                offset = update["update_id"] + 1
                try:
                    await self.handle(update)
                except TelegramError as exc:
                    log.warning("Telegram: %s", exc)

    async def handle(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            await self._on_button(update["callback_query"])
            return
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id, text = chat.get("id"), (message.get("text") or "").strip()
        if chat_id is None or not text:
            return
        if not self.chats.allowed(chat_id):
            if self.chats.try_pair(chat_id, chat_name(chat), text):
                log.info("Telegram: chat vinculado (%s)", chat_name(chat))
                await self._send(chat_id, "¡Listo! Este chat ya puede usar la lista del súper de la cocina.\n\n" + HELP)
            else:
                await self._send(chat_id, NOT_LINKED)
            return
        reply, buttons = await self.answer(text)
        await self._send(chat_id, reply, buttons)

    async def answer(self, text: str) -> tuple[str, list[list[dict[str, str]]] | None]:
        """Qué contestar a un mensaje de un chat vinculado (y los botones, si van)."""
        command = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        if command in ("/start", "/ayuda", "/help"):
            return HELP, None
        if command == "/lista":
            return self._list()
        intent = self._matcher.match(text)
        if intent is None and _REMOVE.match(text):
            # Aquí todo es de la lista: «quita la leche» basta, sin «de la lista».
            intent = self._matcher.match(f"{text} de la lista")
        if intent is not None and intent.domain == "shopping":
            if intent.name == "shopping.list":
                return self._list()
            before = list(self.shopping.items)
            speech = (await self._skill.handle(intent)).speech
            if self.shopping.items != before:
                self._on_change()
            return speech, None
        # Lo demás es lo que falta: una cosa por renglón o separadas con comas o «y».
        items = [item for line in text.splitlines() for item in split_items(line.strip("-•* "))]
        added, present = self.shopping.add(items)
        if added:
            self._on_change()
        parts = []
        if added:
            parts.append(f"Agregué {join_words(added)}.")
        if present:
            parts.append(f"{join_words(present).capitalize()} ya {'estaba' if len(present) == 1 else 'estaban'}.")
        return " ".join(parts) or "¿Qué agrego a la lista?", None

    def _list(self) -> tuple[str, list[list[dict[str, str]]] | None]:
        items = self.shopping.items
        if not items:
            return "La lista del súper está vacía.", None
        buttons = [[{"text": f"✓ {item}", "callback_data": f"q:{item_key(item)}"[:64]}] for item in items]
        buttons.append([{"text": "Vaciar la lista", "callback_data": "vaciar"}])
        count = f"{len(items)} {'cosa' if len(items) == 1 else 'cosas'}"
        return f"Lista del súper ({count}). Toca lo que ya compraste:", buttons

    async def _on_button(self, query: dict[str, Any]) -> None:
        message = query.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        data = str(query.get("data") or "")
        if chat_id is None or not self.chats.allowed(chat_id):
            await self.api.call("answerCallbackQuery", {"callback_query_id": query["id"], "text": NOT_LINKED})
            return
        notice = ""
        if data.startswith("q:"):
            key = data[2:]
            found = next((item for item in self.shopping.items if item_key(item)[:62] == key), None)
            if found and self.shopping.remove(found):
                notice = f"Quité {found}"
                self._on_change()
        elif data == "vaciar":
            await self._edit(chat_id, message, "¿Vaciar toda la lista?", [[
                {"text": "Sí, vaciar", "callback_data": "vaciar:si"},
                {"text": "No", "callback_data": "lista"},
            ]])
            await self.api.call("answerCallbackQuery", {"callback_query_id": query["id"]})
            return
        elif data == "vaciar:si":
            if self.shopping.clear():
                notice = "Lista vacía"
                self._on_change()
        text, buttons = self._list()
        await self._edit(chat_id, message, text, buttons)
        await self.api.call("answerCallbackQuery", {"callback_query_id": query["id"], "text": notice})

    async def _send(self, chat_id: int, text: str, buttons: list[list[dict[str, str]]] | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        await self.api.call("sendMessage", payload)

    async def _edit(self, chat_id: int, message: dict[str, Any], text: str, buttons) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "message_id": message.get("message_id"), "text": text}
        payload["reply_markup"] = {"inline_keyboard": buttons or []}
        try:
            await self.api.call("editMessageText", payload)
        except TelegramError as exc:
            if "not modified" not in str(exc):  # tocar dos veces el mismo botón
                raise


# --- voxa telegram-vincular -----------------------------------------------------------------
async def link_chat(api: TelegramApi, chats: Chats, *, say: Callable[[str], None] = print,
                    minutes: float = CODE_MINUTES) -> bool:
    """Muestra un código y espera a que alguien se lo mande al bot; ese chat queda vinculado.

    Si VOXA está corriendo, ella atiende el mensaje (Telegram no deja leer a dos a la vez): aquí
    solo se espera a que el chat aparezca en la lista.
    """
    me = await api.call("getMe")
    code = chats.new_code()
    before = set(chats.all())
    say(f"En Telegram, busca @{me.get('username')} y mándale este código: {code}")
    say(f"(vence en {minutes:.0f} minutos; se puede repetir para cada persona o un grupo de la familia)")
    deadline = time.monotonic() + minutes * 60
    offset, service_running = None, False
    while time.monotonic() < deadline:
        if set(chats.all()) - before:
            return True
        if service_running:
            await asyncio.sleep(2)
            continue
        try:
            updates = await api.call("getUpdates", {"timeout": 20, "offset": offset, "allowed_updates": ["message"]},
                                     timeout=30)
        except TelegramError as exc:
            if "409" in str(exc) or "terminated by other" in str(exc):
                service_running = True  # VOXA ya está escuchando: ella vincula
                continue
            raise
        for update in updates or []:
            offset = update["update_id"] + 1
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            if chat.get("id") is not None and chats.try_pair(chat["id"], chat_name(chat), message.get("text") or ""):
                await api.call("sendMessage", {"chat_id": chat["id"], "text": "¡Listo! Este chat ya puede usar la lista del súper de la cocina.\n\n" + HELP})
        if offset is not None:
            await api.call("getUpdates", {"offset": offset, "timeout": 0})  # que VOXA no los vuelva a leer
    return bool(set(chats.all()) - before)

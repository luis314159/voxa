"""Modelos de lenguaje comerciales para lo que las reglas de VOXA no entienden.

Dos formas de hablar con ellos cubren casi todo el mercado:

- **Claude** (Anthropic), con su SDK oficial ``anthropic``.
- **OpenAI** y todo lo que imita su API: Azure OpenAI, Gemini, Groq, Mistral, DeepSeek,
  OpenRouter u Ollama en la red de la casa, con el SDK ``openai``.

Los SDK son opcionales (``pip install 'voxa[ia]'``) y solo se importan si la IA está activada.
A la IA solo le llega el texto de la frase (nunca audio) y las últimas preguntas de esa plática.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from voxa.config import AiConfig

log = logging.getLogger(__name__)

PROVIDERS = ("claude", "openai", "azure", "compatible")
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
_KEY_ENV = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "azure": "AZURE_OPENAI_API_KEY"}

# USD por millón de tokens (entrada, salida). Para otros modelos: price_input / price_output en [ai].
KNOWN_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
}
WEB_SEARCH_USD = 0.01  # Claude cobra 10 USD por cada mil búsquedas

# Modelos con el respaldo del servidor si el modelo declina responder (fallbacks="default").
_SERVER_FALLBACK = frozenset({"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"})
# Modelos con la búsqueda web nueva (filtra resultados antes de leerlos); el resto usa la básica.
_DYNAMIC_SEARCH = frozenset(
    {"claude-opus-5-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
     "claude-sonnet-5-5", "claude-sonnet-5", "claude-sonnet-4-6"}
)

COMMAND_TOOL = "orden_voxa"
COMMAND_DESCRIPTION = (
    "Hace que VOXA ejecute una de sus funciones. Úsala cuando la persona quiera que VOXA HAGA algo que ya "
    "sabe hacer: música, pausa, volumen, temporizadores, recordatorios, alarmas, lista del súper, videos, "
    "hora o clima. Escribe la orden como una frase corta en español, como se la diría una persona a VOXA."
)
COMMAND_SCHEMA = {
    "type": "object",
    "properties": {
        "frase": {
            "type": "string",
            "description": "La orden, p. ej. «pon un temporizador de 10 minutos para el arroz».",
        }
    },
    "required": ["frase"],
    "additionalProperties": False,
}


class AiError(Exception):
    """La IA no respondió. El mensaje es para el registro y el diagnóstico."""


class AiUnavailable(AiError):
    """Sin red, tiempo agotado, servicio caído o límite de peticiones: vale la pena reintentar luego."""


class AiSetupError(AiError):
    """Llave inválida, modelo inexistente o configuración incompleta: hay que corregir algo."""


@dataclass
class AiAnswer:
    text: str = ""
    commands: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0
    refused: bool = False


class ChatModel(Protocol):
    name: str
    """Para el diagnóstico: «Claude · claude-opus-5-5»."""
    model: str

    async def ask(self, system: str, messages: list[dict[str, str]]) -> AiAnswer: ...


def _command(raw: Any) -> str | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if isinstance(raw, dict) and isinstance(raw.get("frase"), str) and raw["frase"].strip():
        return raw["frase"].strip()
    return None


class ClaudeChat:
    def __init__(
        self, client: Any, model: str = DEFAULT_CLAUDE_MODEL, *, effort: str = "low",
        web_search: bool = False, max_tokens: int = 2048,
    ) -> None:
        self._client = client
        self.model = model
        self.name = f"Claude · {model}"
        self._effort = effort
        self._web_search = web_search
        self._max_tokens = max_tokens

    def _tools(self) -> list[dict]:
        tools: list[dict] = [{"name": COMMAND_TOOL, "description": COMMAND_DESCRIPTION, "input_schema": COMMAND_SCHEMA}]
        if self._web_search:
            kind = "web_search_20260209" if self.model in _DYNAMIC_SEARCH else "web_search_20250305"
            tools.append({"type": kind, "name": "web_search", "max_uses": 2})
        return tools

    async def ask(self, system: str, messages: list[dict[str, str]]) -> AiAnswer:
        import anthropic

        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": system,
            "tools": self._tools(),
        }
        if self._effort:
            params["output_config"] = {"effort": self._effort}
        conversation: list[dict[str, Any]] = list(messages)
        answer = AiAnswer()
        try:
            # La búsqueda web puede pausar el turno (pause_turn): se continúa con lo que ya hizo.
            for _ in range(3):
                if self.model in _SERVER_FALLBACK:
                    response = await self._client.beta.messages.create(
                        **params, messages=conversation,
                        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                    )
                else:
                    response = await self._client.messages.create(**params, messages=conversation)
                _add_claude(answer, response)
                if response.stop_reason != "pause_turn":
                    break
                conversation = [*conversation, {"role": "assistant", "content": [b.to_dict() for b in response.content]}]
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise AiSetupError(f"Claude rechazó la llave ({exc.status_code})") from exc
        except anthropic.NotFoundError as exc:
            raise AiSetupError(f"Claude no conoce el modelo «{self.model}»") from exc
        except anthropic.BadRequestError as exc:
            raise AiSetupError(f"Claude rechazó la petición: {exc.message}") from exc
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as exc:
            raise AiUnavailable(f"Claude no respondió: {type(exc).__name__}") from exc
        except anthropic.APIStatusError as exc:
            raise AiUnavailable(f"Claude respondió {exc.status_code}") from exc
        return answer


def _add_claude(answer: AiAnswer, response: Any) -> None:
    parts = [answer.text] if answer.text else []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
        elif block.type == "tool_use" and block.name == COMMAND_TOOL:
            if (phrase := _command(block.input)) is not None:
                answer.commands.append(phrase)
    answer.text = "".join(parts).strip()
    answer.refused = answer.refused or response.stop_reason == "refusal"
    usage = response.usage
    answer.input_tokens += (usage.input_tokens or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0) + (
        getattr(usage, "cache_creation_input_tokens", 0) or 0
    )
    answer.output_tokens += usage.output_tokens or 0
    server = getattr(usage, "server_tool_use", None)
    answer.searches += (getattr(server, "web_search_requests", 0) or 0) if server else 0


class OpenAiChat:
    """Chat Completions: OpenAI, Azure OpenAI (API v1) y los servicios compatibles."""

    def __init__(
        self, client: Any, model: str, *, label: str = "OpenAI", reasoning_effort: str = "",
        max_tokens: int = 2048, modern_limit: bool = True,
    ) -> None:
        self._client = client
        self.model = model
        self.name = f"{label} · {model}"
        self._reasoning_effort = reasoning_effort
        self._max_tokens = max_tokens
        # OpenAI y Azure piden max_completion_tokens (los modelos que razonan rechazan max_tokens);
        # muchos servicios compatibles solo conocen max_tokens.
        self._limit_param = "max_completion_tokens" if modern_limit else "max_tokens"

    async def ask(self, system: str, messages: list[dict[str, str]]) -> AiAnswer:
        import openai

        params: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "tools": [{
                "type": "function",
                "function": {"name": COMMAND_TOOL, "description": COMMAND_DESCRIPTION, "parameters": COMMAND_SCHEMA},
            }],
            self._limit_param: self._max_tokens,
        }
        if self._reasoning_effort:
            params["reasoning_effort"] = self._reasoning_effort
        try:
            response = await self._client.chat.completions.create(**params)
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise AiSetupError(f"{self.name} rechazó la llave ({exc.status_code})") from exc
        except openai.NotFoundError as exc:
            raise AiSetupError(f"{self.name}: no existe el modelo o la dirección") from exc
        except openai.BadRequestError as exc:
            raise AiSetupError(f"{self.name} rechazó la petición: {exc.message}") from exc
        except (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError) as exc:
            raise AiUnavailable(f"{self.name} no respondió: {type(exc).__name__}") from exc
        except openai.APIStatusError as exc:
            raise AiUnavailable(f"{self.name} respondió {exc.status_code}") from exc

        answer = AiAnswer()
        if not response.choices:
            return answer
        choice = response.choices[0]
        answer.text = (choice.message.content or "").strip()
        for call in choice.message.tool_calls or []:
            function = getattr(call, "function", None)
            if function is not None and function.name == COMMAND_TOOL:
                if (phrase := _command(function.arguments)) is not None:
                    answer.commands.append(phrase)
        answer.refused = choice.finish_reason == "content_filter"
        if response.usage is not None:
            answer.input_tokens = response.usage.prompt_tokens or 0
            answer.output_tokens = response.usage.completion_tokens or 0
        return answer


def read_key(config: AiConfig, key_path: Path) -> str | None:
    """La llave: de la variable de entorno si está, si no del archivo de ``voxa ia-clave``."""
    env = config.key_env or _KEY_ENV.get(config.provider, "")
    if env and os.environ.get(env, "").strip():
        return os.environ[env].strip()
    try:
        key = key_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return key or None


def save_key(key_path: Path, key: str) -> None:
    """Guarda la llave solo legible por el usuario (600), como el token de Spotify."""
    key_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key.strip() + "\n")
    os.chmod(key_path, 0o600)


def needs_key(config: AiConfig) -> bool:
    # Un servicio compatible en la red de la casa (Ollama, LM Studio) puede no pedir llave.
    return config.provider != "compatible"


def build_chat(config: AiConfig, key: str | None) -> ChatModel:
    """El cliente del proveedor configurado. ``AiSetupError`` dice qué falta."""
    provider = config.provider.lower()
    if provider not in PROVIDERS:
        raise AiSetupError(f"Proveedor de IA desconocido: «{config.provider}» (usa {', '.join(PROVIDERS)}).")
    if not key and needs_key(config):
        raise AiSetupError("Falta la llave de la IA: corre «voxa ia-clave».")
    timeout = config.timeout_seconds
    if provider == "claude":
        try:
            import anthropic
        except ImportError as exc:
            raise AiSetupError("Falta el SDK de Anthropic: pipx inject voxa anthropic") from exc
        client = anthropic.AsyncAnthropic(api_key=key, timeout=timeout, max_retries=1)
        effort = "low" if config.effort == "" else config.effort.replace("ninguno", "")
        return ClaudeChat(client, config.model or DEFAULT_CLAUDE_MODEL, effort=effort, web_search=config.web_search)

    try:
        import openai
    except ImportError as exc:
        raise AiSetupError("Falta el SDK de OpenAI: pipx inject voxa openai") from exc
    if not config.model:
        what = "el nombre del deployment" if provider == "azure" else "el modelo"
        raise AiSetupError(f"Falta {what} en model de [ai].")
    if provider == "openai":
        client = openai.AsyncOpenAI(api_key=key, base_url=config.endpoint or None, timeout=timeout, max_retries=1)
        return OpenAiChat(client, config.model, reasoning_effort=config.effort)
    if not config.endpoint:
        example = "https://RECURSO.openai.azure.com" if provider == "azure" else "https://api.groq.com/openai/v1"
        raise AiSetupError(f"Falta endpoint en [ai] (p. ej. {example}).")
    if provider == "azure":
        # API v1 de Azure OpenAI: el cliente normal de OpenAI, sin api-version; model = deployment.
        base = config.endpoint.rstrip("/")
        if not base.endswith("/openai/v1"):
            base += "/openai/v1"
        client = openai.AsyncOpenAI(api_key=key, base_url=base + "/", timeout=timeout, max_retries=1)
        return OpenAiChat(client, config.model, label="Azure OpenAI", reasoning_effort=config.effort)
    client = openai.AsyncOpenAI(api_key=key or "sin-llave", base_url=config.endpoint, timeout=timeout, max_retries=1)
    return OpenAiChat(client, config.model, label="IA", reasoning_effort=config.effort, modern_limit=False)


def prices_for(config: AiConfig, model: str) -> tuple[float, float] | None:
    if config.price_input or config.price_output:
        return config.price_input, config.price_output
    return KNOWN_PRICES.get(model)


def cost_usd(answer: AiAnswer, prices: tuple[float, float] | None) -> float:
    tokens = 0.0
    if prices is not None:
        tokens = (answer.input_tokens * prices[0] + answer.output_tokens * prices[1]) / 1_000_000
    return tokens + answer.searches * WEB_SEARCH_USD

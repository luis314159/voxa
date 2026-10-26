import json
import re
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from voxa.app import build_app
from voxa.config import AiConfig, Config
from voxa.nlu.matcher import load_matcher
from voxa.service import Service
from voxa.services.ai import (
    AiAnswer,
    AiSetupError,
    AiUnavailable,
    ClaudeChat,
    OpenAiChat,
    build_chat,
    cost_usd,
    prices_for,
    read_key,
    save_key,
)
from voxa.skills.ai import (
    BUDGET_REACHED,
    DAILY_LIMIT,
    SETUP_PROBLEM,
    SYSTEM_PROMPT,
    UNAVAILABLE,
    AiFallback,
    context_line,
    speakable,
    worth_asking,
)
from voxa.state.ai_usage import AiUsage

NOW = datetime(2026, 10, 25, 19, 40)


class FakeChat:
    name = "Prueba · modelo"
    model = "claude-haiku-5-5"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked: list[list[dict]] = []

    async def ask(self, system, messages, tools=(), *, max_tokens=2048):
        self.tools = tools
        self.asked.append(messages)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def fallback(chat, *, usage=None, run_command=None, clock=None):
    async def nothing(_):
        return None

    return AiFallback(
        chat,
        usage or AiUsage(None, 5.0, 60),
        run_command=run_command or nothing,
        prices=(0.10, 0.50),
        now=lambda: NOW,
        clock=clock or Clock(),
    )


# --- texto ----------------------------------------------------------------------
def test_only_real_questions_are_sent():
    assert worth_asking("¿con qué sustituyo el huevo?")
    assert worth_asking("quién ganó")
    assert not worth_asking("eh")
    assert not worth_asking("a")
    assert not worth_asking("Subtítulos realizados por la comunidad de Amara.org")
    assert not worth_asking("¡Gracias por ver el video!")


def test_answers_lose_formatting_and_stay_short():
    assert speakable("**Unos 6 minutos** 🥚 en agua hirviendo.") == "Unos 6 minutos en agua hirviendo."
    assert speakable("Necesitas:\n- 2 tazas de harina\n- 1 huevo") == "Necesitas: 2 tazas de harina 1 huevo"
    assert speakable("Mira [esta receta](https://x.mx/r) o https://y.mx") == "Mira esta receta o"
    long = "Primera frase corta. " + "palabra " * 50 + "fin. Tercera frase."
    assert speakable(long, max_words=10) == "Primera frase corta."
    assert speakable("uno dos tres cuatro cinco seis", max_words=3) == "uno dos tres."


def test_context_has_date_and_time():
    assert context_line(NOW) == "[Ahora es domingo 25 de octubre de 2026, las 7 y 40 de la tarde.]"
    assert context_line(NOW, "Vivimos en Monterrey").endswith("[Vivimos en Monterrey]")


def test_examples_in_the_prompt_are_real_voxa_commands():
    matcher = load_matcher()
    examples = re.findall(r"«([^»]+)»", SYSTEM_PROMPT.split("por ejemplo:")[1])
    assert len(examples) >= 5
    for example in examples:
        assert matcher.match(example) is not None, example


# --- gasto ----------------------------------------------------------------------
def test_budget_and_daily_limit(tmp_path):
    store = tmp_path / "uso.json"
    usage = AiUsage(store, monthly_budget_usd=0.01, daily_questions=2)
    assert usage.blocked(NOW) is None
    usage.record(0.004, NOW)
    usage.record(0.004, NOW)
    assert usage.blocked(NOW) == "day"
    assert usage.blocked(datetime(2026, 10, 26, 8)) is None
    usage.record(0.004, datetime(2026, 10, 26, 8))
    assert usage.blocked(datetime(2026, 10, 26, 9)) == "month"
    assert usage.blocked(datetime(2026, 11, 1, 9)) is None  # mes nuevo
    again = AiUsage(store, 0.01, 2)
    assert again.month == "2026-10" and again.month_questions == 3
    assert again.summary() == "0.01 USD de 0.01 este mes · 3 preguntas"


def test_cost_from_tokens_and_searches():
    answer = AiAnswer(input_tokens=1_000_000, output_tokens=100_000, searches=2)
    assert cost_usd(answer, (4.0, 20.0)) == pytest.approx(4.0 + 2.0 + 0.02)
    assert cost_usd(answer, None) == pytest.approx(0.02)
    assert prices_for(AiConfig(), "claude-opus-5-5") == (4.0, 20.0)
    assert prices_for(AiConfig(price_input=0.4, price_output=1.6), "gpt-x") == (0.4, 1.6)
    assert prices_for(AiConfig(), "modelo-raro") is None


# --- el respaldo ---------------------------------------------------------------
async def test_question_is_answered_and_charged():
    chat = FakeChat(AiAnswer("Unos **6 minutos** en agua hirviendo.", input_tokens=1000, output_tokens=100))
    ai = fallback(chat)
    response = await ai("cuánto se cuece un huevo tibio")
    assert response.speech == "Unos 6 minutos en agua hirviendo."
    assert ai.usage.month_questions == 1
    assert ai.usage.month_usd == pytest.approx((1000 * 0.10 + 100 * 0.50) / 1e6)
    question = chat.asked[0][-1]["content"]
    assert question.startswith("[Ahora es domingo") and question.endswith("cuánto se cuece un huevo tibio")


async def test_noise_is_not_sent():
    chat = FakeChat()
    assert await fallback(chat)("eh") is None
    assert chat.asked == []


async def test_short_memory_for_follow_ups():
    clock = Clock()
    chat = FakeChat(AiAnswer("Pozole rojo: maíz, carne de cerdo y chile guajillo."), AiAnswer("Para 4, un kilo."), AiAnswer("Ok."))
    ai = fallback(chat, clock=clock)
    await ai("cómo se hace el pozole")
    clock.t = 60
    await ai("y para cuatro personas")
    assert [m["role"] for m in chat.asked[1]] == ["user", "assistant", "user"]
    assert chat.asked[1][1]["content"] == "Pozole rojo: maíz, carne de cerdo y chile guajillo."
    clock.t = 60 + 600  # diez minutos después ya es otra plática
    await ai("qué es el epazote")
    assert len(chat.asked[2]) == 1


async def test_budget_reached_does_not_call_the_ai():
    usage = AiUsage(None, monthly_budget_usd=1.0, daily_questions=0)
    usage.record(1.5, NOW)
    chat = FakeChat()
    assert await fallback(chat, usage=usage)("qué es el epazote") is BUDGET_REACHED
    usage = AiUsage(None, monthly_budget_usd=0, daily_questions=1)
    usage.record(0.0, NOW)
    assert await fallback(chat, usage=usage)("qué es el epazote") is DAILY_LIMIT
    assert chat.asked == []


async def test_errors_are_spoken_and_setup_problems_reported():
    chat = FakeChat(AiUnavailable("sin red"), AiSetupError("llave inválida"), AiAnswer("Sí."))
    ai = fallback(chat)
    problems, cleared = [], []
    ai.on_setup_error, ai.on_ok = problems.append, lambda: cleared.append(True)
    assert await ai("qué es el epazote") is UNAVAILABLE
    assert await ai("qué es el epazote") is SETUP_PROBLEM
    assert problems == ["llave inválida"]
    assert (await ai("qué es el epazote")).speech == "Sí."
    assert cleared == [True]
    assert ai.usage.month_questions == 1  # solo se cobra lo que respondió


async def test_ai_turns_free_speech_into_voxa_commands():
    app = build_app(Config(), simulated=True)
    chat = FakeChat(
        AiAnswer("Claro.", commands=["pon un temporizador de 12 minutos para la pasta"]),
        AiAnswer("", commands=["agrega jitomate y cebolla a la lista", "bájale al volumen"]),
        AiAnswer("No sé hacer eso, pero te ayudo con otra cosa.", commands=["prende el horno"]),
    )
    ai = fallback(chat, run_command=app.assistant.try_command)
    app.assistant.fallback = ai

    response = await app.assistant.handle_text("oye échale un ojo a la pasta unos doce minutitos")
    assert [t.label for t in app.timers.active] == ["la pasta"]
    assert "12 minutos" in response.speech

    response = await app.assistant.handle_text("para el pico de gallo me falta jitomate y cebolla y está muy fuerte")
    assert app.shopping.items == ["jitomate", "cebolla"]
    assert response.speech.startswith("Agregué jitomate y cebolla a la lista.")

    response = await app.assistant.handle_text("precalienta el horno a doscientos")
    assert response.speech == "No sé hacer eso, pero te ayudo con otra cosa."


async def test_ai_problems_show_up_in_health_and_help(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = Config(ai=AiConfig(enabled=True, provider="openai", model="gpt-x"), config_dir=tmp_path, state_dir=tmp_path)
    service = Service.create(build_app(config, simulated=True))
    problem = next(p for p in service.health.problems if p.id == "ia")
    assert "voxa ia-clave" in problem.detail
    assert (await service.handle_text("estás bien")).speech == "Aquí estoy, pero no puedo usar la IA."
    assert "IA" not in (await service.handle_text("qué puedes hacer")).speech


# --- llaves y proveedores --------------------------------------------------------
def test_key_comes_from_env_or_private_file(tmp_path, monkeypatch):
    path = tmp_path / "ia_clave"
    config = AiConfig(provider="claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert read_key(config, path) is None
    save_key(path, "  sk-de-archivo \n")
    assert read_key(config, path) == "sk-de-archivo"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-de-entorno")
    assert read_key(config, path) == "sk-de-entorno"
    monkeypatch.setenv("MI_LLAVE", "sk-propia")
    assert read_key(AiConfig(key_env="MI_LLAVE"), path) == "sk-propia"


def test_build_chat_says_what_is_missing():
    with pytest.raises(AiSetupError, match="ia-clave"):
        build_chat(AiConfig(provider="claude"), None)
    with pytest.raises(AiSetupError, match="desconocido"):
        build_chat(AiConfig(provider="watson"), "k")
    pytest.importorskip("openai")
    with pytest.raises(AiSetupError, match="deployment"):
        build_chat(AiConfig(provider="azure", endpoint="https://casa.openai.azure.com"), "k")
    with pytest.raises(AiSetupError, match="endpoint"):
        build_chat(AiConfig(provider="azure", model="gpt-cocina"), "k")
    azure = build_chat(AiConfig(provider="azure", model="gpt-cocina", endpoint="https://casa.openai.azure.com/"), "k")
    assert str(azure._client.base_url) == "https://casa.openai.azure.com/openai/v1/"
    local = build_chat(AiConfig(provider="compatible", model="llama3", endpoint="http://192.168.1.5:11434/v1"), None)
    assert local.name == "IA · llama3"


# --- los SDK de verdad, contra un servidor local ------------------------------------
class FakeApi:
    """Un servidor HTTP local que contesta como Claude u OpenAI y guarda lo que recibió."""

    def __init__(self, status=200, body=None):
        self.status, self.body = status, body or {}
        self.requests: list[tuple[str, dict, dict]] = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                api.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}, json.loads(self.rfile.read(length) or b"{}")))
                payload = json.dumps(api.body).encode()
                self.send_response(api.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_api():
    servers = []

    def make(status=200, body=None):
        servers.append(FakeApi(status, body))
        return servers[-1]

    yield make
    for server in servers:
        server.close()


CLAUDE_REPLY = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
    "content": [
        {"type": "thinking", "thinking": "", "signature": "x"},
        {"type": "text", "text": "Va."},
        {"type": "tool_use", "id": "toolu_1", "name": "orden_voxa", "input": {"frase": "pon un temporizador de 6 minutos"}},
    ],
    "stop_reason": "tool_use", "stop_sequence": None,
    "usage": {"input_tokens": 500, "output_tokens": 40, "server_tool_use": {"web_search_requests": 1}},
}


async def test_claude_request_and_answer(fake_api):
    anthropic = pytest.importorskip("anthropic")
    api = fake_api(body=CLAUDE_REPLY)
    client = anthropic.AsyncAnthropic(api_key="sk-prueba", base_url=api.url, max_retries=0)
    chat = ClaudeChat(client, "claude-opus-5-5", effort="low", web_search=True)
    answer = await chat.ask("sistema", [{"role": "user", "content": "hola"}])
    assert answer.text == "Va." and answer.commands == ["pon un temporizador de 6 minutos"]
    assert (answer.input_tokens, answer.output_tokens, answer.searches) == (500, 40, 1)
    path, headers, body = api.requests[0]
    assert path.startswith("/v1/messages")
    assert "sk-prueba" in headers.get("x-api-key", "") + headers.get("authorization", "")
    assert "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert body["fallbacks"] == "default" and body["output_config"] == {"effort": "low"}
    assert body["system"] == "sistema" and body["messages"] == [{"role": "user", "content": "hola"}]
    assert [t.get("type", "custom") for t in body["tools"]] == ["custom", "web_search_20260209"]
    assert "temperature" not in body


async def test_claude_models_without_server_fallback_use_the_plain_endpoint(fake_api):
    anthropic = pytest.importorskip("anthropic")
    api = fake_api(body={**CLAUDE_REPLY, "content": [{"type": "text", "text": "Sí."}], "stop_reason": "end_turn"})
    client = anthropic.AsyncAnthropic(api_key="k", base_url=api.url, max_retries=0)
    answer = await ClaudeChat(client, "claude-haiku-5-5", effort="", web_search=True).ask("s", [])
    assert answer.text == "Sí."
    _, headers, body = api.requests[0]
    assert "anthropic-beta" not in headers and "fallbacks" not in body and "output_config" not in body
    assert body["tools"][1]["type"] == "web_search_20250305"


@pytest.mark.parametrize("status, error", [(401, AiSetupError), (404, AiSetupError), (429, AiUnavailable), (529, AiUnavailable)])
async def test_claude_errors(fake_api, status, error):
    anthropic = pytest.importorskip("anthropic")
    api = fake_api(status, {"type": "error", "error": {"type": "x", "message": "no"}})
    client = anthropic.AsyncAnthropic(api_key="k", base_url=api.url, max_retries=0)
    with pytest.raises(error):
        await ClaudeChat(client, "claude-haiku-5-5").ask("s", [])


OPENAI_REPLY = {
    "id": "c1", "object": "chat.completion", "created": 0, "model": "gpt-x",
    "choices": [{
        "index": 0, "finish_reason": "tool_calls",
        "message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "orden_voxa", "arguments": "{\"frase\": \"pausa\"}"}},
        ]},
    }],
    "usage": {"prompt_tokens": 300, "completion_tokens": 20, "total_tokens": 320},
}


async def test_openai_request_and_answer(fake_api):
    openai = pytest.importorskip("openai")
    api = fake_api(body=OPENAI_REPLY)
    client = openai.AsyncOpenAI(api_key="sk-prueba", base_url=api.url + "/v1", max_retries=0)
    answer = await OpenAiChat(client, "gpt-x", reasoning_effort="minimal").ask("sistema", [{"role": "user", "content": "hola"}])
    assert answer.commands == ["pausa"] and answer.text == ""
    assert (answer.input_tokens, answer.output_tokens) == (300, 20)
    path, headers, body = api.requests[0]
    assert path == "/v1/chat/completions" and headers["authorization"] == "Bearer sk-prueba"
    assert body["messages"][0] == {"role": "system", "content": "sistema"}
    assert body["max_completion_tokens"] == 2048 and body["reasoning_effort"] == "minimal"
    assert body["tools"][0]["function"]["name"] == "orden_voxa"


async def test_azure_and_compatible_services(fake_api):
    pytest.importorskip("openai")
    api = fake_api(body={**OPENAI_REPLY, "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "Hola."}}]})
    azure = build_chat(AiConfig(provider="azure", model="gpt-cocina", endpoint=api.url), "k")
    assert (await azure.ask("s", [])).text == "Hola."
    local = build_chat(AiConfig(provider="compatible", model="llama3", endpoint=api.url + "/v1"), None)
    await local.ask("s", [])
    (azure_path, _, azure_body), (local_path, _, local_body) = api.requests
    assert azure_path == "/openai/v1/chat/completions" and azure_body["model"] == "gpt-cocina"
    assert local_path == "/v1/chat/completions" and local_body["max_tokens"] == 2048 and "max_completion_tokens" not in local_body


@pytest.mark.parametrize("status, error", [(401, AiSetupError), (429, AiUnavailable), (503, AiUnavailable)])
async def test_openai_errors(fake_api, status, error):
    openai = pytest.importorskip("openai")
    api = fake_api(status, {"error": {"message": "no", "type": "x"}})
    client = openai.AsyncOpenAI(api_key="k", base_url=api.url, max_retries=0)
    with pytest.raises(error):
        await OpenAiChat(client, "gpt-x").ask("s", [])

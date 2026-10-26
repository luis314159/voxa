import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

from voxa.audio.clip import Clip
from voxa.audio.devices import SilentOutput
from voxa.audio.sounds import make_sounds
from voxa.core.assistant import Assistant
from voxa.core.speech import SpeechChunker, speech_chunks
from voxa.core.types import Response
from voxa.nlu import load_matcher
from voxa.services.ai import AiAnswer, ClaudeChat, OpenAiChat
from voxa.skills.ai import AiFallback
from voxa.skills.system import SystemSkill
from voxa.state.ai_usage import AiUsage
from voxa.voice import VoiceSession

LONG = (
    "Para el pozole rojo necesitas un kilo de maíz pozolero, un kilo de carne de cerdo, cinco chiles guajillo, "
    "tres chiles anchos, una cebolla, cuatro dientes de ajo, orégano y sal al gusto. Para servir, lechuga, "
    "rábanos y limón. Si quieres, te lo guío paso a paso."
)


# --- trozos -----------------------------------------------------------------------
def test_long_answers_start_with_a_short_chunk():
    assert speech_chunks(LONG) == [
        "Para el pozole rojo necesitas un kilo de maíz pozolero,",
        "un kilo de carne de cerdo, cinco chiles guajillo, tres chiles anchos, una cebolla, cuatro dientes de ajo, "
        "orégano y sal al gusto.",
        "Para servir, lechuga, rábanos y limón.",
        "Si quieres, te lo guío paso a paso.",
    ]
    assert speech_chunks("Son las 7 de la tarde.") == ["Son las 7 de la tarde."]


def test_short_sentences_and_abbreviations_are_not_cut():
    text = "Claro. Son las 7 p. m. y el pozole tarda unas dos horas en total, así que conviene empezar ya. ¡Suerte!"
    assert speech_chunks(text) == [
        "Claro. Son las 7 p. m. y el pozole tarda unas dos horas en total,",
        "así que conviene empezar ya.",
        "¡Suerte!",
    ]


def test_streamed_text_gives_the_same_chunks_as_it_arrives():
    chunker, ready = SpeechChunker(), []
    for n in range(0, len(LONG), 5):
        ready += chunker.feed(LONG[n:n + 5])
        if n < 60:
            assert ready == []  # aún no hay coma tras 5 palabras
    assert ready[0] == "Para el pozole rojo necesitas un kilo de maíz pozolero,"
    assert ready + chunker.flush() == speech_chunks(LONG)


# --- la voz encadena síntesis y audio -------------------------------------------------
class SlowTts:
    def __init__(self, log):
        self.log = log

    def synthesize(self, text):
        self.log.append(("síntesis", text.split()[0]))
        return Clip(np.zeros(10, dtype=np.float32), 22050)


class LoggingOutput(SilentOutput):
    def __init__(self, log):
        super().__init__()
        self.log = log

    async def play(self, clip):
        self.log.append(("suena", len(self.played)))
        await asyncio.sleep(0.01)
        await super().play(clip)


class NoDucking:
    async def duck(self):
        pass

    async def restore(self):
        pass


def voice_session(log):
    assistant = Assistant(load_matcher(), {"system": SystemSkill()})
    return VoiceSession(assistant, None, SlowTts(log), LoggingOutput(log), make_sounds(), NoDucking())


async def test_long_answers_play_while_the_rest_is_synthesized():
    log = []
    voice = voice_session(log)
    await voice.say(Response(LONG))
    assert len(voice._output.played) == 4
    # el primer trozo suena antes de que se sintetice el último
    assert log.index(("suena", 0)) < log.index(("síntesis", "Si"))


async def test_already_spoken_answers_are_not_repeated_but_can_be_repeated_on_request():
    log = []
    voice = voice_session(log)
    voice.assistant.last_response = Response("Unos 6 minutos.", spoken=True)
    await voice.say(voice.assistant.last_response)
    assert voice._output.played == []
    again = await voice.assistant.handle_text("repite")
    assert again == Response("Unos 6 minutos.")
    await voice.say(again)
    assert len(voice._output.played) == 1


# --- la IA transmite --------------------------------------------------------------------
class StreamingChat:
    name, model = "Prueba", "claude-haiku-5-5"

    def __init__(self, text, commands=()):
        self.text, self.commands = text, list(commands)

    async def ask(self, system, messages, tools=(), *, max_tokens=2048, on_text=None):
        for n in range(0, len(self.text), 9):
            on_text(self.text[n:n + 9])
            await asyncio.sleep(0)
        return AiAnswer(self.text, commands=self.commands, input_tokens=10, output_tokens=10)


def streaming_fallback(chat, run_command=None):
    async def nothing(_):
        return None

    ai = AiFallback(chat, AiUsage(None, 5.0, 60), run_command=run_command or nothing, prices=(1.0, 1.0))
    heard, said = [], []

    async def speak(chunks, text):
        heard.append(text)
        async for chunk in chunks:
            said.append(chunk)

    ai.speak = speak
    return ai, heard, said


async def test_ai_answers_are_spoken_as_they_arrive():
    ai, heard, said = streaming_fallback(StreamingChat("**Unos 6 minutos** en agua hirviendo. Luego pásalos a agua fría y listo."))
    response = await ai("cuánto se cuece un huevo tibio")
    assert heard == ["cuánto se cuece un huevo tibio"]
    assert said == ["Unos 6 minutos en agua hirviendo.", "Luego pásalos a agua fría y listo."]
    assert response == Response("Unos 6 minutos en agua hirviendo. Luego pásalos a agua fría y listo.", spoken=True)


async def test_spoken_ai_answers_stop_at_the_word_limit():
    sentence = "Esta es una frase de prueba con diez palabras en total. "
    ai, _, said = streaming_fallback(StreamingChat(sentence * 20))
    response = await ai("cuéntame algo largo")
    assert sum(len(s.split()) for s in said) == 88  # 8 frases de 11: la novena pasaría de 90
    assert response.spoken


async def test_commands_from_a_streamed_answer_are_confirmed_by_voxa():
    async def run(phrase):
        return Response("Pausé la música.") if phrase == "pausa" else None

    ai, _, said = streaming_fallback(StreamingChat("", commands=["pausa"]), run)
    assert await ai("ya no quiero oír eso un rato") == Response("Pausé la música.")
    assert said == []


# --- los SDK de verdad transmitiendo, contra un servidor local (SSE) ------------------------
class SseApi:
    def __init__(self, events):
        self.events, self.bodies = events, []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                api.bodies.append(json.loads(self.rfile.read(length) or b"{}"))
                payload = "".join(api.events).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
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


def sse(name, data):
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


async def test_claude_streams_text_and_tools():
    anthropic = pytest.importorskip("anthropic")
    events = [
        sse("message_start", {"type": "message_start", "message": {
            "id": "m", "type": "message", "role": "assistant", "model": "claude-haiku-5-5", "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 50, "output_tokens": 1}}}),
        sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Unos 6 "}}),
        sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "minutos."}}),
        sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
        sse("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {
            "type": "tool_use", "id": "t1", "name": "orden_voxa", "input": {}}}),
        sse("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {
            "type": "input_json_delta", "partial_json": "{\"frase\": \"pon un temporizador de 6 minutos\"}"}}),
        sse("content_block_stop", {"type": "content_block_stop", "index": 1}),
        sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                               "usage": {"output_tokens": 30}}),
        sse("message_stop", {"type": "message_stop"}),
    ]
    api = SseApi(events)
    try:
        client = anthropic.AsyncAnthropic(api_key="k", base_url=api.url, max_retries=0)
        pieces = []
        answer = await ClaudeChat(client, "claude-haiku-5-5").ask("s", [], on_text=pieces.append)
    finally:
        api.close()
    assert pieces == ["Unos 6 ", "minutos."]
    assert answer.text == "Unos 6 minutos." and answer.commands == ["pon un temporizador de 6 minutos"]
    assert (answer.input_tokens, answer.output_tokens) == (50, 30)
    assert api.bodies[0]["stream"] is True


async def test_openai_streams_text_and_tools():
    openai = pytest.importorskip("openai")

    def chunk(delta=None, finish=None, usage=None):
        choices = [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": finish}]
        body = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "gpt-x", "choices": choices}
        if usage:
            body["usage"] = usage
        return f"data: {json.dumps(body)}\n\n"

    events = [
        chunk({"role": "assistant", "content": "Va"}),
        chunk({"content": "le."}),
        chunk({"tool_calls": [{"index": 0, "id": "x", "type": "function", "function": {"name": "orden_voxa", "arguments": "{\"fra"}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": "se\": \"pausa\"}"}}]}, finish="tool_calls"),
        chunk(usage={"prompt_tokens": 40, "completion_tokens": 9, "total_tokens": 49}),
        "data: [DONE]\n\n",
    ]
    api = SseApi(events)
    try:
        client = openai.AsyncOpenAI(api_key="k", base_url=api.url, max_retries=0)
        pieces = []
        answer = await OpenAiChat(client, "gpt-x").ask("s", [], on_text=pieces.append)
    finally:
        api.close()
    assert pieces == ["Va", "le."] and answer.text == "Vale." and answer.commands == ["pausa"]
    assert (answer.input_tokens, answer.output_tokens) == (40, 9)
    assert api.bodies[0]["stream"] is True and api.bodies[0]["stream_options"] == {"include_usage": True}

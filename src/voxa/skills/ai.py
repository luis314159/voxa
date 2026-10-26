"""Respaldo con IA: lo que las reglas no entienden se le pregunta a un modelo de lenguaje.

Responde preguntas abiertas («¿con qué sustituyo el huevo en un pastel?») y, si la persona
pidió algo que VOXA sabe hacer pero dicho de otra forma («ponme algo para cocinar tranquila»),
el modelo lo traduce a una orden de VOXA, que se ejecuta como si se hubiera dicho.

Controles: apagado por defecto, límite de gasto mensual, tope diario de preguntas y una
plática corta (las últimas preguntas de los últimos minutos, nada más).
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from datetime import datetime
from typing import Awaitable, Callable

from voxa.core.phrases import clock_words, date_phrase
from voxa.core.types import Response
from voxa.services.ai import AiError, AiSetupError, ChatModel, cost_usd
from voxa.state.ai_usage import AiUsage

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Eres VOXA, el asistente de voz de la cocina de una familia. Hablas español de México, con calidez y \
sin rodeos.

Todo lo que escribes se lee en voz alta con una voz sintética, así que:
- Responde en 1 a 3 frases cortas (máximo unas 60 palabras). Si piden una receta o una lista, da lo \
esencial en pocas frases y ofrece seguir con más detalle.
- Nada de formato: sin viñetas, asteriscos, encabezados, emojis ni enlaces.
- Escribe las unidades completas («gramos», «grados», «cucharadas»), temperaturas en grados centígrados.
- Si no sabes algo o no estás segura, dilo en vez de inventar.

VOXA ya sabe hacer estas cosas por su cuenta: poner música de Spotify, pausar, cambiar de canción, \
subir o bajar el volumen, temporizadores, recordatorios y alarmas, la lista del súper, videos de \
YouTube, la hora, el clima y conversiones de cocina. Si la persona quiere que VOXA HAGA una de ellas, \
usa la herramienta orden_voxa con la orden dicha de forma sencilla, por ejemplo: «pon música de Café \
Tacvba», «pon un temporizador de 12 minutos para la pasta», «recuérdame sacar el pollo a las 6 de la \
tarde», «agrega jitomate, cebolla y cilantro a la lista», «pon un video de cómo hacer tamales», \
«bájale al volumen». No digas que hiciste algo si no usaste la herramienta. No puedes hacer nada fuera \
de esa lista (compras, llamadas, mensajes, luces).
"""

# Lo que Whisper «oye» en el silencio o el ruido: nunca vale la pena preguntarlo.
_HALLUCINATIONS = ("amara.org", "subtitulos", "suscribete", "gracias por ver", "www.")
_MARKDOWN = re.compile(r"(\*\*|__|\*|`+|^#+\s*|^\s*[-•·]\s+)", re.MULTILINE)
_LINKS = re.compile(r"\[([^\]]+)\]\([^)]+\)|https?://\S+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def worth_asking(text: str) -> bool:
    """Frases con al menos dos palabras de verdad y que no sean alucinaciones del STT."""
    plain = _plain(text)
    if any(h in plain for h in _HALLUCINATIONS):
        return False
    words = [w for w in re.findall(r"[a-zñ]+", plain) if len(w) >= 2]
    return len(words) >= 2


def speakable(text: str, max_words: int = 90) -> str:
    """Quita el formato que la IA a veces pone igual y recorta en el fin de una frase."""
    text = _LINKS.sub(lambda m: m.group(1) or "", text)
    text = _MARKDOWN.sub("", text)
    text = "".join(c for c in text if unicodedata.category(c) not in ("So", "Cs", "Co"))
    text = re.sub(r"\s*\n+\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    words = text.split()
    if len(words) <= max_words:
        return text
    sentences, kept = _SENTENCE_END.split(text), []
    for sentence in sentences:
        if len(" ".join(kept + [sentence]).split()) > max_words:
            break
        kept.append(sentence)
    return " ".join(kept) if kept else " ".join(words[:max_words]).rstrip(",;:") + "."


def context_line(now: datetime, extra: str = "") -> str:
    day = date_phrase(now).removeprefix("Hoy es ").rstrip(".")
    when = f"{day} de {now.year}, {clock_words(now.hour, now.minute, on_the_hour='')}"
    line = f"[Ahora es {when}.]"
    return f"{line} [{extra.strip()}]" if extra.strip() else line


BUDGET_REACHED = Response("Ya se usó el presupuesto de IA de este mes. Se puede subir en la configuración.")
DAILY_LIMIT = Response("Ya respondí muchas preguntas hoy; mañana sigo. Mientras, pregúntame lo de siempre.")
UNAVAILABLE = Response("No pude conectar con la IA. Inténtalo en un momento.", sound="error")
SETUP_PROBLEM = Response("No puedo usar la IA: hay que revisar su configuración.", sound="error")
REFUSED = Response("Prefiero no responder eso.")
NO_ANSWER = Response("No supe qué responder. ¿Me lo dices de otra forma?", sound="error")

RunCommand = Callable[[str], Awaitable["Response | None"]]


class AiFallback:
    def __init__(
        self,
        chat: ChatModel,
        usage: AiUsage,
        *,
        run_command: RunCommand,
        prices: tuple[float, float] | None,
        context: str = "",
        now: Callable[[], datetime] = datetime.now,
        clock: Callable[[], float] = time.monotonic,
        on_setup_error: Callable[[str], None] | None = None,
        on_ok: Callable[[], None] | None = None,
        memory_seconds: float = 180.0,
        memory_turns: int = 4,
    ) -> None:
        self.chat = chat
        self.usage = usage
        self._run_command = run_command
        self._prices = prices
        self._context = context
        self._now = now
        self._clock = clock
        self.on_setup_error = on_setup_error
        self.on_ok = on_ok
        self._memory_seconds = memory_seconds
        self._memory_turns = memory_turns
        self._history: list[dict[str, str]] = []
        self._last_at = float("-inf")
        self.last_cost = 0.0
        if prices is None:
            log.warning("No sé el precio de %s: pon price_input y price_output en [ai] para que cuente el gasto.", chat.model)

    async def __call__(self, text: str) -> Response | None:
        if not worth_asking(text):
            return None
        now = self._now()
        match self.usage.blocked(now):
            case "month":
                return BUDGET_REACHED
            case "day":
                return DAILY_LIMIT
        if self._clock() - self._last_at > self._memory_seconds:
            self._history.clear()
        question = {"role": "user", "content": f"{context_line(now, self._context)}\n{text}"}
        try:
            answer = await self.chat.ask(SYSTEM_PROMPT, [*self._history, question])
        except AiSetupError as exc:
            log.error("IA: %s", exc)
            if self.on_setup_error:
                self.on_setup_error(str(exc))
            return SETUP_PROBLEM
        except AiError as exc:
            log.warning("IA: %s", exc)
            return UNAVAILABLE
        if self.on_ok:
            self.on_ok()
        self.last_cost = cost_usd(answer, self._prices)
        self.usage.record(self.last_cost, now)
        log.info(
            "IA «%s»: %d+%d tokens, %d búsquedas, %.4f USD → %s",
            text, answer.input_tokens, answer.output_tokens, answer.searches, self.last_cost,
            answer.commands or answer.text[:80],
        )

        if answer.refused and not answer.text:
            response = REFUSED
        elif answer.commands:
            response = await self._run(answer.commands, answer.text)
        else:
            spoken = speakable(answer.text)
            response = Response(spoken) if spoken else NO_ANSWER
        self._remember(question, response)
        return response

    async def _run(self, commands: list[str], text: str) -> Response:
        """Ejecuta las órdenes que pidió la IA; habla VOXA (su respuesta ya dice qué hizo)."""
        done: list[Response] = []
        for phrase in commands[:3]:
            result = await self._run_command(phrase)
            if result is None:
                log.warning("La IA pidió una orden que VOXA no entiende: «%s»", phrase)
            else:
                done.append(result)
        if not done:
            spoken = speakable(text)
            return Response(spoken) if spoken else NO_ANSWER
        if len(done) == 1:
            return done[0]
        speech = " ".join(r.speech for r in done if r.speech) or None
        action = next((r.action for r in done if r.action), None)
        return Response(speech, sound=None if speech else "ok", action=action)

    def _remember(self, question: dict[str, str], response: Response) -> None:
        reply = response.speech or "Listo."
        self._history += [question, {"role": "assistant", "content": reply}]
        self._history = self._history[-2 * self._memory_turns:]
        self._last_at = self._clock()

    def forget(self) -> None:
        self._history.clear()

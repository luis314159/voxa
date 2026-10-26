"""«Aprende mi voz»: graba a alguien de la familia y entrena el verificador de «Hey Voxa».

VOXA guía en voz alta y graba con el micrófono de la cocina (el que importa): unas cuantas veces
«Hey Voxa» y un rato de plática normal. Al terminar entrena sola el verificador con las
grabaciones de todos y lo empieza a usar sin reiniciar. Se puede pedir por voz, desde el celular
o con ``voxa grabar-activacion``. Las grabaciones se quedan en esta PC.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from voxa.core.types import Response
from voxa.nlu.normalize import strip_accents

if TYPE_CHECKING:
    import numpy as np

    from voxa.config import Config

log = logging.getLogger(__name__)

TIMES = 8
WAKE_SECONDS = 2.5
TALK_SECONDS = 20
MIN_WAKE = 5
MIN_TALK_SECONDS = 20
QUIET_RMS = 150.0  # int16: por debajo, nadie habló cerca del micrófono
TRIES = 3

TALK_PROMPT = (
    "Ahora platícame lo que sea durante veinte segundos, sin decir mi nombre: "
    "qué vas a cocinar, cómo estuvo tu día. Empieza después del sonido."
)


class NotEnoughRecordings(Exception):
    pass


@dataclass(frozen=True)
class Training:
    accepted: float
    rejected: float
    people: int
    notes: list[str] = field(default_factory=list)


def folder_name(person: str) -> str:
    """«María José» → «maria-jose»: el nombre solo sirve para ordenar las carpetas."""
    name = re.sub(r"[^a-z0-9]+", "-", strip_accents(person.lower())).strip("-")
    return name or "familia"


def people(recordings: Path) -> list[str]:
    if not recordings.is_dir():
        return []
    return sorted(p.name for p in recordings.iterdir() if p.is_dir() and any(p.glob("si_*.wav")))


def rms(audio: np.ndarray) -> float:
    import numpy as np

    return float(np.sqrt(np.mean(audio.astype(np.float32) ** 2))) if len(audio) else 0.0


def train_family_verifier(config: Config) -> Training:
    """Entrena con las grabaciones de todos y guarda el verificador; ``NotEnoughRecordings`` si faltan."""
    from voxa.audio.verifier import train_verifier, windows_from_recordings
    from voxa.audio.wakeword import DEFAULT_MODEL, Classifier, FeatureModels

    folder = config.wake_recordings_dir
    feature_dir = Path(config.wake.feature_dir).expanduser()
    model = Path(config.wake.model).expanduser() if config.wake.model else DEFAULT_MODEL
    positives, negatives, notes = windows_from_recordings(folder, FeatureModels(feature_dir), Classifier.load(model))
    if len(positives) < 3 * MIN_WAKE or len(negatives) < 50:
        raise NotEnoughRecordings(
            f"faltan grabaciones en {folder}: al menos {MIN_WAKE} «Hey Voxa» y {MIN_TALK_SECONDS} s de plática"
        )
    verifier = train_verifier(positives, negatives)
    accepted = float((verifier.predict(positives) >= verifier.threshold).mean())
    rejected = float((verifier.predict(negatives) < verifier.threshold).mean())
    verifier.save(config.verifier_path)
    return Training(accepted, rejected, len(people(folder)), notes)


class VoiceEnrollment:
    """La sesión guiada: qué decir, qué grabar y cuándo entrenar (todo inyectable para probarlo)."""

    def __init__(
        self,
        folder: Path,
        record: Callable[[float], Awaitable[np.ndarray]],
        say: Callable[[Response], Awaitable[None]],
        train: Callable[[], Awaitable[Training]],
        show: Callable[[str], None] = lambda text: None,
        *,
        times: int = TIMES,
        talk_seconds: float = TALK_SECONDS,
    ) -> None:
        self.folder = folder
        self._record = record
        self._say = say
        self._train = train
        self._show = show
        self.times = times
        self.talk_seconds = talk_seconds

    async def run(self, person: str) -> Response:
        from voxa.audio.clip import MIC_RATE, Clip

        name = person.strip() or "familia"
        folder = self.folder / folder_name(name)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        await self._say(Response(
            f"Vamos a grabar tu voz{', ' + name if person.strip() else ''}. Cada vez que escuches el sonido, "
            "di «Hey Voxa» como me hablarías desde la cocina."
        ))
        saved, quiet = 0, 0
        while saved < self.times:
            self._show(f"Di «Hey Voxa» ({saved + 1} de {self.times})")
            await self._say(Response(sound="listening"))
            audio = await self._record(WAKE_SECONDS)
            if rms(audio) < QUIET_RMS:
                quiet += 1
                if quiet >= TRIES:
                    return Response("No te escucho bien. Acércate al micrófono y vuelve a pedirme que aprenda tu voz.",
                                    sound="error")
                await self._say(Response("No te oí. Otra vez, un poco más fuerte."))
                continue
            Clip.from_int16(audio, MIC_RATE).save(folder / f"si_{stamp}_{saved + 1:02d}.wav")
            saved += 1
        self._show("Platica normal, sin decir «Voxa»")
        await self._say(Response(TALK_PROMPT))
        await self._say(Response(sound="listening"))
        talk = await self._record(self.talk_seconds)
        Clip.from_int16(talk, MIC_RATE).save(folder / f"no_{stamp}.wav")
        self._show("Aprendiendo tu voz…")
        await self._say(Response("Gracias. Dame unos segundos para aprenderla."))
        try:
            result = await self._train()
        except NotEnoughRecordings as exc:
            log.warning("Verificador: %s", exc)
            return Response("Guardé tu voz, pero me faltan grabaciones para aprenderla. Repítelo otra vez.")
        log.info("Verificador: acepta %.0f%% de «Hey Voxa», descarta %.0f%% de la plática (%d personas)",
                 result.accepted * 100, result.rejected * 100, result.people)
        if result.accepted < 0.8:
            return Response("Listo, aunque todavía te confundo a veces. Si no te hago caso, repítelo en un lugar "
                            "más silencioso.")
        return Response("Listo, ya reconozco tu voz.")

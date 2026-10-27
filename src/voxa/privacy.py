"""Qué se queda en esta PC y qué sale a internet, según lo que la casa tiene encendido.

Lo muestra el celular (Ajustes → Privacidad), para que cualquier persona de la familia lo entienda.
"""

from __future__ import annotations

from voxa.config import Config
from voxa.i18n import tr
from voxa.settings import read_secret

_PROVIDERS = {"claude": "Anthropic (Claude)", "openai": "OpenAI", "azure": "Azure OpenAI", "compatible": "el servicio que se configuró"}


def privacy_report(config: Config) -> dict[str, list[str]]:
    local = [
        tr("Lo que dices: el audio se reconoce en esta PC y no se guarda ni se manda a ningún lado."),
        tr("Las grabaciones de «aprende mi voz» y las voces de la familia."),
        tr("La lista del súper, los pendientes, las notas, las medicinas, los temporizadores y las mediciones de «Cómo va VOXA»."),
        tr("Las llaves y contraseñas (Spotify, IA, Telegram, calendario), en archivos que solo tu usuario puede leer."),
    ]
    internet: list[str] = []
    if config.ai.enabled:
        provider = tr(_PROVIDERS.get(config.ai.provider, config.ai.provider))
        internet.append(tr("IA (de paga): solo el texto de las frases que VOXA no entiende sola, nunca el audio, va a {provider}. "
                           "En la pantalla se ve la marca «IA» mientras está encendida.", provider=provider))
    if config.music.provider != "youtube" and config.spotify.client_id:
        internet.append(tr("Spotify: lo que pides poner y lo que suena, con tu cuenta."))
    if config.music.provider != "spotify" or config.video.enabled:
        internet.append(tr("YouTube: las búsquedas de música y videos (sin cuenta)."))
    if config.weather.latitude is not None:
        internet.append(tr("El clima: la ubicación aproximada de la casa va a Open-Meteo."))
    if config.calendar.enabled and read_secret(config.calendar_url_path):
        internet.append(tr("El calendario: VOXA lee la dirección secreta del calendario; no escribe en él."))
    if config.telegram.enabled:
        internet.append(tr("Telegram: la lista del súper, solo con los chats que vinculaste."))
    if config.update.check:
        internet.append(tr("Actualizaciones: VOXA pregunta a GitHub si hay versión nueva."))
    internet.append(tr("La primera vez: los modelos de voz se bajan de su fuente, con su huella."))
    return {"local": local, "internet": internet}

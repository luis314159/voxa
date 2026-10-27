# Licencias de lo que VOXA baja y usa

VOXA baja sus modelos en el primer arranque (`src/voxa/prepare.py`), cada uno con su huella SHA-256 fija. Esta tabla dice de quién es cada cosa y con qué licencia, para saber qué se puede hacer con VOXA. Revisado el 27 de octubre de 2026; si se cambia o se agrega un modelo, se actualiza aquí.

## Modelos

| Qué | Para qué | De dónde | Licencia |
|---|---|---|---|
| Voz `es_MX-claude-high` (Piper) | La voz en español | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/v1.0.0/es/es_MX/claude/high) | Apache 2.0 (según su *model card*) |
| Voz `en_US-lessac-medium` (Piper) | La voz en inglés | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/v1.0.0/en/en_US/lessac/medium) | **Restringida:** se entrenó con los datos de Lessac del Blizzard Challenge 2013, cuya licencia se otorga a quien la firma y es para investigación. Ver «Pendientes» |
| `vosk-model-small-es-0.42`, `vosk-model-small-en-us-0.15` | Órdenes cortas (Vosk) | [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models) | Apache 2.0 |
| Whisper *base* (faster-whisper) | Frases con texto libre | [Systran/faster-whisper-base](https://huggingface.co/Systran/faster-whisper-base) | MIT |
| `melspectrogram.onnx`, `embedding_model.onnx` | La base de «Hey Voxa» | [openWakeWord v0.5.1](https://github.com/dscripka/openWakeWord/releases/tag/v0.5.1) | Código Apache 2.0; el *speech embedding* es de Google (Apache 2.0). El README de openWakeWord pone sus modelos preentrenados bajo CC BY-NC-SA 4.0 |
| `hey_voxa.npz` (viene en VOXA) | El clasificador de «Hey Voxa» | Entrenado por VOXA ([scripts/hey_voxa/](../scripts/hey_voxa/README.md)) | **CC BY-NC-SA 4.0** (se entrenó con datos de openWakeWord de esa licencia): uso no comercial |
| WeSpeaker ResNet34 (VoxCeleb) | Saber quién habla | [csukuangfj/speaker-embedding-models](https://huggingface.co/csukuangfj/speaker-embedding-models) (exportado de [WeSpeaker](https://github.com/wenet-e2e/wespeaker)) | Código Apache 2.0; datos de VoxCeleb, CC BY 4.0: hay que dar crédito |
| Fondos de pantalla | Fotos de la cocina | Wikimedia Commons ([catálogo](../assets/fondos/catalogo.json)) | Dominio público o CC0 (el script lo revisa foto por foto) |

## Programas

| Qué | Licencia |
|---|---|
| `piper-tts` (síntesis de voz, desde la versión 1.3 es [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl)) | **GPL-3.0** |
| Vosk | Apache 2.0 |
| faster-whisper | MIT |
| Spotifast ([crmne/spotifast](https://github.com/crmne/spotifast)) | MIT |
| yt-dlp | Unlicense |
| mpv | GPL-2.0 o posterior (y LGPL) |

## Qué quiere decir

- **VOXA es para usarse en casa, sin fines comerciales.** «Hey Voxa» es CC BY-NC-SA 4.0 y la voz en inglés viene de datos de investigación. Venderla o usarla en un negocio necesitaría otro detector de «Hey Voxa» y otra voz en inglés.
- **Créditos:** VoxCeleb (CC BY 4.0) y openWakeWord piden que se les dé crédito; este documento lo hace.
- **piper-tts es GPL-3.0:** el `.deb` instala VOXA junto con él. Al repartir el paquete hay que dejar a la mano el código de VOXA, y el repositorio de GitHub ya cumple con eso.

## Pendientes

- **VOXA todavía no tiene licencia** (no hay `LICENSE` en el repositorio). Sin ella, el código es público pero nadie más tiene permiso de usarlo. La elección es de quien hizo VOXA; por lo de arriba, encajan GPL-3.0 o AGPL-3.0.
- **Voz en inglés con licencia clara:** probar `en_US-libritts_r-medium` (LibriTTS-R, CC BY 4.0) o Kokoro (Apache 2.0) en lugar de `en_US-lessac-medium`.

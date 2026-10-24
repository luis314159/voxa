# Entrenar «Hey Voxa»

El detector de VOXA ([src/voxa/audio/wakeword.py](../../src/voxa/audio/wakeword.py)) sigue el esquema de [openWakeWord](https://github.com/dscripka/openWakeWord): dos modelos base convierten el audio en resúmenes de 96 números cada 80 ms, y un clasificador pequeño, entrenado para «Hey Voxa», decide si se acaba de decir. El clasificador que trae VOXA (`src/voxa/audio/hey_voxa.npz`) sale de estos dos scripts.

## Qué hace falta

| Qué | De dónde | Licencia |
|---|---|---|
| `melspectrogram.onnx`, `embedding_model.onnx` | [openWakeWord v0.5.1](https://github.com/dscripka/openWakeWord/releases/tag/v0.5.1) (los baja `scripts/install.sh`) | Apache 2.0 (código de openWakeWord; el *speech embedding* es de Google) |
| Voces de Piper (español y de muchos hablantes en inglés) | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) | Varía por voz; solo se usan para generar datos de entrenamiento, no se redistribuyen |
| Negativos precalculados: `openwakeword_features_ACAV100M_2000_hrs_16bit.npy` (primeras ~700 mil filas, 2 GB) y `validation_set_features.npy` | [davidscripka/openwakeword_features](https://huggingface.co/datasets/davidscripka/openwakeword_features) | CC BY-NC-SA 4.0 (uso no comercial) |

Voces usadas: `en_US-libritts_r-medium` (904 hablantes), `en_GB-vctk-medium` (109), `en_US-l2arctic-medium` (24, varios con español como lengua materna), `en_US-arctic-medium`, y en español `es_MX-claude-high`, `es_MX-ald-medium`, `es_MX-ald-x_low`, `es_AR-daniela-high`, `es_ES-davefx-medium`, `es_ES-sharvard-medium`, `es_ES-carlfm-x_low`, `es_ES-mls_10246-low`, `es_ES-mls_9972-low`.

ACAV100M completo pesa 17 GB; basta con las primeras filas, que se bajan con una petición por rangos:

```bash
U=https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main
curl -L -r 0-2150400127 -o negativos/acav_parcial.bin "$U/openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
curl -L -o negativos/validation_set_features.npy "$U/validation_set_features.npy"
```

## Pasos

```bash
python scripts/hey_voxa/generar.py --voces voces/ --modelos modelos/ --salida datos/ --procesos 12
python scripts/hey_voxa/entrenar.py --datos datos/ --negativos negativos/ --modelos modelos/
```

`generar.py` arma miles de «Hey Voxa» y «Oye Voxa» como sonarían en la cocina: con alguien hablando antes, a veces con la orden pegada («Hey Voxa, pon música»), eco de cuarto, ruido de extractor o agua, plática, música y a distintos volúmenes. También genera lo que no debe activarla: frases normales, parecidos («oye Rosa», «Oaxaca», «Alexa») y «Hey Vo…» cortado a la mitad. Tarda unos minutos con 12 procesos.

`entrenar.py` entrena con numpy (sin PyTorch), mide con voces que nunca vio y con ~11 h de pláticas y música, elige el umbral y guarda `src/voxa/audio/hey_voxa.npz`.

## En la cocina

Las voces sintéticas son un buen comienzo, pero la medida que manda es la de la familia:

```bash
voxa probar-activacion                 # en vivo: qué tan seguro está de oír «Hey Voxa»
voxa probar-activacion --umbral 0.6    # probar otro umbral
voxa probar-activacion --archivo grabacion.wav   # contar activaciones en una grabación larga
```

Si se activa sola, sube `threshold` en `[wake]` de `~/.config/voxa/config.toml`; si no te oye, bájalo. El plan (§3.4) contempla además un verificador entrenado con grabaciones de la familia.

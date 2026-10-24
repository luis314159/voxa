<p align="center"><img src="assets/brand/voxa_logo_light.svg" width="280" alt="VOXA — Tu voz, tu hogar, más fácil"></p>

# VOXA

Asistente de voz familiar para la cocina, sobre una PC All-in-One con Linux Mint: música de Spotify, temporizadores, volumen, hora y clima, todo por voz y en español.

- **Plan del proyecto:** [docs/voxa_plan.md](docs/voxa_plan.md)
- **Fase 0 (diagnóstico del equipo):** [docs/fase0_guia.md](docs/fase0_guia.md)
- **Marca:** [assets/brand/](assets/brand/)

## Estado

| Parte | Estado |
|---|---|
| NLU en español (gramática, números, duraciones, corrección de errores del STT) | ✅ |
| Temporizadores persistentes con alarma | ✅ |
| Música: Web API + Connect → CLI de Spotifast → MPRIS | ✅ (falta probar en el equipo real) |
| Volumen (PipeWire), hora, clima (Open-Meteo) | ✅ |
| Modo texto (`voxa texto`) | ✅ |
| Voz con «pulsar para hablar» (`voxa voz`): micrófono, fin de frase, STT híbrido Vosk/Whisper, Piper, sonidos, ducking | ✅ (falta calibrar en el equipo real) |
| Pantalla de cocina (`ui/`, Rust + egui): reloj, temporizadores, música, anillo animado, fondos | ✅ (falta probar en el equipo real) |
| «Hey Voxa» (detector de palabra de activación) | ⏳ Fase 3 |
| Servicios systemd e instalador | ⏳ Fase 4 |
| Videos (mpv + yt-dlp) | ⏳ Fase 5 |

## Probarlo (sin micrófono)

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"          # Windows: .venv\Scripts\pip
.venv/bin/voxa texto --simulado            # música y volumen simulados
```

```text
> pon un temporizador de diez minutos para el arroz
VOXA: 10 minutos para el arroz.
> cuánto le falta al arroz
VOXA: Faltan 10 minutos.
> pon Soda Stereo
VOXA: Soda Stereo.
```

### Con voz

```bash
.venv/bin/pip install -e ".[audio]"
python -m piper.download_voices es_MX-claude-high --download-dir models/piper
# + modelo de Vosk en español en models/vosk/ (https://alphacephei.com/vosk/models)
export VOXA_CONFIG=config/dev.toml          # PowerShell: $env:VOXA_CONFIG="config/dev.toml"
voxa voz --simulado                         # Enter → hablar
voxa decir "Diez minutos para el arroz."    # probar la voz
voxa sonidos                                # escuchar los sonidos de VOXA
voxa decir --fonemas "Juan Gabriel"         # revisar una pronunciación
voxa escuchar grabacion.wav                 # procesar una grabación
```

`scripts/evaluar_voz.py` mide la cadena voz → intención: Piper «dice» todo el corpus (con ruido opcional) y compara Vosk, Whisper y el híbrido. Con voces sintéticas (más difíciles que una voz real) el híbrido llega a 81 % con Whisper *base* y a 87 % con *small*. La elección final sale del benchmark de la Fase 0 en el equipo real.

Si VOXA pronuncia mal un nombre, agrégalo a `~/.config/voxa/pronunciacion.yaml` (formato en [src/voxa/audio/pronunciacion.yaml](src/voxa/audio/pronunciacion.yaml)).

### Pantalla de cocina

```bash
cd ui && cargo build --release               # requiere Rust (https://rustup.rs)
python scripts/demo_pantalla.py              # datos de ejemplo, sin micrófono ni Spotify
ui/target/release/voxa-ui                    # --completa para pantalla completa
python scripts/descargar_fondos.py           # ~77 fondos: México, pueblos y paisajes de todo el mundo
```

La pantalla se conecta sola a `voxa texto`, `voxa voz` o `voxa servicio` (puerto 8766, solo local) y se reconecta si VOXA se reinicia. Tocar el anillo equivale a pulsar para hablar. Las fotos de `~/.local/share/voxa/fondos/` (también las tuyas) rotan cada 10 minutos (`--cambio-fondo`).

Los fondos ([assets/fondos/catalogo.json](assets/fondos/catalogo.json)) son fotos de Wikimedia Commons en **dominio público o CC0**. El script vuelve a consultar en Commons la licencia de cada una antes de bajarla y, por precaución, omite las importadas de Unsplash que Commons aún no revisa a mano (`--incluir-sin-revisar` las agrega).

Sin `--simulado`, usa Spotify, Spotifast y PipeWire reales. Para configurarlos, ver la [guía de la Fase 0](docs/fase0_guia.md#51-probar-voxa-con-spotify-real-modo-texto).

## Instalar en la PC de la cocina

```bash
git clone <este repositorio> ~/voxa && cd ~/voxa
bash scripts/install.sh --simular     # ver qué hará, sin cambiar nada
bash scripts/install.sh               # paquetes, VOXA, modelos, pantalla, fondos, audio y arranque automático
```

El instalador se puede repetir sin miedo: respeta lo ya instalado y nunca sobrescribe `~/.config/voxa/config.toml`. Deja la bocina Bluetooth fija en alta calidad y sin «dormirse» ([deploy/wireplumber/](deploy/wireplumber/)), VOXA como servicio de usuario (`systemctl --user status voxa`) y la pantalla abriéndose al iniciar sesión. Queda a mano el inicio de sesión automático y `voxa spotify-login`.

## Pruebas

```bash
.venv/bin/pytest
```

El corpus [tests/data/utterances.yaml](tests/data/utterances.yaml) guarda frases reales con su intención esperada. Cada frase que VOXA no entienda debe agregarse ahí antes de corregir la gramática ([src/voxa/nlu/grammar.yaml](src/voxa/nlu/grammar.yaml)).

## Estructura

```text
src/voxa/
├── nlu/        normalización, números/duraciones, grammar.yaml, matcher
├── core/       asistente (enrutamiento), tipos, frases en español
├── skills/     música, volumen, temporizadores, hora, clima, sistema
├── services/   Spotify (Web API, auth PKCE), Spotifast CLI, MPRIS, PipeWire, Open-Meteo
├── state/      temporizadores persistentes
├── display.py  estado para la pantalla y su canal local
├── service.py  voz + pantalla + temporizadores juntos
├── app.py      arma todo
└── main.py     CLI: voxa texto | voz | servicio | decir | spotify-login
ui/             voxa-ui: pantalla de cocina (Rust + egui)
scripts/fase0/  diagnóstico y benchmarks para correr en la PC
config/         configuración de ejemplo
```

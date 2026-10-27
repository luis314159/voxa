<p align="center"><img src="assets/brand/voxa_logo_light.svg" width="280" alt="VOXA — Tu voz, tu hogar, más fácil"></p>

# VOXA

Asistente de voz familiar para la cocina, sobre una PC All-in-One con Linux Mint: música de Spotify, videos de recetas, temporizadores, recordatorios, lista del súper, conversiones de cocina, volumen, hora y clima, todo por voz y en español.

- **Plan del proyecto:** [docs/voxa_plan.md](docs/voxa_plan.md)
- **Fase 0 (diagnóstico del equipo):** [docs/fase0_guia.md](docs/fase0_guia.md)
- **Marca:** [assets/brand/](assets/brand/)

## Estado

| Parte | Estado |
|---|---|
| NLU en español (gramática, números, duraciones, corrección de errores del STT) | ✅ |
| Temporizadores persistentes con alarma («agrégale 5 minutos», «pausa el temporizador», «5 minutos más» al sonar); recordatorios y despertador a una hora fija o cada semana («de lunes a viernes a las 6», «los martes») | ✅ |
| Conversiones de cocina sin internet (tazas, cucharadas, gramos, °F/°C) | ✅ |
| Lista del súper por voz (y en la pantalla), «buenos días» / «buenas noches» | ✅ |
| Música: Web API + Connect → CLI de Spotifast → MPRIS; por ambiente o género («algo tranquilo para cocinar», «salsa», «los 80») | ✅ (falta probar en el equipo real) |
| Volumen (PipeWire), hora, clima (Open-Meteo) | ✅ |
| Modo texto (`voxa texto`) | ✅ |
| Voz con «pulsar para hablar» (`voxa voz`): micrófono, fin de frase, STT híbrido Vosk/Whisper, Piper, sonidos, ducking | ✅ (falta calibrar en el equipo real) |
| Pantalla de cocina (`ui/`, Rust + egui): reloj, clima, temporizadores, música, anillo animado, fondos, modo noche, diagnóstico | ✅ (falta probar en el equipo real) |
| Avisos de problemas (sin internet, sin micrófono, Spotifast cerrado…) y micrófono apagable | ✅ |
| Videos de YouTube (yt-dlp + mpv) controlados por voz | ✅ (falta probar en el equipo real) |
| Servicios systemd e instalador | ✅ (falta probar en el equipo real) |
| «Hey Voxa»: detector propio, alarmas que se apagan con «ya», cancelación de eco opcional | ✅ (falta calibrar con la familia) |
| Respaldo con IA (opcional): Claude, OpenAI, Azure OpenAI o cualquier servicio compatible, con tope de gasto | ✅ (falta poner la llave) |
| Recetas paso a paso con la IA: ingredientes, pasos en la pantalla, tiempo de cada paso, ingredientes a la lista | ✅ (falta poner la llave) |

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
> recuérdame sacar la basura a las 8 de la noche
VOXA: A las 8 de la noche te recuerdo sacar la basura.
> cuántos gramos es una taza de harina
VOXA: Una taza de harina son unos 125 gramos.
> se acabó el café
VOXA: Agregué café a la lista.
> pon un video de cómo hacer pan de elote
VOXA: Poniendo: Cómo hacer pan de elote.
> pausa
VOXA: [sonido: ok]
```

Mientras hay un video puesto, «pausa», «sigue», «adelanta 30 segundos» y «cierra el video» le hablan al video; al cerrarlo, vuelven a la música. En el equipo real, yt-dlp busca en YouTube y mpv lo reproduce a pantalla completa (720p como máximo, `[video]` en la configuración); encima del video aparecen «Te escucho…» y las respuestas. Tocar la pantalla pausa y dos toques cierran el video.

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

`scripts/evaluar_voz.py` mide la cadena voz → intención: Piper «dice» todo el corpus (con ruido opcional) y compara Vosk, Whisper y el híbrido. Con 177 frases y Whisper *base*, el híbrido acierta 86 % con la voz de VOXA (0.6 s por frase) y 72 % con `es_MX-ald-medium`, una voz sintética más difícil que una real; con ruido de extractor (`--ruido-db 15`) 66 %, y con música encima y eco (`--fondo musica --ruido-db 12 --eco`) 50 %: por eso VOXA baja la música al oír «Hey Voxa». Las órdenes cortas las resuelve primero Vosk con el vocabulario de la gramática (~0.1 s). A Whisper no se le da frase de contexto ni palabras clave: sube un par de puntos pero inventa órdenes («para» → «bájale»). La elección entre *base* y *small* sale de correr esta evaluación en el equipo real.

**«Hey Voxa».** Con `voxa voz` o `voxa servicio`, VOXA escucha «Hey Voxa» (u «Oye Voxa») todo el tiempo y se puede decir la orden de corrido: «Hey Voxa, pon música». Mientras suena una alarma basta con «para», «ya» o «gracias». `voxa probar-activacion` muestra en vivo qué tan seguro está de oírlo, para ajustar `threshold` en `[wake]`. Para que reconozca a la familia y no se active con la tele, cada quien dice «Hey Voxa, aprende mi voz» (o «aprende la voz de Ana»): VOXA guía la grabación en voz alta con el micrófono de la cocina (8 veces «Hey Voxa» y 20 s de plática), entrena el verificador con las voces de todos y lo usa de inmediato. Con esas mismas grabaciones VOXA reconoce quién le habla: arma un prototipo de voz por persona (modelo WeSpeaker ResNet34, CC BY 4.0) y compara cada orden por similitud coseno. Si nadie se parece lo suficiente, VOXA dice que no sabe quién es, con un umbral calibrado para cada familia. Así saluda («¡Buenos días, Ana!»), y «recuérdame tomar la medicina a las 8» suena como «Ana, te recuerdo: …». También funciona «recuérdale a Luis que saque la basura a las 9». Las grabaciones se quedan en esa PC (`~/.local/share/voxa/activacion/`); `voxa grabar-activacion` y `voxa entrenar-verificador` hacen lo mismo desde la terminal. Cómo se entrenó y cómo reentrenarlo: [scripts/hey_voxa/](scripts/hey_voxa/README.md).

**Respaldo con IA (opcional, de paga).** Lo que las reglas no entienden se le puede preguntar a un modelo de lenguaje: «¿con qué sustituyo el huevo en un pastel?», «¿qué le pongo al pozole para que no quede simple?». Si alguien pide algo que VOXA ya sabe hacer pero dicho de otra forma («échale un ojo a la pasta unos doce minutitos»), la IA lo traduce a una orden de VOXA y VOXA la ejecuta. Funciona con Claude, OpenAI, Azure OpenAI y cualquier servicio con la API de OpenAI (Gemini, Groq, Mistral, DeepSeek, OpenRouter, Ollama). Está apagada por defecto y tiene tope de gasto al mes y de preguntas al día; solo se manda el texto de la frase, nunca audio. La respuesta se transmite: VOXA empieza a decir la primera frase mientras la IA sigue escribiendo.

```bash
voxa ia-clave                                     # guarda la llave (permisos 600, fuera del repositorio)
voxa ia-probar "¿cuánto se cuece un huevo tibio?" # respuesta, segundos y costo
```

**Recetas paso a paso (con la IA).** «Dame la receta de pozole» (o «cómo se hace el arroz rojo», «quiero hacer enchiladas») arma la receta y la deja en la pantalla: «los ingredientes», «siguiente paso», «paso anterior», «repite el paso», «ve al paso 4», «pon el tiempo» (cuenta los minutos de ese paso), «agrega los ingredientes a la lista» y «termina la receta». Mientras tanto se le puede preguntar a la IA sobre esa receta («¿cuánto chile le pongo?»). Sin IA, «receta de pozole» pone un video, como antes.

Luego `enabled = true` en `[ai]` de `~/.config/voxa/config.toml` (ahí se elige proveedor, modelo y tope) y `systemctl --user restart voxa`. El gasto del mes se ve en el diagnóstico de la pantalla.

Si VOXA pronuncia mal un nombre, agrégalo a `~/.config/voxa/pronunciacion.yaml` (formato en [src/voxa/audio/pronunciacion.yaml](src/voxa/audio/pronunciacion.yaml)).

### Pantalla de cocina

```bash
cd ui && cargo build --release               # requiere Rust (https://rustup.rs)
python scripts/demo_pantalla.py              # datos de ejemplo, sin micrófono ni Spotify
ui/target/release/voxa-ui                    # --completa para pantalla completa
python scripts/descargar_fondos.py           # ~77 fondos: México, pueblos y paisajes de todo el mundo
```

**Música sin trámites.** Recién instalada, VOXA pone música desde YouTube (gratis, sin cuenta): yt-dlp busca y mpv toca solo el audio, en cola para que siga sonando. Spotify Premium es opcional y agrega tus playlists, tus Me gusta y poner la música en otras bocinas. Spotify exige una app de desarrollador (también para Spotifast), así que el celular guía ese trámite paso a paso (Ajustes → Spotify, con botones para copiar las dos Redirect URIs). El mismo Client ID sirve para VOXA y para Spotifast: VOXA escribe `~/.config/spotifast/settings.json` con ese ID y con el nombre del cuarto. Si Spotify falla, la música sale de YouTube. En `[music]` (o en Ajustes) se elige automática, solo Spotify o solo YouTube.

**Desde el celular.** «Conecta mi celular» muestra un código QR: al escanearlo (en el wifi de la casa) el celular abre una página para ver y cancelar temporizadores, poner temporizadores rápidos, manejar la lista del súper y la música, ver las playlists de la cuenta o buscar otras en Spotify y ponerlas con un toque (y «♥ Mis Me gusta»; por voz, «pon mis me gusta»), escribirle órdenes a VOXA (sin que hable en la cocina, salvo que se pida) y subir fotos de la familia al fondo de pantalla, además de los **Ajustes** de arriba. El código lleva la clave de esa PC (`~/.config/voxa/web_clave`); sin ella, nadie más en la red puede usarlo. Se apaga con `enabled = false` en `[web]`.

**VOXA en varios cuartos.** La cocina es la VOXA principal, y la sala, el comedor o las recámaras pueden tener la suya: otra PC o una Raspberry Pi con micrófono y bocina (la pantalla es opcional).

- **Agregar un cuarto:** en el celular, Ajustes → Cuartos → «Agregar» da un comando para pegar en esa PC. Instala VOXA y la une a la casa con `voxa unir-casa`.
- **Qué hace cada cuarto:** cada uno tiene su «Hey Voxa», sus temporizadores y su música («VOXA Sala» en Spotify).
- **Qué comparten:** la lista del súper y el calendario son los de la cocina.
- **Avisos:** «avisa a todos que ya está la comida», «dile a la sala que se bajen a cenar» o «llama a todos a comer» se oyen en los otros cuartos. También se mandan desde el celular, en la sección «Casa». Si una alarma suena 45 segundos sin que nadie la apague, se avisa en los demás cuartos («Aviso de la cocina: ¡terminó el temporizador de arroz!»).
- **Cómo se conectan:** cada cuarto le avisa a la principal cada minuto que sigue ahí. Todo va por la red de la casa y con la clave de cada VOXA.

**En inglés y en casas bilingües.** Con `language = "en"` en `[voice]` (o en Ajustes → Funciones → Idioma), VOXA entiende y contesta en inglés todo lo de todos los días, también las recetas paso a paso («give me a recipe for pancakes», «next step», «start the timer»), las conversiones de cocina («how many grams is a cup of flour», «350 fahrenheit in celsius»), la grabación guiada de «aprende mi voz» y los avisos entre cuartos («Message from the kitchen»). La pantalla y la página del celular también cambian a inglés. Usa su propia gramática (`nlu/grammar_en.yaml`, con números, horas y días en inglés), la voz de Piper `en_US-lessac-medium` y Vosk en inglés, que el primer arranque baja con sus huellas; la IA contesta y arma las recetas en inglés.

Con **casa bilingüe** (`bilingual = true`, o el interruptor en Ajustes → Funciones), VOXA entiende los dos idiomas a la vez y contesta cada frase en el idioma en que se dijo, con la voz de ese idioma: «pon un temporizador de diez minutos» y luego «what's the weather like?». Whisper detecta el idioma de cada frase (solo entre español e inglés); las órdenes cortas en el idioma de la casa siguen yendo por Vosk, que es más rápido. Lo escrito desde el celular se reconoce por sus palabras.

**Modo niños.** En Ajustes → Modo niños se marca quiénes son niños (los que grabaron su voz con «aprende mi voz»). Cuando VOXA reconoce la voz de uno de ellos:

- **Música sin canciones explícitas:** con Spotify, elige versiones sin la marca «explicit» y, mientras suena lo que pidió un niño, salta las explícitas. Con YouTube no hay esa marca.
- **Volumen con tope** (70 % de entrada): «pon el volumen al 100» se queda en el tope.
- **La IA contesta como para un niño**: sencillo, amable y sin temas de adultos.
- **Videos solo en su horario** (por ejemplo de 16:00 a 19:00).

«Para todos» aplica las reglas a cualquiera (visitas, o si nadie ha grabado su voz). Por voz, «Hey Voxa, modo niños» o «ya vienen los sobrinos» lo enciende para todos; para que no lo apaguen los niños, se apaga solo desde el celular.

**Notas y recados.** «Déjale una nota a papá que compre tortillas», «deja un recado para Ana que ya llegó el gas» o «pon una nota que diga no hay agua caliente» (para todos). Las notas se ven en la pantalla de la cocina y, la siguiente vez que VOXA reconoce la voz de a quien van, se las dice al final de su respuesta: «Por cierto, Luis: Ana te dejó un recado: compre tortillas». «¿Tengo recados?» las repite y «ya leí mis recados» las quita; si no, se borran solas a los 3 días. Para que «papá» o «la abuela» lleguen a la persona correcta, en Ajustes → Voz de la familia se escribe cómo más le dicen a cada quien. En el celular también se dejan y se borran notas.

**Medicinas con confirmación.** Un recordatorio que habla de medicina («recuérdale a Ana que se tome la pastilla de la presión a las 8», «recuérdame la insulina todos los días a las 7») no solo suena: pregunta «Ana, ¿ya te tomaste la medicina?» cada 5 minutos, sin tener que decir «Hey Voxa» para contestar. «Ya me la tomé» (o apagar la alarma) la anota; «todavía no» la vuelve a preguntar más tarde. Si después de 3 veces nadie contesta, avisa a otra persona por Telegram y en los otros cuartos (de noche, en horas de silencio, solo por Telegram). «¿Ya se tomó Ana la medicina?» lo dice, y en el celular se ven las de hoy, con un botón para marcar la que se tomó sin avisar. Se ajusta en Ajustes → Medicinas.

**Horas de silencio.** En Ajustes → Horas de silencio (por ejemplo de 22:00 a 7:00), VOXA habla y suena bajito, y una alarma que nadie apaga ya no se avisa en los otros cuartos. Las alarmas siguen sonando a su volumen: para eso se pusieron.

**Rutina de la mañana.** Con la hora de salida (Ajustes → Rutina de la mañana: hora, días y «no olviden»), los días de escuela VOXA avisa «Faltan 15 minutos para salir. No olviden: mochila, lonche y uniforme», luego a los 5 minutos y «¡Hora de salir!». «¿Cuánto falta para salir?» también lo dice. «Buenos días» saluda por nombre y junta la hora, el clima, los recordatorios, el calendario de la familia y el de quien saluda, sus pendientes y cuánto falta para salir; si se configuró, también pone la música de la mañana.

**Pendientes de cada quien.** «Agrega llamar al plomero a mis pendientes», «¿qué pendientes tengo?», «ya hice la tarea de mate», «agrega la tarea de mate a los pendientes de Luis», «¿qué pendientes tiene Ana?». «Mis» es de quien habla (si VOXA reconoce su voz); si no, de la casa. «Buenos días» dice los pendientes de quien saluda, y en el celular están todos, por persona, para tacharlos.

**Calendario de la familia (opcional).** «¿Qué tengo hoy?», «¿qué tengo mañana?», «¿cuál es mi siguiente cita?», y lo de hoy en «buenos días»; además avisa en voz alta 10 minutos antes de cada evento (se cambia en Ajustes). Puede haber uno de la familia y uno por persona (Ajustes → Calendario → «¿De quién es?»): «¿qué tengo hoy?» junta el de la familia con el de quien pregunta (si VOXA reconoce su voz), «¿qué tiene Ana hoy?» el de Ana, y los avisos personales llevan nombre («Ana, en 10 minutos: natación»). Lee la dirección secreta iCal del calendario (Google Calendar, iCloud, Outlook), sin pedir acceso a la cuenta y solo para leer. Entiende eventos de todo el día, zonas horarias, eventos que se repiten y sus cambios. Se refresca cada 15 minutos y, sin internet, responde con la última copia.

**La lista del súper en Telegram (opcional).** Para apuntar cosas desde la calle:

1. Se crea un bot con @BotFather.
2. Se pega su token en Ajustes → Telegram (o con `voxa telegram-vincular`). Se guarda en `~/.config/voxa/telegram_token` (600).
3. «Vincular un chat» da un código de 6 dígitos que cada persona, o el grupo de la familia, le manda al bot.
 Al bot se le escribe «leche, huevos y tortillas» o «quita la leche», y «/lista» manda la lista con un botón por cosa para ir palomeando en la tienda; la pantalla de la cocina se actualiza al momento. Solo contesta a los chats vinculados.

**Modo foto.** «Modo foto», «solo el fondo» o un doble toque en una parte vacía de la pantalla dejan solo la imagen de fondo, sin información; tocar la pantalla o «muestra la información» la regresan. Mientras VOXA escucha o habla, o si suena una alarma, la información aparece sola.

La pantalla se conecta sola a `voxa texto`, `voxa voz` o `voxa servicio` (puerto 8766, solo local) y se reconecta si VOXA se reinicia. Las fotos de `~/.local/share/voxa/fondos/` (también las tuyas) rotan cada 10 minutos (`--cambio-fondo`).

- **Anillo:** tocarlo equivale a pulsar para hablar. Se pone **ámbar** con el problema debajo cuando algo falla («Sin internet», «No encuentro el micrófono», «Spotifast no responde», «Falta conectar Spotify»).
- **Micrófono:** el botón junto al anillo (o decir «deja de escuchar») lo apaga de verdad: VOXA suelta el micrófono. Tocar el anillo lo vuelve a encender.
- **Clima:** con `latitude` y `longitude` en `[weather]`, se ve el clima del momento y el del día.
- **Modo noche:** de 22:00 a 6:30 la pantalla se oscurece (`--noche 23:00-07:00` para cambiarlo, `--sin-noche` para quitarlo). Un toque la enciende 30 s sin activar ningún botón; las alarmas y las respuestas la encienden solas.
- **Diagnóstico:** mantener presionado el reloj muestra versión, voz, micrófono, música, red, problemas y los últimos avisos del registro.

Los fondos ([assets/fondos/catalogo.json](assets/fondos/catalogo.json)) son fotos de Wikimedia Commons en **dominio público o CC0**. El script vuelve a consultar en Commons la licencia de cada una antes de bajarla y, por precaución, omite las importadas de Unsplash que Commons aún no revisa a mano (`--incluir-sin-revisar` las agrega).

Sin `--simulado`, usa Spotify, Spotifast y PipeWire reales. Para configurarlos, ver la [guía de la Fase 0](docs/fase0_guia.md#51-probar-voxa-con-spotify-real-modo-texto).

## Instalar en la PC de la cocina

**Lo más fácil (sin terminal):** en [Releases](https://github.com/luis314159/voxa/releases/latest), baja `voxa_X.Y.Z_amd64.deb` (PC normal) o `voxa_X.Y.Z_arm64.deb` (Raspberry Pi) y ábrelo con doble clic. Funciona en Linux Mint, Ubuntu y Raspberry Pi OS de 64 bits.

- Pide la contraseña una vez e instala lo necesario.
- Al volver a entrar a la sesión, VOXA baja sola sus modelos de voz, con la huella de cada uno, y lo muestra en la pantalla. Después enseña el código para configurarla desde el celular.
- Se actualiza sola de madrugada. «Hey Voxa, actualízate» lo hace al momento.

Con la terminal (u otras distribuciones), desde un release:

Desde un release (Linux Mint / Ubuntu 22.04 o más nuevo, de 64 bits; también ARM de 64 bits como una Raspberry Pi 4/5). No hace falta git ni compilar: la pantalla viene lista.

```bash
curl -fLO https://github.com/luis314159/voxa/releases/latest/download/instalar-voxa.sh
bash instalar-voxa.sh                 # opciones: --simular, --sin-video, --cancelar-eco… (se recuerdan)
voxa revisar                          # qué falta configurar
```

**Lo demás se configura desde el celular.** Al arrancar sin configurar, la pantalla de la cocina muestra un código QR (también con «Hey Voxa, configura VOXA» o «conecta mi celular»). Al escanearlo, en la pestaña **Ajustes** están:

- **Pendientes**: lo mismo que `voxa revisar`, como lista.
- **Voz de la familia**: «Grabar» guía a cada persona en la cocina para que VOXA la reconozca.
- **Spotify**: el Client ID y «Conectar con Spotify». Se acepta en el celular y se pega la dirección de regreso.
- **Clima**: se busca la ciudad por nombre.
- **Calendario**: la dirección iCal.
- **Telegram**: el token del bot y el código para vincular cada chat.
- **IA**: proveedor, modelo, llave, tope de gasto y «Probar».
- **Funciones**: videos y actualizaciones automáticas, y la precisión del reconocimiento.

Lo que se elige ahí se guarda en `~/.config/voxa/ajustes.json` (600) encima de `config.toml`. Las llaves y tokens van cada uno en su archivo 600 y nunca regresan al celular. Al guardar, VOXA se reinicia sola.

Después, `voxa actualizar` instala la versión más reciente (`--revisar` solo avisa; `--version 0.1.0` regresa a una anterior: se guardan la actual y la previa en `~/.local/share/voxa/app/`). El instalador revisa la huella del paquete contra `SHA256SUMS` del release. VOXA también revisa sola cada 6 horas si hay versión nueva: lo dice el diagnóstico de la pantalla, se puede preguntar «¿hay actualizaciones?» y «actualízate» la instala; con `automatic = true` en `[update]` se actualiza sola de madrugada (3 a 5 a. m.) si la cocina está quieta.

Desde el código (para desarrollar, o en otra arquitectura; compila la pantalla con Rust):

```bash
git clone https://github.com/luis314159/voxa ~/voxa && cd ~/voxa
bash scripts/install.sh --simular     # ver qué hará, sin cambiar nada
bash scripts/install.sh               # paquetes, VOXA, modelos, pantalla, fondos, videos, audio y arranque automático
```

Para publicar un release: subir la versión en `pyproject.toml`, `src/voxa/__init__.py` y `ui/Cargo.toml`, y empujar la etiqueta `vX.Y.Z`; [release.yml](.github/workflows/release.yml) compila la pantalla (x86_64 y aarch64), arma los paquetes y los publica.

El instalador se puede repetir sin miedo: respeta lo ya instalado y nunca sobrescribe `~/.config/voxa/config.toml`. Deja la bocina Bluetooth fija en alta calidad y sin «dormirse» ([deploy/wireplumber/](deploy/wireplumber/)), VOXA como servicio de usuario (`systemctl --user status voxa`), la pantalla abriéndose al iniciar sesión y yt-dlp actualizándose cada semana (`voxa-ytdlp.timer`), porque YouTube cambia seguido. Si al servicio le faltan los modelos de voz o el micrófono, no se cae: la pantalla lo avisa en ámbar. Queda a mano el inicio de sesión automático y `voxa spotify-login`.

`voxa revisar` revisa la instalación de punta a punta (modelos y sus huellas, micrófono, bocina Bluetooth en A2DP, Spotify y Spotifast, yt-dlp/mpv/deno, internet y clima, IA, servicios de systemd y erratas en `config.toml`) y dice, para cada cosa que falte, el comando que la arregla. Solo lee: no cambia nada ni gasta.

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
├── skills/     música, video, volumen, temporizadores, hora, clima, cocina, súper, recetas, sistema, respaldo con IA
├── services/   Spotify (Web API, auth PKCE), Spotifast CLI, MPRIS, PipeWire, Open-Meteo, yt-dlp + mpv, IA
├── state/      temporizadores, lista del súper, receta en curso y gasto de IA persistentes
├── display.py  estado para la pantalla y su canal local
├── health.py   problemas que la pantalla avisa en ámbar
├── diagnostics.py  reporte de la pantalla de diagnóstico
├── service.py  voz + pantalla + temporizadores + video juntos
├── app.py      arma todo
├── checkup.py  voxa revisar: qué falta en la instalación y cómo arreglarlo
└── main.py     CLI: voxa texto | voz | servicio | decir | revisar | spotify-login | ia-clave | ia-probar…
ui/             voxa-ui: pantalla de cocina (Rust + egui)
scripts/fase0/  diagnóstico y benchmarks para correr en la PC
config/         configuración de ejemplo
```

# VOXA — Plan del proyecto (v2)

> Reemplaza al plan de [voxa_idea.md](voxa_idea.md), que queda como antecedente. Marca vigente: [assets/brand/](../assets/brand/). Estado de avance: [README](../README.md#estado).

## 0. Qué cambió respecto a la idea original

| Tema | Antes | Ahora | Por qué |
|---|---|---|---|
| Spotify | Spotifast + `playerctl` (solo pausa y siguiente) | **Spotify Connect + Web API** como base; **Spotifast** como reproductor de la PC (dispositivo Connect «VOXA Cocina»), controlado también por su CLI y MPRIS | Con Premium se puede *buscar y reproducir por voz* («pon Soda Stereo»), no solo pausar. Spotifast es rápido y ligero, y cualquiera puede mandar música desde su teléfono. |
| YouTube | Firefox | **mpv + yt-dlp** (Firefox como plan B) | Menos RAM/CPU, control total por IPC, se puede mostrar «Escuchando…» encima del video. |
| Audio | Micrófono y bocinas genéricas | **Bocina Bluetooth** + micrófono de la PC, con *ducking* y cancelación de eco | El mayor riesgo real es oír «Hey Voxa» con música sonando. |
| Funciones | Música y video | + **temporizadores**, volumen, hora, clima, ayuda | En una cocina, los temporizadores son la función más usada. |
| Rust | Fase 6 | **La pantalla (`voxa-ui`) en Rust con egui** desde ya; el núcleo sigue en Python | La pantalla está encendida todo el día: en Rust usa 0.3 % de CPU en reposo y un binario de 9 MB, sin navegador. Lo pesado del núcleo (wake word, STT, TTS) ya corre en C/C++; pasarlo a Rust se decide con mediciones de la Fase 3. |
| Calidad | Criterios generales | **Métricas con objetivos numéricos** y pruebas con audio real | «Excelente» tiene que poder medirse. |

## 1. Visión y principios

**VOXA** convierte una PC All-in-One con Linux Mint en el asistente de la cocina: música, videos, temporizadores y respuestas rápidas, todo por voz y en español.

*Tu voz, tu hogar, más fácil.*

Principios que guían cada decisión:

1. **Local primero.** La activación, los comandos y los temporizadores funcionan sin internet. La nube solo se usa para Spotify, YouTube y, opcionalmente, IA.
2. **Rápido o no sirve.** Una orden simple se ejecuta en menos de 1.5 s desde que la persona deja de hablar.
3. **Siempre se sabe si escucha.** Hay señal sonora y visual al empezar y al terminar, y una forma clara de silenciar el micrófono.
4. **Se arregla solo.** Si algo falla (Bluetooth, red, Spotify), VOXA lo dice en voz alta, se recupera y nunca exige teclado.
5. **Privacidad por defecto.** No se guarda audio y no se transmite audio continuo.

## 2. Experiencia objetivo

Escenarios que deben funcionar de forma impecable:

| La persona dice | VOXA hace | VOXA responde |
|---|---|---|
| «Hey Voxa… pon Soda Stereo» | Baja la música (*ducking*), busca al artista y lo reproduce en «VOXA Cocina» | «Soda Stereo» |
| «Hey Voxa, pon un temporizador de diez minutos para el arroz» | Crea el temporizador y lo muestra en pantalla | «Diez minutos para el arroz» |
| «Hey Voxa, ¿cuánto le falta al arroz?» | Consulta el temporizador | «Faltan cuatro minutos» |
| *(suena la alarma)* «¡Ya!» / «Para» | Detiene la alarma sin necesidad de «Hey Voxa» | — |
| «Hey Voxa, más fuerte» / «volumen a treinta» | Ajusta el volumen de la bocina | Sonido corto de confirmación |
| «Hey Voxa, ¿qué canción es esta?» | Lee el estado del reproductor | «Persiana americana, de Soda Stereo» |
| «Hey Voxa, pon un video de cómo hacer pan de elote» | Busca y reproduce en pantalla completa | «Poniendo: …» |
| «Hey Voxa, adelanta treinta segundos» / «pausa» | Controla el video | — |
| «Hey Voxa, ¿qué puedes hacer?» | Muestra y dice ejemplos | Breve lista |
| «Hey Voxa, deja de escuchar» | Silencia el micrófono; la pantalla lo indica | «Micrófono apagado. Toca la pantalla para reactivarme» |

Las confirmaciones son cortas. Si la acción es evidente (pausa, volumen), basta un sonido.

## 3. Hardware y audio

### 3.1 Equipo

- PC All-in-One de 64 bits con Linux Mint y 2–4 GB de RAM (por confirmar en la Fase 0).
- **Salida:** bocina Bluetooth.
- **Entrada:** micrófono integrado de la PC. Si no pasa las pruebas de la Fase 0, se cambia por un micrófono USB omnidireccional de conferencias, que es la mejora más barata con mayor impacto.
- Si la RAM es de 2 GB, conviene considerar la edición **Xfce** de Mint en lugar de Cinnamon.

### 3.2 Pila de audio

Linux Mint 22 usa **PipeWire** + WirePlumber; Mint 21 usaba PulseAudio. Se confirma con `pactl info | grep "Server Name"`. El plan asume PipeWire.

```text
Micrófono PC ──► [echo-cancel (WebRTC)] ──► VOXA (16 kHz mono)
                         ▲ referencia
VOXA TTS / earcons ─┐    │
Spotifast ──────────┼──► sink Bluetooth (A2DP) ──► Bocina
mpv ────────────────┘
```

### 3.3 Detalles de la bocina Bluetooth (no omitir)

| Problema | Solución |
|---|---|
| No se reconecta tras reiniciar | Emparejar y marcar como confiable (`bluetoothctl trust <MAC>`). Agregar un servicio `voxa-bt` que reconecte cada 30 s si la bocina está disponible. |
| El sistema cambia a perfil «auricular» (HFP/HSP) y el audio se oye mal | Desactivar en WirePlumber el cambio automático a perfil de auricular. El micrófono **siempre** es el de la PC y la bocina se queda en A2DP. La sintaxis depende de la versión de WirePlumber. |
| Se pierde el inicio de un sonido (la bocina o el sink «despiertan» tarde) | Desactivar la suspensión del nodo Bluetooth en WirePlumber (`session.suspend-timeout-seconds = 0`) y agregar 200–300 ms de silencio al inicio de los *earcons* si hace falta. |
| La bocina se apaga sola tras minutos sin sonido | Probar el comportamiento en la Fase 0. Si se apaga aunque haya conexión, documentarlo; si es posible, usarla conectada a la corriente. |
| Latencia de A2DP (≈150–300 ms) | Ajustar la cancelación de eco a ese retraso. El *ducking* es la defensa principal y no depende del retraso. |
| La bocina se desconecta | Respaldo automático a las bocinas internas y aviso en voz: «Perdí la bocina, uso las de la pantalla». |

**Colocación:** la bocina debe quedar lo más lejos posible del micrófono, y nunca apuntando hacia él.

### 3.4 Oír «Hey Voxa» con música sonando

Defensa en capas:

1. **Cancelación de eco** de PipeWire (`module-echo-cancel` con WebRTC). Le resta al micrófono lo que suena por la bocina.
2. **Ducking:** al detectar la activación, la música baja al 20 % de inmediato y vuelve a su nivel al terminar la respuesta. Se hace sobre el volumen del *stream* en PipeWire (`wpctl set-volume <id-del-stream>`), así funciona igual con Spotifast, mpv o cualquier reproductor, es local e instantáneo y no toca el volumen de Spotify.
3. **Umbral adaptativo:** si hay música, el umbral del detector se ajusta según las mediciones de la Fase 3.
4. **Modelo verificador personalizado** (openWakeWord lo permite) entrenado con muestras de voz de la familia.

## 4. Arquitectura

### 4.1 Procesos

Todos corren como servicios `systemd --user` con `Restart=on-failure`:

| Servicio | Qué es | RAM estimada |
|---|---|---|
| `voxa-core` | Demonio Python (asyncio): audio, wake word, STT, intenciones, habilidades, TTS, servidor de la interfaz | 300–600 MB según el STT |
| `spotifast` | Reproductor y dispositivo Spotify Connect «VOXA Cocina» (librespot). Arranca con la sesión en modo bandeja, sin ventana | 100–250 MB (dato del proyecto) |
| `mpv` | Se lanza bajo demanda para videos | 150–250 MB a 720p |
| `voxa-ui` | Pantalla de cocina en Rust + egui (OpenGL), conectada a `voxa-core` por 127.0.0.1 | ~50–150 MB (a medir en el equipo) |
| `voxa-bt` | Reconexión de la bocina (puede vivir dentro de `voxa-core`) | — |

Con 4 GB hay margen. Con 2 GB: STT solo con Vosk (sin Whisper), escritorio Xfce, videos a 480p y, si aun así falta memoria, spotifyd (~30 MB, sin interfaz) en lugar de Spotifast.

### 4.2 Dentro de `voxa-core`

```text
           ┌──────────── Bus de eventos (asyncio) ────────────┐
Audio ──► Wake word ──► VAD/fin de frase ──► STT ──► NLU ──► Habilidad ──► Respuesta
  │           │                                         │          │            │
  │           └──► ducking + earcon + UI «escuchando»   │          │            ├──► TTS (Piper)
  │                                                     │          │            └──► UI
  └── (silenciado mientras VOXA habla)          Fallback IA    Servicios: Spotify API,
                                                (opcional)      MPRIS, mpv IPC, PipeWire,
                                                                temporizadores, clima
```

- **Habilidades (skills):** cada una declara sus intenciones y expone `handle(intent, ctx) -> Response(speech, ui_event, sound)`. Se prueban sin audio.
- **Estado persistente:** temporizadores en `~/.local/state/voxa/`, para que sobrevivan a un reinicio.
- **Configuración:** `~/.config/voxa/config.toml`. Los secretos (token de Spotify, llave de IA) van aparte con permisos `600`.

## 5. Pipeline de voz

| Etapa | Elección | Alternativa | Notas |
|---|---|---|---|
| Captura | `sounddevice` sobre PipeWire, 16 kHz mono, bloques de 80 ms | ALSA directo | Lee de la fuente con cancelación de eco |
| Wake word | **Esquema de openWakeWord** (sus modelos base + clasificador propio «hey voxa», ejecutado con onnxruntime sin el paquete `openwakeword`) + verificador familiar | Porcupine (revisar licencia y modelo en español); Vosk con gramática como último recurso | Se entrena con voces sintéticas + negativos (`scripts/hey_voxa/`); se valida con audio real de la cocina |
| Fin de frase | **Silero VAD** | `webrtcvad` | Corta tras ~700 ms de silencio; máximo 8 s |
| STT | **Híbrido:** Vosk (es) en streaming para comandos + **faster-whisper** (base/small, int8) para texto libre | Solo uno de los dos, según el benchmark | Los nombres de canciones y videos son vocabulario abierto: Vosk con gramática no basta |
| NLU | Reglas en YAML (patrones con *slots*) + `rapidfuzz` + números en palabras (`text2num`) | IA con *tool calling* si las reglas fallan | Normaliza acentos, muletillas («este…», «oye») y diminutivos |
| TTS | **Piper**, voz es_MX (elegir del catálogo vigente) | espeak-ng como respaldo | Frases frecuentes pre-generadas en caché = respuesta instantánea |
| Earcons | 3 sonidos propios: escuchando, entendido, error | — | Cortos, agradables, coherentes con la marca |

**Flujo del STT híbrido:** Vosk transcribe mientras la persona habla. Si la frase es un comando cerrado («pausa», «más fuerte»), se ejecuta de inmediato. Si trae texto libre («pon…», «busca…», «un video de…»), se pasa el audio guardado en memoria a faster-whisper para extraer el nombre con precisión.

**Diálogo:**
- Si VOXA hace una pregunta («¿Cuál temporizador, el del arroz o el del horno?»), el micrófono queda abierto 5 s sin necesidad de «Hey Voxa».
- Mientras suena una alarma, se activa una gramática mínima («para», «ya», «apágala») que no necesita la palabra de activación.
- El contexto corto permite «otra vez», «la siguiente» y «más».

### 5.1 Presupuesto de latencia

| Tramo | Objetivo |
|---|---|
| Fin de «Hey Voxa» → earcon + ducking | < 300 ms (+ latencia Bluetooth) |
| Fin de la orden → acción (comando cerrado) | < 1.0 s |
| Fin de la orden → acción (búsqueda Spotify/YouTube) | < 2.5 s |
| Fin de la orden → inicio de la respuesta hablada | < 1.5 s |

## 6. Habilidades v1

| Habilidad | Intenciones | Implementación |
|---|---|---|
| **Música** | poner artista / canción / álbum / playlist («mi playlist de cocina»), pausa, sigue, siguiente, anterior, qué suena, aleatorio, «me gusta», «ponla en la sala» | Spotify Web API + Connect (búsqueda y reproducción en «VOXA Cocina» o en otro dispositivo); CLI de Spotifast y MPRIS para controles locales (ver 6.1) |
| **Volumen** | sube, baja, «a treinta», silencio | `wpctl` sobre el sink Bluetooth |
| **Temporizadores** | crear (con nombre y duración), consultar, cancelar, varios a la vez, detener la alarma | Propios, persistentes, alarma con ducking y repetición cada 30 s hasta que alguien la detenga |
| **Recordatorios y despertador** | «recuérdame sacar la basura a las 8 de la noche», «despiértame mañana a las 6 y media», «pon una alarma a mediodía», qué recordatorios tengo, cancelar | Los mismos temporizadores con hora fija (12 h ambiguas → la próxima ocurrencia) |
| **Conversiones de cocina** | «¿cuántos gramos es una taza de harina?», «¿cuántas cucharadas son un cuarto de taza?», «350 Fahrenheit en centígrados» | Local, sin IA: tazas de 240 ml y gramos por taza de recetario |
| **Video** | poner un video de X, pausa, sigue, adelanta/atrasa N, cierra, más fuerte | yt-dlp (`ytsearch1:`) + mpv con IPC; `show-text` de mpv para mostrar estados encima del video |
| **Hora y fecha** | qué hora es, qué día es | Local |
| **Clima** | cómo está el clima, va a llover | Open-Meteo (gratis, sin llave) |
| **Lista del súper** | «agrega leche y huevos a la lista», «se acabó el café», qué hay que comprar, quita, borra la lista | Local y persistente; se ve en la pantalla |
| **Rutinas** | «buenos días» (hora, clima, recordatorios del día y, si se configura, la música de la mañana), «buenas noches» | Local |
| **Sistema** | deja de escuchar, ayuda, «¿estás ahí?» / «¿estás bien?» (dice qué falla), reinicia | Local |

**Fase IA (opcional):** preguntas abiertas y frases que las reglas no entiendan.

### 6.1 Spotify: Connect + Web API como base, Spotifast como reproductor

**Prioridad:** VOXA habla con Spotify a través de **Spotify Connect y la Web API**. El reproductor de la PC es **Spotifast**, que ya es un dispositivo Spotify Connect. Así VOXA no depende de un reproductor concreto y puede manejar cualquier dispositivo Connect de la casa.

**Lo que se confirmó de Spotifast** (v0.14.1, documentación del repositorio, octubre de 2026):
- Al activar «Set up playback here» aparece como dispositivo **Spotify Connect**, y **el nombre se puede cambiar** en Ajustes → «VOXA Cocina».
- Puede **arrancar con la sesión en modo bandeja**, sin ventana, y la música sigue al cerrar la ventana. En Linux necesita una bandeja del sistema funcional; Cinnamon y Xfce la tienen.
- Es un **reproductor MPRIS**: `playerctl --player=spotifast play-pause` y las teclas multimedia funcionan.
- Tiene una **CLI oficial** pensada para lanzadores y scripts:
  `play`, `pause`, `next`, `previous`, `seek`, `volume-up/down`, `mute`, `shuffle`, `repeat`, `like`,
  `play-uri <uri>`, `play-search [--kind artist|album|playlist] <palabras>`,
  `now-playing --raw` (campos separados por tabulador: estado, título, artistas, álbum, posición, duración, volumen, …, dispositivo),
  `devices --raw` (JSON), `transfer <device-id>`. Si Spotifast no está corriendo, el comando sale con código distinto de cero.
- Se recupera solo de cortes de red con reintentos escalonados.

**Tres capas de control.** VOXA elige la más rápida que esté disponible:

| Capa | Para qué | Ventaja | Si falla |
|---|---|---|---|
| **1. Web API + Connect** (app propia de VOXA, `spotipy`) | Buscar con la lógica de VOXA (búsqueda difusa, «¿quisiste decir…?»), reproducir en «VOXA Cocina» por `device_id`, transferir a otros dispositivos («ponla en la sala»), consultar qué suena | Independiente del reproductor; funciona con teléfonos, bocinas Connect, el cliente oficial o spotifyd | Pasa a la capa 2 |
| **2. CLI de Spotifast** | `play-search`, `play-uri`, `now-playing --raw`, `like` | Local, sin depender del token de VOXA; muy rápido | Pasa a la capa 3 o avisa por voz |
| **3. MPRIS** (`playerctl`/D-Bus) | Pausa, sigue, siguiente, anterior, metadatos | Instantáneo, sin red | Avisa: «Spotify no responde» |

- Los comandos de transporte (pausa, siguiente) van **primero por MPRIS**, que no usa red. Las búsquedas van primero por la Web API.
- Todo vive detrás de una interfaz `MusicBackend` en `services/`, así cambiar de reproductor no toca las habilidades.
- VOXA llama la CLI con `subprocess` y listas de argumentos, nunca con `shell=True`.

**Web API (condiciones vigentes en 2026):**
- La app de Spotify for Developers en *Development Mode* exige que la persona dueña tenga **Premium** activo (ya lo tienen) y permite hasta 5 usuarios autorizados, suficiente para la familia.
- Búsqueda (`/v1/search`, máximo 10 resultados por petición) y reproducción siguen disponibles. *Top tracks* de artista ya no existe; para «pon a X» se reproduce el contexto del artista (`context_uri`).
- **Autenticación:** OAuth con PKCE una sola vez. Se guarda el *refresh token*. Si caduca, VOXA lo dice, muestra un QR para volver a autorizar y mientras tanto sigue con las capas 2 y 3.

**Respaldos del reproductor:** si Spotifast falla, se usa spotifyd (sin interfaz, ~30 MB) o el cliente oficial de Spotify (Flatpak) como dispositivo Connect. La capa 1 sigue funcionando igual.

**Bonus:** cualquier miembro de la familia puede mandar música a «VOXA Cocina» desde su teléfono, y VOXA la controla por voz igual.

### 6.2 YouTube: detalles

- `yt-dlp` trae los primeros 5 resultados (`ytsearch5:`) y VOXA elige el primero que no sea transmisión en vivo ni *short* (entre 90 s y 3 h); mpv lo reproduce a pantalla completa con `--hwdec=auto` y un formato limitado a 720p (480p con 2 GB). «Cómo se hace…» y «receta de…» se buscan como «receta de …».
- Desde finales de 2025, yt-dlp necesita un intérprete de JavaScript para YouTube: se instala **deno** con pipx junto a `yt-dlp[default]`.
- Un temporizador de systemd (`voxa-ytdlp.timer`) **actualiza yt-dlp y deno cada semana**, porque YouTube cambia a menudo.
- Mientras hay video, «pausa», «sigue», «adelanta» y «qué es esto» le hablan al video (IPC de mpv); pedir música lo cierra. Tocar la pantalla pausa y dos toques cierran.
- Cuando el video termina o se cierra, la interfaz de VOXA vuelve al frente.
- **Nota:** reproducir YouTube fuera de su sitio puede ir contra sus términos de servicio. Si la familia prefiere evitarlo, el plan B es Firefox en modo kiosco con MPRIS (más pesado y menos controlable).

## 7. Interfaz de cocina

Pensada para leerse a 3 metros y, si la pantalla es táctil, para usarse con el dedo.

| Estado | Qué se ve |
|---|---|
| Reposo | Hora grande, temporizadores activos con cuenta regresiva y «Sonando ahora» con portada |
| Escuchando | **El anillo del logo** se ilumina y pulsa con la voz (la marca se vuelve el indicador) |
| Pensando | El anillo gira |
| Respondiendo | Texto de lo entendido + respuesta |
| Error | Anillo ámbar + mensaje claro («Sin internet: la música no está disponible») |
| Micrófono apagado | Ícono tachado permanente y botón grande para reactivarlo |

- **Hecho:** clima en reposo (Open-Meteo, se consulta cada 15 min y se conserva sin red), anillo ámbar con el problema más grave, botón de micrófono que suelta el dispositivo de verdad, modo noche de 22:00 a 6:30 (un toque la enciende 30 s sin activar botones; alarmas y respuestas la encienden solas) y diagnóstico al mantener presionado el reloj.
- Programa aparte en **Rust + egui** (`ui/`), que recibe el estado de `voxa-core` como JSON por líneas en 127.0.0.1 (`src/voxa/display.py`). Los segundos de temporizadores y canciones los cuenta la pantalla; solo se repinta una vez por segundo, o a 30 fps mientras el anillo se anima.
- **Fondos:** fotos de paisajes y pueblos (dominio público/CC0, `scripts/descargar_fondos.py`) o de la familia, que rotan cada 10 minutos con un velo oscuro para que el texto se lea.
- Durante un video, los estados se muestran con el OSD de mpv.

## 8. Fiabilidad y operación

- **Arranque:** inicio de sesión automático, sin bloqueo de pantalla ni suspensión, y servicios `systemd --user` habilitados.
- **Recuperación:** reinicio automático de cada servicio. `voxa-core` reintenta Spotify, red y Bluetooth con *backoff* y avisa por voz una sola vez, sin repetirlo en bucle.
- **Salud:** comando «¿estás bien?», y una pantalla de diagnóstico oculta (mantener presionado el reloj) con versión, voz, micrófono, Spotify, yt-dlp/mpv, red, problemas y los últimos avisos del registro. Cada minuto se revisan internet, la autorización de Spotify y que Spotifast responda; si faltan los modelos de voz o el micrófono, el servicio no se cae: lo avisa en la pantalla y reintenta el micrófono cada 30 s.
- **Logs:** journald, sin audio ni transcripciones completas por defecto.
- **Actualizaciones:** `pipx`/`uv` para VOXA y yt-dlp; las actualizaciones del sistema se hacen a mano.
- **Instalación reproducible:** script `scripts/install.sh` idempotente con paquetes, servicios, configuración de WirePlumber y modelos.

## 9. Privacidad, seguridad y costos

- La activación y el STT de comandos son 100 % locales. Nunca se envía audio a la nube, salvo que se habilite explícitamente un STT remoto.
- A la IA opcional solo se le envía el **texto** de la orden, después de la activación. El proveedor y los datos enviados se documentan en el README.
- **Límite mensual de gasto** de IA configurable. Al alcanzarlo, VOXA lo dice y sigue funcionando sin IA.
- No se guarda audio. El modo de depuración que graba se activa explícitamente, se marca en pantalla y se borra con un comando.
- Las acciones del sistema usan `subprocess` con listas de argumentos (nunca `shell=True`) y una lista cerrada de acciones permitidas.
- Los secretos nunca se guardan en el repositorio.

## 10. Calidad: cómo sabremos que es excelente

| Métrica | Objetivo | Cómo se mide |
|---|---|---|
| Falsas activaciones | ≤ 1 cada 24 h con la cocina en uso normal | Registro de activaciones durante una semana |
| Activaciones perdidas | ≤ 5 % sin música, ≤ 10 % con música al 60 % | Set de grabaciones de la familia |
| Precisión de intención | ≥ 95 % | Corpus de frases reales (`tests/data/utterances.yaml`) |
| Acierto en búsquedas de música | ≥ 90 % pone lo que se pidió | Lista de 50 peticiones reales |
| Latencia de comando (p90) | < 1.5 s | Tiempos registrados por etapa |
| Disponibilidad | Funciona 7 días seguidos sin intervención | Prueba de uso real |
| RAM de `voxa-core` | < 600 MB | `systemd-cgtop` / `ps` |

**Pruebas:**
- Unitarias de NLU y habilidades con `pytest`.
- Pruebas de integración con *mocks* de Spotify y mpv.
- **Regresión de audio:** WAV grabados en la cocina (con y sin música) que se pasan por wake word + STT + NLU. Se graban con el consentimiento de la familia y se guardan fuera del repositorio.

## 11. Roadmap

Cada fase termina con un **criterio de salida** verificable.

### Fase 0 — Diagnóstico y bancos de prueba
- Inventario: `lscpu`, `free -h`, versión de Mint y servidor de audio.
- Bocina: emparejar, reconexión tras reinicio, latencia, comportamiento al quedar en silencio, perfil A2DP fijo.
- Micrófono: grabar a 1, 2 y 3 m con y sin música sonando y comparar.
- Benchmark de STT (Vosk vs faster-whisper base/small) con 30 frases grabadas: precisión y tiempo.
- Piper: elegir voz y medir tiempo de síntesis.
- Spotifast: instalar, activar la reproducción local, renombrarlo a «VOXA Cocina», arranque en bandeja; probar `spotifast now-playing --raw`, `play-search` y `playerctl --list-all`; medir RAM.
- Crear la app de Spotify for Developers y comprobar que la Web API ve «VOXA Cocina» y reproduce en él.

**Salida:** documento `docs/fase0_resultados.md` con números y decisión de micrófono y STT.

### Fase 1 — Núcleo con pulsar para hablar
- Esqueleto de `voxa-core`: bus de eventos, configuración, logs.
- Captura → VAD → STT → NLU → habilidad → Piper.
- Habilidades: hora, volumen, ayuda. Earcons.

**Salida:** 20 frases de prueba con ≥ 90 % de acierto y latencia < 2 s, activando con Enter.

### Fase 2 — Música y temporizadores (el corazón de la cocina)
- Spotify: `MusicBackend` con las tres capas (Web API + Connect, CLI de Spotifast, MPRIS), OAuth, búsqueda, reproducción en «VOXA Cocina», transferir a otros dispositivos, «qué suena».
- Temporizadores persistentes con alarma.
- Corpus de NLU con frases reales de la familia.

**Salida:** la familia usa VOXA (todavía con Enter) para música y temporizadores durante 3 días.

### Fase 3 — «Hey Voxa»
- Entrenar el modelo de openWakeWord y el verificador familiar.
- Cancelación de eco + ducking + umbral adaptativo.
- Gramática sin activación para detener alarmas.

**Hecho sin el equipo real:** detector propio con los modelos base de openWakeWord y onnxruntime (el paquete `openwakeword` pide `tflite-runtime`, que no existe para Python 3.12); clasificador «Hey Voxa»/«Oye Voxa» entrenado con ~2,400 voces sintéticas y ruido de cocina simulado (`scripts/hey_voxa/`); la orden pegada («Hey Voxa, pon música») no pierde su inicio; mientras suena una alarma, «para», «ya» o «gracias» la apagan sin «Hey Voxa»; cancelación de eco de PipeWire opcional (`install.sh --cancelar-eco`); `voxa probar-activacion` para calibrar; verificador familiar (`voxa grabar-activacion` + `voxa entrenar-verificador`). Resultado con voces sintéticas nuevas: detecta 86 % en vivo con 0.09 activaciones falsas por hora de plática y música (umbral 0.4); 1.4 ms de CPU por bloque de 80 ms. **Falta en la cocina:** medir con la familia (con y sin música), ajustar el umbral y grabar el verificador.

**Salida:** se cumplen las métricas de activación de la sección 10.

### Fase 4 — Experiencia de cocina (versión 1.0)
- Interfaz a pantalla completa con estados y anillo animado.
- Servicios systemd, reconexión Bluetooth, respaldo de audio, pantalla de diagnóstico.
- Script de instalación.

**Salida:** 7 días de uso real sin intervención técnica. **Esta es la versión 1.0.**

### Fase 5 — Video
- yt-dlp + mpv, controles por voz, OSD, regreso a la interfaz, actualización semanal.

**Salida:** 10 búsquedas de recetas reproducidas correctamente y controladas por voz.

### Fase 6 — IA opcional ✅ (falta poner la llave)
- Respaldo de NLU con *tool calling* para frases que las reglas no entienden: la herramienta `orden_voxa` traduce la frase libre a una orden que la gramática entiende y VOXA la ejecuta (nunca acciones fuera de las suyas).
- Preguntas abiertas con respuestas cortas para voz; plática corta (las preguntas de los últimos 3 minutos). Las conversiones y la lista del súper ya son locales.
- Proveedores: Claude (SDK de Anthropic, con respaldo del servidor si el modelo declina y búsqueda web opcional), OpenAI, Azure OpenAI (API v1) y cualquier servicio compatible con OpenAI (Gemini, Groq, Mistral, DeepSeek, OpenRouter, Ollama).
- **Recetas paso a paso:** la IA arma la receta (herramienta `mostrar_receta`: ingredientes con cantidad, pasos cortos con sus minutos) y VOXA la guía por voz y en la pantalla: siguiente/anterior/repite/ve al paso N, «pon el tiempo» del paso, ingredientes a la lista. La receta en curso va en el contexto de las preguntas libres. Sin IA, «receta de…» pone un video.
- Límite de gasto mensual en USD y tope diario de preguntas (`~/.local/state/voxa/ia_uso.json`), visibles en el diagnóstico. Privacidad: apagada por defecto, solo texto (nunca audio), llave con permisos `600`, y las alucinaciones típicas de Whisper en el silencio no se mandan.

**Salida:** ≥ 80 % de las frases que antes fallaban ahora se resuelven, dentro del presupuesto.

### Después de la 1.0 (ideas)
Recordatorios, reconocer quién habla para tener playlists por persona y rutinas («buenos días»).

## 12. Estructura del repositorio

```text
voxa/
├── README.md
├── pyproject.toml
├── config/
│   └── default.toml
├── deploy/
│   ├── systemd/            # voxa.service, voxa-ui.service, voxa-ytdlp.timer
│   └── wireplumber/        # bluetooth (A2DP fijo, sin suspensión), echo-cancel
├── scripts/
│   └── install.sh
├── assets/
│   ├── sounds/             # earcons
│   └── brand/              # logo e ícono
├── src/voxa/
│   ├── main.py
│   ├── bus.py
│   ├── config.py
│   ├── audio/              # capture, wake_word, vad, stt, tts, ducking, earcons
│   ├── nlu/                # grammar/*.yaml, normalize, numbers, matcher, llm_fallback
│   ├── skills/             # music, volume, timers, video, clock, weather, system, help
│   ├── services/           # music_backend, spotify_api, spotifast_cli, mpris, mpv_ipc, pipewire, bluetooth
│   ├── state/              # persistencia (temporizadores)
│   ├── display.py          # estado y canal local para la pantalla
│   ├── health.py           # problemas: internet, micrófono, Spotify, Spotifast
│   ├── diagnostics.py      # reporte de la pantalla de diagnóstico
│   └── service.py          # voz + pantalla + temporizadores + video
├── ui/                     # voxa-ui: pantalla de cocina en Rust + egui
└── tests/
    ├── data/utterances.yaml
    ├── test_nlu.py
    ├── test_skills_*.py
    └── test_audio_regression.py   # usa WAV locales fuera del repo
```

## 13. Riesgos y mitigaciones

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| No se oye «Hey Voxa» con música | Alta | Alto | Eco + ducking + verificador; micrófono USB si hace falta |
| La bocina Bluetooth se desconecta o se duerme | Media | Alto | `voxa-bt`, respaldo a bocinas internas, aviso por voz |
| Spotifast/librespot se rompe por cambios de Spotify | Media | Medio | El proyecto se actualiza seguido; respaldo con spotifyd o el cliente oficial como dispositivo Connect |
| Spotify cambia otra vez las reglas de la Web API | Media | Medio | `MusicBackend` cae a la CLI de Spotifast y a MPRIS, que no dependen de la app de VOXA |
| Cambia la CLI de Spotifast | Baja | Bajo | Su `--raw` solo agrega campos al final; fijar versión y probar en cada actualización |
| yt-dlp deja de funcionar | Media | Medio | Actualización semanal; plan B con Firefox |
| Poca RAM (2 GB) | Media | Medio | Perfil «ligero» documentado (Xfce, solo Vosk, 480p) |
| STT falla con nombres de artistas | Media | Medio | faster-whisper para texto libre + búsqueda difusa de Spotify + «¿Quisiste decir…?» |
| Niños o visitas activan sin querer | Baja | Bajo | Enfriamiento, verificador, acciones no destructivas |

## 14. Pendiente de verificar en la Fase 0

- RAM exacta y edición o versión de Linux Mint.
- Versión de WirePlumber y sintaxis para fijar A2DP y desactivar la suspensión.
- **Versión de Mint:** Spotifast nativo (AppImage o .tar.gz) necesita **glibc ≥ 2.39, es decir, Mint 22**. En Mint 21 solo queda el Flatpak, y su sandbox puede limitar la CLI y MPRIS. Si el equipo tiene Mint 21, conviene actualizar a Mint 22 antes de la Fase 2.
- Que la CLI de Spotifast y MPRIS funcionen desde un servicio `systemd --user`.
- Catálogo actual de voces es_MX de Piper.
- Condiciones vigentes de Spotify for Developers (cambiaron en febrero de 2026 y de nuevo después).
- Licencia y soporte de español de Porcupine, solo si openWakeWord no alcanza las métricas.

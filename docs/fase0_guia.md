# VOXA — Guía de la Fase 0 (diagnóstico)

Objetivo: medir el equipo real antes de escribir el resto de VOXA. Al final tendrás un informe y unas tablas de resultados para decidir qué micrófono, qué motor de voz y qué configuración de audio usar ([plan, §11](voxa_plan.md)).

Todo se hace en la PC All-in-One con Linux Mint, **desde la sesión gráfica** (no por SSH), con la bocina Bluetooth encendida.

Tiempo aproximado: 1–2 horas, la mayor parte grabando.

---

## 1. Preparar

Copia la carpeta `scripts/fase0/` del proyecto al equipo, con una USB o clonando el repositorio. Abre una terminal en la carpeta del proyecto. Todos los comandos de esta guía se corren desde ahí.

```bash
sudo apt update
sudo apt install playerctl pipx alsa-utils
pipx ensurepath   # cierra y abre la terminal después
```

## 2. Diagnóstico inicial

```bash
bash scripts/fase0/diagnostico.sh
```

Genera `~/voxa-fase0/informe-<fecha>.md` con una tabla resumen:
- ✅ listo
- ⚠️ revisar
- ❌ bloquea el plan

Vuelve a correrlo después de configurar la bocina y Spotifast; cada vez se crea un informe nuevo.

## 3. Bocina Bluetooth

1. Empareja la bocina desde el applet de Bluetooth del panel.
2. Márcala como **confiable** para que se reconecte sola después de reiniciar:

   ```bash
   bluetoothctl devices          # copia la dirección MAC de la bocina (XX:XX:XX:XX:XX:XX)
   bluetoothctl trust XX:XX:XX:XX:XX:XX
   ```

3. Reinicia la PC y comprueba que la bocina se reconecta sola. Anota si tarda o si hay que encenderla primero.
4. Verifica el **perfil A2DP**, que es el de buena calidad. El diagnóstico lo muestra en la sección «Bluetooth: perfil de audio activo». Si dice `headset`, `hfp` o `hsp`, cámbialo en *Configuración de sonido → Dispositivos* a un perfil «A2DP» o «High Fidelity».
5. **Prueba de sueño:** deja la bocina 15–30 minutos sin sonido y reproduce algo. Anota si:
   - se apagó sola,
   - se desconectó, o
   - se pierde el primer medio segundo del sonido.

> Fijar A2DP permanentemente y evitar que el audio «se duerma» se hace en WirePlumber. La configuración exacta depende de su versión, que aparece en el informe. VOXA la incluirá en `deploy/wireplumber/`; en esta fase solo se diagnostica.

**Colocación:** la bocina debe quedar lejos del micrófono de la PC y sin apuntar hacia él.

## 4. Spotifast

Spotifast se publica como AppImage, Flatpak y archivo `.tar.gz` (ver [descargas](https://spotifast.rocks/)). Necesita **glibc 2.39 o mayor**, que trae Linux Mint 22; el informe lo indica en la fila «glibc».

**Recomendado (Mint 22): AppImage**, que se actualiza sola:

```bash
mkdir -p ~/Applications ~/.local/bin
mv ~/Descargas/spotifast-*-x86_64.AppImage ~/Applications/spotifast.AppImage   # o ~/Downloads
chmod +x ~/Applications/spotifast.AppImage
ln -sf ~/Applications/spotifast.AppImage ~/.local/bin/spotifast
spotifast
```

- Si no abre por falta de FUSE: `sudo apt install libfuse2t64`, o ejecútala con `--appimage-extract-and-run`.
- Si la actualización automática no funciona con el nombre cambiado, conserva el nombre original del archivo y apunta el enlace a él.

**Solo si glibc es menor a 2.39 (Mint 21):** usa el Flatpak (`flatpak install --user <archivo>.flatpak`). El comando será `flatpak run rocks.spotifast.Spotifast`, y el sandbox podría limitar el control desde VOXA; anótalo en los resultados.

Configuración dentro de Spotifast:
1. Inicia sesión con la cuenta Premium.
2. En la barra inferior, abre el menú de dispositivos → **Set up playback here** y aprueba en el navegador.
3. **Ajustes:** renombra el dispositivo a **VOXA Cocina**.
4. **Ajustes → Playback on this computer:** activa iniciar con la computadora en modo **In the tray** y mantén «Keep music playing when the window closes».

Pruebas (con algo sonando):

```bash
spotifast now-playing --raw
spotifast devices --raw
spotifast play-search --kind artist Soda Stereo
playerctl --list-all
playerctl --player=spotifast play-pause
```

Abre Spotify en tu teléfono y comprueba que aparece **VOXA Cocina** como dispositivo.

## 5. App de Spotify for Developers

VOXA usará la Web API para buscar y reproducir por voz.

1. Entra a <https://developer.spotify.com/dashboard> con la cuenta **Premium** y crea una app:
   - Nombre: `VOXA`. Descripción: «Asistente de voz familiar».
   - **Redirect URI:** `http://127.0.0.1:8765/callback`. Usa exactamente esa dirección: Spotify ya no acepta `localhost`.
   - API: marca **Web API**.
2. Copia el **Client ID**. **No** hace falta el *Client secret*: VOXA usará OAuth con PKCE.
3. En **User Management**, agrega a los miembros de la familia que usarán su propia cuenta.

> Las reglas cambiaron en febrero de 2026:
> - En *Development Mode*, la persona dueña de la app **debe tener Premium**; si lo pierde, la app deja de funcionar.
> - Hay un máximo de **5 usuarios autorizados**.
> - La búsqueda devuelve hasta 10 resultados por petición.
>
> Para uso familiar es suficiente.

Guarda el Client ID y no lo subas al repositorio.

### 5.1 Probar VOXA con Spotify real (modo texto)

El núcleo de VOXA ya entiende órdenes escritas. Esto valida de punta a punta Web API + Spotify Connect + Spotifast:

```bash
pipx install .                                   # desde la carpeta del proyecto
mkdir -p ~/.config/voxa
cp config/default.toml ~/.config/voxa/config.toml
nano ~/.config/voxa/config.toml                  # pega el Client ID en [spotify] client_id
voxa spotify-login                               # abre el navegador; autoriza una sola vez
voxa texto
```

Con Spotifast abierto, escribe por ejemplo:
- `pon Soda Stereo`
- `qué canción es esta`
- `pausa`
- `súbele`
- `temporizador de un minuto para la prueba`

Para ver qué capa respondió (Web API, CLI de Spotifast o MPRIS), usa `voxa -v texto`. Anota cualquier frase que no entienda.

## 6. Grabaciones de prueba

```bash
bash scripts/fase0/grabar_pruebas.sh          # todo: ruido, «Hey Voxa» y frases
bash scripts/fase0/grabar_pruebas.sh frases   # solo una sección: ruido | wake | frases
```

- Pide permiso a cada persona que grabe; idealmente graben al menos dos personas distintas en otra ronda.
- «Hey Voxa» se graba a 1, 2 y 3 m, con y sin música en la bocina (~60 % de volumen).
- Las 30 frases están en `scripts/fase0/frases_stt.txt`; se puede repetir cada una.
- Los audios quedan en `~/voxa-fase0/audio/` y **no se comparten**. Para borrarlos: `rm -r ~/voxa-fase0/audio`.

## 7. Benchmarks

### Reconocimiento de voz (STT)

```bash
python3 -m venv ~/voxa-fase0/venv
~/voxa-fase0/venv/bin/pip install vosk faster-whisper
```

Descarga el modelo **español pequeño** de Vosk desde <https://alphacephei.com/vosk/models>. Descomprímelo en `~/voxa-fase0/modelos/`.

```bash
~/voxa-fase0/venv/bin/python scripts/fase0/bench_stt.py \
  --vosk-model ~/voxa-fase0/modelos/<carpeta-del-modelo> \
  --whisper-sizes tiny,base,small
```

- La primera vez, faster-whisper descarga sus modelos y necesita internet.
- Si `small` tarda demasiado, quítalo de la lista.
- Resultado: tabla en pantalla y `~/voxa-fase0/bench_stt.md`.

### Cadena completa con voces sintéticas (sin grabar)

Mide en este equipo la velocidad y la precisión de voz → intención sobre las ~100 frases del corpus. Requiere VOXA instalado con `pip install -e ".[audio]"` y los modelos en `models/`:

```bash
python scripts/evaluar_voz.py --voz models/piper/es_MX-ald-medium.onnx \
  --vosk models/vosk/vosk-model-small-es-0.42 --whisper base
python scripts/evaluar_voz.py ... --whisper small    # ¿vale la pena el modelo grande aquí?
python scripts/evaluar_voz.py ... --ruido-db 10      # con ruido de cocina
```

Copia las tablas a los resultados. Referencia de la PC de desarrollo con la voz `es_MX-claude-high`: híbrido 81 % (base, p90 0.5 s) y 87 % (small, p90 1.5 s).

### Voz de VOXA (TTS)

```bash
bash scripts/fase0/bench_tts.sh                                  # muestra cómo instalar Piper y elegir voz
bash scripts/fase0/bench_tts.sh ~/voxa-fase0/voces/<voz>.onnx    # mide y genera WAV para escuchar
```

Escuchen los WAV en familia y elijan la voz.

## 8. Qué enviar de vuelta

- ✅ `~/voxa-fase0/informe-<fecha>.md`, el más reciente.
- ✅ `~/voxa-fase0/bench_stt.md` y la salida de `bench_tts.sh`.
- ✅ La plantilla de resultados de abajo, llenada.
- ❌ **Nunca** los audios de `~/voxa-fase0/audio/`.

---

## Plantilla de resultados

Copia esto en `docs/fase0_resultados.md` y llénalo:

```markdown
# VOXA — Resultados de la Fase 0

Fecha:
Quién lo corrió:

## Equipo
- CPU / hilos / AVX2:
- RAM:
- Linux Mint (versión y edición):
- Servidor de audio / versión de WirePlumber:

## Bocina Bluetooth
- Modelo:
- ¿Se reconecta sola al reiniciar? (sí / no / a veces):
- Perfil activo (A2DP / otro):
- Tras 15–30 min en silencio: (sigue conectada / se desconecta / se apaga / pierde el inicio del sonido):
- ¿Se puede dejar conectada a la corriente?:

## Micrófono
- Micrófono usado (integrado / USB):
- Impresión al escuchar las grabaciones (1 m / 2 m / 3 m, con y sin música):

## Spotifast
- Forma de instalación (AppImage / Flatpak / tar.gz) y versión:
- ¿Aparece «VOXA Cocina» en el teléfono?:
- ¿Funcionan `spotifast now-playing --raw` y `playerctl --player=spotifast play-pause`?:
- ¿Arranca en la bandeja al iniciar sesión?:
- RAM de Spotifast reproduciendo (Monitor del sistema):

## Spotify for Developers
- App creada (sí / no) · usuarios autorizados:
- `voxa spotify-login` (funcionó / error):
- En `voxa texto`: ¿«pon Soda Stereo» suena en VOXA Cocina? ¿Qué capa respondió?:
- Frases que VOXA no entendió:

## STT (pegar tabla de bench_stt.md)

## TTS
- Voz elegida:
- Tiempo de síntesis de la frase larga:

## Decisiones propuestas
- Micrófono:
- Motor STT para comandos:
- Motor STT para texto libre:
- Voz TTS:
- Pendientes / problemas encontrados:
```

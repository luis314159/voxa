# VOXA: backlog

Lo que falta para que VOXA sea un producto excelente para familias, en orden de prioridad.

## Ahora

1. **Probar en una cocina real.** Nada de lo hecho ha corrido en la PC de la cocina con la familia. Hay que:
   - instalar el `.deb`;
   - correr «aprende mi voz» con cada persona;
   - usarla dos semanas y revisar «Cómo va VOXA» (celular o `voxa como-va`): lo que no entendió, activaciones falsas, tiempos.

   Luego, dársela a 2 o 3 familias más. Con eso se miden:
   - qué tan seguido se activa «Hey Voxa» por error y qué tan seguido no oye;
   - qué tan seguido entiende la orden;
   - si reconoce bien a cada persona.
2. **Inglés y casas bilingües, en una casa real.** Ya está todo en inglés (también recetas, conversiones, pantalla, celular y «aprende mi voz») y el modo bilingüe contesta cada frase en su idioma. Falta medirlo con una familia:
   - qué tan seguido Whisper confunde el idioma en órdenes muy cortas;
   - si conviene un Vosk cerrado también para el otro idioma (hoy las órdenes cortas solo van rápido en el idioma de la casa);
   - nombres de temporizadores entre idiomas: «the rice timer» no encuentra el temporizador «arroz».
3. **Spotifast:** sus comandos (`play-search --kind`, `now-playing --raw`, `like`) ya se confirmaron con Spotifast 0.14 en Windows; falta verlos en la PC de la cocina con `voxa -v texto`.

## Siguiente

- **Agregar al calendario por voz** («agrega dentista el martes a las 5»). Hoy solo se lee el iCal; escribir requiere conectar la cuenta de Google con OAuth.
- **Spotify por persona:** cada quien conecta su cuenta, y «pon mis me gusta» usa la de quien habla.
- **Reconocer mejor a quien habla en órdenes muy cortas:**
  - sumar el audio de «Hey Voxa» al de la orden;
  - ajustar el prototipo poco a poco con las órdenes en que VOXA esté muy segura (voz con catarro, niños que crecen).
- **Privacidad visible:**
  - una página en el celular que explique qué se queda en la PC y qué sale a internet;
  - una marca en la pantalla cuando la IA (de paga) está encendida.
- **Apodos en todo:** «los pendientes de papá» y «¿qué tiene mamá hoy?» con los apodos de Ajustes (hoy solo las notas los usan).
- **Modo niños, siguiente paso:** con YouTube no se sabe si una canción es explícita; probar si YouTube Music lo expone, o un filtro por letra.

## Producto e instalación

- **Imagen lista para Raspberry Pi:** se graba, se conecta y se configura desde el celular, sin instalar nada.
- **Repositorio apt firmado:** actualizaciones por el Gestor de actualizaciones de Mint, en lugar del temporizador nocturno.
- **Ubuntu 22.04:** su polkit no lee reglas JavaScript, así que «actualízate» no arranca ahí la actualización (la nocturna sí funciona). Opción: una regla `.pkla` o un servicio de usuario con un puente.
- **Satélites mínimos:** solo micrófono y bocina (por ejemplo una ESP32-S3 o una Raspberry Pi Zero 2 W) que mandan el audio a la principal, en lugar de una VOXA completa por cuarto.
- **Llamar a alguien por la casa:** «llama a Ana» usa el reconocimiento de voz para saber en qué cuarto habló Ana por última vez.
- **Versión para Windows** (no es prioridad). Lo investigado:
  - Spotifast ya tiene versión para Windows y sus comandos son los mismos;
  - en lugar de PipeWire: volumen y bajar la música con pycaw; cancelación de eco con el mismo algoritmo de WebRTC (librería livekit, Apache 2.0) y lo que suena en las bocinas capturado con PyAudioWPatch como referencia (en una prueba con eco sintético quitó 35 dB);
  - mpv por *named pipe*, arranque con una tarea programada e instalador `.exe`;
  - unas 3 sesiones de trabajo, sin tocar la versión de Linux.

## Calidad

- **Probar motores más nuevos en la PC real** (con `scripts/evaluar_voz.py`; ideas de los que compara VoiceStudio, sin usar su código, que es AGPL):
  - voz: Kokoro (Apache 2.0, por sherpa-onnx; trae español e inglés) contra Piper, midiendo naturalidad y cuánto tarda la primera frase en CPU;
  - reconocimiento: Parakeet TDT (25 idiomas, rápido en CPU) y SenseVoice (detecta el idioma, útil para casas bilingües; revisar su licencia) contra Whisper *base*;
  - descargar de memoria los modelos que no se usan un rato, si la PC tiene poca RAM.
- **Voz en inglés con licencia abierta:** cambiar Lessac (licencia de investigación) por LibriTTS-R o Kokoro después de escucharlas ([docs/licencias.md](licencias.md)).

- **Más frases de familias reales** en el corpus de pruebas (`tests/data/utterances.yaml`), con acentos de distintas regiones.
- **Accesibilidad:**
  - habla más lenta para abuelos;
  - letra grande en la pantalla;
  - repetir sin «Hey Voxa» justo después de una respuesta.

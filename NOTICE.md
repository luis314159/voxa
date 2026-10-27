# Licencias de VOXA

## El código de VOXA: AGPL-3.0

Copyright (C) 2026 Luis Ángel Almazán López

VOXA es software libre: se puede usar, copiar, estudiar, cambiar y compartir gratis, bajo la
[GNU Affero General Public License](LICENSE), versión 3 o (a elección de quien lo use) cualquier
versión posterior (`AGPL-3.0-or-later`).

En pocas palabras: quien reparta VOXA, con o sin cambios, o la ofrezca a otros por la red (por
ejemplo, la página del celular), tiene que dar también el código completo con sus cambios, bajo
esta misma licencia. VOXA se da sin garantía de ningún tipo. El texto que vale es el de
[LICENSE](LICENSE).

La AGPL cubre todo lo de este repositorio salvo lo que se lista abajo.

## Lo que tiene su propia licencia

### El modelo de «Hey Voxa»: CC BY-NC-SA 4.0

`src/voxa/audio/hey_voxa.npz` se entrenó con datos de [openWakeWord](https://github.com/dscripka/openWakeWord)
que tienen licencia [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.es), así
que el modelo queda bajo esa licencia: uso no comercial, dando crédito y compartiendo igual. Cómo se
entrenó: [scripts/hey_voxa/](scripts/hey_voxa/README.md).

### La voz en inglés «Lessac»: la licencia de sus datos, no la AGPL

La voz `en_US-lessac-medium` de [Piper](https://huggingface.co/rhasspy/piper-voices/tree/v1.0.0/en/en_US/lessac/medium)
**no es parte de VOXA ni viene en este repositorio o en sus paquetes**: VOXA la baja de su fuente
la primera vez que una casa elige inglés (o casa bilingüe), con su huella SHA-256. La AGPL de VOXA
no la cubre.

Se entrenó con los datos de Lessac Technologies del [Blizzard Challenge 2013](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/),
cuya [licencia](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html) se
otorga a quien la firma y es para investigación, sin uso comercial. Esos términos son los que
aplican a la voz: usarla solo en casa, sin fines comerciales, y no volver a repartirla. Para un uso
distinto hay que cambiarla por otra voz de inglés con licencia abierta (ver [docs/licencias.md](docs/licencias.md)).

### Los demás modelos y programas

Los modelos que VOXA baja (voz en español, Vosk, Whisper, la base de «Hey Voxa», el modelo para
saber quién habla) y los programas que usa (piper-tts, Vosk, faster-whisper, Spotifast, yt-dlp, mpv)
conservan sus licencias. La lista completa, con de dónde viene cada uno y los créditos que piden,
está en [docs/licencias.md](docs/licencias.md).

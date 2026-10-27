# VOXA: backlog

Lo que falta para que VOXA sea un producto excelente para familias, en orden de prioridad.

## Ahora

1. **Probar en una cocina real.** Nada de lo hecho ha corrido en la PC de la cocina con la familia. Hay que:
   - instalar el `.deb`;
   - correr «aprende mi voz» con cada persona;
   - usarla dos semanas y revisar el registro de lo que no entendió.

   Luego, dársela a 2 o 3 familias más. Con eso se miden:
   - qué tan seguido se activa «Hey Voxa» por error y qué tan seguido no oye;
   - qué tan seguido entiende la orden;
   - si reconoce bien a cada persona.
2. **Inglés** (en curso), para familias bilingües. Por partes:
   1. Idioma de la casa (`language = "es" | "en"`), con su propia gramática, números y horas.
   2. Voz de Piper en inglés y modelo de Vosk en inglés, con sus huellas; Whisper con el idioma fijo.
   3. Respuestas en un catálogo por idioma, empezando por temporizadores, música, volumen, lista del súper, hora y clima.
   4. Lo demás (recetas, calendario, pendientes, casa) a medida que se traduzca.
   5. Después, las dos lenguas a la vez: Whisper detecta el idioma de cada frase y VOXA contesta en ese idioma.
3. **Confirmar los comandos de Spotifast en la PC real.** VOXA usa `play-search`, `now-playing --raw` y `like`, pero la documentación pública solo muestra `spotifast [LINK]`. Si no existen, la capa de Spotifast se salta sola; hay que revisarlo con `voxa -v texto`.

## Siguiente

- **Modo niños:**
  - sin canciones explícitas (Spotify trae la marca `explicit`);
  - volumen máximo;
  - respuestas de la IA para niños;
  - horario en que los niños pueden pedir videos.
- **Horas de silencio:**
  - de noche, voz bajita y sin sonidos fuertes;
  - las alarmas siguen sonando, pero sin avisar en los otros cuartos.
- **Medicinas con confirmación:** «Ana, ¿ya te tomaste la medicina?». Si no contesta, se repite y se avisa a otra persona.
- **Notas y mensajes:** «déjale una nota a papá» aparece en la pantalla y se dice cuando VOXA reconoce su voz.
- **Agregar al calendario por voz** («agrega dentista el martes a las 5»). Hoy solo se lee el iCal; escribir requiere conectar la cuenta de Google con OAuth.
- **Spotify por persona:** cada quien conecta su cuenta, y «pon mis me gusta» usa la de quien habla.
- **Reconocer mejor a quien habla en órdenes muy cortas:**
  - sumar el audio de «Hey Voxa» al de la orden;
  - ajustar el prototipo poco a poco con las órdenes en que VOXA esté muy segura (voz con catarro, niños que crecen).
- **Privacidad visible:**
  - una página en el celular que explique qué se queda en la PC y qué sale a internet;
  - una marca en la pantalla cuando la IA (de paga) está encendida.

## Producto e instalación

- **Imagen lista para Raspberry Pi:** se graba, se conecta y se configura desde el celular, sin instalar nada.
- **Repositorio apt firmado:** actualizaciones por el Gestor de actualizaciones de Mint, en lugar del temporizador nocturno.
- **Ubuntu 22.04:** su polkit no lee reglas JavaScript, así que «actualízate» no arranca ahí la actualización (la nocturna sí funciona). Opción: una regla `.pkla` o un servicio de usuario con un puente.
- **Satélites mínimos:** solo micrófono y bocina (por ejemplo una ESP32-S3 o una Raspberry Pi Zero 2 W) que mandan el audio a la principal, en lugar de una VOXA completa por cuarto.
- **Llamar a alguien por la casa:** «llama a Ana» usa el reconocimiento de voz para saber en qué cuarto habló Ana por última vez.

## Calidad

- **Mediciones del uso real** (solo en esa PC):
  - frases no entendidas;
  - activaciones falsas por hora;
  - tiempo de respuesta;
  - aciertos al reconocer a la persona.

  En el celular, una página de «cómo va VOXA».
- **Más frases de familias reales** en el corpus de pruebas (`tests/data/utterances.yaml`), con acentos de distintas regiones.
- **Accesibilidad:**
  - habla más lenta para abuelos;
  - letra grande en la pantalla;
  - repetir sin «Hey Voxa» justo después de una respuesta.

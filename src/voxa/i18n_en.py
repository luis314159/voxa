"""English for what VOXA says. The key is the Spanish template (``voxa.i18n.tr``) or fixed phrase.

Templates get the same values as in Spanish; some use other names that the Spanish one ignores
(«{name}» instead of «{of}», for «the rice timer»).
"""

EN: dict[str, str] = {
    # --- timers and alarms -----------------------------------------------------------------------
    "¡Terminaron los {duration}!": "Your {duration} timer is done!",
    "{person}, es la hora.": "{person}, it's time.",
    "¡Son {hour}!": "It's {hour}!",
    "¡Terminó el temporizador {of}!": "The {label} timer is done!",
    "le recuerdo a {person}": "I'll remind {person} to",
    "te recuerdo": "I'll remind you to",
    "Todavía no sé hacer eso con los temporizadores.": "I can't do that with timers yet.",
    "de {duration}": "{duration}",
    "{person}, te recuerdo: {label}.": "{person}, this is your reminder: {label}.",
    "Te recuerdo: {label}.": "Reminder: {label}.",
    "No hay ninguna alarma sonando.": "No alarm is ringing.",
    "Puedo poner temporizadores de hasta 24 horas.": "I can set timers for up to 24 hours.",
    "No entendí la hora. Prueba con «a las 8 de la noche».": "I didn't get the time. Try «at 8 pm».",
    "mañana a {hour}": "tomorrow at {hour}",
    "a {hour}": "at {hour}",
    "Alarma para {when}.": "Alarm set for {when}.",
    "{days} a {hour}": "{days} at {hour}",
    "el {day} a {hour}": "on {day} at {hour}",
    "Alarma {when}.": "Alarm set {when}.",
    " {to}": " to the {label} timer",
    "Le quité {duration}{whom}: {left}.": "Took {duration} off{whom}: {left}.",
    "Le agregué {duration}{whom}: {left}.": "Added {duration}{whom}: {left}.",
    "Sigue el temporizador {of}: {left}.": "The {name} timer is running again: {left}.",
    "Tienes {count}: {items}.": "You have {count}: {items}.",
    "{what}, {day}a {hour}": "{what}, {day}at {hour}",
    " (en pausa)": " (paused)",
    "Cancelé el temporizador {of}.": "Canceled the {name} timer.",
    "No entendí para cuándo. Dime, por ejemplo: «alarma a las siete» o «temporizador de diez minutos».":
        "I didn't get when. Say, for example, «alarm at seven» or «timer for ten minutes».",
    "{duration}. Empezando.": "{duration}. Starting now.",
    "Te aviso en {duration}.": "I'll let you know in {duration}.",
    "¿A cuál? Tienes {names}.": "Which one? You have {names}.",
    "¿Cuál? Tienes {names}.": "Which one? You have {names}.",
    "Pausé el temporizador {of}; quedan {left}.": "Paused the {name} timer; {left} left.",
    "El temporizador {of} no estaba en pausa.": "The {name} timer wasn't paused.",
    "El temporizador {of} ya estaba en pausa.": "The {name} timer was already paused.",
    "No hay temporizadores.": "There are no timers.",
    " para {label}": " for {label}",
    "alarma": "alarm",
    "{what}, {days} a {hour}": "{what}, {days} at {hour}",
    "mañana ": "tomorrow ",
    "{duration} para {label}.": "{duration} for {label}.",
    "el {day} ": "on {day} ",
    "No encontré un temporizador {of}.": "I couldn't find a {name} timer.",
    "Cancelé todos los temporizadores.": "Canceled all timers.",
    # --- music -----------------------------------------------------------------------------------
    "No pude conectar con Spotify. Revisa que Spotifast esté abierto.": "I couldn't reach Spotify. Check that Spotifast is open.",
    "No pude conectar con Spotify. Revisa que Spotifast esté abierto. Además, falta autorizar Spotify en VOXA.":
        "I couldn't reach Spotify. Check that Spotifast is open. Also, Spotify still needs to be connected to VOXA.",
    "Para tus Me gusta, vuelve a conectar Spotify desde el celular: Ajustes, Spotify, «Conectar con Spotify».":
        "For your liked songs, reconnect Spotify from your phone: Settings, Spotify, «Connect with Spotify».",
    "Modo aleatorio.": "Shuffle on.",
    "Guardada en tus Me gusta.": "Saved to your liked songs.",
    "Todavía no sé hacer eso con la música.": "I can't do that with music yet.",
    "No encontré eso: «{what}».": "I couldn't find that: «{what}».",
    "No está sonando nada.": "Nothing is playing.",
    "No encontré playlists en tu cuenta de Spotify.": "I didn't find any playlists in your Spotify account.",
    "una playlist": "one playlist",
    "{count} playlists": "{count} playlists",
    "Tienes {count}: {items}. Dime «pon mi playlist» y su nombre; en el celular están todas.":
        "You have {count}: {items}. Say «play my playlist» and its name; they're all on your phone too.",
    "Pasando la música a {device}.": "Moving the music to {device}.",
    "No encontré ese dispositivo: «{what}».": "I couldn't find that device: «{what}».",
    "{title}, de {artist}.": "{title}, by {artist}.",
    "{title}, de {artist}": "{title}, by {artist}",
    "{count} más": "{count} more",
    "El álbum {title}": "The album {title}",
    "El álbum {title}, de {artist}": "The album {title}, by {artist}",
    "La playlist {title}": "The playlist {title}",
    "Tus Me gusta, en aleatorio": "Your liked songs, shuffled",
    # --- volume -----------------------------------------------------------------------------------
    "Todavía no sé hacer eso con el volumen.": "I can't do that with the volume yet.",
    "No pude cambiar el volumen.": "I couldn't change the volume.",
    "Volumen al {percent}.": "Volume at {percent}.",
    # --- shopping list ------------------------------------------------------------------------------
    "Todavía no sé hacer eso con la lista.": "I can't do that with the list yet.",
    "¿Qué agrego a la lista?": "What should I add to the list?",
    "Agregué {items} a la lista.": "Added {items} to the list.",
    "Quité {items} de la lista.": "Removed {items} from the list.",
    "La lista del súper está vacía.": "The shopping list is empty.",
    "En la lista hay {count} cosas: {items}.": "There are {count} things on the list: {items}.",
    "En la lista hay una cosa: {items}.": "There's one thing on the list: {items}.",
    "{items} ya estaban en la lista.": "{items} were already on the list.",
    "{items} ya estaba en la lista.": "{items} was already on the list.",
    "No encontré {items} en la lista.": "I didn't find {items} on the list.",
    "Borré la lista del súper.": "I cleared the shopping list.",
    "La lista ya estaba vacía.": "The list was already empty.",
    # --- kitchen conversions and recipes ----------------------------------------------------------------
    "{degrees} grados Fahrenheit son {celsius} grados centígrados.": "{degrees} degrees Fahrenheit is {celsius} degrees Celsius.",
    "{degrees} grados centígrados son {fahrenheit} grados Fahrenheit.": "{degrees} degrees Celsius is {fahrenheit} degrees Fahrenheit.",
    "No hay ninguna receta abierta. Pídeme una, por ejemplo: «dame la receta de arroz rojo».":
        "No recipe is open. Ask me for one, for example: «give me a recipe for pancakes».",
    "¿De cuánto? Di, por ejemplo, «temporizador de 10 minutos».": "For how long? Say, for example, «a 10 minute timer».",
    "Esta receta no trae lista de ingredientes.": "This recipe doesn't have an ingredient list.",
    "Para {title} necesitas: {items}.": "For {title} you need: {items}.",
    "Ese era el último paso. ¡Buen provecho! Di «termina la receta» para cerrarla.":
        "That was the last step. Enjoy! Say «finish the recipe» to close it.",
    "Todavía no empezamos {title}. Di «siguiente paso» para empezar.": "We haven't started {title} yet. Say «next step» to begin.",
    "La receta tiene {total} pasos.": "The recipe has {total} steps.",
    "Todo eso ya estaba en la lista.": "All of that was already on the list.",
    "Esta receta no trae ingredientes.": "This recipe has no ingredients.",
    " {count} ya estaba.": " {count} was already there.",
    " {count} ya estaban.": " {count} were already there.",
    "Agregué una cosa a la lista.{extra}": "Added one thing to the list.{extra}",
    "Agregué {count} cosas a la lista.{extra}": "Added {count} things to the list.{extra}",
    "Cerré la receta de {title}.": "I closed the {title} recipe.",
    "Todavía no sé hacer eso con la receta.": "I can't do that with the recipe yet.",
    "Déjame ver la receta de {dish}…": "Let me look up a recipe for {dish}…",
    "Para recetas paso a paso hay que activar la IA en la configuración.":
        "For step by step recipes, turn on the AI in Settings on your phone.",
    "{ingredients} ingredientes y {steps} pasos": "{ingredients} ingredients and {steps} steps",
    "{steps} pasos": "{steps} steps",
    "{title}, para {servings} porciones: son {count}. Di «los ingredientes» para que te los lea, o «siguiente paso» para empezar.":
        "{title}, for {servings} servings: {count}. Say «the ingredients» and I'll read them, or «next step» to start.",
    "Paso {number} de {total}: {text}": "Step {number} of {total}: {text}",
    " Si quieres, di «pon el tiempo» y cuento {duration}.": " If you want, say «start the timer» and I'll count {duration}.",
    "el paso {number} de la receta": "recipe step {number}",
    "Listo: {duration} para {label}.": "Done: {duration} for {label}.",
    "receta de {dish}": "{dish} recipe",
    "No encontré un video de «{what}».": "I couldn't find a video of «{what}».",
    "Poniendo: {title}.": "Playing: {title}.",
    "Es «{title}».": "It's «{title}».",
    # --- weather ----------------------------------------------------------------------------------------
    "Aún no sé dónde estamos. Agrega la ubicación en la configuración.":
        "I don't know where we are yet. Add your city in Settings on your phone.",
    "No pude consultar el clima.": "I couldn't get the weather.",
    "No parece. La probabilidad de lluvia es de {rain} %.": "Doesn't look like it. The chance of rain is {rain} percent.",
    "Ahora hay {now} grados y está {sky}. Hoy, máxima de {high} y mínima de {low}.":
        "It's {now} degrees and {sky}. Today, a high of {high} and a low of {low}.",
    "Sí, probablemente. Hay {rain} % de probabilidad de lluvia.": "Yes, probably. There's a {rain} percent chance of rain.",
    "Tal vez. Hay {rain} % de probabilidad de lluvia.": "Maybe. There's a {rain} percent chance of rain.",
    " Probabilidad de lluvia: {rain} %.": " Chance of rain: {rain} percent.",
    "despejado": "clear",
    "parcialmente nublado": "partly cloudy",
    "nublado": "cloudy",
    "con niebla": "foggy",
    "con llovizna": "drizzling",
    "lloviendo": "raining",
    "nevando": "snowing",
    "con chubascos": "showery",
    "con tormenta": "stormy",
    "variable": "changing",
    # --- system -------------------------------------------------------------------------------------------
    "Aquí estoy.": "I'm here.",
    "Micrófono apagado. Toca la pantalla para reactivarme.": "Microphone off. Touch the screen to wake me up.",
    "¡De nada!": "You're welcome!",
    "Aquí estoy, pero {problems}.": "I'm here, but {problems}.",
    "me faltan los modelos de voz": "my voice models are missing",
    "no encuentro el micrófono": "I can't find the microphone",
    "no puedo escuchar «Hey Voxa»": "I can't listen for «Hey Voxa»",
    "no tengo internet": "I have no internet",
    "falta conectar Spotify": "Spotify isn't connected",
    "Spotifast no responde": "Spotifast isn't responding",
    "no puedo usar la IA": "I can't use the AI",
    # what the screen shows in amber
    "Sin internet": "No internet",
    "Falta conectar Spotify": "Spotify isn't connected",
    "«Hey Voxa» no está disponible": "«Hey Voxa» isn't available",
    "Faltan los modelos de voz": "The voice models are missing",
    "La IA no está lista": "The AI isn't ready",
    "La IA no funciona": "The AI isn't working",
    "No te entendí. Puedes preguntarme «¿qué puedes hacer?».": "Sorry, I didn't get that. You can ask me «what can you do?».",
    "Algo salió mal. Inténtalo de nuevo.": "Something went wrong. Please try again.",
    "Todavía no sé hacer eso.": "I can't do that yet.",
    "Todavía no sé poner videos: falta instalar mpv y yt-dlp.": "I can't play videos yet: mpv and yt-dlp are missing.",
    "No he dicho nada todavía.": "I haven't said anything yet.",
    (
        "Puedo poner música de Spotify, por ejemplo «pon Soda Stereo» o «pon algo tranquilo para cocinar»; "
        "poner temporizadores, como «temporizador de diez minutos para el arroz», "
        "y recordatorios, como «recuérdame sacar la basura a las 8» o «despiértame de lunes a viernes a las 6»; "
        "subir o bajar el volumen, decirte la hora y el clima. "
        "También pongo videos de recetas: «pon un video de cómo hacer pozole». "
        "Si quieres que deje de escuchar, di «deja de escuchar»."
    ): (
        "I can play music, like «play Soda Stereo» or «play some music for cooking»; set timers, like "
        "«set a timer for ten minutes for the rice», and reminders, like «remind me to take out the trash at 8 pm» "
        "or «wake me up on weekdays at 6»; turn the volume up or down, and tell you the time and the weather. "
        "I keep the shopping list, your to do list and your calendar. "
        "If you want me to stop listening, say «stop listening»."
    ),
    "No encuentro el micrófono.": "I can't find the microphone.",
    "Sí: hay la versión {new}; tienes la {current}. Di «actualízate» para instalarla.":
        "Yes: version {new} is out; you have {current}. Say «update yourself» to install it.",
    "Estoy al día: tengo la versión {current}.": "I'm up to date: I have version {current}.",
    "Ya tengo la versión más reciente, la {current}.": "I already have the latest version, {current}.",
    "Me actualizo a la versión {new}. En unos minutos vuelvo.": "Updating to version {new}. I'll be back in a few minutes.",
    # --- AI -------------------------------------------------------------------------------------------------------
    "Ya se usó el presupuesto de IA de este mes. Se puede subir en la configuración.":
        "This month's AI budget is used up. You can raise it in Settings.",
    "Ya respondí muchas preguntas hoy; mañana sigo. Mientras, pregúntame lo de siempre.":
        "I've answered a lot of questions today; more tomorrow. Meanwhile, ask me the usual things.",
    "No pude conectar con la IA. Inténtalo en un momento.": "I couldn't reach the AI. Try again in a moment.",
    "No puedo usar la IA: hay que revisar su configuración.": "I can't use the AI: its settings need a look.",
    "Prefiero no responder eso.": "I'd rather not answer that.",
    "No supe qué responder. ¿Me lo dices de otra forma?": "I didn't know what to say. Can you put it another way?",
    # --- good morning / night -------------------------------------------------------------------------------
    "Buenos días": "Good morning",
    "Buenas tardes": "Good afternoon",
    "Buenas noches": "Good evening",
    "Buenas noches.": "Good night.",
    "Buenas noches. Te aviso: {items}.": "Good night. Heads up: {items}.",
    "¡{greeting}, {person}!": "{greeting}, {person}!",
    "¡{greeting}!": "{greeting}!",
    "Hoy tienes: {items}.": "Today you have: {items}.",
    " y {rain} % de probabilidad de lluvia": " and a {rain} percent chance of rain",
    "Hay {now} grados; hoy, máxima de {high}{rain}.": "It's {now} degrees; today's high is {high}{rain}.",
    "{what} a {hour}": "{what} at {hour}",
    "la alarma": "the alarm",
    # --- to do list ------------------------------------------------------------------------------------------------
    "un pendiente": "one task",
    "{count} pendientes": "{count} tasks",
    "Todavía no sé hacer eso con los pendientes.": "I can't do that with tasks yet.",
    "{who} {count}: {items}.": "{who} {count}: {items}.",
    "Tienes": "You have",
    "Eso ya estaba en los pendientes.": "That was already on the to do list.",
    "los pendientes de {person}": "{person}'s to do list",
    "Anotado en {whose}: {task}.": "Added to {whose}: {task}.",
    " Quedan {count}.": " {count} left.",
    " ¡Ya no hay pendientes!": " Nothing left to do!",
    "{person} tiene": "{person} has",
    "de la casa: {items}.": "for the house: {items}.",
    "tus pendientes": "your to do list",
    "los pendientes de la casa": "the house to do list",
    "No encontré «{task}» en los pendientes.": "I didn't find «{task}» on the to do list.",
    "Listo, taché {task}.": "Done, I crossed off {task}.",
    "{person} no tiene pendientes.": "{person} has nothing to do.",
    "No tienes pendientes.": "You have nothing to do.",
    "No hay pendientes.": "There's nothing on the to do list.",
    # --- calendar ---------------------------------------------------------------------------------------------------
    "una cosa": "one thing",
    "{count} cosas": "{count} things",
    "Todavía no sé hacer eso con el calendario.": "I can't do that with the calendar yet.",
    "{lead} {count}: {events}.": "{lead} {count}: {events}.",
    "{when} tienes {count}: {events}.": "{when} you have {count}: {events}.",
    "Lo siguiente es {title}, {when} a {hour}.": "Next up is {title}, {when} at {hour}.",
    "a {hour}, {title}": "at {hour}, {title}",
    "y {count} más": "and {count} more",
    "todo el día: {items}": "all day: {items}",
    "En el calendario de hoy hay": "Today's calendar has",
    "Mañana": "Tomorrow",
    "{when} no tienes nada en el calendario.": "{when} you have nothing on the calendar.",
    "hoy": "today",
    "mañana": "tomorrow",
    "el {day}": "on {day}",
    "el {day} {number}": "on {day} the {number}",
    "No pude leer el calendario. Revisa la dirección en Ajustes.": "I couldn't read the calendar. Check its address in Settings.",
    "Hoy {person} ya no tiene nada en el calendario.": "{person} has nothing else on the calendar today.",
    "Hoy {person} tiene": "Today {person} has",
    "Hoy tienes": "Today you have",
    "Hoy ya no tienes nada en el calendario.": "You have nothing else on the calendar today.",
    "No tienes nada en el calendario en las próximas dos semanas.": "You have nothing on the calendar for the next two weeks.",
    "No tengo tu calendario. Agrégalo desde el celular, en Ajustes: «conecta mi celular».":
        "I don't have your calendar. Add it from your phone, in Settings: say «connect my phone».",
    "en {minutes} minutos: {title}.": "in {minutes} minutes: {title}.",
    "ya casi empieza: {title}.": "starting now: {title}.",
    # adding to the calendar (Google)
    "cita": "appointment",
    "Listo, lo anoté en el calendario: {title}, {when}.": "Done, it's on the calendar: {title}, {when}.",
    "{day}, todo el día": "{day}, all day",
    "{day} a {hour}": "{day} at {hour}",
    "¿Para cuándo? Dime, por ejemplo, «agrega dentista al calendario el martes a las 5».":
        "For when? Say, for example, «add dentist to the calendar on tuesday at 5».",
    "Para agregar citas, conecta Google Calendar desde el celular: Ajustes, Calendario.":
        "To add appointments, connect Google Calendar from your phone: Settings, Calendar.",
    "No pude agregarlo al calendario. Revisa la conexión de Google en el celular.":
        "I couldn't add it to the calendar. Check the Google connection on your phone.",
    # --- house ------------------------------------------------------------------------------------------------------------
    "Todavía no sé hacer eso con la casa.": "I can't do that with the house yet.",
    "¿Qué aviso?": "What should I announce?",
    "¡A {what}!": "Time to {what}!",
    "No hay otros cuartos con VOXA conectados.": "There are no other rooms with VOXA connected.",
    "Listo, avisé en {places}.": "Done, I announced it in {places}.",
    "No pude avisar: no contesta la VOXA principal.": "I couldn't announce it: the main VOXA isn't answering.",
    "No contesta la VOXA de la cocina; inténtalo en un momento.": "The kitchen VOXA isn't answering; try again in a moment.",
    "No encontré {place} conectada.": "I couldn't find {place} connected.",
    # --- screen, voice, updates, video ---------------------------------------------------------------------------------
    "Todavía no sé hacer eso con la pantalla.": "I can't do that with the screen yet.",
    "Escanea el código con la cámara del celular. Ahí también están los ajustes.":
        "Scan the code with your phone's camera. The settings are there too.",
    "La página del celular está apagada: enabled en [web] de la configuración.": "The phone page is turned off: enabled in [web] in the settings.",
    "Para aprender tu voz necesito el micrófono de la cocina y «Hey Voxa» encendido.":
        "To learn your voice I need the kitchen microphone and «Hey Voxa» turned on.",
    "No pude empezar la actualización. En la terminal: voxa actualizar.": "I couldn't start the update. In a terminal: voxa actualizar.",
    "Ya me estoy actualizando.": "I'm already updating.",
    "No pude poner el video. Revisa la conexión a internet.": "I couldn't play the video. Check the internet connection.",
    "No hay ningún video puesto.": "No video is playing.",
    "Con los videos no hay siguiente ni anterior; pide otro video.": "Videos have no next or previous; ask for another video.",
    "Todavía no sé hacer eso con los videos.": "I can't do that with videos yet.",
    # --- «learn my voice» --------------------------------------------------------------------------------------------------
    "Vamos a grabar tu voz{name}. Cada vez que escuches el sonido, di «Hey Voxa» como me hablarías desde la cocina.":
        "Let's record your voice{name}. Each time you hear the sound, say «Hey Voxa» the way you'd talk to me in the kitchen.",
    "Di «Hey Voxa» ({number} de {total})": "Say «Hey Voxa» ({number} of {total})",
    "No te escucho bien. Acércate al micrófono y vuelve a pedirme que aprenda tu voz.":
        "I can't hear you well. Come closer to the microphone and ask me to learn your voice again.",
    "No te oí. Otra vez, un poco más fuerte.": "I didn't hear you. Once more, a little louder.",
    "Platica normal, sin decir «Voxa»": "Talk normally, without saying «Voxa»",
    (
        "Ahora platícame lo que sea durante veinte segundos, sin decir mi nombre: "
        "qué vas a cocinar, cómo estuvo tu día. Empieza después del sonido."
    ): (
        "Now talk to me about anything for twenty seconds, without saying my name: "
        "what you're cooking, how your day went. Start after the sound."
    ),
    "Aprendiendo tu voz…": "Learning your voice…",
    "Gracias. Dame unos segundos para aprenderla.": "Thanks. Give me a few seconds to learn it.",
    "Guardé tu voz, pero me faltan grabaciones para aprenderla. Repítelo otra vez.":
        "I saved your voice, but I need more recordings to learn it. Please do it once more.",
    "Listo, aunque todavía te confundo a veces. Si no te hago caso, repítelo en un lugar más silencioso.":
        "Done, though I still mix you up sometimes. If I don't answer you, do it again somewhere quieter.",
    "Listo, ya reconozco tu voz.": "Done, I know your voice now.",
    # --- privacy (phone) ----------------------------------------------------------------------------------------
    "Lo que dices: el audio se reconoce en esta PC y no se guarda ni se manda a ningún lado.":
        "What you say: the audio is recognized on this PC and is never saved or sent anywhere.",
    "Las grabaciones de «aprende mi voz» y las voces de la familia.": "The «learn my voice» recordings and the family's voices.",
    "La lista del súper, los pendientes, las notas, las medicinas, los temporizadores y las mediciones de «Cómo va VOXA».":
        "The shopping list, to do lists, notes, medicine, timers and the «How VOXA is doing» measurements.",
    "Las llaves y contraseñas (Spotify, IA, Telegram, calendario), en archivos que solo tu usuario puede leer.":
        "Keys and passwords (Spotify, AI, Telegram, calendar), in files only your user can read.",
    "IA (de paga): solo el texto de las frases que VOXA no entiende sola, nunca el audio, va a {provider}. "
    "En la pantalla se ve la marca «IA» mientras está encendida.":
        "AI (paid): only the text of the sentences VOXA doesn't understand on its own, never the audio, goes to {provider}. "
        "The screen shows an «AI» badge while it's on.",
    "el servicio que se configuró": "the service you set up",
    "Spotify: lo que pides poner y lo que suena, con tu cuenta.": "Spotify: what you ask to play and what's playing, with your account.",
    "YouTube: las búsquedas de música y videos (sin cuenta).": "YouTube: music and video searches (no account).",
    "El clima: la ubicación aproximada de la casa va a Open-Meteo.": "Weather: the house's approximate location goes to Open-Meteo.",
    "El calendario: VOXA lo lee con su dirección secreta (iCal).": "Calendar: VOXA reads it through its secret (iCal) address.",
    "Google Calendar: solo las citas que pides agregar («agrega dentista el martes a las 5»).":
        "Google Calendar: only the appointments you ask to add («add dentist on tuesday at 5»).",
    "Telegram: la lista del súper, solo con los chats que vinculaste.": "Telegram: the shopping list, only with the chats you linked.",
    "Actualizaciones: VOXA pregunta a GitHub si hay versión nueva.": "Updates: VOXA asks GitHub whether there's a new version.",
    "La primera vez: los modelos de voz se bajan de su fuente, con su huella.":
        "The first time: the voice models are downloaded from their source, with their checksum.",
    # --- notes -------------------------------------------------------------------------------------------------
    "{author} te dejó un recado: {text}": "{author} left you a message: {text}",
    "Te dejaron un recado: {text}": "Someone left you a message: {text}",
    "¿Qué le digo?": "What should I tell them?",
    "Listo, dejé la nota en la pantalla.": "Done, the note is on the screen.",
    "Listo, le dejo la nota a {person}: se la digo cuando lo oiga.": "Done, I'll give {person} the note when I hear them.",
    "No hay notas.": "There are no notes.",
    "No tienes recados.": "You have no messages.",
    "Listo, quité los recados.": "Done, I cleared the messages.",
    "No había recados.": "There were no messages.",
    "Todavía no sé hacer eso con las notas.": "I can't do that with notes yet.",
    "para {person}: {text}": "for {person}: {text}",
    "para todos: {text}": "for everyone: {text}",
    "Por cierto, {person}: {notes}": "By the way, {person}: {notes}",
    # --- medicine -------------------------------------------------------------------------------------------------
    "{person}, es hora de tu medicina: {label}. Cuando te la tomes, dime «ya me la tomé».":
        "{person}, it's time for your medicine: {label}. When you've taken it, tell me «I took it».",
    "Es hora de la medicina: {label}. Cuando se la tomen, díganme «ya me la tomé».":
        "It's time for the medicine: {label}. When it's taken, tell me «I took it».",
    "{person}, ¿ya te tomaste la medicina? {label}.": "{person}, did you take your medicine? {label}.",
    "¿Ya se tomaron la medicina? {label}.": "Has the medicine been taken? {label}.",
    "{person} no ha confirmado su medicina de las {hour}: {label}.": "{person} hasn't confirmed their {hour} medicine: {label}.",
    "Nadie confirmó la medicina de las {hour}: {label}.": "No one confirmed the {hour} medicine: {label}.",
    "No hay ninguna medicina pendiente ahorita.": "There's no medicine waiting right now.",
    "Va, te pregunto otra vez en {duration}.": "OK, I'll ask you again in {duration}.",
    "¡Muy bien, {person}! Lo anoté.": "Great, {person}! I wrote it down.",
    "¡Muy bien! Lo anoté.": "Great! I wrote it down.",
    "Hoy no tengo medicinas anotadas.": "I don't have any medicine written down for today.",
    "Sí: {label}, a las {hour}.": "Yes: {label}, at {hour}.",
    "No está confirmada: la de las {hour} ({label}). Se puede marcar desde el celular.":
        "It isn't confirmed: the {hour} one ({label}). You can mark it from your phone.",
    # --- kids mode -------------------------------------------------------------------------------------------------
    "Listo, modo niños para todos: música sin groserías, volumen con tope y la IA para niños. Se apaga desde el celular.":
        "Done, kids mode for everyone: clean music, a volume limit and kid-friendly AI answers. Turn it off from your phone.",
    "El modo niños ya está apagado.": "Kids mode is already off.",
    "El modo niños se apaga desde el celular: Ajustes, Modo niños.": "Kids mode is turned off from your phone: Settings, Kids mode.",
    "Volumen al {percent}, el máximo del modo niños.": "Volume at {percent}, the kids mode limit.",
    "Los videos son de {start} a {end}.": "Videos are from {start} to {end}.",
    # --- leaving in the morning ---------------------------------------------------------------------------------------------
    "un minuto": "one minute",
    "{count} minutos": "{count} minutes",
    "Salen a {hour}: faltan {minutes}.": "You leave at {hour}: {minutes} to go.",
    " No olviden: {items}.": " Don't forget: {items}.",
    "Hoy no hay salida programada; los días de escuela es a {hour}.": "No departure today; on school days it's at {hour}.",
    "La salida era a {hour}.": "You were leaving at {hour}.",
    "Faltan {minutes} para salir (a {hour}).": "{minutes} until you leave (at {hour}).",
    "¡Ya es hora de salir!": "It's time to leave!",
    "¡Hora de salir!": "Time to leave!",
    "Faltan {minutes} para salir.": "{minutes} until you leave.",
    "No tengo hora de salida. Ponla en el celular: Ajustes, Rutina de la mañana.":
        "I don't have a departure time. Set it on your phone: Settings, Morning routine.",
    "Eso todavía solo lo sé hacer en español.": "I can only do that in Spanish for now.",
}

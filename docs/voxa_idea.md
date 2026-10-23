# VOXA — Asistente de voz familiar para Linux

## 1. Visión

**VOXA** es un asistente de voz para el hogar, pensado para reutilizar una PC All-in-One antigua con Linux Mint. Se usa sin teclado ni mouse: una persona dice **«Hey Voxa»**, VOXA escucha la petición y controla música, videos y funciones del equipo. La primera versión se centra en comandos útiles y fiables; la IA conversacional queda como función opcional.

**Frase de marca:** *Tu voz, tu hogar, más fácil.*

## 2. Objetivos del primer prototipo

- Detectar la frase de activación **«Hey Voxa»** sin enviar audio continuamente a la nube.
- Responder con voz en español.
- Controlar YouTube en Firefox: abrir búsquedas o enlaces y reproducir, pausar y detener.
- Controlar **Spotifast** mediante los controles multimedia de Linux (MPRIS/`playerctl`, si la versión instalada los expone).
- Mantener un modo de comandos locales que funcione sin API.
- Poder arrancar automáticamente y ejecutarse en modo kiosco.
- Mantener una arquitectura modular para reemplazar componentes Python por Rust cuando el prototipo esté validado.

## 3. Hardware y límites

Equipo objetivo: PC All-in-One con Linux Mint, micrófono y bocinas, aproximadamente 2–4 GB de RAM y CPU todavía por identificar.

La memoria y el procesador son recursos limitados. Por eso:
- No ejecutar un LLM local grande en la primera versión.
- No mantener un navegador adicional si Firefox ya está reproduciendo video.
- Usar audio local para la activación y reservar llamadas de API para solicitudes que realmente necesiten razonamiento.
- Medir el uso real de RAM/CPU antes de elegir reconocimiento de voz y síntesis de voz definitivos.

## 4. Cómo detectar «Hey Voxa»

La solución recomendada es una **detección por etapas**:

1. **Captura de audio local:** el proceso lee el micrófono en bloques pequeños.
2. **Detector de palabra de activación (wake word):** analiza esos bloques y busca «Hey Voxa». En esta fase no se envía audio a un servicio remoto.
3. **Ventana de escucha:** al detectar la frase, VOXA reproduce un sonido breve y escucha la orden durante unos segundos.
4. **Reconocimiento de voz (STT):** convierte la orden en texto.
5. **Interpretación de intención:** primero intenta resolverla con reglas locales, por ejemplo «pausa», «siguiente canción» o «abre YouTube».
6. **Acción:** llama a la integración correspondiente.
7. **Respuesta hablada (TTS):** confirma brevemente el resultado.

### Elección del detector

Conviene probar un motor de wake word que admita modelos personalizados y comprobar explícitamente su soporte para español y para una frase propia. **openWakeWord** es una opción para investigar, pero no se debe asumir que trae un modelo listo para «Hey Voxa»: quizá haya que entrenar o conseguir un modelo personalizado y probarlo en el hardware objetivo. **Porcupine** es otra alternativa, pero hay que revisar licencia, disponibilidad de modelos y requisitos vigentes antes de adoptarlo.

Para el primer día, implementar un modo **pulsar Enter para hablar** o un botón de prueba. Así se valida micrófono, STT, comandos y TTS antes de depurar el wake word. Después se integra el detector continuo.

### Evitar activaciones falsas

- Ajustar el umbral con voces reales de la familia y con ruido de cocina.
- Añadir un pequeño periodo de enfriamiento después de una activación.
- No volver a activar el detector mientras VOXA está hablando.
- Dar una señal sonora al comenzar y terminar la escucha.
- Permitir desactivar el micrófono mediante un comando o interruptor físico si el equipo lo permite.

## 5. Arquitectura propuesta

```text
Micrófono
   │
   ▼
Captura local ──► Wake word: «Hey Voxa»
                       │ activación
                       ▼
                Captura de la orden
                       │
                       ▼
               STT (voz → texto)
                       │
                       ▼
               Router de intenciones
                 ┌─────┼─────────┐
                 ▼     ▼         ▼
              YouTube Spotifast  Sistema
                 └─────┼─────────┘
                       ▼
                 Respuesta TTS
```

La API de IA, si se habilita, se coloca como alternativa después de la interpretación local. No debe ser necesaria para comandos sencillos.

## 6. Integraciones

### YouTube

- Abrir Firefox con una búsqueda o URL.
- Controlar reproducción, pausa y volumen cuando sea posible mediante controles multimedia compatibles.
- Mantener la interfaz sencilla y visible desde la cocina.
- No intentar automatizar inicios de sesión ni guardar contraseñas en el proyecto.

### Spotifast

Spotifast es un cliente de Spotify independiente. La integración debe comprobar primero si está instalado y si publica controles MPRIS. Si `playerctl` detecta su reproductor, se pueden probar comandos como:

```bash
playerctl --list-all
playerctl --player=spotifast play-pause
playerctl --player=spotifast next
playerctl --player=spotifast previous
```

Los nombres del reproductor y los comandos disponibles pueden variar según la instalación. Confirmarlo en el equipo antes de programar la integración. La reproducción puede requerir Spotify Premium, según las condiciones vigentes de Spotifast.

## 7. Stack inicial

- **Python:** prototipo rápido y pruebas de integración.
- **Captura de audio:** ALSA o una biblioteca compatible con el entorno de Linux.
- **Wake word:** evaluar openWakeWord y otras opciones con modelo personalizado.
- **STT:** comparar una opción local ligera con una API opcional; medir precisión y consumo en español.
- **TTS:** probar un motor local como Piper, verificando disponibilidad y requisitos actuales.
- **Acciones del sistema:** `playerctl`, apertura de URLs y procesos del sistema con argumentos seguros.
- **Configuración:** TOML o YAML.
- **Pruebas:** `pytest`.

La elección definitiva de bibliotecas depende de la distribución, arquitectura del procesador y resultados de las pruebas.

## 8. Estructura inicial del repositorio

```text
voxa/
├── README.md
├── pyproject.toml
├── config/
│   └── default.toml
├── src/voxa/
│   ├── main.py
│   ├── audio/
│   │   ├── capture.py
│   │   ├── wake_word.py
│   │   ├── stt.py
│   │   └── tts.py
│   ├── core/
│   │   ├── intents.py
│   │   ├── router.py
│   │   └── conversation.py
│   └── integrations/
│       ├── youtube.py
│       ├── spotifast.py
│       └── system_media.py
└── tests/
    ├── test_intents.py
    ├── test_router.py
    └── test_integrations.py
```

## 9. Comandos iniciales

En Linux Mint, recopilar primero los datos del equipo:

```bash
lscpu
free -h
uname -m
arecord -l
aplay -l
```

Comprobar también si están disponibles las herramientas de audio y Spotifast:

```bash
command -v playerctl
playerctl --list-all
```

Si `playerctl` no está instalado, instalarlo desde el gestor de paquetes de la distribución. No instalar ni configurar servicios de escucha permanente hasta confirmar que el micrófono funciona correctamente.

## 10. Roadmap

### Fase 0 — Diagnóstico
- Identificar CPU, arquitectura y RAM.
- Verificar micrófono, salida de audio y nivel de ruido.
- Comprobar si Spotifast expone controles multimedia.

### Fase 1 — Prototipo conversacional mínimo
- Capturar una orden bajo demanda.
- Transcribir en español.
- Reconocer 5–10 intenciones.
- Ejecutar una acción local y responder por voz.

### Fase 2 — Música y video
- Integrar controles de Spotifast.
- Abrir búsquedas de YouTube en Firefox.
- Probar pausa, reanudación, siguiente, anterior y volumen.

### Fase 3 — «Hey Voxa»
- Evaluar el modelo de wake word.
- Medir falsas activaciones y latencia.
- Hacer pruebas con distintos miembros de la familia y ruido ambiente.

### Fase 4 — Experiencia de cocina
- Inicio automático al entrar a la sesión.
- Interfaz a pantalla completa con estado de escucha y reproducción.
- Recuperación después de errores y registro local mínimo.

### Fase 5 — IA opcional
- Usar una API solo para peticiones abiertas o difíciles.
- Establecer límites de coste y tiempo.
- No transmitir audio de forma continua; enviar solo lo necesario tras la activación y con una política de privacidad clara.

### Fase 6 — Optimización en Rust
Migrar cuando el flujo y las interfaces estén probados. Rust puede mejorar control de recursos y robustez del proceso principal, pero no elimina el consumo del navegador ni reduce por sí mismo el coste de una API.

## 11. Criterios de aceptación

- [ ] La activación y los comandos locales funcionan sin API.
- [ ] «Hey Voxa» se detecta con una tasa aceptable de falsas activaciones en la cocina.
- [ ] VOXA puede controlar reproducción y volumen en Spotifast cuando los controles estén disponibles.
- [ ] Puede abrir YouTube en Firefox y realizar las acciones previstas.
- [ ] El programa se recupera de fallos de red o de una aplicación cerrada.
- [ ] El consumo de CPU y RAM se mide y se documenta en el equipo real.
- [ ] La familia sabe cuándo el micrófono está escuchando una orden.

## 12. Privacidad y costes

- El detector de activación debe funcionar localmente.
- Mantener los comandos comunes en un router local y evitar llamadas innecesarias a IA.
- Si se usa una API, informar claramente qué se envía, cuándo y a qué proveedor.
- No guardar audio por defecto; si se requiere para depuración, habilitarlo explícitamente y con borrado fácil.
- Añadir límite mensual de gasto y manejo de errores de API.

## 13. Referencias para verificar

- Spotifast — sitio oficial: https://spotifast.rocks/
- Spotifast — código fuente: https://github.com/crmne/spotifast
- openWakeWord — proyecto: https://github.com/dscripka/openWakeWord

Revisar la documentación actual de cada proyecto antes de fijar versiones, licencias o requisitos.

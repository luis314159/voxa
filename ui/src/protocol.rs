//! Mensajes entre VOXA (`voxa servicio`) y la pantalla. Ver `src/voxa/display.py`.
//!
//! JSON, uno por línea, sobre TCP en 127.0.0.1. VOXA manda la foto completa del estado cada
//! vez que algo cambia; los segundos de temporizadores y canción los calcula la pantalla.

use serde::{Deserialize, Serialize};

pub const PROTOCOL_VERSION: u32 = 1;

#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
pub struct State {
    #[serde(default)]
    pub v: u32,
    #[serde(default)]
    pub phase: Phase,
    pub heard: Option<String>,
    pub answer: Option<String>,
    /// Hora (epoch, s) de la última orden; el texto se muestra unos segundos.
    pub exchange_at: Option<f64>,
    #[serde(default)]
    pub timers: Vec<Timer>,
    pub music: Option<Music>,
    pub weather: Option<Weather>,
    /// Micrófono apagado («deja de escuchar» o el botón de la pantalla).
    #[serde(default)]
    pub muted: bool,
    /// Lo que impide que VOXA funcione bien, el más grave primero: «Sin internet».
    #[serde(default)]
    pub problems: Vec<Problem>,
    /// «Hey Voxa» si VOXA está escuchando la palabra de activación.
    pub wake_word: Option<String>,
    /// Lista del súper.
    #[serde(default)]
    pub shopping: Vec<String>,
    /// La receta que se está cocinando paso a paso.
    pub recipe: Option<Recipe>,
    /// «Modo foto»: solo la imagen de fondo, sin información.
    #[serde(default)]
    pub photo: bool,
    /// Dirección (con la clave) para abrir VOXA en el celular: se muestra como código QR.
    pub phone: Option<String>,
    /// Idioma de la casa: «es» o «en» (vacío con un VOXA anterior: español).
    #[serde(default)]
    pub language: String,
    /// Notas y recados («déjale una nota a papá»).
    #[serde(default)]
    pub notes: Vec<Note>,
    /// Accesibilidad: letra más grande para leer de lejos.
    #[serde(default)]
    pub big_text: bool,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Note {
    pub text: String,
    /// Para quién; sin nadie, es para todos.
    pub to: Option<String>,
    pub from: Option<String>,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Recipe {
    pub title: String,
    #[serde(default)]
    pub servings: u32,
    /// Con cantidad: «1 kilo de maíz pozolero».
    #[serde(default)]
    pub ingredients: Vec<String>,
    #[serde(default)]
    pub steps: Vec<RecipeStep>,
    /// Paso actual desde 0; -1 mientras no se empieza (se ven los ingredientes).
    #[serde(default = "not_started")]
    pub current: i32,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct RecipeStep {
    pub text: String,
    /// Espera o cocción del paso; 0 si no hay.
    #[serde(default)]
    pub minutes: u32,
}

fn not_started() -> i32 {
    -1
}

impl Recipe {
    /// El paso actual (índice desde 0), o `None` si aún no se empieza.
    pub fn step(&self) -> Option<(usize, &RecipeStep)> {
        let n = usize::try_from(self.current).ok()?;
        self.steps.get(n).map(|step| (n, step))
    }

    /// Fracción hecha, para la barra: el paso 3 de 4 es 0.75.
    pub fn progress(&self) -> f32 {
        match self.step() {
            Some((n, _)) if !self.steps.is_empty() => (n + 1) as f32 / self.steps.len() as f32,
            _ => 0.0,
        }
    }
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Problem {
    pub id: String,
    pub text: String,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Weather {
    pub temperature: i32,
    pub high: i32,
    pub low: i32,
    #[serde(default)]
    pub rain_probability: u32,
    /// Código WMO de Open-Meteo.
    pub code: u32,
    #[serde(default = "day")]
    pub is_day: bool,
    #[serde(default)]
    pub description: String,
}

fn day() -> bool {
    true
}

/// Qué dibujo le toca a un código WMO.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Sky {
    Clear,
    PartlyCloudy,
    Cloudy,
    Fog,
    Rain,
    Snow,
    Storm,
}

impl Weather {
    pub fn sky(&self) -> Sky {
        match self.code {
            0 => Sky::Clear,
            1 | 2 => Sky::PartlyCloudy,
            45 | 48 => Sky::Fog,
            51..=67 | 80..=82 => Sky::Rain,
            71..=77 | 85 | 86 => Sky::Snow,
            95.. => Sky::Storm,
            _ => Sky::Cloudy,
        }
    }
}

/// Respuesta a `Command::Diagnostics`: secciones de «etiqueta: valor», problemas y registro.
#[derive(Debug, Clone, Default, Deserialize, PartialEq)]
pub struct Diagnostics {
    #[serde(default)]
    pub sections: Vec<Section>,
    #[serde(default)]
    pub problems: Vec<ProblemDetail>,
    #[serde(default)]
    pub log: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Section {
    pub title: String,
    pub items: Vec<(String, String)>,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct ProblemDetail {
    pub text: String,
    #[serde(default)]
    pub detail: String,
}

#[derive(Debug, Clone, Copy, Default, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Phase {
    #[default]
    Idle,
    Listening,
    Thinking,
    Speaking,
    /// Una versión más nueva de VOXA mandó algo que esta pantalla no conoce.
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Timer {
    pub id: u64,
    pub label: Option<String>,
    /// Duración original en segundos.
    pub total: f64,
    pub ends_at: f64,
    #[serde(default)]
    pub ringing: bool,
    /// `timer` («en 10 minutos») o `reminder` («a las 8»).
    #[serde(default)]
    pub kind: String,
    /// En pausa: los segundos que le quedan (no corren).
    pub paused_remaining: Option<f64>,
    /// Recordatorio semanal: «de lunes a viernes».
    pub repeat: Option<String>,
}

impl Timer {
    pub fn is_reminder(&self) -> bool {
        self.kind == "reminder"
    }

    pub fn remaining(&self, now: f64) -> f64 {
        match self.paused_remaining {
            Some(left) => left.max(0.0),
            None => (self.ends_at - now).max(0.0),
        }
    }

    /// Fracción que falta (1 → recién puesto, 0 → terminó).
    pub fn fraction_left(&self, now: f64) -> f32 {
        if self.total <= 0.0 {
            return 0.0;
        }
        (self.remaining(now) / self.total).clamp(0.0, 1.0) as f32
    }
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Music {
    pub title: String,
    pub artist: Option<String>,
    pub album: Option<String>,
    pub art_url: Option<String>,
    #[serde(default)]
    pub playing: bool,
    pub position: Option<f64>,
    pub position_at: Option<f64>,
    pub length: Option<f64>,
}

impl Music {
    /// Posición estimada ahora: la medida más lo que ha avanzado desde entonces.
    pub fn position_now(&self, now: f64) -> Option<f64> {
        let position = self.position?;
        let advanced = match (self.playing, self.position_at) {
            (true, Some(at)) => (now - at).max(0.0),
            _ => 0.0,
        };
        let estimate = position + advanced;
        Some(self.length.map_or(estimate, |len| estimate.min(len)))
    }
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Incoming {
    State(State),
    Diagnostics(Diagnostics),
    #[serde(other)]
    Other,
}

/// Interpreta una línea de VOXA. Mensajes desconocidos o inválidos se ignoran.
pub fn parse_line(line: &str) -> Option<Incoming> {
    match serde_json::from_str::<Incoming>(line) {
        Ok(Incoming::Other) | Err(_) => None,
        Ok(message) => Some(message),
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Command {
    /// Botón del micrófono: un turno de voz.
    Talk,
    /// Igual que decir la orden en voz alta.
    Say { text: String },
    CancelTimer { id: u64 },
    StopAlarm,
    /// Apagar o encender el micrófono.
    Mute { on: bool },
    /// «Modo foto» (solo la imagen de fondo) o de regreso a la información.
    Photo { on: bool },
    /// Pide el reporte para la pantalla de diagnóstico.
    Diagnostics,
}

impl Command {
    pub fn to_line(&self) -> String {
        let mut line = serde_json::to_string(self).expect("los comandos siempre se serializan");
        line.push('\n');
        line
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_state_from_voxa() {
        let line = r#"{"type": "state", "v": 1, "phase": "listening", "heard": null, "answer": null,
            "exchange_at": null, "timers": [{"id": 3, "label": "arroz", "total": 600, "ends_at": 1600.0,
            "ringing": false}], "music": {"title": "Persiana americana", "artist": "Soda Stereo",
            "album": null, "art_url": null, "playing": true, "position": 10.0, "position_at": 1000.0,
            "length": 290.0}}"#;
        let state = parse_state(line).unwrap();
        assert_eq!(state.phase, Phase::Listening);
        assert_eq!(state.timers[0].label.as_deref(), Some("arroz"));
        assert_eq!(state.timers[0].remaining(1300.0), 300.0);
        assert_eq!(state.timers[0].fraction_left(1300.0), 0.5);
        let music = state.music.unwrap();
        assert_eq!(music.position_now(1005.0), Some(15.0));
        assert_eq!(music.position_now(2000.0), Some(290.0));
    }

    #[test]
    fn paused_timers_do_not_count_down() {
        let line = r#"{"type": "state", "timers": [{"id": 1, "label": "arroz", "total": 600, "ends_at": 1000.0,
            "paused_remaining": 300.0}, {"id": 2, "label": null, "total": 60, "ends_at": 5000.0, "kind": "reminder",
            "repeat": "de lunes a viernes"}]}"#;
        let state = parse_state(line).unwrap();
        assert_eq!(state.timers[0].remaining(4000.0), 300.0);
        assert_eq!(state.timers[0].fraction_left(9999.0), 0.5);
        assert_eq!(state.timers[1].repeat.as_deref(), Some("de lunes a viernes"));
    }

    #[test]
    fn unknown_phase_and_messages_are_tolerated() {
        let state = parse_state(r#"{"type": "state", "phase": "dancing"}"#).unwrap();
        assert_eq!(state.phase, Phase::Unknown);
        assert!(!state.muted && state.problems.is_empty() && state.weather.is_none() && state.wake_word.is_none());
        assert!(parse_line(r#"{"type": "hello"}"#).is_none());
        assert!(parse_line("no es json").is_none());
    }

    fn parse_state(line: &str) -> Option<State> {
        match parse_line(line) {
            Some(Incoming::State(state)) => Some(state),
            _ => None,
        }
    }

    #[test]
    fn parses_language_and_notes() {
        let line = r#"{"type": "state", "language": "en",
            "notes": [{"id": 1, "text": "compra pan", "to": "Luis", "from": "Ana"}, {"id": 2, "text": "hay pastel", "to": null, "from": null}]}"#;
        let Incoming::State(state) = parse_line(line).unwrap() else { panic!() };
        assert_eq!(state.language, "en");
        assert_eq!(state.notes[0].to.as_deref(), Some("Luis"));
        assert!(state.notes[1].to.is_none());
    }

    #[test]
    fn parses_weather_problems_and_diagnostics() {
        let line = r#"{"type": "state", "muted": true, "problems": [{"id": "internet", "text": "Sin internet"}],
            "weather": {"temperature": 22, "high": 27, "low": 12, "rain_probability": 40, "code": 61,
            "is_day": false, "description": "lloviendo"}, "video": {"title": "Pozole"}}"#;
        let state = parse_state(line).unwrap();
        assert!(state.muted);
        assert_eq!(state.problems[0].text, "Sin internet");
        let weather = state.weather.unwrap();
        assert_eq!((weather.temperature, weather.sky(), weather.is_day), (22, Sky::Rain, false));

        let line = r#"{"type": "diagnostics", "v": 1, "sections": [{"title": "Voz", "items": [["Micrófono", "abierto"]]}],
            "problems": [{"id": "x", "text": "Sin internet", "detail": "DNS"}], "log": ["⚠ 12:00 algo"]}"#;
        let Some(Incoming::Diagnostics(report)) = parse_line(line) else { panic!("no es diagnóstico") };
        assert_eq!(report.sections[0].items[0], ("Micrófono".to_owned(), "abierto".to_owned()));
        assert_eq!(report.problems[0].detail, "DNS");
    }

    #[test]
    fn parses_a_recipe_in_progress() {
        let line = r#"{"type": "state", "recipe": {"title": "Pozole rojo", "servings": 6,
            "ingredients": ["1 kilo de maíz"], "steps": [{"text": "Cuece la carne", "minutes": 60},
            {"text": "Licúa los chiles", "minutes": 0}], "current": 1}}"#;
        let recipe = parse_state(line).unwrap().recipe.unwrap();
        let (n, step) = recipe.step().unwrap();
        assert_eq!((n, step.text.as_str(), recipe.progress()), (1, "Licúa los chiles", 1.0));
        let fresh = parse_state(r#"{"type": "state", "recipe": {"title": "Arroz", "steps": [{"text": "Lava"}]}}"#).unwrap();
        let fresh = fresh.recipe.unwrap();
        assert_eq!((fresh.current, fresh.step(), fresh.progress()), (-1, None, 0.0));
        assert!(parse_state(r#"{"type": "state"}"#).unwrap().recipe.is_none());
    }

    #[test]
    fn weather_codes_map_to_skies() {
        let sky = |code| Weather { temperature: 0, high: 0, low: 0, rain_probability: 0, code, is_day: true, description: String::new() }.sky();
        assert_eq!([sky(0), sky(2), sky(3), sky(45), sky(81), sky(73), sky(95)], [
            Sky::Clear, Sky::PartlyCloudy, Sky::Cloudy, Sky::Fog, Sky::Rain, Sky::Snow, Sky::Storm
        ]);
    }

    #[test]
    fn commands_serialize_like_python_expects() {
        assert_eq!(Command::Talk.to_line(), "{\"type\":\"talk\"}\n");
        assert_eq!(
            Command::Say { text: "pausa".into() }.to_line(),
            "{\"type\":\"say\",\"text\":\"pausa\"}\n"
        );
        assert_eq!(Command::CancelTimer { id: 3 }.to_line(), "{\"type\":\"cancel_timer\",\"id\":3}\n");
        assert_eq!(Command::StopAlarm.to_line(), "{\"type\":\"stop_alarm\"}\n");
        assert_eq!(Command::Mute { on: true }.to_line(), "{\"type\":\"mute\",\"on\":true}\n");
        assert_eq!(Command::Photo { on: false }.to_line(), "{\"type\":\"photo\",\"on\":false}\n");
        assert_eq!(Command::Diagnostics.to_line(), "{\"type\":\"diagnostics\"}\n");
    }
}

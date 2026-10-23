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
}

impl Timer {
    pub fn remaining(&self, now: f64) -> f64 {
        (self.ends_at - now).max(0.0)
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

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
enum Incoming {
    State(State),
    #[serde(other)]
    Other,
}

/// Interpreta una línea de VOXA. Mensajes desconocidos o inválidos se ignoran.
pub fn parse_line(line: &str) -> Option<State> {
    match serde_json::from_str::<Incoming>(line) {
        Ok(Incoming::State(state)) => Some(state),
        _ => None,
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
        let state = parse_line(line).unwrap();
        assert_eq!(state.phase, Phase::Listening);
        assert_eq!(state.timers[0].label.as_deref(), Some("arroz"));
        assert_eq!(state.timers[0].remaining(1300.0), 300.0);
        assert_eq!(state.timers[0].fraction_left(1300.0), 0.5);
        let music = state.music.unwrap();
        assert_eq!(music.position_now(1005.0), Some(15.0));
        assert_eq!(music.position_now(2000.0), Some(290.0));
    }

    #[test]
    fn unknown_phase_and_messages_are_tolerated() {
        let state = parse_line(r#"{"type": "state", "phase": "dancing"}"#).unwrap();
        assert_eq!(state.phase, Phase::Unknown);
        assert!(parse_line(r#"{"type": "hello"}"#).is_none());
        assert!(parse_line("no es json").is_none());
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
    }
}

//! La pantalla de cocina: reloj, temporizadores, lo que suena y el anillo de VOXA.
//!
//! Todo se dibuja sobre un diseño de 1920×1080 escalado a la ventana, para leerse a 3 m.

use std::path::PathBuf;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use egui::{Align2, Color32, CornerRadius, Painter, Pos2, Rect, Sense, Ui, pos2, vec2};

use crate::backgrounds::Backgrounds;
use crate::format;
use crate::link::Link;
use crate::protocol::{Command, Diagnostics, Music, Phase, State, Timer, Weather};
use crate::theme;
use crate::widgets::{self, Icon, RingMode};

/// Segundos que se ve lo que se oyó y la respuesta.
const CAPTION_SECONDS: f64 = 10.0;
const HIDE_CURSOR_AFTER: Duration = Duration::from_secs(4);
/// Tras tocar una tarjeta, cuánto tiempo se ve su botón para cancelar.
const SELECT_SECONDS: Duration = Duration::from_secs(5);
/// De noche, un toque enciende la pantalla este tiempo (y no se toma como botón).
const NIGHT_WAKE: Duration = Duration::from_secs(30);
/// Cuánto oscurece la pantalla de noche (0 = nada, 1 = negro).
const NIGHT_DARKNESS: f32 = 0.68;
/// Mantener presionado el reloj abre el diagnóstico.
const LONG_PRESS: Duration = Duration::from_millis(1200);
const DIAGNOSTICS_REFRESH: Duration = Duration::from_secs(5);
const DIAGNOSTICS_CLOSE: Duration = Duration::from_secs(120);
const HINTS: [&str; 7] = [
    "«Pon un temporizador de 10 minutos para el arroz»",
    "«¿Cuánto le falta al arroz?»",
    "«Pon a Juan Gabriel»",
    "«Pon un video de cómo hacer pozole»",
    "«Súbele a la música»",
    "«¿Va a llover hoy?»",
    "«¿Qué canción es esta?»",
];

pub struct Options {
    pub twenty_four_hours: bool,
    pub kiosk: bool,
    /// Guarda una imagen de la pantalla en este archivo y termina.
    pub capture: Option<PathBuf>,
    /// Horas de «modo noche» (inicio, fin): la pantalla se oscurece.
    pub night: Option<(chrono::NaiveTime, chrono::NaiveTime)>,
    /// Abre el diagnóstico al arrancar (para capturas).
    pub diagnostics: bool,
}

/// ¿`now` cae en el horario de noche? El horario puede cruzar la medianoche (22:00–06:30).
pub fn in_night(now: chrono::NaiveTime, (start, end): (chrono::NaiveTime, chrono::NaiveTime)) -> bool {
    if start <= end { now >= start && now < end } else { now >= start || now < end }
}

struct DiagnosticsView {
    opened: Instant,
    requested: Instant,
}

pub struct VoxaApp {
    link: Link,
    options: Options,
    started: Instant,
    art_url: Option<String>,
    pointer: Option<Pos2>,
    pointer_moved: Instant,
    /// Temporizador tocado: muestra su «×» unos segundos (en pantalla táctil no hay «hover»).
    selected: Option<(u64, Instant)>,
    backgrounds: Option<Backgrounds>,
    /// Oscuridad actual del modo noche (animada), 0..1.
    night_level: f32,
    night_awake_until: Option<Instant>,
    /// El toque que despertó la pantalla no debe llegar a los botones.
    swallow_touch: bool,
    clock_pressed: Option<Instant>,
    diagnostics: Option<DiagnosticsView>,
}

fn epoch_now() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map_or(0.0, |d| d.as_secs_f64())
}

impl VoxaApp {
    pub fn new(link: Link, options: Options, backgrounds: Option<Backgrounds>) -> Self {
        Self {
            link,
            options,
            started: Instant::now(),
            art_url: None,
            pointer: None,
            pointer_moved: Instant::now(),
            selected: None,
            backgrounds,
            night_level: 0.0,
            night_awake_until: None,
            swallow_touch: false,
            clock_pressed: None,
            diagnostics: None,
        }
    }

    fn send(&self, command: Command) {
        if !self.link.send(&command) {
            log_warn("Sin conexión con VOXA: no se envió la orden");
        }
    }
}

fn log_warn(message: &str) {
    eprintln!("voxa-ui: {message}");
}

/// Medidas de la pantalla: `s` convierte unidades del diseño de 1920×1080 a píxeles.
struct Frame {
    s: f32,
    now: f64,
    time: f64,
}

impl Frame {
    fn px(&self, design: f32) -> f32 {
        design * self.s
    }
}

impl eframe::App for VoxaApp {
    fn ui(&mut self, ui: &mut Ui, _frame: &mut eframe::Frame) {
        let (state, connected) = self.link.snapshot();
        let rect = ui.max_rect();
        let f = Frame {
            s: (rect.width() / 1920.0).min(rect.height() / 1080.0),
            now: epoch_now(),
            time: self.started.elapsed().as_secs_f64(),
        };
        if self.options.diagnostics && self.diagnostics.is_none() && connected {
            self.options.diagnostics = false;
            self.open_diagnostics();
        }
        self.night_touch(ui);
        if self.diagnostics.is_some() {
            block_input(ui); // el diagnóstico tapa todo: nada de abajo responde
        }
        let painter = ui.painter().clone();
        painter.rect_filled(rect, CornerRadius::ZERO, theme::BG);
        if let Some(backgrounds) = &mut self.backgrounds {
            let ppp = ui.ctx().pixels_per_point();
            backgrounds.update(ui.ctx(), [(rect.width() * ppp) as u32, (rect.height() * ppp) as u32]);
            backgrounds.paint(&painter, rect, 0.66);
        }

        let margin = f.px(72.0);
        let split = rect.left() + rect.width() * 0.57;
        let left = Rect::from_min_max(rect.min + vec2(margin, margin), pos2(split - margin * 0.5, rect.bottom() - margin));
        let right = Rect::from_min_max(pos2(split + margin * 0.5, rect.top() + margin), rect.max - vec2(margin, margin));

        let caption_bottom = self.clock_and_caption(ui, &painter, &f, left, &state);
        if let Some(music) = &state.music {
            let height = f.px(200.0);
            let card = Rect::from_min_max(pos2(left.left(), left.bottom() - height), left.max);
            if card.top() > caption_bottom {
                self.music_card(ui, &painter, &f, card, music);
            }
        } else if let Some(old) = self.art_url.take() {
            ui.ctx().forget_image(&old);
        }
        let ring_left = self.ring(ui, &painter, &f, right, &state, connected);
        if let Some(weather) = &state.weather {
            let band = Rect::from_min_max(right.min, pos2(ring_left - f.px(24.0), right.top() + f.px(230.0)));
            weather_block(&painter, &f, band, weather);
        }
        let timers_area = Rect::from_min_max(pos2(right.left(), right.top() + f.px(250.0)), right.max);
        self.timers(ui, &painter, &f, timers_area, &state);
        let mut footer = rect.bottom() - f.px(28.0);
        if let Some(place) = self.backgrounds.as_ref().and_then(Backgrounds::caption) {
            let shown = widgets::shadow_text(&painter, 
                pos2(right.right(), footer),
                Align2::RIGHT_BOTTOM,
                place,
                theme::regular(f.px(24.0)),
                theme::alpha(theme::TEXT, 0.7),
            );
            footer = shown.top() - f.px(6.0);
        }
        if !connected {
            widgets::shadow_text(&painter, 
                pos2(right.right(), footer),
                Align2::RIGHT_BOTTOM,
                "Sin conexión con VOXA · reintentando…",
                theme::regular(f.px(24.0)),
                theme::TEXT_DIM,
            );
        }

        self.night(ui, &painter, rect, &state);
        if self.diagnostics.is_some() {
            self.diagnostics_overlay(ui, &painter, &f, rect, connected);
        }

        self.manage_cursor(ui);
        schedule_repaint(ui, &f, &state, self.backgrounds.as_ref());
        self.capture_if_requested(ui);
    }

    fn clear_color(&self, _visuals: &egui::Visuals) -> [f32; 4] {
        theme::BG.to_normalized_gamma_f32()
    }
}

impl VoxaApp {
    /// Fecha, hora grande y, debajo, lo último que se dijo. Devuelve dónde termina.
    fn clock_and_caption(&mut self, ui: &mut Ui, painter: &Painter, f: &Frame, area: Rect, state: &State) -> f32 {
        let local = chrono::Local::now();
        let date = format::date(local.date_naive());
        widgets::shadow_text(painter, area.left_top(), Align2::LEFT_TOP, &date, theme::regular(f.px(44.0)), theme::TEXT_DIM);

        let (time, suffix) = format::clock(local.time(), self.options.twenty_four_hours);
        let clock_top = area.top() + f.px(50.0);
        let clock = widgets::tabular_text(
            painter,
            pos2(area.left() - f.px(8.0), clock_top),
            Align2::LEFT_TOP,
            &time,
            theme::strong(f.px(250.0)),
            theme::TEXT,
        );
        if let Some(suffix) = suffix {
            widgets::shadow_text(painter, 
                pos2(clock.right() + f.px(18.0), clock.bottom() - f.px(58.0)),
                Align2::LEFT_BOTTOM,
                suffix,
                theme::regular(f.px(48.0)),
                theme::TEXT_DIM,
            );
        }

        self.long_press_for_diagnostics(ui, area.left_top(), clock.right_bottom());

        let mut y = clock.bottom() + f.px(24.0);
        let age = state.exchange_at.map_or(f64::INFINITY, |at| f.now - at);
        let fade = ((CAPTION_SECONDS - age) as f32).clamp(0.0, 1.0);
        let listening = matches!(state.phase, Phase::Listening | Phase::Thinking);
        if listening {
            let text = if state.phase == Phase::Listening { "Te escucho…" } else { "Un momento…" };
            widgets::shadow_text(painter, pos2(area.left(), y), Align2::LEFT_TOP, text, theme::regular(f.px(52.0)), theme::CYAN);
        } else if fade > 0.0 {
            if let Some(heard) = &state.heard {
                let galley = painter.layout(
                    format!("«{heard}»"),
                    theme::regular(f.px(38.0)),
                    theme::alpha(theme::TEXT_DIM, fade),
                    area.width(),
                );
                let h = galley.size().y;
                widgets::shadow_galley(painter, pos2(area.left(), y), galley, theme::TEXT_DIM);
                y += h + f.px(12.0);
            }
            if let Some(answer) = &state.answer {
                let galley = painter.layout(
                    answer.clone(),
                    theme::strong(f.px(54.0)),
                    theme::alpha(theme::TEXT, fade),
                    area.width(),
                );
                let h = galley.size().y;
                widgets::shadow_galley(painter, pos2(area.left(), y), galley, theme::TEXT);
                y += h;
            }
        }
        y
    }

    fn music_card(&mut self, ui: &mut Ui, painter: &Painter, f: &Frame, card: Rect, music: &Music) {
        let cover = Rect::from_min_size(card.min, vec2(card.height(), card.height()));
        let radius = CornerRadius::same(f.px(20.0) as u8);
        painter.rect_filled(cover, radius, theme::CARD);
        widgets::icon(painter, cover.center(), cover.width() * 0.35, Icon::Note, theme::alpha(theme::BLUE, 0.8));
        if self.art_url != music.art_url {
            if let Some(old) = self.art_url.take() {
                ui.ctx().forget_image(&old); // una portada por canción: no se acumulan en memoria
            }
            self.art_url = music.art_url.clone();
        }
        if let Some(url) = &music.art_url {
            egui::Image::new(url.as_str()).corner_radius(radius).paint_at(ui, cover);
        }

        let x = cover.right() + f.px(32.0);
        let width = card.right() - x;
        widgets::fitted_text(
            painter,
            pos2(x, card.top() + f.px(4.0)),
            Align2::LEFT_TOP,
            &music.title,
            theme::strong(f.px(46.0)),
            theme::TEXT,
            width,
        );
        if let Some(artist) = &music.artist {
            widgets::fitted_text(
                painter,
                pos2(x, card.top() + f.px(58.0)),
                Align2::LEFT_TOP,
                artist,
                theme::regular(f.px(34.0)),
                theme::TEXT_DIM,
                width,
            );
        }

        // Controles: anterior, reproducir/pausar, siguiente.
        let size = f.px(72.0);
        let y = card.bottom() - size / 2.0;
        let buttons = [
            (Icon::Previous, "anterior", Command::Say { text: "anterior".into() }),
            (
                if music.playing { Icon::Pause } else { Icon::Play },
                "reproducir",
                Command::Say { text: if music.playing { "pausa" } else { "continúa" }.into() },
            ),
            (Icon::Next, "siguiente", Command::Say { text: "siguiente".into() }),
        ];
        let progress_left = x + 3.0 * (size + f.px(16.0)) + f.px(16.0);
        for (n, (icon, id, command)) in buttons.into_iter().enumerate() {
            let center = pos2(x + size / 2.0 + n as f32 * (size + f.px(16.0)), y);
            let hit = Rect::from_center_size(center, vec2(size, size));
            let response = ui.interact(hit, ui.scope_id().with(("musica", id)), Sense::click());
            let primary = n == 1;
            let fill = if primary { theme::TEXT } else if response.hovered() { theme::CARD_HOVER } else { theme::CARD };
            painter.circle_filled(center, size / 2.0, fill);
            let color = if primary { theme::BG } else { theme::TEXT };
            widgets::icon(painter, center, size * 0.36, icon, color);
            if response.clicked() {
                self.send(command);
            }
        }

        if let (Some(position), Some(length)) = (music.position_now(f.now), music.length) {
            if length > 0.0 && card.right() - progress_left > f.px(160.0) {
                let bar = Rect::from_min_max(pos2(progress_left, y - f.px(4.0)), pos2(card.right(), y + f.px(4.0)));
                widgets::progress_bar(painter, bar, (position / length) as f32, None);
                let font = theme::regular(f.px(24.0));
                widgets::shadow_text(painter, bar.left_bottom() + vec2(0.0, f.px(12.0)), Align2::LEFT_TOP, format::track_time(position), font.clone(), theme::TEXT_DIM);
                widgets::shadow_text(painter, bar.right_bottom() + vec2(0.0, f.px(12.0)), Align2::RIGHT_TOP, format::track_time(length), font, theme::TEXT_DIM);
            }
        }
    }

    /// El anillo es también el botón para hablar; a su izquierda, el del micrófono.
    /// Devuelve dónde empieza (para acomodar el clima a la izquierda).
    fn ring(&self, ui: &mut Ui, painter: &Painter, f: &Frame, area: Rect, state: &State, connected: bool) -> f32 {
        let radius = f.px(92.0);
        let center = pos2(area.right() - radius - f.px(16.0), area.top() + radius + f.px(8.0));
        let response = ui.interact(Rect::from_center_size(center, vec2(radius, radius) * 2.6), ui.scope_id().with("hablar"), Sense::click());
        let problem = state.problems.first();
        let mode = if !connected {
            RingMode::Disconnected
        } else if state.phase != Phase::Idle {
            RingMode::Phase(state.phase)
        } else if state.muted {
            RingMode::Muted
        } else if problem.is_some() {
            RingMode::Problem
        } else {
            RingMode::Phase(state.phase)
        };
        let scale = if response.is_pointer_button_down_on() { 0.94 } else { 1.0 };
        widgets::voxa_ring(painter, center, radius * scale, mode, f.time);
        if response.clicked() && connected && state.phase == Phase::Idle {
            self.send(Command::Talk); // con el micrófono apagado, también lo enciende
        }
        if !connected {
            return center.x - radius * 1.3;
        }

        // Micrófono: apagarlo es el «modo privado» (suelta el micrófono de verdad).
        let size = f.px(76.0);
        let mic_center = pos2(center.x - radius - f.px(78.0), center.y);
        let mic = ui.interact(Rect::from_center_size(mic_center, vec2(size, size)), ui.scope_id().with("microfono"), Sense::click());
        let (fill, color) = if state.muted {
            (theme::ALARM, theme::BG)
        } else if mic.hovered() {
            (theme::CARD_HOVER, theme::TEXT)
        } else {
            (theme::CARD, theme::TEXT)
        };
        painter.circle_filled(mic_center, size / 2.0, fill);
        widgets::icon(painter, mic_center, size * 0.42, if state.muted { Icon::MicOff } else { Icon::Mic }, color);
        if mic.clicked() {
            self.send(Command::Mute { on: !state.muted });
        }

        // Debajo, qué pasa: en reposo se invita a tocar; al escuchar o pensar lo dice el texto grande.
        let below = pos2(area.right(), center.y + radius + f.px(18.0));
        let font = theme::regular(f.px(28.0));
        if state.phase == Phase::Idle {
            if state.muted {
                widgets::shadow_text(painter, below, Align2::RIGHT_TOP, "Micrófono apagado", font, theme::ALARM);
            } else if let Some(problem) = problem {
                let more = state.problems.len() - 1;
                let text = if more > 0 { format!("{} · y {more} más", problem.text) } else { problem.text.clone() };
                widgets::shadow_text(painter, below, Align2::RIGHT_TOP, text, font, theme::ALARM);
            } else {
                widgets::shadow_text(painter, below, Align2::RIGHT_TOP, "Toca para hablar", font, theme::TEXT_DIM);
            }
        }
        mic_center.x - size / 2.0
    }

    fn timers(&mut self, ui: &mut Ui, painter: &Painter, f: &Frame, area: Rect, state: &State) {
        if state.timers.is_empty() {
            self.hints(painter, f, area);
            return;
        }
        let gap = f.px(24.0);
        let height = f.px(176.0);
        let fit = (((area.height() + gap) / (height + gap)).floor() as usize).max(1);
        let shown = if state.timers.len() > fit { fit - 1 } else { state.timers.len() };
        let mut y = area.top();
        for timer in &state.timers[..shown] {
            let card = Rect::from_min_size(pos2(area.left(), y), vec2(area.width(), height));
            self.timer_card(ui, painter, f, card, timer);
            y += height + gap;
        }
        let hidden = state.timers.len() - shown;
        if hidden > 0 {
            let text = if hidden == 1 { "y 1 temporizador más".to_owned() } else { format!("y {hidden} temporizadores más") };
            widgets::shadow_text(painter, pos2(area.left(), y), Align2::LEFT_TOP, text, theme::regular(f.px(32.0)), theme::TEXT_DIM);
        }
    }

    fn timer_card(&mut self, ui: &mut Ui, painter: &Painter, f: &Frame, card: Rect, timer: &Timer) {
        let radius = CornerRadius::same(f.px(28.0) as u8);
        let response = ui.interact(card, ui.scope_id().with(("temporizador", timer.id)), Sense::click());
        let pad = f.px(32.0);
        let label = timer.label.as_deref().map(format::capitalize).unwrap_or_else(|| "Temporizador".into());

        if timer.ringing {
            let glow = widgets::pulse(f.time, 1.2);
            painter.rect_filled(card, radius, theme::lerp(theme::ALARM_DIM, theme::lerp(theme::CARD, theme::ALARM, 0.45), glow));
            painter.rect_stroke(card, radius, egui::Stroke::new(f.px(3.0), theme::ALARM), egui::StrokeKind::Inside);
            widgets::shadow_text(painter, card.left_top() + vec2(pad, pad * 0.8), Align2::LEFT_TOP, format!("¡{label} listo!"), theme::strong(f.px(52.0)), theme::TEXT);
            widgets::shadow_text(painter, card.left_bottom() + vec2(pad, -pad * 0.8), Align2::LEFT_BOTTOM, "Toca para detener la alarma", theme::regular(f.px(30.0)), theme::TEXT);
            if response.clicked() {
                self.send(Command::StopAlarm);
            }
            return;
        }

        painter.rect_filled(card, radius, if response.hovered() { theme::CARD_HOVER } else { theme::CARD });
        let label_font = theme::regular(f.px(36.0));
        widgets::fitted_text(painter, card.left_top() + vec2(pad, pad * 0.75), Align2::LEFT_TOP, &label, label_font, theme::TEXT_DIM, card.width() * 0.45);
        widgets::shadow_text(painter, 
            card.left_top() + vec2(pad, pad * 0.75 + f.px(48.0)),
            Align2::LEFT_TOP,
            format::duration(timer.total),
            theme::regular(f.px(26.0)),
            theme::alpha(theme::TEXT_DIM, 0.7),
        );
        widgets::tabular_text(
            painter,
            pos2(card.right() - pad, card.center().y - f.px(10.0)),
            Align2::RIGHT_CENTER,
            &format::countdown(timer.remaining(f.now)),
            theme::strong(f.px(104.0)),
            theme::TEXT,
        );
        let bar = Rect::from_min_max(
            pos2(card.left() + pad, card.bottom() - pad * 0.75 - f.px(10.0)),
            pos2(card.right() - pad, card.bottom() - pad * 0.75),
        );
        widgets::progress_bar(painter, bar, timer.fraction_left(f.now), None);

        // Cancelar: un toque en la tarjeta muestra la «×» unos segundos; otro en la «×» lo cancela.
        let selected = self.selected.is_some_and(|(id, at)| id == timer.id && at.elapsed() < SELECT_SECONDS);
        if response.clicked() {
            self.selected = if selected { None } else { Some((timer.id, Instant::now())) };
        }
        if selected {
            let center = pos2(card.left() + card.width() * 0.5, card.top() + pad + f.px(12.0));
            let size = f.px(56.0);
            let close = ui.interact(Rect::from_center_size(center, vec2(size, size)), ui.scope_id().with(("cancelar", timer.id)), Sense::click());
            painter.circle_filled(center, size / 2.0, if close.hovered() { theme::alpha(theme::PURPLE, 0.6) } else { theme::TRACK });
            widgets::icon(painter, center, size * 0.36, Icon::Close, theme::TEXT);
            if close.clicked() {
                self.send(Command::CancelTimer { id: timer.id });
                self.selected = None;
            }
        }
    }

    fn hints(&self, painter: &Painter, f: &Frame, area: Rect) {
        let mut y = area.top() + f.px(40.0);
        widgets::shadow_text(painter, pos2(area.left(), y), Align2::LEFT_TOP, "Prueba decir:", theme::regular(f.px(34.0)), theme::TEXT_DIM);
        y += f.px(64.0);
        let n = (f.time / 8.0) as usize;
        for row in 0..3 {
            let hint = HINTS[(n + row) % HINTS.len()];
            let color = theme::alpha(theme::TEXT, if row == 0 { 0.9 } else { 0.45 });
            let galley = painter.layout(hint.to_owned(), theme::regular(f.px(40.0)), color, area.width());
            let height = galley.size().y;
            widgets::shadow_galley(painter, pos2(area.left(), y), galley, color);
            y += height + f.px(28.0);
        }
    }

    /// De noche, el primer toque solo enciende la pantalla: no pausa la música por accidente.
    fn night_touch(&mut self, ui: &mut Ui) {
        let (pressed, busy) = ui.input(|i| (i.pointer.any_pressed(), i.pointer.any_down() || i.pointer.any_released()));
        if pressed && self.night_level > 0.5 {
            self.night_awake_until = Some(Instant::now() + NIGHT_WAKE);
            self.swallow_touch = true;
        } else if self.swallow_touch && !busy {
            self.swallow_touch = false;
        }
        if self.swallow_touch {
            block_input(ui);
        }
    }

    /// Oscurece todo (menos si suena una alarma, VOXA habla o alguien tocó la pantalla).
    fn night(&mut self, ui: &Ui, painter: &Painter, rect: Rect, state: &State) {
        let night = self.options.night.is_some_and(|hours| in_night(chrono::Local::now().time(), hours));
        let awake = self.night_awake_until.is_some_and(|until| Instant::now() < until);
        let busy = state.phase != Phase::Idle || state.timers.iter().any(|t| t.ringing) || self.diagnostics.is_some();
        let target = if night && !awake && !busy { 1.0 } else { 0.0 };
        self.night_level = ui.ctx().animate_value_with_time(ui.scope_id().with("noche"), target, 1.5);
        if self.night_level > 0.0 {
            let alpha = (self.night_level * NIGHT_DARKNESS * 255.0) as u8;
            painter.rect_filled(rect, CornerRadius::ZERO, Color32::from_black_alpha(alpha));
        }
    }

    fn long_press_for_diagnostics(&mut self, ui: &mut Ui, min: Pos2, max: Pos2) {
        let response = ui.interact(Rect::from_min_max(min, max), ui.scope_id().with("reloj"), Sense::click());
        if !response.is_pointer_button_down_on() {
            self.clock_pressed = None;
            return;
        }
        let since = *self.clock_pressed.get_or_insert_with(Instant::now);
        if since.elapsed() >= LONG_PRESS {
            self.clock_pressed = None;
            self.open_diagnostics();
        } else {
            ui.ctx().request_repaint_after(Duration::from_millis(100));
        }
    }

    fn open_diagnostics(&mut self) {
        self.send(Command::Diagnostics);
        let now = Instant::now();
        self.diagnostics = Some(DiagnosticsView { opened: now, requested: now });
    }

    fn diagnostics_overlay(&mut self, ui: &Ui, painter: &Painter, f: &Frame, rect: Rect, connected: bool) {
        let Some(view) = &mut self.diagnostics else { return };
        let clicked = ui.input(|i| i.pointer.any_click());
        if (clicked && view.opened.elapsed() > Duration::from_millis(600)) || view.opened.elapsed() > DIAGNOSTICS_CLOSE {
            self.diagnostics = None;
            return;
        }
        if view.requested.elapsed() > DIAGNOSTICS_REFRESH {
            view.requested = Instant::now();
            self.link.send(&Command::Diagnostics);
        }
        ui.ctx().request_repaint_after(Duration::from_secs(1));
        painter.rect_filled(rect, CornerRadius::ZERO, theme::alpha(theme::BG, 0.95));
        draw_diagnostics(painter, f, rect, self.link.diagnostics().as_ref(), connected);
    }

    fn capture_if_requested(&mut self, ui: &Ui) {
        const WAIT: Duration = Duration::from_millis(3500); // conexión, estado, portada y fundido del fondo
        let Some(path) = &self.options.capture else { return };
        if self.started.elapsed() < WAIT {
            ui.ctx().request_repaint_after(Duration::from_millis(100));
            return;
        }
        let path = path.clone();
        self.options.capture = None;
        let callback = egui::ScreenshotCallback::new(move |image| {
            let size = [image.size[0] as u32, image.size[1] as u32];
            let pixels = image.pixels.iter().flat_map(|c| c.to_array()).collect();
            let code = match image::RgbaImage::from_raw(size[0], size[1], pixels).map(|img| img.save(&path)) {
                Some(Ok(())) => 0,
                _ => {
                    eprintln!("voxa-ui: no pude guardar {}", path.display());
                    1
                }
            };
            std::process::exit(code);
        });
        ui.ctx().send_viewport_cmd(egui::ViewportCommand::Screenshot(callback));
    }

    fn manage_cursor(&mut self, ui: &Ui) {
        if !self.options.kiosk {
            return;
        }
        let pos = ui.input(|i| i.pointer.latest_pos());
        if pos != self.pointer {
            self.pointer = pos;
            self.pointer_moved = Instant::now();
        }
        if self.pointer_moved.elapsed() > HIDE_CURSOR_AFTER {
            ui.ctx().set_cursor_icon(egui::CursorIcon::None);
        }
    }
}

/// Ningún botón responde en este cuadro, pero todo se ve igual (`disable` también lo desvanece).
fn block_input(ui: &mut Ui) {
    ui.disable();
    ui.set_opacity(1.0);
}

/// El clima en reposo: dibujo, temperatura y, debajo, cómo estará el día.
fn weather_block(painter: &Painter, f: &Frame, area: Rect, weather: &Weather) {
    let icon = f.px(104.0);
    let icon_center = pos2(area.left() + icon / 2.0, area.top() + f.px(16.0) + icon / 2.0);
    widgets::sky_icon(painter, icon_center, icon, weather.sky(), weather.is_day);
    widgets::shadow_text(
        painter,
        pos2(icon_center.x + icon / 2.0 + f.px(20.0), icon_center.y),
        Align2::LEFT_CENTER,
        format!("{}°", weather.temperature),
        theme::strong(f.px(92.0)),
        theme::TEXT,
    );
    let font = theme::regular(f.px(28.0));
    let mut detail = format::capitalize(&weather.description);
    if weather.rain_probability >= 30 {
        detail = format!("{detail} · lluvia {} %", weather.rain_probability);
    }
    let y = icon_center.y + icon / 2.0 + f.px(14.0);
    let width = area.width().max(f.px(200.0));
    widgets::fitted_text(painter, pos2(area.left(), y), Align2::LEFT_TOP, &detail, font.clone(), theme::TEXT_DIM, width);
    let range = format!("Máx {}° · Mín {}°", weather.high, weather.low);
    widgets::fitted_text(painter, pos2(area.left(), y + f.px(38.0)), Align2::LEFT_TOP, &range, font, theme::TEXT_DIM, width);
}

/// La pantalla de diagnóstico: bloques de «etiqueta: valor» en dos columnas, problemas y registro.
fn draw_diagnostics(painter: &Painter, f: &Frame, rect: Rect, report: Option<&Diagnostics>, connected: bool) {
    let area = rect.shrink(f.px(72.0));
    widgets::shadow_text(painter, area.left_top(), Align2::LEFT_TOP, "Diagnóstico", theme::strong(f.px(56.0)), theme::TEXT);
    widgets::shadow_text(painter, area.right_top(), Align2::RIGHT_TOP, "Toca para cerrar", theme::regular(f.px(28.0)), theme::TEXT_DIM);
    let report = match report {
        Some(report) if connected => report,
        _ => {
            let text = if connected { "Pidiendo el reporte a VOXA…" } else { "Sin conexión con VOXA: revisa «systemctl --user status voxa»" };
            widgets::shadow_text(painter, area.left_top() + vec2(0.0, f.px(100.0)), Align2::LEFT_TOP, text, theme::regular(f.px(34.0)), theme::TEXT_DIM);
            return;
        }
    };

    let label_font = theme::regular(f.px(26.0));
    let value_font = theme::strong(f.px(26.0));
    let line = f.px(38.0);
    let gap = f.px(56.0);
    let col_width = (area.width() - gap) / 2.0;
    let mut column_y = [area.top() + f.px(100.0); 2];
    for (n, section) in report.sections.iter().enumerate() {
        let col = n % 2;
        let x = area.left() + col as f32 * (col_width + gap);
        let mut y = column_y[col];
        widgets::shadow_text(painter, pos2(x, y), Align2::LEFT_TOP, &section.title, theme::strong(f.px(30.0)), theme::CYAN);
        y += line * 1.2;
        for (label, value) in &section.items {
            widgets::shadow_text(painter, pos2(x, y), Align2::LEFT_TOP, label, label_font.clone(), theme::TEXT_DIM);
            let value_x = x + col_width * 0.34;
            widgets::fitted_text(painter, pos2(value_x, y), Align2::LEFT_TOP, value, value_font.clone(), theme::TEXT, col_width * 0.66);
            y += line;
        }
        column_y[col] = y + f.px(24.0);
    }

    let mut y = column_y[0].max(column_y[1]);
    if report.problems.is_empty() {
        widgets::shadow_text(painter, pos2(area.left(), y), Align2::LEFT_TOP, "Sin problemas detectados", label_font.clone(), theme::CYAN);
        y += line;
    }
    for problem in &report.problems {
        let text = if problem.detail.is_empty() { problem.text.clone() } else { format!("{} — {}", problem.text, problem.detail) };
        widgets::fitted_text(painter, pos2(area.left(), y), Align2::LEFT_TOP, &text, label_font.clone(), theme::ALARM, area.width());
        y += line;
    }
    y += f.px(12.0);
    let small = theme::regular(f.px(22.0));
    let row = f.px(30.0);
    let fits = ((area.bottom() - y) / row).floor().max(0.0) as usize;
    let skip = report.log.len().saturating_sub(fits);
    for entry in &report.log[skip..] {
        widgets::fitted_text(painter, pos2(area.left(), y), Align2::LEFT_TOP, entry, small.clone(), theme::TEXT_DIM, area.width());
        y += row;
    }
}

/// Repinta solo lo necesario: una vez por segundo en reposo, fluido mientras algo se mueve.
fn schedule_repaint(ui: &Ui, f: &Frame, state: &State, backgrounds: Option<&Backgrounds>) {
    let animating = state.phase != Phase::Idle && state.phase != Phase::Unknown
        || backgrounds.is_some_and(Backgrounds::is_fading)
        || state.timers.iter().any(|t| t.ringing)
        || state.exchange_at.is_some_and(|at| (CAPTION_SECONDS - 1.0..CAPTION_SECONDS).contains(&(f.now - at)));
    if animating {
        ui.ctx().request_repaint_after(Duration::from_millis(33)); // ~30 fps bastan para el anillo
    } else {
        let to_next_second = Duration::from_secs_f64(1.01 - f.now.fract());
        let next_photo = backgrounds.map_or(Duration::MAX, Backgrounds::next_change);
        ui.ctx().request_repaint_after(to_next_second.min(next_photo));
    }
}

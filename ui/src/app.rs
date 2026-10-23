//! La pantalla de cocina: reloj, temporizadores, lo que suena y el anillo de VOXA.
//!
//! Todo se dibuja sobre un diseño de 1920×1080 escalado a la ventana, para leerse a 3 m.

use std::path::PathBuf;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use egui::{Align2, CornerRadius, Painter, Pos2, Rect, Sense, Ui, pos2, vec2};

use crate::backgrounds::Backgrounds;
use crate::format;
use crate::link::Link;
use crate::protocol::{Command, Music, Phase, State, Timer};
use crate::theme;
use crate::widgets::{self, Icon, RingMode};

/// Segundos que se ve lo que se oyó y la respuesta.
const CAPTION_SECONDS: f64 = 10.0;
const HIDE_CURSOR_AFTER: Duration = Duration::from_secs(4);
/// Tras tocar una tarjeta, cuánto tiempo se ve su botón para cancelar.
const SELECT_SECONDS: Duration = Duration::from_secs(5);
const HINTS: [&str; 6] = [
    "«Pon un temporizador de 10 minutos para el arroz»",
    "«¿Cuánto le falta al arroz?»",
    "«Pon a Juan Gabriel»",
    "«Súbele a la música»",
    "«¿Va a llover hoy?»",
    "«¿Qué canción es esta?»",
];

pub struct Options {
    pub twenty_four_hours: bool,
    pub kiosk: bool,
    /// Guarda una imagen de la pantalla en este archivo y termina.
    pub capture: Option<PathBuf>,
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
        let painter = ui.painter().clone();
        painter.rect_filled(rect, CornerRadius::ZERO, theme::BG);
        if let Some(backgrounds) = &mut self.backgrounds {
            let ppp = ui.ctx().pixels_per_point();
            backgrounds.update(ui.ctx(), [(rect.width() * ppp) as u32, (rect.height() * ppp) as u32]);
            backgrounds.paint(&painter, rect, 0.72);
        }

        let margin = f.px(72.0);
        let split = rect.left() + rect.width() * 0.57;
        let left = Rect::from_min_max(rect.min + vec2(margin, margin), pos2(split - margin * 0.5, rect.bottom() - margin));
        let right = Rect::from_min_max(pos2(split + margin * 0.5, rect.top() + margin), rect.max - vec2(margin, margin));

        let caption_bottom = self.clock_and_caption(&painter, &f, left, &state);
        if let Some(music) = &state.music {
            let height = f.px(200.0);
            let card = Rect::from_min_max(pos2(left.left(), left.bottom() - height), left.max);
            if card.top() > caption_bottom {
                self.music_card(ui, &painter, &f, card, music);
            }
        } else if let Some(old) = self.art_url.take() {
            ui.ctx().forget_image(&old);
        }
        self.ring(ui, &painter, &f, right, &state, connected);
        let timers_area = Rect::from_min_max(pos2(right.left(), right.top() + f.px(250.0)), right.max);
        self.timers(ui, &painter, &f, timers_area, &state);
        let mut footer = rect.bottom() - f.px(28.0);
        if let Some(place) = self.backgrounds.as_ref().and_then(Backgrounds::caption) {
            let shown = painter.text(
                pos2(right.right(), footer),
                Align2::RIGHT_BOTTOM,
                place,
                theme::regular(f.px(24.0)),
                theme::alpha(theme::TEXT, 0.7),
            );
            footer = shown.top() - f.px(6.0);
        }
        if !connected {
            painter.text(
                pos2(right.right(), footer),
                Align2::RIGHT_BOTTOM,
                "Sin conexión con VOXA · reintentando…",
                theme::regular(f.px(24.0)),
                theme::TEXT_DIM,
            );
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
    fn clock_and_caption(&self, painter: &Painter, f: &Frame, area: Rect, state: &State) -> f32 {
        let local = chrono::Local::now();
        let date = format::date(local.date_naive());
        painter.text(area.left_top(), Align2::LEFT_TOP, &date, theme::regular(f.px(44.0)), theme::TEXT_DIM);

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
            painter.text(
                pos2(clock.right() + f.px(18.0), clock.bottom() - f.px(58.0)),
                Align2::LEFT_BOTTOM,
                suffix,
                theme::regular(f.px(48.0)),
                theme::TEXT_DIM,
            );
        }

        let mut y = clock.bottom() + f.px(24.0);
        let age = state.exchange_at.map_or(f64::INFINITY, |at| f.now - at);
        let fade = ((CAPTION_SECONDS - age) as f32).clamp(0.0, 1.0);
        let listening = matches!(state.phase, Phase::Listening | Phase::Thinking);
        if listening {
            let text = if state.phase == Phase::Listening { "Te escucho…" } else { "Un momento…" };
            painter.text(pos2(area.left(), y), Align2::LEFT_TOP, text, theme::regular(f.px(52.0)), theme::CYAN);
        } else if fade > 0.0 {
            if let Some(heard) = &state.heard {
                let galley = painter.layout(
                    format!("«{heard}»"),
                    theme::regular(f.px(38.0)),
                    theme::alpha(theme::TEXT_DIM, fade),
                    area.width(),
                );
                let h = galley.size().y;
                painter.galley(pos2(area.left(), y), galley, theme::TEXT_DIM);
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
                painter.galley(pos2(area.left(), y), galley, theme::TEXT);
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
                painter.text(bar.left_bottom() + vec2(0.0, f.px(12.0)), Align2::LEFT_TOP, format::track_time(position), font.clone(), theme::TEXT_DIM);
                painter.text(bar.right_bottom() + vec2(0.0, f.px(12.0)), Align2::RIGHT_TOP, format::track_time(length), font, theme::TEXT_DIM);
            }
        }
    }

    /// El anillo es también el botón para hablar.
    fn ring(&self, ui: &mut Ui, painter: &Painter, f: &Frame, area: Rect, state: &State, connected: bool) {
        let radius = f.px(92.0);
        let center = pos2(area.right() - radius - f.px(16.0), area.top() + radius + f.px(8.0));
        let response = ui.interact(Rect::from_center_size(center, vec2(radius, radius) * 2.6), ui.scope_id().with("hablar"), Sense::click());
        let mode = if connected { RingMode::Phase(state.phase) } else { RingMode::Disconnected };
        let scale = if response.is_pointer_button_down_on() { 0.94 } else { 1.0 };
        widgets::voxa_ring(painter, center, radius * scale, mode, f.time);
        if response.clicked() && connected && state.phase == Phase::Idle {
            self.send(Command::Talk);
        }

        // En reposo se invita a tocar; al escuchar o pensar lo dice el texto grande de la izquierda.
        if connected && state.phase == Phase::Idle {
            painter.text(
                pos2(center.x - radius * 1.45, center.y),
                Align2::RIGHT_CENTER,
                "Toca para hablar",
                theme::regular(f.px(30.0)),
                theme::TEXT_DIM,
            );
        }
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
            painter.text(pos2(area.left(), y), Align2::LEFT_TOP, text, theme::regular(f.px(32.0)), theme::TEXT_DIM);
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
            painter.text(card.left_top() + vec2(pad, pad * 0.8), Align2::LEFT_TOP, format!("¡{label} listo!"), theme::strong(f.px(52.0)), theme::TEXT);
            painter.text(card.left_bottom() + vec2(pad, -pad * 0.8), Align2::LEFT_BOTTOM, "Toca para detener la alarma", theme::regular(f.px(30.0)), theme::TEXT);
            if response.clicked() {
                self.send(Command::StopAlarm);
            }
            return;
        }

        painter.rect_filled(card, radius, if response.hovered() { theme::CARD_HOVER } else { theme::CARD });
        let label_font = theme::regular(f.px(36.0));
        widgets::fitted_text(painter, card.left_top() + vec2(pad, pad * 0.75), Align2::LEFT_TOP, &label, label_font, theme::TEXT_DIM, card.width() * 0.45);
        painter.text(
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
        painter.text(pos2(area.left(), y), Align2::LEFT_TOP, "Prueba decir:", theme::regular(f.px(34.0)), theme::TEXT_DIM);
        y += f.px(64.0);
        let n = (f.time / 8.0) as usize;
        for row in 0..3 {
            let hint = HINTS[(n + row) % HINTS.len()];
            let color = theme::alpha(theme::TEXT, if row == 0 { 0.9 } else { 0.45 });
            let galley = painter.layout(hint.to_owned(), theme::regular(f.px(40.0)), color, area.width());
            let height = galley.size().y;
            painter.galley(pos2(area.left(), y), galley, color);
            y += height + f.px(28.0);
        }
    }

    fn capture_if_requested(&mut self, ui: &Ui) {
        const WAIT: Duration = Duration::from_millis(2500); // conexión, estado y portada
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

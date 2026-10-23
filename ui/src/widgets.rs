//! Piezas dibujadas a mano: el anillo de VOXA, números de ancho fijo, botones y barras.

use std::f32::consts::TAU;

use egui::{Align2, Color32, CornerRadius, FontId, Painter, Pos2, Rect, Shape, Stroke, Vec2, pos2, vec2};

use crate::protocol::Phase;
use crate::theme;

/// Cómo se ve el anillo: depende de lo que VOXA está haciendo.
#[derive(Clone, Copy, PartialEq)]
pub enum RingMode {
    Phase(Phase),
    Disconnected,
}

/// El logo de VOXA (anillo abierto, barras de sonido y la V), animado como indicador.
///
/// Geometría tomada de `assets/brand/voxa_icon.svg`: centro (600, 470) y radio 250.
pub fn voxa_ring(painter: &Painter, center: Pos2, radius: f32, mode: RingMode, time: f64) {
    let k = radius / 250.0;
    let t = time as f32;
    let (brightness, glow) = match mode {
        RingMode::Disconnected => (0.35, 0.0),
        RingMode::Phase(Phase::Listening) => (1.0, 0.55 + 0.25 * (t * 4.0).sin()),
        RingMode::Phase(Phase::Speaking) => (1.0, 0.45),
        RingMode::Phase(Phase::Thinking) => (0.55, 0.0),
        RingMode::Phase(_) => (0.8, 0.0),
    };
    let color_at = |p: Vec2| {
        // El degradado del SVG va de arriba-izquierda a abajo-derecha.
        let along = (p.x * 0.8 + p.y * 0.55) / (250.0 * 1.95);
        let color = theme::gradient(0.5 + along);
        let color = if mode == RingMode::Disconnected { theme::gray(color) } else { color };
        // Opaco (mezclado con el fondo): los trazos se enciman y con transparencia se verían manchas.
        theme::lerp(theme::BG, color, brightness)
    };

    // Anillo: abierto arriba a la derecha (de -38° a -62°, como el logo).
    let (gap_start, gap_end) = ((-38.0f32).to_radians(), (-62.0f32).to_radians());
    let sweep = TAU - (gap_start - gap_end);
    let steps = 96;
    let point = |i: usize| {
        let a = gap_start + sweep * i as f32 / steps as f32;
        vec2(a.cos(), a.sin()) * 250.0
    };
    if glow > 0.0 {
        for (width, a) in [(70.0, 0.06), (46.0, 0.10)] {
            for i in 0..steps {
                let (p, q) = (point(i), point(i + 1));
                painter.line_segment(
                    [center + p * k, center + q * k],
                    Stroke::new(width * k, theme::alpha(color_at(p), a * glow)),
                );
            }
        }
    }
    for i in 0..steps {
        let (p, q) = (point(i), point(i + 1));
        let mut color = color_at(p);
        if mode == RingMode::Phase(Phase::Thinking) {
            // Un destello recorre el anillo mientras VOXA piensa.
            let head = (t * 1.6).rem_euclid(1.0) * steps as f32;
            let dist = ((i as f32 - head).rem_euclid(steps as f32)) / steps as f32;
            let tail = (1.0 - dist * 3.0).max(0.0);
            color = theme::lerp(color, theme::TEXT, tail * 0.6);
        }
        painter.line_segment([center + p * k, center + q * k], Stroke::new(26.0 * k, color));
    }
    painter.circle_filled(center + point(0) * k, 13.0 * k, color_at(point(0)));
    painter.circle_filled(center + point(steps) * k, 13.0 * k, color_at(point(steps)));

    // Barras de sonido: se mueven al escuchar y al hablar.
    let base = [26.0, 62.0, 26.0];
    let xs = [-196.0, -164.0, -132.0, 132.0, 164.0, 196.0];
    for (n, x) in xs.iter().enumerate() {
        let h = base[n % 3];
        let level = match mode {
            RingMode::Phase(Phase::Listening) => 0.55 + 0.6 * ((t * 7.0 + n as f32 * 1.3).sin() * 0.5 + 0.5),
            RingMode::Phase(Phase::Speaking) => 0.5 + 0.8 * ((t * 11.0 + n as f32 * 2.1).sin() * 0.5 + 0.5),
            _ => 1.0,
        };
        let half = (h * level).min(90.0);
        let top = vec2(*x, -half);
        let bottom = vec2(*x, half);
        painter.line_segment([center + top * k, center + bottom * k], Stroke::new(20.0 * k, color_at(vec2(*x, 0.0))));
        painter.circle_filled(center + top * k, 10.0 * k, color_at(top));
        painter.circle_filled(center + bottom * k, 10.0 * k, color_at(bottom));
    }

    // La V con su punta redondeada.
    let mut v = vec![vec2(-88.0, -98.0), vec2(-12.0, 70.0)];
    for i in 1..8 {
        let s = i as f32 / 8.0;
        let (a, c, b) = (vec2(-12.0, 70.0), vec2(0.0, 96.0), vec2(12.0, 70.0));
        v.push(a * (1.0 - s) * (1.0 - s) + c * 2.0 * s * (1.0 - s) + b * s * s);
    }
    v.extend([vec2(12.0, 70.0), vec2(88.0, -98.0)]);
    for pair in v.windows(2) {
        painter.line_segment(
            [center + pair[0] * k, center + pair[1] * k],
            Stroke::new(68.0 * k, color_at(pair[0])),
        );
    }
    for p in &v {
        painter.circle_filled(center + *p * k, 34.0 * k, color_at(*p));
    }
}

/// Texto con dígitos de ancho fijo: el reloj y las cuentas regresivas no «bailan» al cambiar.
pub fn tabular_text(painter: &Painter, pos: Pos2, anchor: Align2, text: &str, font: FontId, color: Color32) -> Rect {
    let digit_width = (0..10)
        .map(|d| painter.layout_no_wrap(d.to_string(), font.clone(), color).size().x)
        .fold(0.0, f32::max);
    let glyphs: Vec<_> = text
        .chars()
        .map(|c| {
            let galley = painter.layout_no_wrap(c.to_string(), font.clone(), color);
            let width = if c.is_ascii_digit() { digit_width } else { galley.size().x };
            (galley, width)
        })
        .collect();
    let height = glyphs.iter().map(|(g, _)| g.size().y).fold(0.0, f32::max);
    let width: f32 = glyphs.iter().map(|(_, w)| w).sum();
    let rect = anchor.anchor_size(pos, vec2(width, height));
    let mut x = rect.left();
    for (galley, w) in glyphs {
        let offset = (w - galley.size().x) / 2.0;
        painter.galley(pos2(x + offset, rect.top()), galley, color);
        x += w;
    }
    rect
}

/// Texto que no cabe en `max`: se corta con «…».
pub fn fitted_text(painter: &Painter, pos: Pos2, anchor: Align2, text: &str, font: FontId, color: Color32, max: f32) -> Rect {
    let fits = |s: &str| painter.layout_no_wrap(s.to_owned(), font.clone(), color).size().x <= max;
    let mut shown = text.to_owned();
    if !fits(text) {
        let chars: Vec<char> = text.chars().collect();
        for n in (1..chars.len()).rev() {
            shown = chars[..n].iter().collect::<String>().trim_end().to_owned() + "…";
            if fits(&shown) {
                break;
            }
        }
    }
    painter.text(pos, anchor, shown, font, color)
}

/// Barra de progreso redondeada; sin color fijo usa el degradado de la marca.
pub fn progress_bar(painter: &Painter, rect: Rect, fraction: f32, fill: Option<Color32>) {
    let r = rect.height() / 2.0;
    painter.rect_filled(rect, CornerRadius::same(r.round() as u8), theme::TRACK);
    let fraction = fraction.clamp(0.0, 1.0);
    if fraction <= 0.0 {
        return;
    }
    let width = (rect.width() * fraction).max(rect.height());
    let (x0, x1) = (rect.left() + r, rect.left() + width - r);
    let (left, right) = match fill {
        Some(color) => (color, color),
        None => (theme::gradient(0.0), theme::gradient(fraction)),
    };
    let mut mesh = egui::Mesh::default();
    mesh.colored_vertex(pos2(x0, rect.top()), left);
    mesh.colored_vertex(pos2(x1, rect.top()), right);
    mesh.colored_vertex(pos2(x1, rect.bottom()), right);
    mesh.colored_vertex(pos2(x0, rect.bottom()), left);
    mesh.add_triangle(0, 1, 2);
    mesh.add_triangle(0, 2, 3);
    painter.add(Shape::mesh(mesh));
    painter.circle_filled(pos2(x0, rect.center().y), r, left);
    painter.circle_filled(pos2(x1, rect.center().y), r, right);
}

#[derive(Clone, Copy)]
pub enum Icon {
    Play,
    Pause,
    Next,
    Previous,
    Close,
    Note,
}

/// Iconos dibujados con formas simples (no dependen de que la letra tenga esos símbolos).
pub fn icon(painter: &Painter, center: Pos2, size: f32, icon: Icon, color: Color32) {
    let s = size / 2.0;
    let tri = |points: [Vec2; 3]| Shape::convex_polygon(points.map(|p| center + p * s).to_vec(), color, Stroke::NONE);
    match icon {
        Icon::Play => {
            painter.add(tri([vec2(-0.55, -0.8), vec2(0.85, 0.0), vec2(-0.55, 0.8)]));
        }
        Icon::Pause => {
            for x in [-0.4, 0.4] {
                let r = Rect::from_center_size(center + vec2(x, 0.0) * s, vec2(0.42, 1.6) * s);
                painter.rect_filled(r, CornerRadius::same((s * 0.12) as u8), color);
            }
        }
        Icon::Next | Icon::Previous => {
            let dir = if matches!(icon, Icon::Next) { 1.0 } else { -1.0 };
            painter.add(tri([vec2(-0.7 * dir, -0.7), vec2(0.4 * dir, 0.0), vec2(-0.7 * dir, 0.7)]));
            let bar = Rect::from_center_size(center + vec2(0.6 * dir, 0.0) * s, vec2(0.25, 1.4) * s);
            painter.rect_filled(bar, CornerRadius::same((s * 0.1) as u8), color);
        }
        Icon::Close => {
            let stroke = Stroke::new(s * 0.22, color);
            painter.line_segment([center + vec2(-0.6, -0.6) * s, center + vec2(0.6, 0.6) * s], stroke);
            painter.line_segment([center + vec2(0.6, -0.6) * s, center + vec2(-0.6, 0.6) * s], stroke);
        }
        Icon::Note => {
            let stroke = Stroke::new(s * 0.14, color);
            painter.circle_filled(center + vec2(-0.35, 0.55) * s, s * 0.3, color);
            painter.line_segment([center + vec2(-0.08, 0.55) * s, center + vec2(-0.08, -0.75) * s], stroke);
            painter.line_segment([center + vec2(-0.08, -0.75) * s, center + vec2(0.5, -0.45) * s], stroke);
        }
    }
}

/// Fase de una animación periódica, 0..1.
pub fn pulse(time: f64, period: f64) -> f32 {
    (0.5 - 0.5 * ((time / period) * std::f64::consts::TAU).cos()) as f32
}

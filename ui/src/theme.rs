//! Colores y tipografía de la marca (assets/brand).

use egui::{Color32, FontData, FontDefinitions, FontFamily, FontId};
use std::sync::Arc;

pub const BG: Color32 = Color32::from_rgb(0x0B, 0x10, 0x20);
// Tarjetas algo translúcidas: sobre una foto de fondo se alcanza a ver el paisaje.
pub const CARD: Color32 = Color32::from_rgba_unmultiplied_const(0x15, 0x1C, 0x33, 0xD8);
pub const CARD_HOVER: Color32 = Color32::from_rgba_unmultiplied_const(0x1C, 0x25, 0x42, 0xE6);
pub const TRACK: Color32 = Color32::from_rgba_unmultiplied_const(0x3A, 0x45, 0x6A, 0xB0);
pub const TEXT: Color32 = Color32::from_rgb(0xF8, 0xFA, 0xFF);
pub const TEXT_DIM: Color32 = Color32::from_rgb(0x9A, 0xA4, 0xC2);
pub const CYAN: Color32 = Color32::from_rgb(0x11, 0xDD, 0xF2);
pub const BLUE: Color32 = Color32::from_rgb(0x34, 0x78, 0xFF);
pub const PURPLE: Color32 = Color32::from_rgb(0xD5, 0x2B, 0xFF);
pub const ALARM: Color32 = Color32::from_rgb(0xFF, 0xB3, 0x47);
pub const ALARM_DIM: Color32 = Color32::from_rgb(0x3A, 0x2C, 0x22);

const STRONG: &str = "fuerte";

/// Inter (la letra del logo), incluida en el binario: se ve igual en cualquier equipo.
pub fn fonts() -> FontDefinitions {
    let mut fonts = FontDefinitions::default();
    fonts.font_data.insert(
        "Inter".into(),
        Arc::new(FontData::from_static(include_bytes!("../assets/fonts/Inter-Regular.ttf"))),
    );
    fonts.font_data.insert(
        "Inter-SemiBold".into(),
        Arc::new(FontData::from_static(include_bytes!("../assets/fonts/Inter-SemiBold.ttf"))),
    );
    let fallback = fonts.families.get(&FontFamily::Proportional).cloned().unwrap_or_default();
    fonts.families.insert(FontFamily::Proportional, [vec!["Inter".to_owned()], fallback.clone()].concat());
    fonts
        .families
        .insert(FontFamily::Name(STRONG.into()), [vec!["Inter-SemiBold".to_owned()], fallback].concat());
    fonts
}

pub fn regular(size: f32) -> FontId {
    FontId::proportional(size)
}

pub fn strong(size: f32) -> FontId {
    FontId::new(size, FontFamily::Name(STRONG.into()))
}

/// Degradado de la marca: cian → azul → morado, `t` en 0..1.
pub fn gradient(t: f32) -> Color32 {
    let t = t.clamp(0.0, 1.0);
    if t < 0.48 { lerp(CYAN, BLUE, t / 0.48) } else { lerp(BLUE, PURPLE, (t - 0.48) / 0.52) }
}

pub fn lerp(a: Color32, b: Color32, t: f32) -> Color32 {
    let mix = |x: u8, y: u8| (x as f32 + (y as f32 - x as f32) * t).round() as u8;
    Color32::from_rgba_unmultiplied(mix(a.r(), b.r()), mix(a.g(), b.g()), mix(a.b(), b.b()), mix(a.a(), b.a()))
}

pub fn alpha(color: Color32, a: f32) -> Color32 {
    color.gamma_multiply(a.clamp(0.0, 1.0))
}

/// Gris con la misma luminosidad (anillo sin conexión).
pub fn gray(color: Color32) -> Color32 {
    let l = (0.3 * color.r() as f32 + 0.59 * color.g() as f32 + 0.11 * color.b() as f32) as u8;
    Color32::from_rgba_unmultiplied(l, l, l, color.a())
}

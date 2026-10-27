//! Fechas, horas y duraciones para la pantalla, en el idioma de la casa.

use chrono::{Datelike, NaiveDate, NaiveTime, Timelike};

use crate::i18n;

const DAYS: [&str; 7] = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
const MONTHS: [&str; 12] = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
    "noviembre", "diciembre",
];
const DAYS_EN: [&str; 7] = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const MONTHS_EN: [&str; 12] = [
    "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
    "November", "December",
];

/// «jueves 23 de octubre» («Thursday, October 23»)
pub fn date(date: NaiveDate) -> String {
    if i18n::english() {
        let day = DAYS_EN[date.weekday().num_days_from_monday() as usize];
        return format!("{day}, {} {}", MONTHS_EN[date.month0() as usize], date.day());
    }
    let day = DAYS[date.weekday().num_days_from_monday() as usize];
    let month = MONTHS[date.month0() as usize];
    format!("{day} {} de {month}", date.day())
}

/// Hora y, en formato de 12 h, «a. m.» / «p. m.» aparte (se dibuja más chico).
pub fn clock(time: NaiveTime, twenty_four: bool) -> (String, Option<&'static str>) {
    if twenty_four {
        return (format!("{}:{:02}", time.hour(), time.minute()), None);
    }
    let (pm, hour) = time.hour12();
    let suffix = match (pm, i18n::english()) {
        (true, true) => "PM",
        (false, true) => "AM",
        (true, false) => "p. m.",
        (false, false) => "a. m.",
    };
    (format!("{hour}:{:02}", time.minute()), Some(suffix))
}

/// Cuenta regresiva: «9», «4:05», «1:02:03». Redondea hacia arriba: «0:01» hasta el final.
pub fn countdown(seconds: f64) -> String {
    let total = seconds.max(0.0).ceil() as u64;
    let (h, m, s) = (total / 3600, total / 60 % 60, total % 60);
    if h > 0 { format!("{h}:{m:02}:{s:02}") } else { format!("{m}:{s:02}") }
}

/// Posición de una canción: «3:07».
pub fn track_time(seconds: f64) -> String {
    let total = seconds.max(0.0).floor() as u64;
    format!("{}:{:02}", total / 60, total % 60)
}

/// Duración para el subtítulo de un temporizador: «10 min», «1 h 30 min», «45 s».
pub fn duration(seconds: f64) -> String {
    let total = seconds.round() as u64;
    let (h, m, s) = (total / 3600, total / 60 % 60, total % 60);
    match (h, m, s) {
        (0, 0, s) => format!("{s} s"),
        (0, m, 0) => format!("{m} min"),
        (0, m, s) => format!("{m} min {s} s"),
        (h, 0, _) => format!("{h} h"),
        (h, m, _) => format!("{h} h {m} min"),
    }
}

/// «arroz» → «Arroz».
pub fn capitalize(text: &str) -> String {
    let mut chars = text.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().chain(chars).collect(),
        None => String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spanish_date() {
        assert_eq!(date(NaiveDate::from_ymd_opt(2026, 10, 23).unwrap()), "viernes 23 de octubre");
        assert_eq!(date(NaiveDate::from_ymd_opt(2026, 9, 16).unwrap()), "miércoles 16 de septiembre");
        i18n::set_language("en");
        assert_eq!(date(NaiveDate::from_ymd_opt(2026, 10, 23).unwrap()), "Friday, October 23");
        assert_eq!(clock(NaiveTime::from_hms_opt(16, 5, 0).unwrap(), false), ("4:05".into(), Some("PM")));
        i18n::set_language("es");
    }

    #[test]
    fn clock_12_and_24() {
        let t = NaiveTime::from_hms_opt(16, 5, 0).unwrap();
        assert_eq!(clock(t, false), ("4:05".into(), Some("p. m.")));
        assert_eq!(clock(t, true), ("16:05".into(), None));
        let midnight = NaiveTime::from_hms_opt(0, 30, 0).unwrap();
        assert_eq!(clock(midnight, false), ("12:30".into(), Some("a. m.")));
    }

    #[test]
    fn countdowns() {
        assert_eq!(countdown(245.0), "4:05");
        assert_eq!(countdown(0.2), "0:01");
        assert_eq!(countdown(0.0), "0:00");
        assert_eq!(countdown(3723.0), "1:02:03");
        assert_eq!(track_time(187.9), "3:07");
    }

    #[test]
    fn durations() {
        assert_eq!(duration(600.0), "10 min");
        assert_eq!(duration(5400.0), "1 h 30 min");
        assert_eq!(duration(45.0), "45 s");
        assert_eq!(duration(90.0), "1 min 30 s");
        assert_eq!(capitalize("ñoquis"), "Ñoquis");
    }
}

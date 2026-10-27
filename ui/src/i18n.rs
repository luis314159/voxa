//! El idioma de la pantalla: el de la casa, que VOXA manda en el estado (`language`).
//!
//! Cada texto lleva sus dos versiones juntas: `t("Te escucho…", "Listening…")`.

use std::cell::Cell;

thread_local! {
    // La pantalla se dibuja en un solo hilo; así cada prueba tiene el suyo.
    static ENGLISH: Cell<bool> = const { Cell::new(false) };
}

pub fn set_language(code: &str) {
    ENGLISH.with(|english| english.set(code == "en"));
}

pub fn english() -> bool {
    ENGLISH.with(Cell::get)
}

/// El texto en el idioma de la casa.
pub fn t<'a>(spanish: &'a str, english_text: &'a str) -> &'a str {
    if english() { english_text } else { spanish }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn picks_the_home_language() {
        assert_eq!(t("Te escucho…", "Listening…"), "Te escucho…");
        set_language("en");
        assert_eq!(t("Te escucho…", "Listening…"), "Listening…");
        set_language("es");
        assert!(!english());
    }
}

//! voxa-ui: la pantalla de cocina de VOXA.
//!
//! Se conecta a `voxa servicio` por 127.0.0.1 y dibuja reloj, temporizadores, música y el anillo.
//!
//!     voxa-ui [--completa] [--24h] [--puerto 8766] [--fondos CARPETA] [--cambio-fondo MINUTOS]
//!     voxa-ui --captura pantalla.png [--tamano 1920x1080]   (imagen para documentar y revisar)

mod app;
mod backgrounds;
mod format;
mod link;
mod protocol;
mod theme;
mod widgets;

use std::net::{Ipv4Addr, SocketAddr};
use std::path::PathBuf;
use std::time::Duration;

const DEFAULT_PORT: u16 = 8766;

const USAGE: &str = "uso: voxa-ui [--completa] [--24h] [--puerto 8766] [--fondos CARPETA | --sin-fondos] \
                     [--cambio-fondo MINUTOS] [--captura archivo.png] [--tamano 1920x1080]";

struct Args {
    kiosk: bool,
    twenty_four_hours: bool,
    port: u16,
    capture: Option<PathBuf>,
    size: [f32; 2],
    backgrounds: Option<PathBuf>,
    background_minutes: f32,
}

/// Carpeta de fondos por defecto: `~/.local/share/voxa/fondos` (o `%LOCALAPPDATA%\voxa\fondos`).
fn default_backgrounds() -> Option<PathBuf> {
    let env = |name: &str| std::env::var_os(name).filter(|v| !v.is_empty()).map(PathBuf::from);
    let data = if cfg!(windows) {
        env("LOCALAPPDATA")?
    } else {
        env("XDG_DATA_HOME").or_else(|| env("HOME").map(|home| home.join(".local").join("share")))?
    };
    Some(data.join("voxa").join("fondos"))
}

fn parse_args() -> Result<Args, String> {
    let mut args = Args {
        kiosk: false,
        twenty_four_hours: false,
        port: DEFAULT_PORT,
        capture: None,
        size: [1280.0, 720.0],
        backgrounds: default_backgrounds(),
        background_minutes: 10.0,
    };
    let mut iter = std::env::args().skip(1);
    while let Some(arg) = iter.next() {
        match arg.as_str() {
            "--completa" => args.kiosk = true,
            "--24h" => args.twenty_four_hours = true,
            "--puerto" => {
                let value = iter.next().ok_or("falta el número después de --puerto")?;
                args.port = value.parse().map_err(|_| format!("puerto inválido: {value}"))?;
            }
            "--captura" => args.capture = Some(iter.next().ok_or("falta el archivo después de --captura")?.into()),
            "--tamano" => {
                let value = iter.next().ok_or("falta el tamaño después de --tamano (p. ej. 1920x1080)")?;
                let (w, h) = value.split_once('x').ok_or(format!("tamaño inválido: {value}"))?;
                let parse = |n: &str| n.parse::<f32>().map_err(|_| format!("tamaño inválido: {value}"));
                args.size = [parse(w)?, parse(h)?];
            }
            "--fondos" => args.backgrounds = Some(iter.next().ok_or("falta la carpeta después de --fondos")?.into()),
            "--sin-fondos" => args.backgrounds = None,
            "--cambio-fondo" => {
                let value = iter.next().ok_or("faltan los minutos después de --cambio-fondo")?;
                args.background_minutes = value
                    .parse::<f32>()
                    .ok()
                    .filter(|m| *m > 0.0)
                    .ok_or(format!("minutos inválidos: {value}"))?;
            }
            "-h" | "--help" | "--ayuda" => return Err(USAGE.into()),
            other => return Err(format!("opción desconocida: {other}")),
        }
    }
    Ok(args)
}

fn main() -> eframe::Result {
    let args = match parse_args() {
        Ok(args) => args,
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(2);
        }
    };
    let mut viewport = egui::ViewportBuilder::default()
        .with_title("VOXA")
        .with_inner_size(args.size)
        .with_min_inner_size([640.0, 360.0]);
    if args.kiosk {
        viewport = viewport.with_fullscreen(true).with_decorations(false);
    }
    let options = eframe::NativeOptions { viewport, ..Default::default() };
    let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, args.port));
    if args.capture.is_some() {
        // Si la ventana no llega a pintarse (minimizada, sin pantalla), no quedarse colgado.
        std::thread::spawn(|| {
            std::thread::sleep(Duration::from_secs(20));
            eprintln!("voxa-ui: la captura no se completó en 20 s");
            std::process::exit(1);
        });
    }

    eframe::run_native(
        "VOXA",
        options,
        Box::new(move |cc| {
            cc.egui_ctx.set_fonts(theme::fonts());
            egui_extras::install_image_loaders(&cc.egui_ctx);
            let ctx = cc.egui_ctx.clone();
            let link = link::Link::start(addr, move || ctx.request_repaint());
            let options =
                app::Options { twenty_four_hours: args.twenty_four_hours, kiosk: args.kiosk, capture: args.capture };
            let interval = Duration::from_secs_f32(args.background_minutes * 60.0);
            let backgrounds = args
                .backgrounds
                .as_deref()
                .and_then(|folder| backgrounds::Backgrounds::start(folder, interval, cc.egui_ctx.clone()));
            Ok(Box::new(app::VoxaApp::new(link, options, backgrounds)))
        }),
    )
}

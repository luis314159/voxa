//! Fondos de pantalla: fotos de una carpeta que rotan con un fundido suave.
//!
//! Las fotos se leen y escalan en un hilo aparte (decodificar un JPEG grande tarda) y solo hay
//! dos texturas en memoria a la vez: la actual y la anterior durante el fundido. Si en la
//! carpeta hay un `catalogo.json` (ver `scripts/descargar_fondos.py`), se muestra el lugar.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use egui::{Color32, ColorImage, Context, Painter, Rect, TextureHandle, TextureOptions, pos2};
use image::imageops::FilterType;
use serde::Deserialize;

const FADE: Duration = Duration::from_millis(2500);
const EXTENSIONS: [&str; 3] = ["jpg", "jpeg", "png"];

struct Loaded {
    image: ColorImage,
    caption: Option<String>,
}

struct Shown {
    texture: TextureHandle,
    caption: Option<String>,
}

pub struct Backgrounds {
    requests: Sender<[u32; 2]>,
    loaded: Receiver<Loaded>,
    current: Option<Shown>,
    previous: Option<Shown>,
    shown_at: Instant,
    interval: Duration,
    waiting: bool,
}

#[derive(Deserialize)]
struct Entry {
    archivo: String,
    lugar: Option<String>,
}

impl Backgrounds {
    /// `None` si la carpeta no existe o no tiene fotos: la pantalla usa el fondo liso.
    pub fn start(folder: &Path, interval: Duration, ctx: Context) -> Option<Self> {
        let files = list_images(folder);
        if files.is_empty() {
            return None;
        }
        let mut captions = read_captions(folder);
        let folder = folder.to_path_buf();
        let (requests, worker_requests) = mpsc::channel::<[u32; 2]>();
        let (worker_loaded, loaded) = mpsc::channel();
        thread::Builder::new()
            .name("voxa-fondos".into())
            .spawn(move || {
                let mut files = files;
                let mut order = Shuffled::new(files.len());
                let mut fresh: Vec<PathBuf> = Vec::new();
                for size in worker_requests {
                    // La carpeta se vuelve a leer: las fotos nuevas (p. ej. subidas desde el celular) van primero.
                    let now = list_images(&folder);
                    if now != files {
                        fresh.extend(now.iter().filter(|p| !files.contains(p)).cloned());
                        files = now;
                        captions = read_captions(&folder);
                        order = Shuffled::new(files.len());
                    }
                    // Hasta encontrar una que se pueda leer (una foto dañada no detiene la rotación).
                    for _ in 0..files.len() + fresh.len() {
                        let path = match fresh.pop() {
                            Some(path) => path,
                            None => files[order.next()].clone(),
                        };
                        let path = &path;
                        match load(path, size) {
                            Ok(image) => {
                                let caption = file_name(path).and_then(|name| captions.get(&name).cloned());
                                if worker_loaded.send(Loaded { image, caption }).is_err() {
                                    return;
                                }
                                ctx.request_repaint();
                                break;
                            }
                            Err(err) => eprintln!("voxa-ui: no pude abrir el fondo {}: {err}", path.display()),
                        }
                    }
                }
            })
            .ok()?;
        Some(Self { requests, loaded, current: None, previous: None, shown_at: Instant::now(), interval, waiting: false })
    }

    /// Pide la siguiente foto cuando toca y sube la que ya esté lista.
    pub fn update(&mut self, ctx: &Context, size: [u32; 2]) {
        if let Ok(loaded) = self.loaded.try_recv() {
            let texture = ctx.load_texture("fondo", loaded.image, TextureOptions::LINEAR);
            self.previous = self.current.replace(Shown { texture, caption: loaded.caption });
            self.shown_at = Instant::now();
            self.waiting = false;
        }
        let due = self.current.is_none() || self.shown_at.elapsed() >= self.interval;
        if due && !self.waiting && self.requests.send(size).is_ok() {
            self.waiting = true;
        }
        if self.shown_at.elapsed() >= FADE {
            self.previous = None; // libera la textura anterior
        }
    }

    pub fn is_fading(&self) -> bool {
        self.previous.is_some() || (self.current.is_some() && self.shown_at.elapsed() < FADE)
    }

    /// Cuánto falta para la siguiente foto (para programar el repintado).
    pub fn next_change(&self) -> Duration {
        self.interval.saturating_sub(self.shown_at.elapsed())
    }

    pub fn caption(&self) -> Option<&str> {
        self.current.as_ref()?.caption.as_deref()
    }

    /// Dibuja la foto oscurecida y un velo más denso a la izquierda, donde va el texto grande.
    /// `dim`: brillo de la foto (1 = tal cual). `veil`: cuánto del velo oscuro que hace legible el texto
    /// (más a la izquierda, donde va el reloj); 0 = sin velo.
    pub fn paint(&self, painter: &Painter, rect: Rect, dim: f32, veil: f32) {
        let Some(current) = &self.current else { return };
        let uv = Rect::from_min_max(pos2(0.0, 0.0), pos2(1.0, 1.0));
        let level = (255.0 * dim) as u8;
        let fade = (self.shown_at.elapsed().as_secs_f32() / FADE.as_secs_f32()).clamp(0.0, 1.0);
        if let Some(previous) = &self.previous {
            painter.image(previous.texture.id(), rect, uv, Color32::from_gray(level));
        }
        painter.image(current.texture.id(), rect, uv, Color32::from_gray(level).gamma_multiply(fade));
        if veil <= 0.0 {
            return;
        }

        let mut shade = egui::Mesh::default();
        let dark = |a: f32| Color32::from_rgba_unmultiplied(0x0B, 0x10, 0x20, (a * 255.0) as u8);
        let middle = rect.left() + rect.width() * 0.62;
        for (x, a) in [(rect.left(), 0.66 * veil), (middle, 0.30 * veil), (rect.right(), 0.42 * veil)] {
            shade.colored_vertex(pos2(x, rect.top()), dark(a));
            shade.colored_vertex(pos2(x, rect.bottom()), dark(a));
        }
        for i in [0u32, 2] {
            shade.add_triangle(i, i + 1, i + 2);
            shade.add_triangle(i + 1, i + 3, i + 2);
        }
        painter.add(egui::Shape::mesh(shade));
    }
}

fn list_images(folder: &Path) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(folder) else { return Vec::new() };
    let mut files: Vec<PathBuf> = entries
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| {
            p.extension()
                .and_then(|e| e.to_str())
                .is_some_and(|e| EXTENSIONS.contains(&e.to_ascii_lowercase().as_str()))
        })
        .collect();
    files.sort();
    files
}

fn file_name(path: &Path) -> Option<String> {
    path.file_name()?.to_str().map(str::to_owned)
}

fn read_captions(folder: &Path) -> HashMap<String, String> {
    let Ok(text) = std::fs::read_to_string(folder.join("catalogo.json")) else { return HashMap::new() };
    match serde_json::from_str::<Vec<Entry>>(&text) {
        Ok(entries) => entries.into_iter().filter_map(|e| Some((e.archivo, e.lugar?))).collect(),
        Err(err) => {
            eprintln!("voxa-ui: catalogo.json inválido: {err}");
            HashMap::new()
        }
    }
}

/// Lee la foto y la recorta para cubrir la pantalla sin deformarla.
fn load(path: &Path, [width, height]: [u32; 2]) -> Result<ColorImage, image::ImageError> {
    let photo = image::open(path)?;
    let photo = photo.resize_to_fill(width.max(1), height.max(1), FilterType::Triangle).to_rgba8();
    let size = [photo.width() as usize, photo.height() as usize];
    Ok(ColorImage::from_rgba_unmultiplied(size, photo.as_raw()))
}

/// Recorre todas las fotos en orden aleatorio antes de repetir.
struct Shuffled {
    order: Vec<usize>,
    pos: usize,
    seed: u64,
}

impl Shuffled {
    fn new(len: usize) -> Self {
        let seed = SystemTime::now().duration_since(UNIX_EPOCH).map_or(1, |d| d.as_nanos() as u64) | 1;
        let mut shuffled = Self { order: (0..len).collect(), pos: len, seed };
        shuffled.reshuffle();
        shuffled
    }

    fn random(&mut self) -> u64 {
        // xorshift64: suficiente para barajar fotos.
        self.seed ^= self.seed << 13;
        self.seed ^= self.seed >> 7;
        self.seed ^= self.seed << 17;
        self.seed
    }

    fn reshuffle(&mut self) {
        for i in (1..self.order.len()).rev() {
            let j = (self.random() % (i as u64 + 1)) as usize;
            self.order.swap(i, j);
        }
        self.pos = 0;
    }

    fn next(&mut self) -> usize {
        if self.pos >= self.order.len() {
            let last = self.order.last().copied();
            self.reshuffle();
            if self.order.len() > 1 && self.order.first().copied() == last {
                self.order.swap(0, 1); // que no se repita la misma al dar la vuelta
            }
        }
        self.pos += 1;
        self.order[self.pos - 1]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shuffled_visits_every_photo_before_repeating() {
        let mut order = Shuffled::new(7);
        for _ in 0..3 {
            let mut round: Vec<usize> = (0..7).map(|_| order.next()).collect();
            round.sort();
            assert_eq!(round, (0..7).collect::<Vec<_>>());
        }
    }

    #[test]
    fn single_photo_repeats() {
        let mut order = Shuffled::new(1);
        assert_eq!((order.next(), order.next()), (0, 0));
    }
}

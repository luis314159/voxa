//! Conexión con VOXA en un hilo aparte: se reconecta sola si VOXA se reinicia.

use std::io::{BufRead, BufReader, Write};
use std::net::{SocketAddr, TcpStream};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::Duration;

use crate::protocol::{self, Command, State};

const RETRY: Duration = Duration::from_secs(1);

#[derive(Default)]
struct Shared {
    state: State,
    connected: bool,
}

#[derive(Clone)]
pub struct Link {
    shared: Arc<Mutex<Shared>>,
    writer: Arc<Mutex<Option<TcpStream>>>,
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

impl Link {
    /// Arranca el hilo de conexión; `on_change` se llama con cada novedad (para repintar).
    pub fn start(addr: SocketAddr, on_change: impl Fn() + Send + 'static) -> Self {
        let link = Self { shared: Arc::default(), writer: Arc::default() };
        let worker = link.clone();
        thread::Builder::new()
            .name("voxa-link".into())
            .spawn(move || worker.run(addr, on_change))
            .expect("no se pudo crear el hilo de conexión");
        link
    }

    fn run(&self, addr: SocketAddr, on_change: impl Fn()) {
        let mut warned = false;
        loop {
            if let Ok(stream) = TcpStream::connect_timeout(&addr, RETRY) {
                let _ = stream.set_nodelay(true);
                *lock(&self.writer) = stream.try_clone().ok();
                lock(&self.shared).connected = true;
                on_change();
                for line in BufReader::new(stream).lines() {
                    let Ok(line) = line else { break };
                    if let Some(state) = protocol::parse_line(&line) {
                        if state.v > protocol::PROTOCOL_VERSION && !warned {
                            eprintln!("voxa-ui: VOXA usa una versión más nueva del protocolo; actualiza la pantalla");
                            warned = true;
                        }
                        lock(&self.shared).state = state;
                        on_change();
                    }
                }
                *lock(&self.writer) = None;
                lock(&self.shared).connected = false;
                on_change();
            }
            thread::sleep(RETRY);
        }
    }

    /// Copia del estado actual y si hay conexión.
    pub fn snapshot(&self) -> (State, bool) {
        let shared = lock(&self.shared);
        (shared.state.clone(), shared.connected)
    }

    /// Envía una orden; `false` si no hay conexión.
    pub fn send(&self, command: &Command) -> bool {
        let mut writer = lock(&self.writer);
        match writer.as_mut() {
            Some(stream) => stream.write_all(command.to_line().as_bytes()).is_ok(),
            None => false,
        }
    }
}

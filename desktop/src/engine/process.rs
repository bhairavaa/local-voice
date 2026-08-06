//! Engine process lifecycle.
//!
//! The shell owns the engine: it starts it, waits for the handshake, and stops it on exit.
//! The engine independently supervises this process, so if the shell is killed rather than
//! closed the engine still terminates itself.

use std::io::{BufRead, BufReader};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use crate::engine::handshake::{Handshake, HandshakeError};
use crate::engine::launcher::{self, ResolveError};

/// How long to wait for the engine to publish its handshake before giving up.
const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Debug, thiserror::Error)]
pub enum EngineError {
    #[error(transparent)]
    Resolve(#[from] ResolveError),

    #[error("could not start the engine process: {0}")]
    Spawn(#[source] std::io::Error),

    #[error("engine did not publish a handshake within {}s", STARTUP_TIMEOUT.as_secs())]
    StartupTimeout,

    #[error("engine exited before publishing a handshake")]
    ExitedEarly,

    #[error(transparent)]
    Handshake(#[from] HandshakeError),
}

/// A running engine and the connection details it published.
pub struct EngineProcess {
    child: Child,
    handshake: Handshake,
}

impl EngineProcess {
    /// Start the engine and block until it reports where it is listening.
    pub fn start(resource_dir: &Path, engine_dir: &Path) -> Result<Self, EngineError> {
        let command = launcher::resolve(resource_dir, engine_dir)?;

        let mut builder = Command::new(&command.program);
        builder
            .args(&command.arguments)
            .arg("--parent-pid")
            .arg(std::process::id().to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());

        if let Some(directory) = &command.working_directory {
            builder.current_dir(directory);
        }

        let mut child = builder.spawn().map_err(EngineError::Spawn)?;
        let stdout = child.stdout.take().ok_or(EngineError::ExitedEarly)?;

        match read_handshake_line(stdout) {
            Ok(line) => {
                let handshake = Handshake::parse(&line)?;
                tracing::info!(
                    port = handshake.port,
                    pid = handshake.pid,
                    version = %handshake.version,
                    "engine started"
                );
                Ok(Self { child, handshake })
            }
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                Err(error)
            }
        }
    }

    pub fn handshake(&self) -> &Handshake {
        &self.handshake
    }

    /// Stop the engine, falling back to a kill if it does not exit promptly.
    pub fn shutdown(mut self) {
        tracing::info!(pid = self.handshake.pid, "stopping engine");

        if let Err(error) = self.child.kill() {
            tracing::warn!(%error, "could not signal the engine process");
        }
        if let Err(error) = self.child.wait() {
            tracing::warn!(%error, "could not reap the engine process");
        }
    }
}

/// Read the single handshake line without blocking shutdown forever if it never arrives.
fn read_handshake_line(stdout: std::process::ChildStdout) -> Result<String, EngineError> {
    let (sender, receiver) = mpsc::channel();

    thread::spawn(move || {
        let mut line = String::new();
        let result = BufReader::new(stdout).read_line(&mut line);
        let _ = sender.send(result.map(|bytes| (bytes, line)));
    });

    match receiver.recv_timeout(STARTUP_TIMEOUT) {
        Ok(Ok((0, _))) => Err(EngineError::ExitedEarly),
        Ok(Ok((_, line))) => Ok(line),
        Ok(Err(error)) => Err(EngineError::Spawn(error)),
        Err(mpsc::RecvTimeoutError::Timeout) => Err(EngineError::StartupTimeout),
        Err(mpsc::RecvTimeoutError::Disconnected) => Err(EngineError::ExitedEarly),
    }
}

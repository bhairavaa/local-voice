//! Resolving which engine executable to run.
//!
//! A packaged installation ships a self-contained engine binary next to the application. A
//! development checkout has no such binary, so the interpreter from the engine's virtualenv is
//! used instead. Resolution is explicit rather than implicit so a missing engine produces a
//! clear error rather than a confusing failure to spawn.

use std::path::{Path, PathBuf};

/// How to invoke the engine.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EngineCommand {
    pub program: PathBuf,
    pub arguments: Vec<String>,
    pub working_directory: Option<PathBuf>,
}

#[derive(Debug, thiserror::Error)]
pub enum ResolveError {
    #[error(
        "no engine found. Expected a bundled executable at {bundled}, or a development \
         virtualenv at {virtualenv}. Run `uv sync` in the engine directory."
    )]
    NotFound {
        bundled: PathBuf,
        virtualenv: PathBuf,
    },
}

#[cfg(windows)]
const BUNDLED_ENGINE: &str = "laa-engine.exe";
#[cfg(not(windows))]
const BUNDLED_ENGINE: &str = "laa-engine";

#[cfg(windows)]
const VENV_INTERPRETER: &str = ".venv/Scripts/python.exe";
#[cfg(not(windows))]
const VENV_INTERPRETER: &str = ".venv/bin/python";

/// Choose the bundled engine if present, otherwise the development virtualenv.
///
/// `resource_dir` is where a packaged build places its sidecar; `engine_dir` is the engine
/// source tree in a development checkout.
pub fn resolve(resource_dir: &Path, engine_dir: &Path) -> Result<EngineCommand, ResolveError> {
    let bundled = resource_dir.join(BUNDLED_ENGINE);
    if bundled.is_file() {
        return Ok(EngineCommand {
            program: bundled,
            arguments: Vec::new(),
            working_directory: None,
        });
    }

    let interpreter = engine_dir.join(VENV_INTERPRETER);
    if interpreter.is_file() {
        return Ok(EngineCommand {
            program: interpreter,
            arguments: vec!["-m".to_owned(), "app".to_owned()],
            working_directory: Some(engine_dir.to_path_buf()),
        });
    }

    Err(ResolveError::NotFound {
        bundled,
        virtualenv: interpreter,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn touch(path: &Path) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("should create directory");
        }
        fs::write(path, b"").expect("should create file");
    }

    #[test]
    fn prefers_the_bundled_executable() {
        let root = tempdir();
        let resources = root.join("resources");
        let engine = root.join("engine");
        touch(&resources.join(BUNDLED_ENGINE));
        touch(&engine.join(VENV_INTERPRETER));

        let command = resolve(&resources, &engine).expect("should resolve");

        assert_eq!(command.program, resources.join(BUNDLED_ENGINE));
        assert!(command.arguments.is_empty());
    }

    #[test]
    fn falls_back_to_the_development_virtualenv() {
        let root = tempdir();
        let resources = root.join("resources");
        let engine = root.join("engine");
        touch(&engine.join(VENV_INTERPRETER));

        let command = resolve(&resources, &engine).expect("should resolve");

        assert_eq!(command.arguments, vec!["-m", "app"]);
        assert_eq!(command.working_directory, Some(engine));
    }

    #[test]
    fn reports_both_searched_locations_when_missing() {
        let root = tempdir();

        let error =
            resolve(&root.join("resources"), &root.join("engine")).expect_err("should not resolve");

        let message = error.to_string();
        assert!(message.contains("uv sync"));
    }

    fn tempdir() -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "laa-launcher-{}-{:?}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock should be after the epoch")
                .as_nanos()
        ));
        fs::create_dir_all(&path).expect("should create temp dir");
        path
    }
}

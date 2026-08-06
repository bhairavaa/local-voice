//! The startup contract published by the engine on its stdout.

use serde::{Deserialize, Serialize};

/// Schema version this build knows how to parse.
pub const SUPPORTED_SCHEMA_VERSION: u32 = 1;

/// Connection details the engine prints as a single JSON line when it finishes binding.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Handshake {
    pub port: u16,
    pub token: String,
    /// Process actually running the engine.
    ///
    /// This is not necessarily the process we spawned. A virtualenv launcher on Windows is a
    /// trampoline that starts the real interpreter as a further child, so this is the pid to
    /// use when the engine must be force-killed.
    pub pid: u32,
    pub version: String,
    pub schema_version: u32,
}

/// What the interface needs in order to talk to the engine.
///
/// Deliberately narrower than [`Handshake`]: process details stay in the Rust layer.
#[derive(Debug, Clone, Serialize)]
pub struct EngineConnection {
    pub port: u16,
    pub token: String,
}

impl From<&Handshake> for EngineConnection {
    fn from(handshake: &Handshake) -> Self {
        Self {
            port: handshake.port,
            token: handshake.token.clone(),
        }
    }
}

impl Handshake {
    /// Parse a handshake line, rejecting a schema this build does not understand.
    pub fn parse(line: &str) -> Result<Self, HandshakeError> {
        let handshake: Handshake =
            serde_json::from_str(line.trim()).map_err(HandshakeError::Malformed)?;

        if handshake.schema_version != SUPPORTED_SCHEMA_VERSION {
            return Err(HandshakeError::UnsupportedSchema {
                found: handshake.schema_version,
                supported: SUPPORTED_SCHEMA_VERSION,
            });
        }

        Ok(handshake)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum HandshakeError {
    #[error("engine handshake was not valid JSON: {0}")]
    Malformed(#[source] serde_json::Error),

    #[error("engine handshake declares schema {found}, but this build supports {supported}")]
    UnsupportedSchema { found: u32, supported: u32 },
}

#[cfg(test)]
mod tests {
    use super::*;

    const VALID: &str =
        r#"{"port":51234,"token":"abc","pid":42,"version":"0.1.0","schema_version":1}"#;

    #[test]
    fn parses_a_well_formed_line() {
        let handshake = Handshake::parse(VALID).expect("should parse");

        assert_eq!(handshake.port, 51234);
        assert_eq!(handshake.token, "abc");
        assert_eq!(handshake.pid, 42);
    }

    #[test]
    fn tolerates_a_trailing_newline() {
        assert!(Handshake::parse(&format!("{VALID}\n")).is_ok());
    }

    #[test]
    fn rejects_malformed_json() {
        assert!(matches!(
            Handshake::parse("not json"),
            Err(HandshakeError::Malformed(_))
        ));
    }

    #[test]
    fn rejects_an_unknown_schema_version() {
        let future = r#"{"port":1,"token":"a","pid":2,"version":"9.0.0","schema_version":99}"#;

        assert!(matches!(
            Handshake::parse(future),
            Err(HandshakeError::UnsupportedSchema { found: 99, .. })
        ));
    }

    #[test]
    fn connection_omits_process_details() {
        let handshake = Handshake::parse(VALID).expect("should parse");
        let connection = EngineConnection::from(&handshake);

        let json = serde_json::to_string(&connection).expect("should serialise");
        assert!(!json.contains("pid"));
        assert!(json.contains("51234"));
    }
}

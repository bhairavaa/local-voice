import { useCallback, useMemo, useState } from "react";

import type { EngineConnection } from "../services/connection";
import {
  createEngineClient,
  type DictationResultResponse,
  type EnhancementProfile,
} from "../services/engineClient";
import { copyToClipboard, presentWindow, setRecordingIndicator } from "../services/shell";

export type DictationPhase = "idle" | "recording" | "transcribing";

export interface Dictation {
  readonly phase: DictationPhase;
  readonly result: DictationResultResponse | null;
  readonly error: string | null;
  /** Whether the finished text was placed on the clipboard without the user asking. */
  readonly copiedAutomatically: boolean;
  readonly start: () => void;
  readonly stop: (profile?: EnhancementProfile) => void;
  readonly cancel: () => void;
  /** Start if idle, stop if recording. What the hotkey does. */
  readonly toggle: () => void;
}

/**
 * Drives one recording at a time.
 *
 * The phase is tracked here rather than polled from the engine: the engine is authoritative,
 * but a round trip per render would add latency to the one interaction that must feel instant.
 */
export function useDictation(connection: EngineConnection | null): Dictation {
  const [phase, setPhase] = useState<DictationPhase>("idle");
  const [result, setResult] = useState<DictationResultResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedAutomatically, setCopiedAutomatically] = useState(false);

  const client = useMemo(
    () => (connection ? createEngineClient(connection) : null),
    [connection],
  );

  const start = useCallback(() => {
    if (!client || phase !== "idle") return;

    setError(null);
    setResult(null);
    setCopiedAutomatically(false);
    setPhase("recording");

    void client
      .startDictation()
      .then(() => setRecordingIndicator(true))
      .catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : String(caught));
        setPhase("idle");
        void setRecordingIndicator(false);
      });
  }, [client, phase]);

  const stop = useCallback(
    (profile?: EnhancementProfile) => {
      if (!client || phase !== "recording") return;

      setPhase("transcribing");
      // Hidden the moment the microphone closes, not when the text arrives: the indicator
      // says "listening", and by this point it is not.
      void setRecordingIndicator(false);

      void client
        .stopDictation(profile)
        .then(async (produced) => {
          setResult(produced);

          // Copy first, then raise the window. The text is on the clipboard even if the user
          // switches away before the window appears, which is the whole point of the feature.
          if (produced.text.trim()) {
            await copyToClipboard(produced.text);
            setCopiedAutomatically(true);
          }
          await presentWindow();
        })
        .catch((caught: unknown) => {
          setError(caught instanceof Error ? caught.message : String(caught));
        })
        .finally(() => {
          setPhase("idle");
        });
    },
    [client, phase],
  );

  const cancel = useCallback(() => {
    if (!client || phase !== "recording") return;

    void setRecordingIndicator(false);
    void client
      .cancelDictation()
      .catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : String(caught));
      })
      .finally(() => {
        setPhase("idle");
      });
  }, [client, phase]);

  const toggle = useCallback(() => {
    // Deliberately does nothing while transcribing: pressing the hotkey again during that
    // window should not throw away a recording the user is waiting on.
    if (phase === "recording") stop();
    else if (phase === "idle") start();
  }, [phase, start, stop]);

  return { phase, result, error, copiedAutomatically, start, stop, cancel, toggle };
}

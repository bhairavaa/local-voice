import { useEffect, useRef, useState } from "react";

import type { Dictation } from "../hooks/useDictation";
import { copyToClipboard, type ShortcutBindings } from "../services/shell";
import { HotkeyHint } from "./HotkeyHint";

const ACTION_LABEL: Record<Dictation["phase"], string> = {
  idle: "Start dictating",
  recording: "Stop and transcribe",
  transcribing: "Transcribing…",
};

interface Props {
  readonly dictation: Dictation;
  readonly bindings: ShortcutBindings | null;
  readonly disabled: boolean;
}

/** Record, review the text, and copy it. */
export function DictationPanel({ dictation, bindings, disabled }: Props) {
  const { phase, result, error, copiedAutomatically, start, stop, cancel } = dictation;
  const [draft, setDraft] = useState("");
  const [copied, setCopied] = useState(false);
  const editor = useRef<HTMLTextAreaElement>(null);

  // The transcript is a starting point, not a final answer, so it becomes editable text
  // rather than a read-only result.
  useEffect(() => {
    if (result) {
      setDraft(result.text);
      // The finished text is already on the clipboard; say so rather than inviting a click
      // the user does not need.
      setCopied(copiedAutomatically);
      editor.current?.focus();
    }
  }, [result, copiedAutomatically]);

  const copy = () => {
    void copyToClipboard(draft).then(() => {
      setCopied(true);
    });
  };

  return (
    <section className="flex w-full max-w-xl flex-col gap-4">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={phase === "recording" ? () => { stop(); } : start}
          disabled={disabled || phase === "transcribing"}
          className="flex-1 rounded-lg bg-accent px-4 py-2.5 font-medium text-surface transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {ACTION_LABEL[phase]}
        </button>

        {phase === "recording" && (
          <button
            type="button"
            onClick={cancel}
            className="rounded-lg border border-edge px-4 py-2.5 text-ink transition hover:border-danger hover:text-danger"
          >
            Discard
          </button>
        )}
      </div>

      {phase === "recording" ? (
        <p className="text-center text-sm text-ink-muted" role="status">
          Listening. Recording also stops on its own after a pause.
        </p>
      ) : (
        <HotkeyHint bindings={bindings} recording={false} />
      )}

      {error && (
        <p className="rounded-lg border border-danger/40 px-3 py-2 text-sm text-danger" role="alert">
          {error}
        </p>
      )}

      {result && (
        <>
          <textarea
            ref={editor}
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
              setCopied(false);
            }}
            rows={6}
            spellCheck
            aria-label="Transcribed text"
            className="w-full resize-y rounded-lg border border-edge bg-surface-raised p-3 text-ink outline-none focus-visible:border-accent"
          />

          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-ink-muted tabular-nums">
              {result.audio_seconds.toFixed(1)}s audio · transcribed in{" "}
              {result.transcribe_seconds.toFixed(1)}s
              {result.was_enhanced && " · cleaned up"}
            </p>

            <button
              type="button"
              onClick={copy}
              disabled={!draft}
              className="rounded-md border border-edge px-3 py-1.5 text-sm text-ink transition hover:border-accent hover:text-accent disabled:opacity-40"
            >
              {copied ? "Copied — paste anywhere" : "Copy"}
            </button>
          </div>

          {result.enhancement_error && (
            <p className="text-xs text-ink-muted">
              Cleanup was skipped ({result.enhancement_error}). This is the raw transcript.
            </p>
          )}
        </>
      )}
    </section>
  );
}

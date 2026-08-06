import { DictationPanel } from "./components/DictationPanel";
import { EngineStatusCard } from "./components/EngineStatusCard";
import { useDictation } from "./hooks/useDictation";
import { useEngineHealth } from "./hooks/useEngineHealth";
import { useShellShortcuts } from "./hooks/useShellShortcuts";

export function App() {
  const engine = useEngineHealth();
  const dictation = useDictation(engine.connection);

  const bindings = useShellShortcuts({
    onToggle: dictation.toggle,
    onCancel: dictation.cancel,
  });

  return (
    <main className="flex h-full flex-col items-center justify-center gap-6 bg-surface p-8">
      <div className="text-center">
        <h1 className="text-xl font-semibold tracking-tight text-ink">Local Voice</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Speech stays on this machine. Nothing is sent anywhere.
        </p>
      </div>

      {engine.status === "ready" ? (
        <DictationPanel dictation={dictation} bindings={bindings} disabled={false} />
      ) : (
        <EngineStatusCard {...engine} />
      )}
    </main>
  );
}

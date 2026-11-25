"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import {
  getLatestResult,
  getSandboxStatus,
  runSandboxTests,
  runSelfTest,
  type SandboxResult,
  type SandboxStatus,
  type SelfTest,
} from "@/lib/sandbox";

const BADGE: Record<SandboxResult["status"], { label: string; cls: string }> = {
  passed: { label: "Tests passed", cls: "text-emerald-400" },
  failed: { label: "Tests failed", cls: "text-red-400" },
  timed_out: { label: "Timed out", cls: "text-amber-400" },
  error: { label: "Could not run", cls: "text-amber-400" },
  unavailable: { label: "Docker unavailable", cls: "text-amber-400" },
};

export default function SandboxPanel({ proposalId }: { proposalId: string }) {
  const [status, setStatus] = useState<SandboxStatus | null>(null);
  const [result, setResult] = useState<SandboxResult | null>(null);
  const [selftest, setSelftest] = useState<SelfTest | null>(null);
  const [busy, setBusy] = useState<"test" | "selftest" | null>(null);
  const [installDeps, setInstallDeps] = useState(false);
  const [runAll, setRunAll] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setStatus(await getSandboxStatus());
    } catch (e) {
      setError((e as Error).message);
    }
    setResult(await getLatestResult(proposalId));
  }, [proposalId]);

  // Load on mount. A new proposal gets a fresh component (the parent passes `key`), so no reset is needed.
  useEffect(() => {
    let cancelled = false;
    getSandboxStatus()
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    getLatestResult(proposalId).then((r) => {
      if (!cancelled) setResult(r);
    });
    return () => {
      cancelled = true;
    };
  }, [proposalId]);

  async function onRun() {
    if (busy) return;
    setBusy("test");
    setError("");
    try {
      setResult(
        await runSandboxTests(proposalId, {
          installDeps,
          scope: runAll ? "all" : "generated",
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function onSelfTest() {
    if (busy) return;
    setBusy("selftest");
    setError("");
    try {
      setSelftest(await runSelfTest());
      setStatus(await getSandboxStatus());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="space-y-3 rounded-lg border border-zinc-800 p-4">
      <h2 className="text-sm font-medium">Test in sandbox (Docker)</h2>
      <p className="text-xs text-zinc-400">
        Writes tests for this change, applies it to a temporary copy of your
        project, and runs the tests in a locked-down container: no network,
        read-only project, memory and time limits. Your real files are never
        touched.
      </p>

      {status && !status.docker && (
        <div className="space-y-2 text-sm text-amber-300">
          <p>{status.detail}</p>
          <button
            type="button"
            onClick={load}
            className="rounded-md border border-zinc-700 px-3 py-1 text-xs hover:bg-zinc-900"
          >
            Check again
          </button>
        </div>
      )}

      {status?.docker && (
        <>
          <p className="text-xs text-zinc-500">
            {status.detail}.{" "}
            {status.image_ready
              ? "Sandbox image ready."
              : "The first run builds the sandbox image, which needs internet and takes a few minutes."}
          </p>
          <label className="flex items-start gap-2 text-xs text-zinc-300">
            <input
              type="checkbox"
              checked={installDeps}
              onChange={(e) => setInstallDeps(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              Install the project&apos;s requirements.txt first (the only step
              with network access; wheels only; cached). Needed if the tests
              import your dependencies. Large packages can take many minutes.
            </span>
          </label>
          <label className="flex items-start gap-2 text-xs text-zinc-300">
            <input
              type="checkbox"
              checked={runAll}
              onChange={(e) => setRunAll(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              Also run the project&apos;s existing tests (usually needs the
              requirements above).
            </span>
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onRun}
              disabled={busy !== null}
              className="flex items-center gap-2 rounded-md bg-emerald-700 px-4 py-2 text-sm text-white hover:bg-emerald-600 disabled:opacity-40"
            >
              {busy === "test" && (
                <Loader2 size={14} className="animate-spin" />
              )}
              {busy === "test" ? "Running in sandbox" : "Run tests in sandbox"}
            </button>
            <button
              type="button"
              onClick={onSelfTest}
              disabled={busy !== null}
              className="flex items-center gap-2 rounded-md border border-zinc-700 px-4 py-2 text-sm hover:bg-zinc-900 disabled:opacity-40"
            >
              {busy === "selftest" && (
                <Loader2 size={14} className="animate-spin" />
              )}
              Verify sandbox isolation
            </button>
          </div>
        </>
      )}

      {error && <p className="text-sm text-red-300">{error}</p>}

      {selftest && (
        <div className="space-y-1 text-xs">
          <p className={selftest.passed ? "text-emerald-400" : "text-red-400"}>
            {selftest.passed
              ? "Isolation verified on this machine."
              : "Isolation check did not pass."}
          </p>
          {selftest.detail && (
            <p className="text-amber-300">{selftest.detail}</p>
          )}
          {selftest.checks.map((c) => (
            <p
              key={c.name}
              className={c.passed ? "text-zinc-300" : "text-red-300"}
            >
              {c.passed ? "✓" : "✗"} {c.name}
            </p>
          ))}
        </div>
      )}

      {result && (
        <div className="space-y-3 border-t border-zinc-800 pt-3 text-sm">
          <p>
            <span className={`font-medium ${BADGE[result.status].cls}`}>
              {BADGE[result.status].label}
            </span>
            {result.duration_ms ? (
              <span className="ml-2 text-xs text-zinc-500">
                {(result.duration_ms / 1000).toFixed(1)}s
              </span>
            ) : null}
          </p>
          <p className="text-zinc-200">{result.summary}</p>
          {result.status === "failed" && (
            <p className="text-xs text-amber-300">
              A failing generated test can mean the change is wrong or the test
              is wrong. Read the output before deciding.
            </p>
          )}
          <ul className="space-y-1 text-xs">
            {result.steps.map((s, i) => (
              <li key={i} className={s.ok ? "text-zinc-300" : "text-amber-300"}>
                {s.ok ? "✓" : "!"} {s.name}
                {s.detail && (
                  <span className="text-zinc-500"> — {s.detail}</span>
                )}
              </li>
            ))}
          </ul>
          {result.tests && (
            <details className="text-xs">
              <summary className="cursor-pointer text-zinc-400">
                Generated test file ({result.tests.filename})
              </summary>
              <pre className="mt-2 max-h-80 overflow-auto rounded-md bg-zinc-950 p-3 font-mono text-zinc-300">
                {result.tests.content}
              </pre>
            </details>
          )}
          {result.output && (
            <details className="text-xs" open={result.status !== "passed"}>
              <summary className="cursor-pointer text-zinc-400">
                Test output{result.truncated ? " (truncated)" : ""}
              </summary>
              <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-zinc-950 p-3 font-mono text-zinc-300">
                {result.output}
              </pre>
            </details>
          )}
        </div>
      )}
    </section>
  );
}

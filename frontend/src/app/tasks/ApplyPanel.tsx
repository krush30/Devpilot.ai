"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import {
  applyProposal,
  getProposal,
  undoProposal,
  type ApplyResult,
  type ProposalInfo,
} from "@/lib/proposals";

const STATUS_STYLE: Record<ApplyResult["status"], string> = {
  applied: "text-emerald-400",
  would_apply: "text-sky-400",
  undone: "text-sky-400",
  skipped: "text-amber-400",
};

export default function ApplyPanel({ proposalId }: { proposalId: string }) {
  const [info, setInfo] = useState<ProposalInfo | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [busy, setBusy] = useState<"apply" | "undo" | null>(null);
  const [results, setResults] = useState<ApplyResult[]>([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setInfo(await getProposal(proposalId));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [proposalId]);

  useEffect(() => {
    setSelected([]);
    setResults([]);
    setError("");
    refresh();
  }, [refresh]);

  if (error && !info)
    return (
      <p className="rounded-md border border-red-800 bg-red-950 p-3 text-sm text-red-200">
        {error}
      </p>
    );
  if (!info) return null;

  const toggle = (i: number) =>
    setSelected((s) => (s.includes(i) ? s.filter((x) => x !== i) : [...s, i]));
  const anyApplied = info.changes.some((c) => c.applied);
  const concerns = info.review && info.review.verdict !== "approve";

  async function onApply() {
    if (!info || selected.length === 0 || busy) return;
    const files = selected.map((i) => info.changes[i].path).join("\n");
    const warning = concerns
      ? "\n\nThe reviewer still has concerns about this proposal."
      : "";
    if (
      !window.confirm(
        `Write ${selected.length} change(s) to:\n${info.root}\n\n${files}${warning}`,
      )
    )
      return;
    setBusy("apply");
    setError("");
    try {
      setResults(await applyProposal(proposalId, selected));
      setSelected([]);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function onUndo() {
    if (busy) return;
    setBusy("undo");
    setError("");
    try {
      setResults(await undoProposal(proposalId));
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="space-y-3 rounded-lg border border-emerald-900 p-4">
      <h2 className="text-sm font-medium">Apply changes</h2>

      {!info.can_apply ? (
        <p className="text-sm text-amber-300">{info.cannot_apply_reason}</p>
      ) : (
        <p className="text-xs text-zinc-400">
          Nothing is written until you choose changes and confirm. Files are
          written under{" "}
          <span className="font-mono text-zinc-300">{info.root}</span>.
        </p>
      )}

      {concerns && (
        <p className="text-xs text-amber-300">
          The reviewer has unresolved concerns (see the Reviewer card). Check
          the diff carefully.
        </p>
      )}

      <ul className="space-y-2">
        {info.changes.map((c) => (
          <li key={c.index} className="flex items-start gap-3 text-sm">
            <input
              type="checkbox"
              id={`change-${c.index}`}
              checked={selected.includes(c.index)}
              disabled={!c.eligible || c.applied || busy !== null}
              onChange={() => toggle(c.index)}
              className="mt-1"
            />
            <label htmlFor={`change-${c.index}`} className="flex-1">
              <span className="font-mono text-zinc-100">{c.path}</span>
              {c.line && (
                <span className="ml-2 text-xs text-zinc-500">
                  line {c.line}
                </span>
              )}
              <span className="ml-2 rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-300">
                {c.action}
              </span>
              {c.applied && (
                <span className="ml-2 text-xs text-emerald-400">applied</span>
              )}
              {!c.eligible && (
                <span className="ml-2 text-xs text-amber-400">
                  cannot apply: {c.ineligible_reason}
                </span>
              )}
            </label>
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onApply}
          disabled={selected.length === 0 || busy !== null || !info.can_apply}
          className="flex items-center gap-2 rounded-md bg-emerald-700 px-4 py-2 text-sm text-white hover:bg-emerald-600 disabled:opacity-40"
        >
          {busy === "apply" && <Loader2 size={14} className="animate-spin" />}
          Apply selected ({selected.length})
        </button>
        {anyApplied && (
          <button
            type="button"
            onClick={onUndo}
            disabled={busy !== null}
            className="flex items-center gap-2 rounded-md border border-zinc-700 px-4 py-2 text-sm hover:bg-zinc-900 disabled:opacity-40"
          >
            {busy === "undo" && <Loader2 size={14} className="animate-spin" />}
            Undo applied changes
          </button>
        )}
      </div>

      {error && <p className="text-sm text-red-300">{error}</p>}

      {results.length > 0 && (
        <ul className="space-y-1 text-xs">
          {results.map((r, i) => (
            <li key={i}>
              <span className={STATUS_STYLE[r.status]}>
                {r.status.replace("_", " ")}
              </span>{" "}
              <span className="font-mono text-zinc-300">{r.path}</span>{" "}
              <span className="text-zinc-500">{r.detail}</span>
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs text-zinc-500">
        Tip: after applying, review the result with{" "}
        <span className="font-mono">git diff</span> in your editor. Undo only
        works while the files are unchanged since DevPilot wrote them.
      </p>
    </section>
  );
}

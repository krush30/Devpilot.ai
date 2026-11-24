"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  deleteRun,
  getRun,
  listRuns,
  type RunDetail,
  type RunStatus,
  type RunSummary,
} from "@/lib/runs";
import ApplyPanel from "../tasks/ApplyPanel";
import { emptyBoard, reduceEvent, Timeline } from "../tasks/Timeline";

const STATUS: Record<RunStatus, { label: string; cls: string }> = {
  running: { label: "running", cls: "text-sky-400" },
  done: { label: "proposal ready", cls: "text-emerald-400" },
  needs_input: { label: "needed more detail", cls: "text-amber-400" },
  error: { label: "stopped", cls: "text-red-400" },
  cancelled: { label: "cancelled", cls: "text-zinc-400" },
  interrupted: { label: "interrupted", cls: "text-zinc-400" },
};

export default function HistoryPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<RunDetail | null>(null);

  // Used by event handlers (after a delete). The initial load is in the effect below.
  async function refresh() {
    try {
      setRuns(await listRuns());
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    // State is only set in callbacks, after the request finishes (not synchronously in the effect).
    let active = true;
    listRuns()
      .then((list) => {
        if (active) {
          setRuns(list);
          setError("");
        }
      })
      .catch((e: Error) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function open(id: string) {
    try {
      setSelected(await getRun(id));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(id: string) {
    if (
      !window.confirm(
        "Delete this run from history? Applied file changes are not touched.",
      )
    )
      return;
    try {
      await deleteRun(id);
      if (selected?.id === id) setSelected(null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const board = selected
    ? selected.events.reduce(reduceEvent, emptyBoard())
    : emptyBoard();

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
        <header className="flex items-end justify-between">
          <div>
            <h1 className="text-lg font-semibold">Run history</h1>
            <p className="text-sm text-zinc-400">
              Every agent run is saved. Open one to replay it.
            </p>
          </div>
          <div className="flex gap-4 text-sm">
            <Link href="/tasks" className="text-emerald-400 hover:underline">
              New task
            </Link>
            <Link href="/" className="text-emerald-400 hover:underline">
              Chat
            </Link>
          </div>
        </header>

        {error && (
          <p className="rounded-md border border-red-800 bg-red-950 p-3 text-sm text-red-200">
            {error}
          </p>
        )}

        <div className="grid gap-6 md:grid-cols-[320px_1fr]">
          <aside className="space-y-2">
            {loading && <p className="text-sm text-zinc-500">Loading…</p>}
            {!loading && runs.length === 0 && !error && (
              <p className="text-sm text-zinc-500">
                No runs yet. Run a task and it will show up here.
              </p>
            )}
            {runs.map((r) => (
              <div
                key={r.id}
                className={
                  "rounded-lg border p-3 " +
                  (selected?.id === r.id
                    ? "border-emerald-700 bg-zinc-900"
                    : "border-zinc-800")
                }
              >
                <button
                  type="button"
                  onClick={() => open(r.id)}
                  className="w-full text-left"
                >
                  <p className="line-clamp-2 text-sm text-zinc-100">
                    {r.title}
                  </p>
                  <p className="mt-1 text-xs text-zinc-500">
                    <span className={STATUS[r.status].cls}>
                      {STATUS[r.status].label}
                    </span>{" "}
                    · {r.repo_id.replace(/^repo_/, "")} ·{" "}
                    {new Date(r.created_at).toLocaleString()}
                    {r.duration_ms !== null &&
                      ` · ${(r.duration_ms / 1000).toFixed(0)}s`}
                  </p>
                </button>
                <button
                  type="button"
                  onClick={() => remove(r.id)}
                  className="mt-2 text-xs text-zinc-500 hover:text-red-300"
                >
                  Delete
                </button>
              </div>
            ))}
          </aside>

          <main className="min-w-0 space-y-4">
            {!selected && (
              <p className="text-sm text-zinc-500">
                Select a run to see what each agent did.
              </p>
            )}
            {selected && (
              <>
                <div className="rounded-lg border border-zinc-800 p-4 text-sm">
                  <p className="text-zinc-100">{selected.title}</p>
                  <p className="mt-1 text-xs text-zinc-500">
                    <span className={STATUS[selected.status].cls}>
                      {STATUS[selected.status].label}
                    </span>
                    {selected.error && ` · ${selected.error}`}
                  </p>
                </div>
                {selected.events.length === 0 ? (
                  <p className="text-sm text-zinc-500">
                    This run recorded no agent activity.
                  </p>
                ) : (
                  <Timeline board={board} />
                )}
                {selected.proposal_id && (
                  <ApplyPanel
                    key={selected.proposal_id}
                    proposalId={selected.proposal_id}
                  />
                )}
              </>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}

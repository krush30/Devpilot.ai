"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import {
  Check,
  CircleDashed,
  Loader2,
  RotateCw,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { listRepos, type Repo } from "@/lib/api";
import {
  runTask,
  type AgentName,
  type AgentStatus,
  type Change,
  type FileRef,
} from "@/lib/tasks";

type AgentView = {
  status: AgentStatus;
  provider?: string | null;
  data: Record<string, unknown>;
  note?: string;
};
type Board = Record<AgentName, AgentView>;

const AGENTS: { key: AgentName; title: string; blurb: string }[] = [
  { key: "planner", title: "Planner", blurb: "Breaks the task into steps" },
  { key: "analyst", title: "Analyst", blurb: "Finds the relevant code" },
  { key: "coder", title: "Coder", blurb: "Proposes the change" },
];

const emptyBoard = (): Board => ({
  planner: { status: "pending", data: {} },
  analyst: { status: "pending", data: {} },
  coder: { status: "pending", data: {} },
});

function StatusIcon({ status }: { status: AgentStatus }) {
  if (status === "running")
    return <Loader2 size={18} className="animate-spin text-emerald-400" />;
  if (status === "retrying")
    return <RotateCw size={18} className="animate-spin text-amber-400" />;
  if (status === "done")
    return <Check size={18} className="text-emerald-400" />;
  if (status === "error")
    return <TriangleAlert size={18} className="text-red-400" />;
  if (status === "needs_input")
    return <TriangleAlert size={18} className="text-amber-400" />;
  return <CircleDashed size={18} className="text-zinc-600" />;
}

function Diff({ text }: { text: string }) {
  return (
    <pre className="overflow-x-auto rounded-md bg-zinc-950 p-3 font-mono text-xs leading-relaxed">
      {text.split("\n").map((line, i) => {
        const cls =
          line.startsWith("+++") || line.startsWith("---")
            ? "text-zinc-500"
            : line.startsWith("+")
              ? "bg-emerald-950 text-emerald-300"
              : line.startsWith("-")
                ? "bg-red-950 text-red-300"
                : line.startsWith("@@")
                  ? "text-sky-400"
                  : "text-zinc-400";
        return (
          <div key={i} className={cls}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}

function AgentBody({ agent, view }: { agent: AgentName; view: AgentView }) {
  const d = view.data;
  if (view.status === "error")
    return (
      <p className="text-sm text-red-300">{String(d.message ?? "Failed")}</p>
    );
  if (view.note) return <p className="text-sm text-amber-300">{view.note}</p>;
  if (agent === "planner" && view.status === "needs_input") {
    return (
      <p className="text-sm text-amber-300">
        I need a bit more detail before planning: {String(d.question ?? "")}
      </p>
    );
  }

  if (agent === "planner" && Array.isArray(d.steps)) {
    return (
      <ol className="list-decimal space-y-1 pl-5 text-sm text-zinc-200">
        {(d.steps as string[]).map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
    );
  }
  if (agent === "analyst" && Array.isArray(d.files)) {
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
          {(d.files as FileRef[]).map((f, i) => (
            <span
              key={i}
              className="rounded bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300"
            >
              {f.path}:{f.start_line}-{f.end_line} · {f.score.toFixed(2)}
            </span>
          ))}
        </div>
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-200">
          {String(d.analysis ?? "")}
        </p>
      </div>
    );
  }
  if (agent === "coder" && Array.isArray(d.changes)) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-zinc-200">{String(d.summary ?? "")}</p>
        {Array.isArray(d.skipped) && d.skipped.length > 0 && (
          <div className="rounded-md border border-amber-900 bg-amber-950/40 p-3 text-xs text-amber-200">
            <p className="mb-1 font-medium">Plan steps not done:</p>
            <ul className="list-disc space-y-1 pl-4">
              {(d.skipped as string[]).map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </div>
        )}
        {(d.changes as Change[]).map((c, i) => (
          <div key={i} className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-mono text-zinc-100">{c.path}</span>
              {c.line && (
                <span className="text-xs text-zinc-500">line {c.line}</span>
              )}
              <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-300">
                {c.action}
              </span>
              {c.verified ? (
                <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
                  <ShieldCheck size={14} /> original code found
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-xs text-amber-400">
                  <ShieldAlert size={14} /> original code not found, review
                  carefully
                </span>
              )}
              {c.syntax === "ok" && (
                <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
                  <Check size={14} /> Python syntax OK
                </span>
              )}
              {c.syntax === "error" && (
                <span className="inline-flex items-center gap-1 text-xs text-amber-400">
                  <ShieldAlert size={14} /> syntax problem ({c.syntax_error})
                </span>
              )}
            </div>
            {c.explanation && (
              <p className="text-xs text-zinc-400">{c.explanation}</p>
            )}
            <Diff text={c.diff} />
          </div>
        ))}
        <p className="text-xs text-zinc-500">
          Proposal only. Nothing has been written to your files.
        </p>
      </div>
    );
  }
  return null;
}

export default function TasksPage() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [repoId, setRepoId] = useState("");
  const [task, setTask] = useState("");
  const [board, setBoard] = useState<Board>(emptyBoard());
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{
    ok: boolean;
    error: string;
    question?: string;
  } | null>(null);
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    listRepos()
      .then((r) => {
        setRepos(r);
        if (r.length && !repoId) setRepoId(r[0].repo_id);
      })
      .catch(() => setError("Could not reach the backend on port 8000."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onRun(e: FormEvent) {
    e.preventDefault();
    if (!task.trim() || !repoId || running) return;
    setBoard(emptyBoard());
    setResult(null);
    setError("");
    setRunning(true);
    abortRef.current = new AbortController();
    try {
      await runTask(
        task.trim(),
        repoId,
        (ev) => {
          if (ev.agent === "system") {
            setResult(ev.data);
            return;
          }
          setBoard((b) => {
            const prev = b[ev.agent];
            const next: AgentView = {
              status: ev.status,
              provider: ev.provider ?? prev.provider,
              data: ev.data,
            };
            if (ev.status === "retrying") {
              next.data = prev.data;
              next.note = `Invalid output, retrying: ${String(ev.data.reason ?? "")}`;
            }
            return { ...b, [ev.agent]: next };
          });
        },
        abortRef.current.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError")
        setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
        <header className="flex items-end justify-between">
          <div>
            <h1 className="text-lg font-semibold">DevPilot Agents</h1>
            <p className="text-sm text-zinc-400">
              Give a task. A planner, analyst and coder work on your repository.
            </p>
          </div>
          <Link href="/" className="text-sm text-emerald-400 hover:underline">
            Back to chat
          </Link>
        </header>

        <form
          onSubmit={onRun}
          className="space-y-3 rounded-lg border border-zinc-800 p-4"
        >
          <label
            htmlFor="repo"
            className="text-xs font-medium uppercase tracking-wide text-zinc-400"
          >
            Repository
          </label>
          <select
            id="repo"
            value={repoId}
            onChange={(e) => setRepoId(e.target.value)}
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-2 py-2 text-sm"
          >
            {repos.length === 0 && (
              <option value="">No repositories indexed yet</option>
            )}
            {repos.map((r) => (
              <option key={r.repo_id} value={r.repo_id}>
                {r.repo_id.replace(/^repo_/, "")} ({r.chunks} chunks)
              </option>
            ))}
          </select>
          <label
            htmlFor="task"
            className="block text-xs font-medium uppercase tracking-wide text-zinc-400"
          >
            Task
          </label>
          <textarea
            id="task"
            value={task}
            onChange={(e) => setTask(e.target.value)}
            rows={3}
            placeholder="e.g. Add a GET /api/llm/models endpoint that lists the configured providers and their model names"
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-emerald-600"
          />
          <button
            type="submit"
            disabled={running || !task.trim() || !repoId}
            className="flex items-center gap-2 rounded-md bg-emerald-700 px-4 py-2 text-sm text-white hover:bg-emerald-600 disabled:opacity-40"
          >
            {running && <Loader2 size={14} className="animate-spin" />}
            {running ? "Agents working" : "Run agents"}
          </button>
        </form>

        {error && (
          <p className="rounded-md border border-red-800 bg-red-950 p-3 text-sm text-red-200">
            {error}
          </p>
        )}

        <ol className="space-y-3">
          {AGENTS.map((a) => {
            const view = board[a.key];
            return (
              <li key={a.key} className="rounded-lg border border-zinc-800 p-4">
                <div className="flex items-center gap-3">
                  <StatusIcon status={view.status} />
                  <div className="flex-1">
                    <p className="text-sm font-medium">{a.title}</p>
                    <p className="text-xs text-zinc-500">{a.blurb}</p>
                  </div>
                  {view.provider && (
                    <span className="text-xs text-zinc-500">
                      via {view.provider}
                    </span>
                  )}
                </div>
                {view.status !== "pending" && view.status !== "running" && (
                  <div className="mt-3">
                    <AgentBody agent={a.key} view={view} />
                  </div>
                )}
              </li>
            );
          })}
        </ol>

        {result && !result.ok && result.question && (
          <p className="rounded-md border border-amber-800 bg-amber-950 p-3 text-sm text-amber-200">
            Add more detail to the task and run again.
          </p>
        )}
        {result && !result.ok && !result.question && (
          <p className="rounded-md border border-red-800 bg-red-950 p-3 text-sm text-red-200">
            The run stopped: {result.error || "unknown error"}
          </p>
        )}
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { listRepos, type Repo } from "@/lib/api";
import { loadIssues, type IssueSummary } from "@/lib/github";
import { runTask } from "@/lib/tasks";
import ApplyPanel from "./ApplyPanel";
import { emptyBoard, reduceEvent, Timeline, type Board } from "./Timeline";

export default function TasksPage() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [repoId, setRepoId] = useState("");
  const [task, setTask] = useState("");
  const [ghRepo, setGhRepo] = useState("");
  const [issues, setIssues] = useState<IssueSummary[]>([]);
  const [issue, setIssue] = useState<IssueSummary | null>(null);
  const [ghLoading, setGhLoading] = useState(false);
  const [ghError, setGhError] = useState("");
  const [board, setBoard] = useState<Board>(emptyBoard());
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{
    ok: boolean;
    error: string;
    question?: string;
    proposal_id?: string;
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

  async function onLoadIssues() {
    if (!ghRepo.trim() || ghLoading) return;
    setGhLoading(true);
    setGhError("");
    setIssue(null);
    try {
      const list = await loadIssues(ghRepo.trim());
      setIssues(list);
      if (list.length === 0) setGhError("No open issues found.");
    } catch (err) {
      setIssues([]);
      setGhError((err as Error).message);
    } finally {
      setGhLoading(false);
    }
  }

  const canRun = !!repoId && (!!task.trim() || !!issue);

  async function onRun(e: FormEvent) {
    e.preventDefault();
    if (!canRun || running) return;
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
          setBoard((b) => reduceEvent(b, ev));
        },
        abortRef.current.signal,
        issue ? { repo: ghRepo.trim(), number: issue.number } : undefined,
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
          <div className="flex gap-4 text-sm">
            <Link href="/history" className="text-emerald-400 hover:underline">
              History
            </Link>
            <Link href="/" className="text-emerald-400 hover:underline">
              Back to chat
            </Link>
          </div>
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
          <p className="pt-1 text-xs font-medium uppercase tracking-wide text-zinc-400">
            GitHub issue (optional)
          </p>
          <div className="flex gap-2">
            <input
              value={ghRepo}
              onChange={(e) => setGhRepo(e.target.value)}
              placeholder="owner/name, e.g. psf/requests"
              aria-label="GitHub repository"
              className="flex-1 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-emerald-600"
            />
            <button
              type="button"
              onClick={onLoadIssues}
              disabled={ghLoading || !ghRepo.trim()}
              className="rounded-md border border-zinc-700 px-3 text-sm hover:bg-zinc-900 disabled:opacity-40"
            >
              {ghLoading ? "Loading" : "Load issues"}
            </button>
          </div>
          {ghError && <p className="text-xs text-red-300">{ghError}</p>}
          {issues.length > 0 && (
            <ul className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-zinc-800 p-1">
              {issues.map((i) => (
                <li key={i.number}>
                  <button
                    type="button"
                    onClick={() =>
                      setIssue(issue?.number === i.number ? null : i)
                    }
                    className={
                      "w-full rounded px-2 py-1 text-left text-sm hover:bg-zinc-900 " +
                      (issue?.number === i.number
                        ? "bg-emerald-950 text-emerald-200"
                        : "text-zinc-300")
                    }
                  >
                    <span className="text-zinc-500">#{i.number}</span> {i.title}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {issue && (
            <p className="text-xs text-emerald-400">
              Selected issue #{issue.number}. The agents will work from it;
              click it again to deselect.
            </p>
          )}
          <label
            htmlFor="task"
            className="block text-xs font-medium uppercase tracking-wide text-zinc-400"
          >
            {issue ? "Extra instructions (optional)" : "Task"}
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
            disabled={running || !canRun}
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

        <Timeline board={board} />

        {result?.proposal_id && (
          <ApplyPanel
            key={result.proposal_id}
            proposalId={result.proposal_id}
          />
        )}
        {result && result.ok && result.error && (
          <p className="rounded-md border border-amber-800 bg-amber-950 p-3 text-sm text-amber-200">
            Note: {result.error}. The earlier proposal is shown above.
          </p>
        )}
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

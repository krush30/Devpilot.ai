"use client";

import {
  Check,
  CircleDashed,
  Loader2,
  RotateCw,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import type {
  AgentName,
  AgentStatus,
  AgentUpdate,
  Change,
  FileRef,
  Finding,
  StaticFlag,
} from "@/lib/tasks";

export type AgentView = {
  status: AgentStatus;
  provider?: string | null;
  data: Record<string, unknown>;
  note?: string;
};
export type Board = Record<AgentName, AgentView>;

const AGENTS: { key: AgentName; title: string; blurb: string }[] = [
  {
    key: "github",
    title: "GitHub",
    blurb: "Reads the issue through an MCP server",
  },
  { key: "planner", title: "Planner", blurb: "Breaks the task into steps" },
  { key: "analyst", title: "Analyst", blurb: "Finds the relevant code" },
  { key: "coder", title: "Coder", blurb: "Proposes the change" },
  {
    key: "reviewer",
    title: "Reviewer",
    blurb: "Checks the proposal and can send it back once",
  },
];

export const emptyBoard = (): Board => ({
  github: { status: "pending", data: {} },
  planner: { status: "pending", data: {} },
  analyst: { status: "pending", data: {} },
  coder: { status: "pending", data: {} },
  reviewer: { status: "pending", data: {} },
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
  if (
    view.status === "error" &&
    !(agent === "reviewer" && Array.isArray(d.static_flags))
  )
    return (
      <p className="text-sm text-red-300">{String(d.message ?? "Failed")}</p>
    );
  if (view.note) return <p className="text-sm text-amber-300">{view.note}</p>;
  if (agent === "reviewer" && d.verdict) {
    const findings = (d.findings ?? []) as Finding[];
    const tests = (d.suggested_tests ?? []) as string[];
    const approved = d.verdict === "approve";
    const sev = (s: string) =>
      s === "high"
        ? "text-red-300"
        : s === "medium"
          ? "text-amber-300"
          : "text-zinc-400";
    return (
      <div className="space-y-3 text-sm">
        <p className={approved ? "text-emerald-400" : "text-amber-300"}>
          {approved
            ? "Approved"
            : d.sent_back
              ? "Changes requested: sent back to the coder for one revision"
              : "Changes requested (revision limit reached): the concerns below still apply"}
        </p>
        <p className="text-zinc-200">{String(d.summary ?? "")}</p>
        {findings.length > 0 && (
          <ul className="space-y-2">
            {findings.map((f, i) => (
              <li key={i} className="text-xs">
                <span className={`font-medium uppercase ${sev(f.severity)}`}>
                  {f.severity}
                </span>{" "}
                <span className="font-mono text-zinc-300">{f.path}</span>
                <p className="text-zinc-300">{f.issue}</p>
                {f.suggestion && (
                  <p className="text-zinc-500">Fix: {f.suggestion}</p>
                )}
              </li>
            ))}
          </ul>
        )}
        {tests.length > 0 && (
          <div className="text-xs text-zinc-300">
            <p className="mb-1 font-medium text-zinc-400">
              Suggested tests (DevPilot doesn&apos;t write or run them yet)
            </p>
            <ul className="list-disc space-y-1 pl-4">
              {tests.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  }
  if (
    agent === "reviewer" &&
    view.status === "error" &&
    Array.isArray(d.static_flags)
  ) {
    return (
      <div className="space-y-2 text-xs">
        <p className="text-amber-300">
          {String(d.message ?? "The reviewer could not run.")}
        </p>
        {(d.static_flags as StaticFlag[]).map((f, i) => (
          <p key={i} className="text-zinc-300">
            {f.severity}: {f.rule} in{" "}
            <span className="font-mono">{f.path}</span>
          </p>
        ))}
      </div>
    );
  }
  if (agent === "github" && d.title) {
    return (
      <div className="space-y-1 text-sm text-zinc-200">
        <p>
          <a
            href={String(d.url)}
            target="_blank"
            rel="noreferrer"
            className="text-emerald-400 hover:underline"
          >
            #{String(d.number)}
          </a>{" "}
          {String(d.title)}
        </p>
        {Array.isArray(d.labels) && d.labels.length > 0 && (
          <p className="text-xs text-zinc-500">
            {(d.labels as string[]).join(", ")}
          </p>
        )}
      </div>
    );
  }
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

/** Fold one streamed (or recorded) agent event into the board. */
export function reduceEvent(board: Board, ev: AgentUpdate): Board {
  const prev = board[ev.agent];
  const next: AgentView = {
    status: ev.status,
    provider: ev.provider ?? prev.provider,
    data: ev.data,
  };
  if (ev.status === "retrying") {
    next.data = prev.data;
    next.note = `Invalid output, retrying: ${String(ev.data.reason ?? "")}`;
  }
  return { ...board, [ev.agent]: next };
}

export function Timeline({ board }: { board: Board }) {
  return (
    <ol className="space-y-3">
      {AGENTS.map((a) => {
        const view = board[a.key];
        if (a.key === "github" && view.status === "pending") return null;
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
  );
}

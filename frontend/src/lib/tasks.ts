export type AgentName = "planner" | "analyst" | "coder";
export type AgentStatus =
  | "pending"
  | "running"
  | "retrying"
  | "needs_input"
  | "done"
  | "error";

export type FileRef = {
  path: string;
  start_line: number;
  end_line: number;
  score: number;
};
export type Change = {
  path: string;
  action: "modify" | "create";
  explanation: string;
  line: number | null;
  verified: boolean;
  syntax: "ok" | "error" | "skipped";
  syntax_error: string;
  diff: string;
};

export type AgentEvent =
  | {
      agent: AgentName;
      status: "running" | "retrying" | "needs_input" | "error" | "done";
      provider?: string | null;
      data: Record<string, unknown>;
    }
  | {
      agent: "system";
      status: "finished";
      data: { ok: boolean; error: string; question?: string };
    };

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** POST the task and call onEvent for every Server-Sent Event. (axios can't stream in the browser.) */
export async function runTask(
  task: string,
  repoId: string,
  onEvent: (e: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/api/tasks/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, repo_id: repoId }),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = `Request failed (${res.status})`;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") detail = j.detail;
      else if (Array.isArray(j.detail))
        detail = "Task must be at least 5 characters.";
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)) as AgentEvent);
    }
  }
}

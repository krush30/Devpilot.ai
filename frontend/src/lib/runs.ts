import { api } from "@/lib/api";
import type { AgentUpdate } from "@/lib/tasks";

export type RunStatus =
  | "running"
  | "done"
  | "needs_input"
  | "error"
  | "cancelled"
  | "interrupted";
export type RunSummary = {
  id: string;
  created_at: string;
  status: RunStatus;
  repo_id: string;
  title: string;
  has_proposal: boolean;
  duration_ms: number | null;
  error: string;
};
export type RunDetail = RunSummary & {
  task: string;
  github_repo: string | null;
  issue_number: number | null;
  proposal_id: string | null;
  events: AgentUpdate[];
};

function fail(e: unknown, fallback: string): Error {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response
    ?.data?.detail;
  return new Error(typeof detail === "string" ? detail : fallback);
}

export async function listRuns(): Promise<RunSummary[]> {
  try {
    return (await api.get<RunSummary[]>("/api/runs", { params: { limit: 50 } }))
      .data;
  } catch (e) {
    throw fail(e, "Could not load history. Is the backend running?");
  }
}

export async function getRun(id: string): Promise<RunDetail> {
  try {
    return (await api.get<RunDetail>(`/api/runs/${id}`)).data;
  } catch (e) {
    throw fail(e, "Could not load that run.");
  }
}

export async function deleteRun(id: string): Promise<void> {
  try {
    await api.delete(`/api/runs/${id}`);
  } catch (e) {
    throw fail(e, "Could not delete that run.");
  }
}

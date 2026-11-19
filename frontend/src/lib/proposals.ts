import { api } from "@/lib/api";

export type ProposalChange = {
  index: number;
  path: string;
  action: string;
  line: number | null;
  explanation: string;
  verified: boolean;
  syntax: string;
  eligible: boolean;
  ineligible_reason: string;
  applied: boolean;
};
export type ProposalInfo = {
  id: string;
  root: string | null;
  can_apply: boolean;
  cannot_apply_reason: string;
  summary: string;
  review: { verdict: string } | null;
  changes: ProposalChange[];
};
export type ApplyResult = {
  index: number;
  path: string;
  status: "applied" | "would_apply" | "undone" | "skipped";
  detail: string;
};

function message(e: unknown, fallback: string): Error {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response
    ?.data?.detail;
  return new Error(typeof detail === "string" ? detail : fallback);
}

export async function getProposal(id: string): Promise<ProposalInfo> {
  try {
    return (await api.get<ProposalInfo>(`/api/proposals/${id}`)).data;
  } catch (e) {
    throw message(e, "Could not load the proposal.");
  }
}

export async function applyProposal(
  id: string,
  indexes: number[],
): Promise<ApplyResult[]> {
  try {
    return (
      await api.post<{ results: ApplyResult[] }>(`/api/proposals/${id}/apply`, {
        change_indexes: indexes,
      })
    ).data.results;
  } catch (e) {
    throw message(e, "Apply failed.");
  }
}

export async function undoProposal(id: string): Promise<ApplyResult[]> {
  try {
    return (
      await api.post<{ results: ApplyResult[] }>(`/api/proposals/${id}/undo`)
    ).data.results;
  } catch (e) {
    throw message(e, "Undo failed.");
  }
}

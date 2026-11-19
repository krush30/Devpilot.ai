import { api } from "@/lib/api";

export type IssueSummary = {
  number: number;
  title: string;
  labels: string[];
  url: string;
  comments: number;
};

export async function loadIssues(repo: string): Promise<IssueSummary[]> {
  try {
    const { data } = await api.get<{ issues: IssueSummary[] }>(
      "/api/github/issues",
      { params: { repo } },
    );
    return data.issues;
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: unknown } } })
      ?.response?.data?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : "Could not load issues. Use the form owner/name, e.g. psf/requests.",
    );
  }
}

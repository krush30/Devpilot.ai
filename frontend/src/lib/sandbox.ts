import { api } from "@/lib/api";

export type SandboxStatus = {
  docker: boolean;
  detail: string;
  image_ready: boolean;
};
export type SandboxStep = { name: string; ok: boolean; detail: string };
export type SandboxResult = {
  id?: string;
  status: "passed" | "failed" | "timed_out" | "error" | "unavailable";
  summary: string;
  steps: SandboxStep[];
  tests: {
    filename: string;
    content: string;
    notes: string;
    provider: string;
  } | null;
  output: string;
  duration_ms?: number;
  truncated?: boolean;
};
export type SelfTest = {
  available: boolean;
  passed: boolean;
  detail: string;
  checks: { name: string; passed: boolean }[];
};

function fail(e: unknown, fallback: string): Error {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response
    ?.data?.detail;
  return new Error(typeof detail === "string" ? detail : fallback);
}

export async function getSandboxStatus(): Promise<SandboxStatus> {
  try {
    return (await api.get<SandboxStatus>("/api/sandbox/status")).data;
  } catch (e) {
    throw fail(e, "Could not reach the backend.");
  }
}

export async function getLatestResult(
  proposalId: string,
): Promise<SandboxResult | null> {
  try {
    return (
      await api.get<SandboxResult | null>(`/api/sandbox/results/${proposalId}`)
    ).data;
  } catch {
    return null;
  }
}

export async function runSandboxTests(
  proposalId: string,
  opts: { installDeps: boolean; scope: "generated" | "all" },
): Promise<SandboxResult> {
  try {
    return (
      await api.post<SandboxResult>(
        `/api/sandbox/test/${proposalId}`,
        { install_deps: opts.installDeps, scope: opts.scope },
        { timeout: 1_200_000 }, // installing requirements for the first time can take many minutes
      )
    ).data;
  } catch (e) {
    throw fail(e, "The sandbox run failed.");
  }
}

export async function runSelfTest(): Promise<SelfTest> {
  try {
    return (
      await api.post<SelfTest>("/api/sandbox/selftest", null, {
        timeout: 1_200_000,
      })
    ).data;
  } catch (e) {
    throw fail(e, "The self-test failed to run.");
  }
}

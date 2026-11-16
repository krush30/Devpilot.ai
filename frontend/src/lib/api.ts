import axios from "axios";

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  timeout: 600_000, // indexing a large repo can take minutes
});

export type Source = { path: string; start_line: number; end_line: number };
export type ChatReply = { reply: string; provider: string; sources: Source[] };
export type Repo = { repo_id: string; chunks: number };

export async function sendChat(
  message: string,
  repoId?: string,
): Promise<ChatReply> {
  const { data } = await api.post<ChatReply>("/api/chat", {
    message,
    repo_id: repoId || null,
  });
  return data;
}

export async function listRepos(): Promise<Repo[]> {
  const { data } = await api.get<Repo[]>("/api/repos");
  return data;
}

export async function indexRepo(name: string, source: string) {
  const isUrl = /^https?:\/\//.test(source.trim());
  const body = isUrl
    ? { name, git_url: source.trim() }
    : { name, path: source.trim() };
  const { data } = await api.post<{
    repo_id: string;
    files: number;
    chunks: number;
  }>("/api/repos/index", body);
  return data;
}

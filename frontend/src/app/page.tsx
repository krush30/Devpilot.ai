"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Send, FileCode2, Loader2 } from "lucide-react";
import {
  indexRepo,
  listRepos,
  sendChat,
  type Repo,
  type Source,
} from "@/lib/api";

type Msg = {
  role: "user" | "assistant" | "error";
  text: string;
  provider?: string;
  sources?: Source[];
};

function errorText(e: unknown, fallback: string) {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response
    ?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}

export default function Home() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const [repos, setRepos] = useState<Repo[]>([]);
  const [repoId, setRepoId] = useState("");
  const [name, setName] = useState("");
  const [source, setSource] = useState("");
  const [indexing, setIndexing] = useState(false);
  const [indexMsg, setIndexMsg] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const refreshRepos = useCallback(async () => {
    try {
      setRepos(await listRepos());
    } catch {
      /* backend offline; the chat error will say so */
    }
  }, []);

  useEffect(() => {
    refreshRepos();
  }, [refreshRepos]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function onIndex(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || !source.trim() || indexing) return;
    setIndexing(true);
    setIndexMsg("Indexing… the first run downloads the embedding model.");
    try {
      const r = await indexRepo(name.trim(), source);
      setIndexMsg(`Indexed ${r.files} files (${r.chunks} chunks).`);
      await refreshRepos();
      setRepoId(r.repo_id);
    } catch (err) {
      setIndexMsg(
        errorText(err, "Indexing failed. Check the backend terminal."),
      );
    } finally {
      setIndexing(false);
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setLoading(true);
    try {
      const res = await sendChat(text, repoId);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: res.reply,
          provider: res.provider,
          sources: res.sources,
        },
      ]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        {
          role: "error",
          text: errorText(
            err,
            "Could not reach the backend on port 8000, or no model provider is available.",
          ),
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100">
      <aside className="hidden w-72 shrink-0 flex-col gap-6 border-r border-zinc-800 p-4 md:flex">
        <div>
          <h1 className="text-lg font-semibold">DevPilot</h1>
          <p className="text-sm text-zinc-400">Chat with your codebase.</p>
        </div>

        <div className="space-y-2">
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
            <option value="">None (general chat)</option>
            {repos.map((r) => (
              <option key={r.repo_id} value={r.repo_id}>
                {r.repo_id.replace(/^repo_/, "")} ({r.chunks} chunks)
              </option>
            ))}
          </select>
        </div>

        <form onSubmit={onIndex} className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">
            Index a repository
          </p>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name (e.g. my-app)"
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-2 py-2 text-sm outline-none focus:border-emerald-600"
          />
          <input
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="Folder path or GitHub URL"
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-2 py-2 text-sm outline-none focus:border-emerald-600"
          />
          <button
            type="submit"
            disabled={indexing || !name.trim() || !source.trim()}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-emerald-700 px-3 py-2 text-sm text-white hover:bg-emerald-600 disabled:opacity-40"
          >
            {indexing && <Loader2 size={14} className="animate-spin" />}
            {indexing ? "Indexing" : "Index"}
          </button>
          {indexMsg && <p className="text-xs text-zinc-400">{indexMsg}</p>}
        </form>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <section className="flex-1 space-y-4 overflow-y-auto px-4 py-6">
          {messages.length === 0 && (
            <p className="text-zinc-500">
              {repoId
                ? "Ask about the selected repository, e.g. “Where is the provider fallback handled?”"
                : "Index a repository on the left, or just ask a general question."}
            </p>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              className={
                m.role === "user" ? "flex justify-end" : "flex justify-start"
              }
            >
              <div
                className={
                  "max-w-[85%] whitespace-pre-wrap rounded-lg px-4 py-2 text-sm leading-relaxed " +
                  (m.role === "user"
                    ? "bg-emerald-700 text-white"
                    : m.role === "error"
                      ? "border border-red-800 bg-red-950 text-red-200"
                      : "bg-zinc-900 text-zinc-100")
                }
              >
                {m.text}
                {m.sources && m.sources.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {m.sources.map((s, j) => (
                      <span
                        key={j}
                        className="inline-flex items-center gap-1 rounded bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300"
                      >
                        <FileCode2 size={12} />
                        {s.path}:{s.start_line}-{s.end_line}
                      </span>
                    ))}
                  </div>
                )}
                {m.provider && (
                  <div className="mt-2 text-xs text-zinc-500">
                    via {m.provider}
                  </div>
                )}
              </div>
            </div>
          ))}
          {loading && <p className="text-sm text-zinc-500">Thinking…</p>}
          <div ref={bottomRef} />
        </section>

        <form
          onSubmit={onSubmit}
          className="flex gap-2 border-t border-zinc-800 p-4"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              repoId ? "Ask about this repository" : "Message DevPilot"
            }
            className="flex-1 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-emerald-600"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            aria-label="Send message"
            className="rounded-md bg-emerald-700 px-3 text-white hover:bg-emerald-600 disabled:opacity-40"
          >
            <Send size={18} />
          </button>
        </form>
      </main>
    </div>
  );
}

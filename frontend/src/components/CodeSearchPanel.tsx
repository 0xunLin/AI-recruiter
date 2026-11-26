import { useId, useState, type FormEvent } from "react";
import { api } from "../api";
import type { Application, CodeChunkMatch } from "../types";

interface CodeSearchPanelProps {
  apiKey: string;
  applications: Application[];
  selectedApplicationId: string;
  onSelectApplicationId: (id: string) => void;
  query: string;
  onQueryChange: (q: string) => void;
}

export function CodeSearchPanel({
  apiKey,
  applications,
  selectedApplicationId,
  onSelectApplicationId,
  query,
  onQueryChange,
}: CodeSearchPanelProps) {
  const [matches, setMatches] = useState<CodeChunkMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const appSelectId = useId();
  const queryId = useId();

  const activeAppId = selectedApplicationId || applications[0]?.id || "";

  const handleSearch = async (e: FormEvent) => {
    e.preventDefault();
    if (!activeAppId || !query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.searchCandidateCode(apiKey || undefined, activeAppId, query.trim(), 6);
      setMatches(res.matches);
      setSearched(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Code search failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="space-y-5">
      <div className="border-b-2 border-[var(--border-heavy)] pb-3">
        <span className="sui-spec-label text-[var(--ink-primary)]">[INDEXED REPOSITORY CHUNKS]</span>
        <h2 className="display-heading mt-0.5 text-lg font-bold text-[var(--ink-primary)]">Code Search</h2>
      </div>

      <search className="wire-card block p-5">
        <form onSubmit={handleSearch} className="grid gap-4 md:grid-cols-12">
          <div className="md:col-span-4">
            <label htmlFor={appSelectId} className="sui-spec-label block text-[var(--ink-primary)]">
              Candidate
            </label>
            <select
              id={appSelectId}
              name="application_id"
              value={activeAppId}
              onChange={(e) => onSelectApplicationId(e.target.value)}
              disabled={applications.length === 0}
              className="wire-input mt-1.5 h-10 w-full px-3 text-xs"
            >
              {applications.length === 0 ? (
                <option value="">No applications yet</option>
              ) : (
                applications.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.candidate?.full_name ?? a.id.slice(0, 8)} — {a.job_title ?? "Role"}
                  </option>
                ))
              )}
            </select>
          </div>

          <div className="md:col-span-6">
            <label htmlFor={queryId} className="sui-spec-label block text-[var(--ink-primary)]">
              Query
            </label>
            <input
              id={queryId}
              name="query"
              type="search"
              required
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              value={query}
              onChange={(e) => onQueryChange(e.target.value)}
              placeholder="Search candidate code by behavior, function, or file path"
              className="wire-input mt-1.5 h-10 w-full px-3.5 text-xs"
            />
          </div>

          <div className="flex items-end md:col-span-2">
            <button
              type="submit"
              disabled={loading || !activeAppId}
              className="wire-btn-primary h-10 w-full px-4 text-[11px] uppercase tracking-[0.06em] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? "Searching..." : "Search"}
            </button>
          </div>
        </form>
      </search>

      {error && (
        <p role="alert" className="spec-mono border border-[#FF2A6D] bg-[var(--surface-bg)] px-3 py-2 text-xs text-[#FF2A6D]">
          {error}
        </p>
      )}

      {searched && (
        <div className="space-y-4">
          {matches.length === 0 ? (
            <p className="editorial-note text-sm text-[var(--ink-muted)]">
              No indexed code chunks found for this candidate yet.
            </p>
          ) : (
            matches.map((m) => (
              <div
                key={m.chunk_id}
                className="wire-card"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-card)] bg-[var(--surface-bg)] px-4 py-2.5 text-xs">
                  <span className="spec-mono font-semibold text-[var(--ink-primary)]">
                    {m.file_path} · {m.symbol_name} ({m.symbol_type})
                  </span>
                  <span className="sui-spec-label wire-tag-solid px-2 py-0.5 tabular-nums">
                    Lines {m.start_line}–{m.end_line} · {(m.similarity * 100).toFixed(1)}%
                  </span>
                </div>
                <pre className="wire-terminal overflow-x-auto border-0 p-4 text-xs">
                  <code>{m.content}</code>
                </pre>
              </div>
            ))
          )}
        </div>
      )}
    </section>
  );
}

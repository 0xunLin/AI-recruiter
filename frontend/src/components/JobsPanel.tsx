import { useId, useState, type FormEvent } from "react";
import type { Job } from "../types";

interface JobsPanelProps {
  jobs: Job[];
  selectedJobId: string | null;
  onSelectJob: (jobId: string | null) => void;
  onCreateJob: (title: string, description: string) => Promise<void>;
}

export function JobsPanel({
  jobs,
  selectedJobId,
  onSelectJob,
  onCreateJob,
}: JobsPanelProps) {
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const titleId = useId();
  const descId = useId();

  const selectedJob = jobs.find((j) => j.id === selectedJobId) ?? jobs[0] ?? null;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await onCreateJob(title.trim(), description.trim());
      setTitle("");
      setDescription("");
      setShowForm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create job.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b-2 border-[var(--border-heavy)] pb-3">
        <div>
          <span className="sui-spec-label text-[var(--ink-primary)]">[ROLES &amp; RUBRICS]</span>
          <h2 className="display-heading mt-0.5 text-lg font-bold text-[var(--ink-primary)]">Jobs</h2>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((s) => !s)}
          aria-expanded={showForm}
          className="wire-btn-primary h-9 px-4 text-[11px] uppercase tracking-[0.06em]"
        >
          {showForm ? "Cancel" : "New Job"}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="wire-card space-y-4 p-5 sm:p-6"
        >
          <div>
            <label htmlFor={titleId} className="sui-spec-label block text-[var(--ink-primary)]">
              Role Title <span aria-hidden="true" className="text-[#FF2A6D]">*</span>
            </label>
            <input
              id={titleId}
              name="job_title"
              type="text"
              required
              autoFocus
              minLength={3}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Senior Backend Engineer"
              className="wire-input mt-1.5 h-10 w-full px-3.5 text-sm"
            />
          </div>
          <div>
            <label htmlFor={descId} className="sui-spec-label block text-[var(--ink-primary)]">
              Job Description <span aria-hidden="true" className="text-[#FF2A6D]">*</span>
            </label>
            <textarea
              id={descId}
              name="job_description"
              required
              minLength={20}
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe the engineering responsibilities, required stack, and key technical expectations."
              className="wire-input mt-1.5 w-full p-3.5 text-sm"
            />
          </div>
          {error && (
            <p role="alert" className="spec-mono border border-[#FF2A6D] bg-[var(--surface-bg)] px-3 py-2 text-xs text-[#FF2A6D]">
              {error}
            </p>
          )}
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="wire-btn-primary h-10 px-5 text-[11px] uppercase tracking-[0.06em] disabled:opacity-50"
            >
              {submitting ? "Creating..." : "Create Job"}
            </button>
          </div>
        </form>
      )}

      {jobs.length === 0 ? (
        <div className="wire-card p-6">
          <p className="editorial-note text-sm text-[var(--ink-muted)]">
            No jobs created yet. Click New Job to publish a role and generate its evaluation rubric.
          </p>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-12">
          <div className="divide-y divide-[var(--border-card)] border border-[var(--border-card)] bg-[var(--surface-bg)] lg:col-span-5">
            {jobs.map((job) => {
              const active = selectedJob?.id === job.id;
              return (
                <button
                  key={job.id}
                  type="button"
                  onClick={() => onSelectJob(job.id)}
                  className={`w-full px-4 py-4 text-left transition-colors duration-100 ${
                    active
                      ? "bg-[var(--solid-bg)] text-[var(--solid-fg)]"
                      : "bg-[var(--surface-bg)] text-[var(--ink-primary)] hover:bg-[var(--surface-hover)]"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="display-heading text-sm font-bold">{job.title}</span>
                    <span
                      className={`sui-spec-label border px-1.5 py-0.5 tabular-nums ${
                        active
                          ? "border-[var(--solid-fg)] text-[var(--solid-fg)]"
                          : "border-[var(--border-interactive)] text-[var(--ink-primary)]"
                      }`}
                    >
                      {job.rubric?.criteria.length ?? 0} CRITERIA
                    </span>
                  </div>
                  <p
                    className={`editorial-note mt-1.5 line-clamp-2 text-xs leading-relaxed ${
                      active ? "text-[var(--solid-fg)]/80" : "text-[var(--ink-muted)]"
                    }`}
                  >
                    {job.description}
                  </p>
                </button>
              );
            })}
          </div>

          <div className="wire-card p-5 sm:p-6 lg:col-span-7">
            {selectedJob ? (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2 border-b-2 border-[var(--border-heavy)] pb-3">
                  <h3 className="display-heading text-base font-bold text-[var(--ink-primary)]">
                    {selectedJob.title} — Evaluation Rubric
                  </h3>
                  <code className="sui-spec-label wire-tag px-2 py-0.5">
                    {selectedJob.id.slice(0, 8)}
                  </code>
                </div>
                {selectedJob.rubric ? (
                  <ol className="divide-y divide-[var(--divider-rule)]">
                    {selectedJob.rubric.criteria.map((c, idx) => (
                      <li key={c.name} className="py-3.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="display-heading text-xs font-bold text-[var(--ink-primary)]">
                            <span className="spec-mono mr-2 tabular-nums text-[var(--ink-muted)]">
                              [{idx + 1}]
                            </span>
                            {c.name}
                          </span>
                          <span className="sui-spec-label wire-tag-solid px-2 py-0.5 tabular-nums">
                            {Math.round(c.weight * 100)}%
                          </span>
                        </div>
                        <p className="editorial-note mt-1.5 text-xs leading-relaxed text-[var(--ink-muted)]">
                          {c.description}
                        </p>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="editorial-note mt-4 text-xs text-[var(--ink-muted)]">
                    Rubric pending extraction.
                  </p>
                )}
              </>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}

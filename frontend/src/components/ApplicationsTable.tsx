import { useId } from "react";
import type { Application, ApplicationStatus } from "../types";

interface ApplicationsTableProps {
  applications: Application[];
  shortlistedOnly: boolean;
  onToggleShortlistedOnly: (val: boolean) => void;
  onInspectEvidence: (app: Application) => void;
  onReEvaluate: (applicationId: string) => Promise<void>;
  onOpenSubmit: () => void;
  canSubmit: boolean;
}

const STATUS_BADGES: Record<ApplicationStatus, { label: string; classes: string }> = {
  awaiting_evidence: {
    label: "[AWAITING EVIDENCE]",
    classes: "wire-tag",
  },
  pending: {
    label: "[PENDING]",
    classes: "wire-tag",
  },
  ingesting: {
    label: "[CLONING]",
    classes: "border border-[#B8F200] bg-[#B8F200] text-black",
  },
  evaluating: {
    label: "[EVALUATING]",
    classes: "border border-[#05D9E8] bg-[#05D9E8] text-black",
  },
  completed: {
    label: "[VERIFIED]",
    classes: "border border-[#2E7D32] bg-[#2E7D32] text-white",
  },
  failed: {
    label: "[FAILED]",
    classes: "border border-[#FF2A6D] bg-[#FF2A6D] text-white",
  },
};

export function ApplicationsTable({
  applications,
  shortlistedOnly,
  onToggleShortlistedOnly,
  onInspectEvidence,
  onReEvaluate,
  onOpenSubmit,
  canSubmit,
}: ApplicationsTableProps) {
  const captionId = useId();
  const visibleApps = shortlistedOnly
    ? applications.filter((a) => a.is_shortlisted)
    : applications;

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b-2 border-[var(--border-heavy)] pb-3">
        <div>
          <span className="sui-spec-label text-[var(--ink-primary)]">[PIPELINE &amp; SHORTLIST]</span>
          <h2 id={captionId} className="display-heading mt-0.5 text-lg font-bold text-[var(--ink-primary)]">
            Candidates
          </h2>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <div className="flex border border-[var(--border-interactive)] bg-[var(--surface-bg)]">
            <button
              type="button"
              onClick={() => onToggleShortlistedOnly(false)}
              className={`spec-mono px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] transition-colors duration-100 ${
                !shortlistedOnly
                  ? "bg-[var(--solid-bg)] text-[var(--solid-fg)]"
                  : "bg-[var(--surface-bg)] text-[var(--ink-primary)] hover:bg-[var(--surface-hover)]"
              }`}
            >
              All ({applications.length})
            </button>
            <button
              type="button"
              onClick={() => onToggleShortlistedOnly(true)}
              className={`spec-mono border-l border-[var(--border-interactive)] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] transition-colors duration-100 ${
                shortlistedOnly
                  ? "bg-[var(--solid-bg)] text-[var(--solid-fg)]"
                  : "bg-[var(--surface-bg)] text-[var(--ink-primary)] hover:bg-[var(--surface-hover)]"
              }`}
            >
              Top 30% ({applications.filter((a) => a.is_shortlisted).length})
            </button>
          </div>

          <button
            type="button"
            disabled={!canSubmit}
            onClick={onOpenSubmit}
            className="wire-btn-primary h-9 px-4 text-[11px] uppercase tracking-[0.06em] disabled:cursor-not-allowed disabled:opacity-40"
          >
            Submit Resume
          </button>
        </div>
      </div>

      {visibleApps.length === 0 ? (
        <div className="wire-card p-6">
          <p className="editorial-note text-sm text-[var(--ink-muted)]">
            {shortlistedOnly
              ? "No candidates have qualified for the top-30% shortlist yet."
              : canSubmit
                ? "No candidates submitted yet."
                : "Create a job first before submitting candidate resumes."}
          </p>
        </div>
      ) : (
        <div
          tabIndex={0}
          role="region"
          aria-labelledby={captionId}
          className="table-wrapper wire-card"
        >
          <table className="responsive-apps-table text-left text-sm">
            <caption className="sr-only">Candidate resumes, verified claims, and 0-10 scores</caption>
            <thead className="border-b-2 border-[var(--border-heavy)] bg-[var(--surface-bg)] text-[var(--ink-primary)]">
              <tr>
                <th scope="col" className="sui-spec-label px-4 py-3 font-semibold">Candidate</th>
                <th scope="col" className="sui-spec-label px-4 py-3 font-semibold">Role</th>
                <th scope="col" className="sui-spec-label px-4 py-3 font-semibold">Claims Verified</th>
                <th scope="col" className="sui-spec-label px-4 py-3 font-semibold">Status</th>
                <th scope="col" className="sui-spec-label px-4 py-3 font-semibold">Score / 10</th>
                <th scope="col" className="sui-spec-label px-4 py-3 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--divider-rule)]">
              {visibleApps.map((app) => {
                const badge = STATUS_BADGES[app.status];
                const claims = app.claims ?? [];
                const verifiedCount = claims.filter((c) => c.verification_status === "verified").length;
                return (
                  <tr
                    key={app.id}
                    className="transition-colors duration-100 hover:bg-[var(--surface-hover)]"
                  >
                    <th scope="row" className="px-4 py-3.5 font-medium whitespace-nowrap text-[var(--ink-primary)]">
                      <div className="flex items-center gap-2">
                        <span className="display-heading text-sm font-bold">
                          {app.candidate?.full_name ?? "Candidate"}
                        </span>
                        {app.is_shortlisted && (
                          <span className="sui-spec-label wire-tag-solid px-1.5 py-0.5">
                            [TOP 30%]
                          </span>
                        )}
                      </div>
                      <div className="spec-mono mt-0.5 text-[11px] font-normal text-[var(--ink-muted)]">
                        {app.candidate?.email}
                      </div>
                    </th>
                    <td data-label="Role" className="px-4 py-3.5 text-xs text-[var(--ink-primary)]">
                      {app.job_title ?? app.job_id.slice(0, 8)}
                    </td>
                    <td data-label="Claims Verified" className="spec-mono px-4 py-3.5 text-xs tabular-nums">
                      {claims.length > 0 ? (
                        <div>
                          <span className="font-semibold text-[var(--ink-primary)]">
                            {verifiedCount} / {claims.length}
                          </span>
                          <span className="ml-1.5 text-[var(--ink-muted)]">
                            ({app.repositories?.length ?? 0} links)
                          </span>
                        </div>
                      ) : (
                        <span className="text-[var(--ink-muted)]">0 links</span>
                      )}
                    </td>
                    <td data-label="Status" className="px-4 py-3.5">
                      <span
                        className={`sui-spec-label inline-flex items-center px-2 py-0.5 font-semibold ${badge.classes}`}
                      >
                        {badge.label}
                      </span>
                    </td>
                    <td data-label="Score / 10" className="spec-mono px-4 py-3.5 font-bold tabular-nums">
                      {app.score_out_of_10 !== null ? (
                        <span
                          className={
                            app.score_out_of_10 >= 6.0
                              ? "text-[var(--status-success-text)]"
                              : "text-[var(--ink-primary)]"
                          }
                        >
                          {app.score_out_of_10.toFixed(2)} / 10
                        </span>
                      ) : (
                        <span className="text-[var(--ink-muted)]">—</span>
                      )}
                    </td>
                    <td data-label="Actions" className="px-4 py-3.5 text-right whitespace-nowrap">
                      <div className="inline-flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => onInspectEvidence(app)}
                          className="wire-btn-primary h-8 px-3 text-[11px] uppercase tracking-[0.06em]"
                        >
                          Inspect
                        </button>
                        <button
                          type="button"
                          onClick={() => onReEvaluate(app.id)}
                          aria-label={`Re-evaluate ${app.candidate?.full_name ?? "candidate"}`}
                          className="wire-btn h-8 px-2.5 text-[11px] uppercase tracking-[0.06em]"
                        >
                          Re-run
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

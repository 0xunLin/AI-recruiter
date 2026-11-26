import { useCallback, useEffect, useId, useState, type FormEvent } from "react";
import { api } from "../api";
import type {
  ApplicantApplication,
  ApplicantProfile,
  ApplicationEvidenceOptions,
  ConfirmClaimEvidenceItem,
  PublicJob,
} from "../types";
import { ModalDialog } from "./ModalDialog";

interface ApplicantDashboardProps {
  profile: ApplicantProfile;
}

export function ApplicantDashboard({ profile }: ApplicantDashboardProps) {
  const [jobs, setJobs] = useState<PublicJob[]>([]);
  const [applications, setApplications] = useState<ApplicantApplication[]>([]);
  const [applyingJob, setApplyingJob] = useState<PublicJob | null>(null);
  const [resumeText, setResumeText] = useState("");
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Interactive Evidence & Ownership Defense Step
  const [evidenceAppId, setEvidenceAppId] = useState<string | null>(null);
  const [evidenceOptions, setEvidenceOptions] = useState<ApplicationEvidenceOptions | null>(null);
  const [loadingOptions, setLoadingOptions] = useState(false);
  const [confirmingEvidence, setConfirmingEvidence] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [selectedCommits, setSelectedCommits] = useState<Record<string, string[]>>({});
  const [selectedFiles, setSelectedFiles] = useState<Record<string, string[]>>({});
  const [ownershipAnswers, setOwnershipAnswers] = useState<Record<string, string>>({});

  const fileId = useId();
  const textId = useId();

  const loadData = useCallback(async () => {
    const [pubJobs, myApps] = await Promise.all([
      api.applicant.listPublicJobs(),
      api.applicant.listMyApplications(),
    ]);
    setJobs(pubJobs);
    setApplications(myApps);
  }, []);

  useEffect(() => {
    loadData().catch(() => undefined);
  }, [loadData]);

  useEffect(() => {
    const hasActive = applications.some(
      (a) => a.status === "pending" || a.status === "ingesting" || a.status === "evaluating"
    );
    if (!hasActive) return;
    const timer = setInterval(() => {
      api.applicant.listMyApplications().then(setApplications).catch(() => undefined);
    }, 4000);
    return () => clearInterval(timer);
  }, [applications]);

  const appliedJobIds = new Set(applications.map((a) => a.job_id));

  const openEvidenceStep = async (appId: string) => {
    setEvidenceAppId(appId);
    setEvidenceOptions(null);
    setEvidenceError(null);
    setSelectedCommits({});
    setSelectedFiles({});
    setOwnershipAnswers({});
    setLoadingOptions(true);
    try {
      const opts = await api.applicant.getEvidenceOptions(appId);
      setEvidenceOptions(opts);
    } catch (err) {
      setEvidenceError(
        err instanceof Error ? err.message : "Failed to load repository commit/file options."
      );
    } finally {
      setLoadingOptions(false);
    }
  };

  const handleApply = async (e: FormEvent) => {
    e.preventDefault();
    if (!applyingJob) return;
    if (!resumeFile && resumeText.trim().length < 30) {
      setError("Upload a PDF/TXT resume or paste at least 30 characters of resume text.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const created = await api.applicant.submitResume({
        job_id: applyingJob.id,
        resume_text: resumeText.trim() || undefined,
        resume_file: resumeFile,
        interactive_evidence: true,
      });
      setApplications((prev) => [created, ...prev]);
      setApplyingJob(null);
      setResumeText("");
      setResumeFile(null);
      await openEvidenceStep(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit application.");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleItem = (
    map: Record<string, string[]>,
    setter: (val: Record<string, string[]>) => void,
    claimId: string,
    value: string
  ) => {
    const current = map[claimId] ?? [];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    setter({ ...map, [claimId]: next });
  };

  const handleConfirmEvidence = async (e: FormEvent) => {
    e.preventDefault();
    if (!evidenceAppId || !evidenceOptions) return;

    setConfirmingEvidence(true);
    setEvidenceError(null);
    try {
      const payload: ConfirmClaimEvidenceItem[] = evidenceOptions.claims.map((c) => ({
        claim_id: c.claim_id,
        selected_commits: selectedCommits[c.claim_id] ?? [],
        selected_files: selectedFiles[c.claim_id] ?? [],
        ownership_answer: (ownershipAnswers[c.claim_id] ?? "").trim(),
      }));
      const updated = await api.applicant.confirmEvidence(evidenceAppId, payload);
      setApplications((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
      setEvidenceAppId(null);
      setEvidenceOptions(null);
    } catch (err) {
      setEvidenceError(err instanceof Error ? err.message : "Failed to confirm evidence.");
    } finally {
      setConfirmingEvidence(false);
    }
  };

  return (
    <div className="space-y-10">
      <div className="wire-card flex flex-wrap items-center justify-between gap-4 p-5 sm:p-6">
        <div>
          <span className="sui-spec-label text-[var(--ink-primary)]">[APPLICANT PROFILE]</span>
          <h1 className="display-heading mt-1 text-2xl font-bold text-[var(--ink-primary)]">
            {profile.full_name}
          </h1>
          <p className="spec-mono mt-1 text-xs text-[var(--ink-muted)]">{profile.email}</p>
        </div>
        {profile.github_handle && (
          <span className="sui-spec-label wire-tag-solid px-2.5 py-1">
            @{profile.github_handle}
          </span>
        )}
      </div>

      <section className="space-y-5">
        <div className="flex items-center justify-between border-b-2 border-[var(--border-heavy)] pb-3">
          <h2 className="display-heading text-lg font-bold text-[var(--ink-primary)]">Open Roles</h2>
          <span className="sui-spec-label wire-tag px-2 py-0.5">{jobs.length} AVAILABLE</span>
        </div>

        {jobs.length === 0 ? (
          <div className="wire-card p-6">
            <p className="editorial-note text-sm text-[var(--ink-muted)]">
              No public roles available right now. Check back soon.
            </p>
          </div>
        ) : (
          <div className="grid gap-5 md:grid-cols-2">
            {jobs.map((job) => {
              const alreadyApplied = appliedJobIds.has(job.id);
              return (
                <article
                  key={job.id}
                  className="wire-card flex flex-col justify-between p-5 sm:p-6"
                >
                  <div>
                    <div className="sui-spec-label wire-tag inline-block px-1.5 py-0.5">
                      {job.company_name}
                    </div>
                    <h3 className="display-heading mt-2.5 text-base font-bold text-[var(--ink-primary)]">
                      {job.title}
                    </h3>
                    <p className="editorial-note mt-2 line-clamp-3 text-xs leading-relaxed text-[var(--ink-muted)]">
                      {job.description}
                    </p>
                  </div>
                  <div className="mt-5 border-t border-[var(--divider-rule)] pt-4">
                    <button
                      type="button"
                      disabled={alreadyApplied}
                      onClick={() => {
                        setError(null);
                        setApplyingJob(job);
                      }}
                      className="wire-btn-primary h-9 px-4 text-[11px] uppercase tracking-[0.06em] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {alreadyApplied ? "Application Submitted" : "Apply with Resume"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section className="space-y-5">
        <div className="flex items-center justify-between border-b-2 border-[var(--border-heavy)] pb-3">
          <h2 className="display-heading text-lg font-bold text-[var(--ink-primary)]">
            My Applications
          </h2>
          <span className="sui-spec-label wire-tag px-2 py-0.5">{applications.length} TOTAL</span>
        </div>

        {applications.length === 0 ? (
          <div className="wire-card p-6">
            <p className="editorial-note text-sm text-[var(--ink-muted)]">
              You haven't applied to any roles yet.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {applications.map((app) => (
              <div key={app.id} className="wire-card p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="display-heading text-sm font-bold text-[var(--ink-primary)]">
                      {app.job_title}
                    </div>
                    <div className="editorial-note text-xs text-[var(--ink-muted)]">
                      {app.company_name}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {app.status === "awaiting_evidence" && (
                      <button
                        type="button"
                        onClick={() => openEvidenceStep(app.id)}
                        className="wire-btn-primary h-8 px-3 text-[11px] uppercase tracking-[0.06em]"
                      >
                        Select Commits &amp; Defense
                      </button>
                    )}
                    <span className="sui-spec-label wire-tag-solid px-2.5 py-1">
                      [
                      {app.status === "completed"
                        ? "SUBMITTED"
                        : app.status.replace("_", " ").toUpperCase()}
                      ]
                    </span>
                  </div>
                </div>

                {app.claims.length > 0 && (
                  <ul className="mt-4 space-y-2 border-t border-[var(--divider-rule)] pt-3 text-xs">
                    {app.claims.map((c, idx) => (
                      <li
                        key={`${c.project_title}-${idx}`}
                        className="flex flex-wrap items-center justify-between gap-2"
                      >
                        <span className="font-medium text-[var(--ink-primary)]">
                          {c.project_title}
                        </span>
                        <span className="spec-mono text-xs">
                          {c.link_status === "accessible" && (
                            <span className="font-semibold text-[var(--status-success-text)]">
                              Link accessible
                            </span>
                          )}
                          {c.link_status === "dead_link" && (
                            <span className="font-semibold text-[#FF2A6D]">
                              Unreachable link
                            </span>
                          )}
                          {c.link_status === "missing_link" && (
                            <span className="text-[var(--ink-muted)]">No GitHub link</span>
                          )}
                          {c.link_status === "pending" && (
                            <span className="text-[var(--ink-muted)]">Checking...</span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <ModalDialog
        open={Boolean(applyingJob)}
        onClose={() => setApplyingJob(null)}
        title={applyingJob ? `Apply to ${applyingJob.title}` : "Apply"}
        subtitle={applyingJob ? applyingJob.company_name : undefined}
        maxWidthClass="max-w-lg"
      >
        <form onSubmit={handleApply} className="space-y-4">
          <div>
            <label htmlFor={fileId} className="sui-spec-label block text-[var(--ink-primary)]">
              Upload Resume (PDF / TXT / MD)
            </label>
            <label
              htmlFor={fileId}
              className="spec-mono mt-1.5 flex cursor-pointer items-center justify-between gap-3 border border-dashed border-[var(--border-interactive)] bg-[var(--canvas-bg)] px-4 py-3 text-xs text-[var(--ink-primary)] hover:bg-[var(--surface-hover)]"
            >
              <span>{resumeFile ? resumeFile.name : "Choose a .pdf, .txt, or .md resume"}</span>
            </label>
            <input
              id={fileId}
              name="resume_file"
              type="file"
              accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
              onChange={(e) => setResumeFile(e.target.files?.[0] ?? null)}
              className="sr-only"
            />
          </div>

          <div>
            <label htmlFor={textId} className="sui-spec-label block text-[var(--ink-primary)]">
              Or Paste Resume Text
            </label>
            <textarea
              id={textId}
              name="resume_text"
              rows={6}
              value={resumeText}
              onChange={(e) => setResumeText(e.target.value)}
              placeholder="List your projects with https://github.com/... repo or PR links."
              className="wire-input mt-1.5 w-full p-3 text-xs"
            />
          </div>

          {error && (
            <p
              role="alert"
              className="spec-mono border border-[#FF2A6D] bg-[var(--surface-bg)] px-3 py-2 text-xs text-[#FF2A6D]"
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="wire-btn-primary h-10 w-full px-4 text-xs uppercase tracking-[0.06em] disabled:opacity-50"
          >
            {submitting ? "Extracting Claims..." : "Continue to Evidence Selection"}
          </button>
        </form>
      </ModalDialog>

      {/* Step 2: Interactive Commit / Key-File Evidence Picker + Ownership Defense */}
      <ModalDialog
        open={Boolean(evidenceAppId)}
        onClose={() => setEvidenceAppId(null)}
        title="Verify Commits, Key Files & Ownership"
        subtitle="Select the commits or key files that fulfill each claim and briefly explain your implementation."
        maxWidthClass="max-w-3xl"
      >
        {loadingOptions ? (
          <div className="py-10 text-center">
            <span className="sui-spec-label text-[var(--ink-primary)]">
              FETCHING GITHUB TREES &amp; COMMITS...
            </span>
          </div>
        ) : evidenceOptions ? (
          <form onSubmit={handleConfirmEvidence} className="space-y-5">
            {evidenceOptions.claims.map((claim, idx) => {
              const checkedCommits = selectedCommits[claim.claim_id] ?? [];
              const checkedFiles = selectedFiles[claim.claim_id] ?? [];
              return (
                <article key={claim.claim_id} className="wire-card space-y-3 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--divider-rule)] pb-2.5">
                    <h2 className="display-heading text-sm font-bold text-[var(--ink-primary)]">
                      [{idx + 1}] {claim.project_title}
                    </h2>
                    <span
                      className={`sui-spec-label px-2 py-0.5 ${
                        claim.is_single_commit_dump
                          ? "border border-[#FF2A6D] bg-[#FF2A6D] text-white"
                          : "wire-tag"
                      }`}
                    >
                      [{claim.provenance_tier.replace(/_/g, " ")}]
                    </span>
                  </div>

                  {claim.commits.length > 0 && (
                    <div>
                      <div className="sui-spec-label text-[var(--ink-muted)]">
                        SELECT COMMITS ({checkedCommits.length} SELECTED)
                      </div>
                      <div className="mt-1.5 max-h-36 space-y-1 overflow-y-auto border border-[var(--border-card)] bg-[var(--canvas-bg)] p-2">
                        {claim.commits.map((cm) => {
                          const isChecked = checkedCommits.includes(cm.sha);
                          return (
                            <label
                              key={cm.sha}
                              className="flex cursor-pointer items-start gap-2 px-1.5 py-1 text-xs hover:bg-[var(--surface-hover)]"
                            >
                              <input
                                type="checkbox"
                                checked={isChecked}
                                onChange={() =>
                                  toggleItem(
                                    selectedCommits,
                                    setSelectedCommits,
                                    claim.claim_id,
                                    cm.sha
                                  )
                                }
                                className="mt-0.5"
                              />
                              <span className="spec-mono text-[11px] text-[var(--ink-primary)]">
                                <strong>{cm.sha.slice(0, 7)}</strong> · {cm.message}{" "}
                                <span className="text-[var(--ink-muted)]">({cm.date})</span>
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {claim.file_tree.length > 0 && (
                    <div>
                      <div className="sui-spec-label text-[var(--ink-muted)]">
                        {claim.is_single_commit_dump
                          ? `SINGLE-COMMIT REPO — PICK KEY SOURCE FILES (${checkedFiles.length} SELECTED)`
                          : `KEY IMPLEMENTATION FILES (${checkedFiles.length} SELECTED)`}
                      </div>
                      <div className="mt-1.5 max-h-36 grid gap-1 overflow-y-auto border border-[var(--border-card)] bg-[var(--canvas-bg)] p-2 sm:grid-cols-2">
                        {claim.file_tree.map((fp) => {
                          const isChecked = checkedFiles.includes(fp);
                          return (
                            <label
                              key={fp}
                              className="flex cursor-pointer items-center gap-2 px-1.5 py-0.5 text-xs hover:bg-[var(--surface-hover)]"
                            >
                              <input
                                type="checkbox"
                                checked={isChecked}
                                onChange={() =>
                                  toggleItem(
                                    selectedFiles,
                                    setSelectedFiles,
                                    claim.claim_id,
                                    fp
                                  )
                                }
                              />
                              <span className="spec-mono truncate text-[11px] text-[var(--ink-primary)]">
                                {fp}
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  <div>
                    <div className="sui-spec-label text-[var(--ink-primary)]">
                      OWNERSHIP CHECK
                    </div>
                    <p className="editorial-note mt-1 text-xs text-[var(--ink-muted)]">
                      {claim.ownership_question}
                    </p>
                    <textarea
                      rows={2}
                      value={ownershipAnswers[claim.claim_id] ?? ""}
                      onChange={(e) =>
                        setOwnershipAnswers({
                          ...ownershipAnswers,
                          [claim.claim_id]: e.target.value,
                        })
                      }
                      placeholder="Briefly explain your design, data flow, or edge cases handled..."
                      className="wire-input mt-1.5 w-full p-2.5 text-xs"
                    />
                  </div>
                </article>
              );
            })}

            {evidenceError && (
              <p
                role="alert"
                className="spec-mono border border-[#FF2A6D] bg-[var(--surface-bg)] px-3 py-2 text-xs text-[#FF2A6D]"
              >
                {evidenceError}
              </p>
            )}

            <button
              type="submit"
              disabled={confirmingEvidence}
              className="wire-btn-primary h-10 w-full px-4 text-xs uppercase tracking-[0.06em] disabled:opacity-50"
            >
              {confirmingEvidence
                ? "Starting Verification..."
                : "Confirm Evidence & Start Verification"}
            </button>
          </form>
        ) : (
          evidenceError && (
            <p
              role="alert"
              className="spec-mono border border-[#FF2A6D] bg-[var(--surface-bg)] px-3 py-2 text-xs text-[#FF2A6D]"
            >
              {evidenceError}
            </p>
          )
        )}
      </ModalDialog>
    </div>
  );
}

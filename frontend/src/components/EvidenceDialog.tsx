import { useState } from "react";
import type { Application, ResumeClaim, ToolCallLogEntry } from "../types";
import { ModalDialog } from "./ModalDialog";

interface EvidenceDialogProps {
  application: Application | null;
  onClose: () => void;
  onSearchFile: (applicationId: string, filePath: string) => void;
}

const STEP_STYLES: Record<ToolCallLogEntry["step"], { label: string; badge: string }> = {
  initialize: {
    label: "1 · INITIALIZE",
    badge: "wire-tag",
  },
  plan: {
    label: "2 · PLAN",
    badge: "border border-[#05D9E8] bg-[#05D9E8] text-black",
  },
  gather: {
    label: "3 · GATHER",
    badge: "border border-[#B8F200] bg-[#B8F200] text-black",
  },
  analyse: {
    label: "4 · ANALYSE",
    badge: "wire-tag-solid",
  },
  format_and_seal: {
    label: "5 · FORMAT & SEAL",
    badge: "border border-[#2E7D32] bg-[#2E7D32] text-white",
  },
};

const CLAIM_BADGE: Record<ResumeClaim["verification_status"], string> = {
  pending: "wire-tag",
  verified: "border border-[#2E7D32] bg-[#2E7D32] text-white",
  partial: "border border-[#B8F200] bg-[#B8F200] text-black",
  unverified: "border border-[#FF2A6D] bg-[#FF2A6D] text-white",
  dead_link: "border border-[#FF2A6D] bg-[#FF2A6D] text-white",
};

export function EvidenceDialog({
  application,
  onClose,
  onSearchFile,
}: EvidenceDialogProps) {
  const [activeTab, setActiveTab] = useState<
    "claims" | "probes" | "rubric" | "resume" | "trail"
  >("claims");
  const report = application?.evaluation_report;
  const breakdown = application?.score_breakdown ?? report?.score_breakdown;
  const claims = application?.claims ?? [];
  const probes = report?.interview_probes ?? [];
  const trail = application?.tool_call_log ?? [];
  const evidenceHash = application?.evidence_hash ?? report?.evidence_hash;
  const filledMeterSegments = breakdown
    ? Math.max(0, Math.min(10, Math.round(breakdown.total_score_out_of_10)))
    : 0;

  return (
    <ModalDialog
      open={Boolean(application)}
      onClose={onClose}
      title={
        application
          ? `${application.candidate?.full_name ?? "Candidate"} — Verification Dossier`
          : "Verification Dossier"
      }
      subtitle={
        application
          ? `Application ${application.id.slice(0, 8)} · Status: ${application.status}${
              application.is_shortlisted ? " · Top 30% Shortlist" : ""
            }`
          : undefined
      }
      maxWidthClass="max-w-3xl"
    >
      {application && (
        <div className="space-y-5">
          {application.error_message && (
            <div className="border-2 border-[#FF2A6D] bg-[var(--surface-bg)] p-4 text-xs text-[var(--ink-primary)]">
              <div className="sui-spec-label font-semibold text-[#FF2A6D]">
                [EVALUATION ERROR]
              </div>
              <p className="spec-mono mt-1.5 text-[var(--ink-primary)]">{application.error_message}</p>
            </div>
          )}

          {breakdown && (
            <div className="wire-card space-y-4 p-4">
              <div className="grid gap-4 sm:grid-cols-4">
                <div>
                  <div className="sui-spec-label text-[var(--ink-muted)]">FINAL SCORE</div>
                  <div className="display-heading mt-1 text-2xl font-bold tabular-nums text-[var(--ink-primary)]">
                    {breakdown.total_score_out_of_10.toFixed(2)}
                    <span className="spec-mono ml-1 text-xs font-normal text-[var(--ink-muted)]">/ 10</span>
                  </div>
                </div>
                <div>
                  <div className="sui-spec-label text-[var(--ink-muted)]">CLAIM INTEGRITY</div>
                  <div className="spec-mono mt-1 text-sm font-bold tabular-nums text-[var(--ink-primary)]">
                    {breakdown.claim_verification_score.toFixed(2)} / 4.00
                  </div>
                  <div className="editorial-note text-[11px] text-[var(--ink-muted)]">
                    {breakdown.verified_claims}/{breakdown.total_claims} verified
                  </div>
                </div>
                <div>
                  <div className="sui-spec-label text-[var(--ink-muted)]">AUTHORSHIP</div>
                  <div className="spec-mono mt-1 text-sm font-bold tabular-nums text-[var(--ink-primary)]">
                    {breakdown.authorship_score.toFixed(2)} / 2.00
                  </div>
                  <div className="editorial-note text-[11px] text-[var(--ink-muted)]">Git/PR author match</div>
                </div>
                <div>
                  <div className="sui-spec-label text-[var(--ink-muted)]">TECH DEPTH</div>
                  <div className="spec-mono mt-1 text-sm font-bold tabular-nums text-[var(--ink-primary)]">
                    {breakdown.technical_depth_score.toFixed(2)} / 4.00
                  </div>
                  <div className="editorial-note text-[11px] text-[var(--ink-muted)]">Job rubric audit</div>
                </div>
              </div>

              <div
                aria-label={`Score ${breakdown.total_score_out_of_10.toFixed(2)} out of 10`}
                className="grid h-3.5 w-full grid-cols-10 divide-x divide-[var(--border-heavy)] border-2 border-[var(--border-heavy)] bg-[var(--surface-bg)]"
              >
                {Array.from({ length: 10 }, (_, idx) => (
                  <div
                    key={idx}
                    style={{
                      backgroundColor:
                        idx < filledMeterSegments
                          ? breakdown.total_score_out_of_10 >= 6.0
                            ? "#2E7D32"
                            : "var(--solid-bg)"
                          : "var(--surface-subtle)",
                    }}
                  />
                ))}
              </div>
            </div>
          )}

          {evidenceHash && (
            <div className="flex flex-wrap items-center justify-between gap-2 border border-[var(--border-card)] bg-[var(--surface-bg)] px-4 py-2.5 text-xs">
              <span className="sui-spec-label text-[var(--ink-primary)]">
                Evidence Seal:{" "}
                <code className="spec-mono font-bold text-[var(--ink-primary)]">
                  {evidenceHash.slice(0, 16)}…{evidenceHash.slice(-8)}
                </code>
              </span>
              <span className="sui-spec-label wire-tag px-2 py-0.5">
                {report?.model_id ?? "llm"}
              </span>
            </div>
          )}

          <div className="grid grid-cols-2 border border-[var(--border-interactive)] bg-[var(--surface-bg)] sm:grid-cols-5">
            <button
              type="button"
              onClick={() => setActiveTab("claims")}
              className={`spec-mono border-b border-[var(--border-interactive)] px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.06em] sm:border-b-0 sm:border-r ${
                activeTab === "claims"
                  ? "bg-[var(--solid-bg)] text-[var(--solid-fg)]"
                  : "bg-[var(--surface-bg)] text-[var(--ink-primary)] hover:bg-[var(--surface-hover)]"
              }`}
            >
              Claims ({claims.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("probes")}
              className={`spec-mono border-b border-l border-[var(--border-interactive)] px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.06em] sm:border-b-0 sm:border-l-0 sm:border-r ${
                activeTab === "probes"
                  ? "bg-[var(--solid-bg)] text-[var(--solid-fg)]"
                  : "bg-[var(--surface-bg)] text-[var(--ink-primary)] hover:bg-[var(--surface-hover)]"
              }`}
            >
              Probes ({probes.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("rubric")}
              className={`spec-mono border-b border-[var(--border-interactive)] px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.06em] sm:border-b-0 sm:border-r ${
                activeTab === "rubric"
                  ? "bg-[var(--solid-bg)] text-[var(--solid-fg)]"
                  : "bg-[var(--surface-bg)] text-[var(--ink-primary)] hover:bg-[var(--surface-hover)]"
              }`}
            >
              Rubric
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("resume")}
              className={`spec-mono border-r border-[var(--border-interactive)] px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.06em] ${
                activeTab === "resume"
                  ? "bg-[var(--solid-bg)] text-[var(--solid-fg)]"
                  : "bg-[var(--surface-bg)] text-[var(--ink-primary)] hover:bg-[var(--surface-hover)]"
              }`}
            >
              Resume
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("trail")}
              className={`spec-mono px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.06em] ${
                activeTab === "trail"
                  ? "bg-[var(--solid-bg)] text-[var(--solid-fg)]"
                  : "bg-[var(--surface-bg)] text-[var(--ink-primary)] hover:bg-[var(--surface-hover)]"
              }`}
            >
              Audit Trail ({trail.length})
            </button>
          </div>

          {activeTab === "claims" ? (
            claims.length === 0 ? (
              <p className="editorial-note text-sm text-[var(--ink-muted)]">
                No project claims or GitHub links extracted from this resume.
              </p>
            ) : (
              <div className="space-y-4">
                {claims.map((c) => (
                  <article
                    key={c.id}
                    className="wire-card p-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--divider-rule)] pb-2.5">
                      <h2 className="display-heading text-sm font-bold text-[var(--ink-primary)]">{c.project_title}</h2>
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`sui-spec-label px-2 py-0.5 font-semibold ${
                            CLAIM_BADGE[c.verification_status]
                          }`}
                        >
                          [{c.verification_status.replace("_", " ")}]
                        </span>
                        <span
                          className={`sui-spec-label px-2 py-0.5 ${
                            c.authorship_verified
                              ? "border border-[#2E7D32] bg-[#2E7D32] text-white"
                              : "wire-tag"
                          }`}
                        >
                          {c.authorship_verified ? "[AUTHOR MATCH]" : "[UNCONFIRMED]"}
                        </span>
                        {c.provenance_tier && c.provenance_tier !== "unknown" && (
                          <span
                            className={`sui-spec-label px-2 py-0.5 ${
                              c.provenance_tier === "single_commit_dump"
                                ? "border border-[#FF2A6D] bg-[#FF2A6D] text-white"
                                : "wire-tag"
                            }`}
                          >
                            [{c.provenance_tier.replace(/_/g, " ")}]
                          </span>
                        )}
                      </div>
                    </div>

                    <p className="mt-2.5 text-xs text-[var(--ink-primary)]">
                      <strong className="sui-spec-label mr-1.5">CLAIM:</strong>
                      {c.claimed_contribution}
                    </p>

                    {c.target_url && (
                      <a
                        href={c.target_url}
                        target="_blank"
                        rel="noreferrer"
                        className="spec-mono mt-2 inline-block text-xs text-[var(--ink-primary)] underline underline-offset-4 hover:bg-[var(--solid-bg)] hover:text-[var(--solid-fg)]"
                      >
                        {c.target_url} ({c.link_kind})
                      </a>
                    )}

                    {c.rationale && (
                      <p className="editorial-note mt-2.5 border border-[var(--border-card)] bg-[var(--surface-subtle)] p-3 text-xs leading-relaxed text-[var(--ink-primary)]">
                        {c.rationale}
                      </p>
                    )}

                    {c.ownership_answer && (
                      <div className="mt-2.5 border border-[var(--border-card)] bg-[var(--canvas-bg)] p-3 text-xs">
                        <div className="sui-spec-label text-[var(--ink-muted)]">
                          APPLICANT OWNERSHIP DEFENSE
                        </div>
                        {c.ownership_question && (
                          <p className="editorial-note mt-1 text-[11px] text-[var(--ink-muted)]">
                            {c.ownership_question}
                          </p>
                        )}
                        <p className="mt-1 text-[var(--ink-primary)]">{c.ownership_answer}</p>
                      </div>
                    )}

                    {c.referenced_files && c.referenced_files.length > 0 && (
                      <div className="mt-3 flex flex-wrap items-center gap-1.5">
                        {c.referenced_files.map((fp) => (
                          <button
                            key={fp}
                            type="button"
                            onClick={() => {
                              onSearchFile(application.id, fp);
                              onClose();
                            }}
                            className="wire-btn px-2 py-1 text-[11px]"
                          >
                            {fp}
                          </button>
                        ))}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            )
          ) : activeTab === "probes" ? (
            probes.length === 0 ? (
              <p className="editorial-note text-sm text-[var(--ink-muted)]">
                No technical screen probes generated yet.
              </p>
            ) : (
              <div className="space-y-4">
                {probes.map((probe, idx) => (
                  <article key={`${probe.project_or_area}-${idx}`} className="wire-card p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--divider-rule)] pb-2">
                      <h2 className="display-heading text-sm font-bold text-[var(--ink-primary)]">
                        {probe.project_or_area}
                      </h2>
                      <span
                        className={`sui-spec-label px-2 py-0.5 ${
                          probe.risk_flag === "single_commit_dump"
                            ? "border border-[#FF2A6D] bg-[#FF2A6D] text-white"
                            : "wire-tag-solid"
                        }`}
                      >
                        [{probe.risk_flag.replace(/_/g, " ")}]
                      </span>
                    </div>
                    <p className="mt-2.5 text-xs font-medium text-[var(--ink-primary)]">
                      {probe.question}
                    </p>
                    <p className="editorial-note mt-2 border border-[var(--border-card)] bg-[var(--surface-subtle)] p-2.5 text-xs text-[var(--ink-muted)]">
                      Listen for: {probe.what_to_listen_for}
                    </p>
                    {probe.file_path && (
                      <div className="mt-2.5">
                        <button
                          type="button"
                          onClick={() => {
                            onSearchFile(application.id, probe.file_path!);
                            onClose();
                          }}
                          className="wire-btn px-2 py-1 text-[11px]"
                        >
                          {probe.file_path}
                        </button>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            )
          ) : activeTab === "rubric" ? (
            report ? (
              <div className="space-y-4">
                <p className="editorial-note border-b border-[var(--divider-rule)] pb-3 text-xs leading-relaxed text-[var(--ink-primary)]">
                  {report.summary}
                </p>
                {report.criteria_evaluations.map((item) => (
                  <article
                    key={item.criterion_name}
                    className="wire-card p-4"
                  >
                    <div className="flex items-center justify-between gap-3 border-b border-[var(--divider-rule)] pb-2">
                      <h2 className="display-heading text-sm font-bold text-[var(--ink-primary)]">
                        {item.criterion_name}
                      </h2>
                      <span className="sui-spec-label wire-tag-solid px-2 py-0.5 font-semibold tabular-nums">
                        {item.score} / 5
                      </span>
                    </div>
                    <p className="editorial-note mt-2.5 text-xs leading-relaxed text-[var(--ink-muted)]">
                      {item.justification}
                    </p>
                    {item.referenced_files.length > 0 && (
                      <div className="mt-3 flex flex-wrap items-center gap-1.5">
                        {item.referenced_files.map((filePath) => (
                          <button
                            key={filePath}
                            type="button"
                            onClick={() => {
                              onSearchFile(application.id, filePath);
                              onClose();
                            }}
                            className="wire-btn px-2 py-1 text-[11px]"
                          >
                            {filePath}
                          </button>
                        ))}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <p className="editorial-note text-sm text-[var(--ink-muted)]">Evaluation pending.</p>
            )
          ) : activeTab === "resume" ? (
            application.resume ? (
              <pre className="wire-terminal max-h-96 overflow-auto p-4 text-xs whitespace-pre-wrap">
                {application.resume.raw_text}
              </pre>
            ) : (
              <p className="editorial-note text-sm text-[var(--ink-muted)]">
                No resume stored for this application.
              </p>
            )
          ) : trail.length === 0 ? (
            <p className="editorial-note text-sm text-[var(--ink-muted)]">
              No audit trail entries recorded yet.
            </p>
          ) : (
            <ol className="space-y-3">
              {trail.map((card, idx) => {
                const style = STEP_STYLES[card.step];
                return (
                  <li
                    key={`${card.step}-${card.iteration}-${idx}`}
                    className="wire-card p-3.5 text-xs"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`sui-spec-label px-2 py-0.5 font-semibold ${style.badge}`}>
                          {style.label}
                        </span>
                        <span className="spec-mono tabular-nums text-[var(--ink-muted)]">
                          iter #{card.iteration}
                        </span>
                        {card.criterion_name && (
                          <span className="display-heading font-semibold text-[var(--ink-primary)]">
                            · {card.criterion_name}
                          </span>
                        )}
                      </div>
                      {card.truncated && (
                        <span className="sui-spec-label border border-[#FF2A6D] bg-[#FF2A6D] px-2 py-0.5 font-semibold text-white">
                          [TRUNCATED]
                        </span>
                      )}
                    </div>
                    <div className="wire-terminal mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-[11px]">
                      <span>tool: {card.tool}</span>
                      <span>target: {card.target}</span>
                      {card.chunks_returned > 0 && (
                        <span className="tabular-nums">chunks: {card.chunks_returned}</span>
                      )}
                      {card.char_length > 0 && (
                        <span className="tabular-nums">
                          chars: {card.char_offset}..{card.char_offset + card.char_length}
                        </span>
                      )}
                    </div>
                    {card.note && (
                      <p className="editorial-note mt-2 text-xs text-[var(--ink-muted)]">{card.note}</p>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      )}
    </ModalDialog>
  );
}

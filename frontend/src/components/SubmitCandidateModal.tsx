import { useId, useState, type FormEvent } from "react";
import type { Job } from "../types";
import { ModalDialog } from "./ModalDialog";

interface SubmitCandidateModalProps {
  open: boolean;
  onClose: () => void;
  jobs: Job[];
  defaultJobId: string | null;
  onSubmit: (payload: {
    job_id: string;
    full_name: string;
    email: string;
    resume_text?: string;
    resume_file?: File | null;
  }) => Promise<void>;
}

export function SubmitCandidateModal({
  open,
  onClose,
  jobs,
  defaultJobId,
  onSubmit,
}: SubmitCandidateModalProps) {
  const [jobId, setJobId] = useState(defaultJobId ?? jobs[0]?.id ?? "");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [resumeText, setResumeText] = useState("");
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const jobSelectId = useId();
  const nameId = useId();
  const emailId = useId();
  const fileId = useId();
  const resumeId = useId();

  const activeJobId = jobId || defaultJobId || jobs[0]?.id || "";

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!resumeFile && resumeText.trim().length < 30) {
      setError("Upload a PDF/TXT resume or paste at least 30 characters of resume text.");
      return;
    }

    setError(null);
    setSubmitting(true);
    try {
      await onSubmit({
        job_id: activeJobId,
        full_name: fullName.trim(),
        email: email.trim(),
        resume_text: resumeText.trim() || undefined,
        resume_file: resumeFile,
      });
      setFullName("");
      setEmail("");
      setResumeText("");
      setResumeFile(null);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit candidate.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalDialog
      open={open}
      onClose={onClose}
      title="Submit Candidate Resume"
      subtitle="Upload a resume or paste text containing project descriptions and GitHub links."
      maxWidthClass="max-w-xl"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor={jobSelectId} className="sui-spec-label block text-[var(--ink-primary)]">
            Target Job <span aria-hidden="true" className="text-[#FF2A6D]">*</span>
          </label>
          <select
            id={jobSelectId}
            name="job_id"
            required
            value={activeJobId}
            onChange={(e) => setJobId(e.target.value)}
            className="wire-input mt-1.5 h-10 w-full px-3 text-sm"
          >
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.title}
              </option>
            ))}
          </select>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor={nameId} className="sui-spec-label block text-[var(--ink-primary)]">
              Full Name <span aria-hidden="true" className="text-[#FF2A6D]">*</span>
            </label>
            <input
              id={nameId}
              name="full_name"
              type="text"
              required
              autoFocus
              autoComplete="name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Elena Vance"
              className="wire-input mt-1.5 h-10 w-full px-3.5 text-sm"
            />
          </div>

          <div>
            <label htmlFor={emailId} className="sui-spec-label block text-[var(--ink-primary)]">
              Email <span aria-hidden="true" className="text-[#FF2A6D]">*</span>
            </label>
            <input
              id={emailId}
              name="email"
              type="email"
              required
              autoComplete="email"
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="elena@acme-eng.dev"
              className="wire-input mt-1.5 h-10 w-full px-3.5 text-sm"
            />
          </div>
        </div>

        <div>
          <label htmlFor={fileId} className="sui-spec-label block text-[var(--ink-primary)]">
            Upload Resume PDF / TXT / Markdown
          </label>
          <label
            htmlFor={fileId}
            className="spec-mono mt-1.5 flex cursor-pointer items-center justify-between gap-3 border border-dashed border-[var(--border-interactive)] bg-[var(--canvas-bg)] px-4 py-3 text-xs text-[var(--ink-primary)] hover:bg-[var(--surface-hover)]"
          >
            <span>{resumeFile ? resumeFile.name : "Choose a .pdf, .txt, or .md resume file"}</span>
            {resumeFile && (
              <span className="tabular-nums text-[var(--ink-muted)]">
                {(resumeFile.size / 1024).toFixed(1)} KB
              </span>
            )}
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
          <label htmlFor={resumeId} className="sui-spec-label block text-[var(--ink-primary)]">
            Or Paste Resume Content
          </label>
          <textarea
            id={resumeId}
            name="resume_text"
            rows={6}
            value={resumeText}
            onChange={(e) => setResumeText(e.target.value)}
            placeholder={
              "Projects:\n" +
              "- Distributed Task Queue — Built Redis rate limiter & workers. https://github.com/elena/task-queue"
            }
            className="wire-input mt-1.5 w-full p-3.5 text-xs leading-relaxed"
          />
        </div>

        {error && (
          <p role="alert" className="spec-mono border border-[#FF2A6D] bg-[var(--surface-bg)] px-3 py-2 text-xs text-[#FF2A6D]">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting || jobs.length === 0}
          className="wire-btn-primary h-10 w-full px-4 text-xs uppercase tracking-[0.06em] disabled:opacity-50"
        >
          {submitting ? "Submitting..." : "Submit Resume"}
        </button>
      </form>
    </ModalDialog>
  );
}

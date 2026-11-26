import { useId, useState, type FormEvent } from "react";
import { api } from "../api";
import type { ApplicantProfile, AuthProviders, RecruiterProfile } from "../types";

interface RoleAuthPortalProps {
  providers: AuthProviders | null;
  onRecruiterAuthenticated: (profile: RecruiterProfile, apiKey?: string) => void;
  onApplicantAuthenticated: (profile: ApplicantProfile) => void;
}

type AuthStep = "choose" | "recruiter" | "applicant";

export function RoleAuthPortal({
  providers,
  onRecruiterAuthenticated,
  onApplicantAuthenticated,
}: RoleAuthPortalProps) {
  const [step, setStep] = useState<AuthStep>("choose");

  const [recruiterMode, setRecruiterMode] = useState<"email" | "apikey">("email");
  const [recruiterEmail, setRecruiterEmail] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [inviteToken, setInviteToken] = useState("");
  const [showAdvancedRecruiter, setShowAdvancedRecruiter] = useState(false);
  const [devMagicLink, setDevMagicLink] = useState<string | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [recruiterError, setRecruiterError] = useState<string | null>(null);
  const [recruiterLoading, setRecruiterLoading] = useState(false);

  const [devGhHandle, setDevGhHandle] = useState("");
  const [devGhName, setDevGhName] = useState("");
  const [devGhEmail, setDevGhEmail] = useState("");
  const [applicantError, setApplicantError] = useState<string | null>(null);
  const [applicantLoading, setApplicantLoading] = useState(false);

  const recEmailId = useId();
  const compId = useId();
  const inviteId = useId();
  const keyId = useId();
  const ghHandleId = useId();
  const ghNameId = useId();
  const ghEmailId = useId();

  const backendOrigin =
    typeof window !== "undefined" && window.location.origin.includes(":5173")
      ? "http://localhost:8000"
      : "";

  const handleMagicLinkSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setRecruiterError(null);
    setDevMagicLink(null);
    setRecruiterLoading(true);
    try {
      const res = await api.auth.requestMagicLink(
        recruiterEmail.trim(),
        companyName.trim() || undefined,
        inviteToken.trim() || undefined
      );
      if (res.dev_magic_link) {
        setDevMagicLink(res.dev_magic_link);
      } else {
        setRecruiterError(res.message);
      }
    } catch (err) {
      setRecruiterError(err instanceof Error ? err.message : "Failed to send sign-in link.");
    } finally {
      setRecruiterLoading(false);
    }
  };

  const handleConsumeDevMagicLink = async () => {
    if (!devMagicLink) return;
    setRecruiterLoading(true);
    setRecruiterError(null);
    try {
      const url = new URL(devMagicLink);
      const token = url.searchParams.get("token") ?? "";
      const profile = await api.auth.verifyMagicLink(token);
      onRecruiterAuthenticated(profile);
    } catch (err) {
      setRecruiterError(err instanceof Error ? err.message : "Magic link verification failed.");
    } finally {
      setRecruiterLoading(false);
    }
  };

  const handleApiKeyConnect = async (e: FormEvent) => {
    e.preventDefault();
    setRecruiterLoading(true);
    setRecruiterError(null);
    try {
      const key = apiKeyInput.trim();
      const profile = await api.auth.getRecruiterMe(key);
      onRecruiterAuthenticated(profile, key);
    } catch (err) {
      setRecruiterError(err instanceof Error ? err.message : "Invalid API key.");
    } finally {
      setRecruiterLoading(false);
    }
  };

  const handleDevGitHubSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setApplicantLoading(true);
    setApplicantError(null);
    try {
      const cleanHandle = devGhHandle
        .trim()
        .replace(/^https?:\/\/(www\.)?github\.com\//i, "")
        .replace(/^@+/, "")
        .replace(/\/+$/, "");
      const profile = await api.auth.devGitHubLogin({
        github_handle: cleanHandle,
        full_name: devGhName.trim(),
        email: devGhEmail.trim(),
      });
      onApplicantAuthenticated(profile);
    } catch (err) {
      setApplicantError(err instanceof Error ? err.message : "GitHub sign-in failed.");
    } finally {
      setApplicantLoading(false);
    }
  };

  const handleApplicantChoose = () => {
    if (providers?.github_oauth_enabled) {
      window.location.href = `${backendOrigin}/api/v1/auth/applicant/github/login`;
      return;
    }
    setApplicantError(null);
    setStep("applicant");
  };

  if (step === "choose") {
    return (
      <div className="mx-auto max-w-[460px] py-10">
        <span className="sui-spec-label text-[var(--ink-primary)]">[AUTH // ROLE SELECTION]</span>
        <h1 className="display-heading mt-2 text-3xl font-bold text-[var(--ink-primary)]">Sign in</h1>
        <p className="editorial-note mt-2 text-sm text-[var(--ink-muted)]">
          Recruiters and applicants authenticate differently — pick the one that's you.
        </p>

        <hr className="my-6 border-[var(--border-heavy)]" />

        <div className="space-y-5">
          <section className="wire-card">
            <div className="flex items-center justify-between border-b border-[var(--border-card)] px-5 py-3">
              <span className="sui-spec-label text-[var(--ink-primary)]">APPLICANT</span>
              <span className="sui-spec-label wire-tag px-1.5 py-0.5">
                [GITHUB OAUTH]
              </span>
            </div>
            <div className="space-y-4 p-5">
              <p className="editorial-note text-sm leading-relaxed text-[var(--ink-muted)]">
                Sign in with GitHub. This verifies your GitHub identity and commit or PR authorship on the resume links you submit.
              </p>
              <button
                type="button"
                onClick={handleApplicantChoose}
                className="wire-btn-primary h-10 px-4 text-[11px] uppercase tracking-[0.06em]"
              >
                Continue with GitHub
              </button>
            </div>
          </section>

          <section className="wire-card">
            <div className="flex items-center justify-between border-b border-[var(--border-card)] px-5 py-3">
              <span className="sui-spec-label text-[var(--ink-primary)]">RECRUITER</span>
              <span className="sui-spec-label wire-tag px-1.5 py-0.5">
                [EMAIL / KEY]
              </span>
            </div>
            <div className="space-y-4 p-5">
              <p className="editorial-note text-sm leading-relaxed text-[var(--ink-muted)]">
                Sign in with an email link or Gmail — no password, no GitHub account required.
              </p>
              <div className="flex flex-wrap items-center gap-2.5">
                <button
                  type="button"
                  onClick={() => {
                    setRecruiterError(null);
                    setStep("recruiter");
                  }}
                  className="wire-btn h-10 px-4 text-[11px] uppercase tracking-[0.06em]"
                >
                  Continue with email
                </button>
                {providers?.google_oauth_enabled && (
                  <a
                    href={`${backendOrigin}/api/v1/auth/recruiter/google/login`}
                    className="wire-btn inline-flex h-10 items-center px-4 text-[11px] uppercase tracking-[0.06em]"
                  >
                    Continue with Gmail
                  </a>
                )}
              </div>
            </div>
          </section>
        </div>
      </div>
    );
  }

  if (step === "recruiter") {
    return (
      <div className="mx-auto max-w-[460px] py-10">
        <button
          type="button"
          onClick={() => {
            setStep("choose");
            setDevMagicLink(null);
            setRecruiterError(null);
          }}
          className="wire-btn mb-6 h-8 px-3 text-[11px] uppercase tracking-[0.06em]"
        >
          ← Back
        </button>

        <h1 className="display-heading text-3xl font-bold text-[var(--ink-primary)]">
          {recruiterMode === "email" ? "Sign in with email" : "Sign in with API key"}
        </h1>
        <p className="editorial-note mt-2 text-sm text-[var(--ink-muted)]">
          {recruiterMode === "email"
            ? "We'll send a one-time link — no password to remember."
            : "Connect directly using an existing workspace API key."}
        </p>

        <hr className="my-6 border-[var(--border-heavy)]" />

        <section className="wire-card">
          <div className="flex items-center justify-between border-b border-[var(--border-card)] px-5 py-3">
            <span className="sui-spec-label text-[var(--ink-primary)]">RECRUITER SIGN-IN</span>
            <button
              type="button"
              onClick={() => {
                setRecruiterMode((m) => (m === "email" ? "apikey" : "email"));
                setRecruiterError(null);
              }}
              className="spec-mono px-1.5 py-0.5 text-[11px] uppercase tracking-[0.06em] text-[var(--ink-primary)] underline underline-offset-4 hover:bg-[var(--solid-bg)] hover:text-[var(--solid-fg)]"
            >
              {recruiterMode === "email" ? "Use API key" : "Use email link"}
            </button>
          </div>

          {recruiterMode === "email" ? (
            <form onSubmit={handleMagicLinkSubmit} className="space-y-4 p-5">
              <div>
                <label htmlFor={recEmailId} className="sui-spec-label block text-[var(--ink-primary)]">
                  Email address
                </label>
                <input
                  id={recEmailId}
                  name="recruiter_email"
                  type="email"
                  required
                  autoFocus
                  autoComplete="email"
                  autoCorrect="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={recruiterEmail}
                  onChange={(e) => setRecruiterEmail(e.target.value)}
                  placeholder="you@company.com"
                  className="wire-input mt-2 h-10 w-full px-3 text-sm"
                />
              </div>

              <div>
                <button
                  type="button"
                  onClick={() => setShowAdvancedRecruiter((s) => !s)}
                  className="spec-mono text-[11px] uppercase tracking-[0.05em] text-[var(--ink-primary)] underline underline-offset-4"
                >
                  {showAdvancedRecruiter ? "Hide workspace options" : "+ New workspace name or invite token"}
                </button>
                {showAdvancedRecruiter && (
                  <div className="mt-3 space-y-3 border-t border-[var(--divider-rule)] pt-3">
                    <div>
                      <label htmlFor={compId} className="sui-spec-label block text-[var(--ink-primary)]">
                        Workspace Name (optional)
                      </label>
                      <input
                        id={compId}
                        name="company_name"
                        type="text"
                        value={companyName}
                        onChange={(e) => setCompanyName(e.target.value)}
                        placeholder="Acme Engineering"
                        className="wire-input mt-1.5 h-9 w-full px-3 text-xs"
                      />
                    </div>
                    <div>
                      <label htmlFor={inviteId} className="sui-spec-label block text-[var(--ink-primary)]">
                        Teammate Invite Token (optional)
                      </label>
                      <input
                        id={inviteId}
                        name="invite_token"
                        type="text"
                        autoCorrect="off"
                        autoCapitalize="none"
                        spellCheck={false}
                        value={inviteToken}
                        onChange={(e) => setInviteToken(e.target.value)}
                        placeholder="Paste invite token"
                        className="wire-input mt-1.5 h-9 w-full px-3 text-xs"
                      />
                    </div>
                  </div>
                )}
              </div>

              {devMagicLink && (
                <div className="wire-terminal border border-[var(--border-heavy)] p-4 text-xs">
                  <p className="spec-mono uppercase tracking-[0.06em]">
                    [DEV SIGN-IN LINK READY]
                  </p>
                  <button
                    type="button"
                    onClick={handleConsumeDevMagicLink}
                    className="mt-3 inline-flex h-9 w-full items-center justify-center border border-[#4ADE80] bg-[#4ADE80] px-3 spec-mono text-[11px] font-semibold uppercase tracking-[0.06em] text-black hover:border-white hover:bg-white"
                  >
                    Verify &amp; Sign In
                  </button>
                </div>
              )}

              {recruiterError && (
                <p role="alert" className="spec-mono border border-[#FF2A6D] bg-[var(--surface-bg)] px-3 py-2 text-xs text-[#FF2A6D]">
                  {recruiterError}
                </p>
              )}

              <button
                type="submit"
                disabled={recruiterLoading}
                className="wire-btn-primary h-10 px-4 text-[11px] uppercase tracking-[0.06em] disabled:opacity-50"
              >
                {recruiterLoading ? "Sending..." : "Send sign-in link"}
              </button>
            </form>
          ) : (
            <form onSubmit={handleApiKeyConnect} className="space-y-4 p-5">
              <div>
                <label htmlFor={keyId} className="sui-spec-label block text-[var(--ink-primary)]">
                  Workspace API Key
                </label>
                <input
                  id={keyId}
                  name="api_key"
                  type="password"
                  required
                  autoFocus
                  autoCorrect="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={apiKeyInput}
                  onChange={(e) => setApiKeyInput(e.target.value)}
                  placeholder="air_..."
                  className="wire-input mt-2 h-10 w-full px-3 text-xs"
                />
              </div>
              {recruiterError && (
                <p role="alert" className="spec-mono border border-[#FF2A6D] bg-[var(--surface-bg)] px-3 py-2 text-xs text-[#FF2A6D]">
                  {recruiterError}
                </p>
              )}
              <button
                type="submit"
                disabled={recruiterLoading}
                className="wire-btn-primary h-10 px-4 text-[11px] uppercase tracking-[0.06em] disabled:opacity-50"
              >
                {recruiterLoading ? "Connecting..." : "Connect workspace"}
              </button>
            </form>
          )}
        </section>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[460px] py-10">
      <button
        type="button"
        onClick={() => {
          setStep("choose");
          setApplicantError(null);
        }}
        className="wire-btn mb-6 h-8 px-3 text-[11px] uppercase tracking-[0.06em]"
      >
        ← Back
      </button>

      <h1 className="display-heading text-3xl font-bold text-[var(--ink-primary)]">Sign in with GitHub</h1>
      <p className="editorial-note mt-2 text-sm text-[var(--ink-muted)]">
        Enter your GitHub handle and email to continue.
      </p>

      <hr className="my-6 border-[var(--border-heavy)]" />

      <section className="wire-card">
        <div className="border-b border-[var(--border-card)] px-5 py-3">
          <span className="sui-spec-label text-[var(--ink-primary)]">APPLICANT SIGN-IN</span>
        </div>
        <form onSubmit={handleDevGitHubSubmit} className="space-y-4 p-5">
          <div>
            <label htmlFor={ghHandleId} className="sui-spec-label block text-[var(--ink-primary)]">
              GitHub username
            </label>
            <input
              id={ghHandleId}
              name="github_handle"
              type="text"
              required
              autoFocus
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              value={devGhHandle}
              onChange={(e) => setDevGhHandle(e.target.value)}
              placeholder="elenavance"
              className="wire-input mt-1.5 h-10 w-full px-3 text-xs"
            />
          </div>
          <div>
            <label htmlFor={ghNameId} className="sui-spec-label block text-[var(--ink-primary)]">
              Full name
            </label>
            <input
              id={ghNameId}
              name="full_name"
              type="text"
              required
              value={devGhName}
              onChange={(e) => setDevGhName(e.target.value)}
              placeholder="Elena Vance"
              className="wire-input mt-1.5 h-10 w-full px-3 text-sm"
            />
          </div>
          <div>
            <label htmlFor={ghEmailId} className="sui-spec-label block text-[var(--ink-primary)]">
              GitHub email
            </label>
            <input
              id={ghEmailId}
              name="email"
              type="email"
              required
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              value={devGhEmail}
              onChange={(e) => setDevGhEmail(e.target.value)}
              placeholder="elena@example.dev"
              className="wire-input mt-1.5 h-10 w-full px-3 text-sm"
            />
          </div>
          {applicantError && (
            <p role="alert" className="spec-mono border border-[#FF2A6D] bg-[var(--surface-bg)] px-3 py-2 text-xs text-[#FF2A6D]">
              {applicantError}
            </p>
          )}
          <button
            type="submit"
            disabled={applicantLoading}
            className="wire-btn-primary h-10 px-4 text-[11px] uppercase tracking-[0.06em] disabled:opacity-50"
          >
            {applicantLoading ? "Signing in..." : "Continue with GitHub"}
          </button>
        </form>
      </section>
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type {
  ApplicantProfile,
  Application,
  AuthProviders,
  Job,
  RecruiterProfile,
} from "./types";
import { RoleAuthPortal } from "./components/RoleAuthPortal";
import { ApplicantDashboard } from "./components/ApplicantDashboard";
import { ScoreHistogramCard } from "./components/ScoreHistogramCard";
import { JobsPanel } from "./components/JobsPanel";
import { ApplicationsTable } from "./components/ApplicationsTable";
import { SubmitCandidateModal } from "./components/SubmitCandidateModal";
import { EvidenceDialog } from "./components/EvidenceDialog";
import { CodeSearchPanel } from "./components/CodeSearchPanel";
import { McpConfigDialog } from "./components/McpConfigDialog";

const STORAGE_KEY = "ai_recruiter_api_key";
const THEME_STORAGE_KEY = "recruise_theme";

type NavSection = "overview" | "jobs" | "candidates" | "search";
type ThemeMode = "dark" | "light";

function formatHandle(handle: string | null | undefined): string {
  if (!handle) return "";
  const cleaned = handle
    .trim()
    .replace(/^https?:\/\/(www\.)?github\.com\//i, "")
    .replace(/^@+/, "")
    .replace(/\/+$/, "");
  return cleaned ? `@${cleaned}` : "";
}

export function App() {
  const [theme, setTheme] = useState<ThemeMode>(() => {
    try {
      return localStorage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
    } catch {
      return "dark";
    }
  });

  const [apiKey, setApiKey] = useState<string>(() => localStorage.getItem(STORAGE_KEY) ?? "");
  const [providers, setProviders] = useState<AuthProviders | null>(null);
  const [recruiter, setRecruiter] = useState<RecruiterProfile | null>(null);
  const [applicant, setApplicant] = useState<ApplicantProfile | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  const [jobs, setJobs] = useState<Job[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [shortlistedOnly, setShortlistedOnly] = useState(false);
  const [activeNav, setActiveNav] = useState<NavSection>("overview");

  const [submitModalOpen, setSubmitModalOpen] = useState(false);
  const [mcpModalOpen, setMcpModalOpen] = useState(false);
  const [inspectingApp, setInspectingApp] = useState<Application | null>(null);

  const [searchAppId, setSearchAppId] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) {
      meta.setAttribute("content", theme);
    }
  }, [theme]);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === THEME_STORAGE_KEY) {
        setTheme(e.newValue === "light" ? "light" : "dark");
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const handleToggleTheme = () => {
    const next: ThemeMode = theme === "dark" ? "light" : "dark";
    setTheme(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // ignore storage errors in restricted contexts
    }
  };

  const loadRecruiterWorkspace = useCallback(async (key?: string) => {
    const activeKey = key || undefined;
    const [jobList, appList] = await Promise.all([
      api.listJobs(activeKey),
      api.listApplications(activeKey),
    ]);
    setJobs(jobList);
    setApplications(appList);
    setSelectedJobId((prev) => prev ?? jobList[0]?.id ?? null);
  }, []);

  useEffect(() => {
    api.auth.providers().then(setProviders).catch(() => setProviders(null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function bootstrapSession() {
      try {
        const rec = await api.auth.getRecruiterMe(apiKey || undefined);
        if (!cancelled) {
          setRecruiter(rec);
          setApplicant(null);
          await loadRecruiterWorkspace(apiKey || undefined);
          setAuthChecked(true);
          return;
        }
      } catch {
        if (apiKey) {
          localStorage.removeItem(STORAGE_KEY);
          if (!cancelled) setApiKey("");
        }
      }

      try {
        const appProfile = await api.auth.getApplicantMe();
        if (!cancelled) {
          setApplicant(appProfile);
          setRecruiter(null);
          setAuthChecked(true);
          return;
        }
      } catch {
        // neither session active
      }

      if (!cancelled) setAuthChecked(true);
    }

    bootstrapSession();
    return () => {
      cancelled = true;
    };
  }, [apiKey, loadRecruiterWorkspace]);

  useEffect(() => {
    if (!recruiter) return;
    const hasActive = applications.some(
      (a) => a.status === "pending" || a.status === "ingesting" || a.status === "evaluating"
    );
    if (!hasActive) return;

    const timer = setInterval(() => {
      api.listApplications(apiKey || undefined).then(setApplications).catch(() => undefined);
    }, 4000);
    return () => clearInterval(timer);
  }, [recruiter, apiKey, applications]);

  const handleRecruiterAuthenticated = async (profile: RecruiterProfile, newKey?: string) => {
    if (newKey) {
      localStorage.setItem(STORAGE_KEY, newKey);
      setApiKey(newKey);
    } else {
      localStorage.removeItem(STORAGE_KEY);
      setApiKey("");
    }
    setApplicant(null);
    setRecruiter(profile);
    await loadRecruiterWorkspace(newKey);
  };

  const handleApplicantAuthenticated = (profile: ApplicantProfile) => {
    localStorage.removeItem(STORAGE_KEY);
    setApiKey("");
    setRecruiter(null);
    setApplicant(profile);
  };

  const handleSwitchOrLogout = async () => {
    await api.auth.logoutAll().catch(() => undefined);
    localStorage.removeItem(STORAGE_KEY);
    setApiKey("");
    setRecruiter(null);
    setApplicant(null);
    setJobs([]);
    setApplications([]);
  };

  const handleCreateJob = async (title: string, description: string) => {
    const job = await api.createJob(apiKey || undefined, title, description);
    setJobs((prev) => [job, ...prev]);
    setSelectedJobId(job.id);
  };

  const handleSubmitCandidate = async (payload: {
    job_id: string;
    full_name: string;
    email: string;
    resume_text?: string;
    resume_file?: File | null;
  }) => {
    const created = await api.submitResumeApplication(apiKey || undefined, payload);
    setApplications((prev) => [created, ...prev]);
  };

  const handleReEvaluate = async (applicationId: string) => {
    const updated = await api.reEvaluateApplication(apiKey || undefined, applicationId);
    setApplications((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
  };

  const handleSearchFile = (applicationId: string, filePath: string) => {
    setSearchAppId(applicationId);
    setSearchQuery(filePath);
    setActiveNav("search");
  };

  const scoredApps = applications.filter(
    (a) => a.status === "completed" && a.score_out_of_10 !== null
  );
  const avgScore10 =
    scoredApps.length > 0
      ? scoredApps.reduce((acc, a) => acc + (a.score_out_of_10 ?? 0), 0) / scoredApps.length
      : null;
  const shortlistedCount = applications.filter((a) => a.is_shortlisted).length;
  const inFlightCount = applications.filter(
    (a) => a.status === "pending" || a.status === "ingesting" || a.status === "evaluating"
  ).length;

  const navItems: { id: NavSection; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "jobs", label: "Jobs" },
    { id: "candidates", label: "Candidates" },
    { id: "search", label: "Code Search" },
  ];

  const showJobs = activeNav === "overview" || activeNav === "jobs";
  const showCandidates = activeNav === "overview" || activeNav === "candidates";
  const showSearch = activeNav === "overview" || activeNav === "search";

  return (
    <div className="wire-canvas min-h-screen">
      {/* Utilitarian Header */}
      <header className="wire-header sticky top-0 z-30 h-14">
        <div className="mx-auto grid h-full max-w-[1320px] grid-cols-[1fr_auto_1fr] items-center gap-3 px-4 sm:px-8">
          <div className="justify-self-start">
            <span className="display-heading text-base font-bold tracking-[0.06em] text-[var(--ink-primary)]">
              RECRUISE
            </span>
          </div>

          {/* Center Theme Switch (Light / Dark) */}
          <div className="justify-self-center">
            <button
              type="button"
              role="switch"
              aria-checked={theme === "dark"}
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              onClick={handleToggleTheme}
              className="inline-flex cursor-pointer items-center gap-2 border border-[var(--border-card)] bg-[var(--surface-bg)] px-2.5 py-1 transition-colors duration-100 hover:border-[var(--border-heavy)]"
            >
              <span
                className={`sui-spec-label hidden sm:inline ${
                  theme === "light" ? "text-[var(--ink-primary)]" : "text-[var(--ink-muted)]"
                }`}
              >
                LIGHT
              </span>
              <span
                aria-hidden="true"
                className="wire-switch-track"
                data-checked={theme === "dark" ? "true" : "false"}
              >
                <span className="wire-switch-thumb" />
              </span>
              <span
                className={`sui-spec-label hidden sm:inline ${
                  theme === "dark" ? "text-[var(--ink-primary)]" : "text-[var(--ink-muted)]"
                }`}
              >
                DARK
              </span>
              <span className="sui-spec-label sm:hidden text-[var(--ink-primary)]">
                {theme === "dark" ? "DARK" : "LIGHT"}
              </span>
            </button>
          </div>

          <div className="flex items-center justify-self-end gap-2">
            {recruiter && (
              <button
                type="button"
                onClick={() => setMcpModalOpen(true)}
                className="wire-btn h-8 px-2.5 text-[11px] uppercase tracking-[0.06em] sm:px-3"
              >
                MCP Config
              </button>
            )}

            {(recruiter || applicant) && (
              <div className="flex items-center gap-2">
                <span className="spec-mono wire-tag hidden px-2.5 py-1 text-[11px] uppercase tracking-[0.04em] md:inline">
                  {recruiter
                    ? recruiter.company.name
                    : `${formatHandle(applicant?.github_handle) || applicant?.full_name}`}
                </span>
                <button
                  type="button"
                  onClick={handleSwitchOrLogout}
                  className="wire-btn h-8 px-2.5 text-[11px] uppercase tracking-[0.06em] sm:px-3"
                >
                  Switch Role
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {!authChecked ? (
        <main className="mx-auto max-w-5xl px-4 py-20 text-center sm:px-8">
          <span className="sui-spec-label text-[var(--ink-primary)]">LOADING...</span>
        </main>
      ) : applicant ? (
        <main className="mx-auto max-w-5xl px-4 py-10 sm:px-8">
          <ApplicantDashboard profile={applicant} />
        </main>
      ) : recruiter ? (
        <main className="mx-auto max-w-[1320px] space-y-10 px-4 py-8 sm:px-8 lg:py-10">
          {/* Wireframe Tab Strip */}
          <div className="flex flex-wrap items-end justify-between gap-4 border-b-2 border-[var(--border-heavy)]">
            <nav aria-label="Workspace sections" className="flex items-center gap-0 overflow-x-auto">
              {navItems.map((item) => {
                const active = activeNav === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setActiveNav(item.id)}
                    aria-current={active ? "page" : undefined}
                    className={`spec-mono -mb-[2px] border border-b-2 px-4 py-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] whitespace-nowrap transition-colors duration-100 ${
                      active
                        ? "border-[var(--border-heavy)] bg-[var(--solid-bg)] text-[var(--solid-fg)]"
                        : "border-[var(--border-card)] border-b-[var(--border-heavy)] bg-[var(--surface-bg)] text-[var(--ink-primary)] hover:bg-[var(--surface-hover)]"
                    }`}
                  >
                    {item.label}
                  </button>
                );
              })}
            </nav>

            <span className="sui-spec-label pb-2.5 text-[var(--ink-primary)]">
              {recruiter.company.name}
            </span>
          </div>

          {/* Overview Spec Sheet Metrics */}
          {activeNav === "overview" && (
            <section aria-label="Pipeline telemetry" className="grid gap-6 lg:grid-cols-12">
              <div className="grid grid-cols-2 gap-4 lg:col-span-7">
                <div className="wire-card flex flex-col justify-between p-5 sm:p-6">
                  <div className="flex items-center justify-between gap-2">
                    <span className="sui-spec-label text-[var(--ink-primary)]">AVG SCORE</span>
                    <span className="sui-spec-label wire-tag px-1.5 py-0.5">
                      [0–10 SCALE]
                    </span>
                  </div>
                  <div className="display-heading mt-5 text-4xl font-bold tabular-nums text-[var(--ink-primary)]">
                    {avgScore10 !== null ? avgScore10.toFixed(2) : "—"}
                    {avgScore10 !== null && (
                      <span className="spec-mono ml-1.5 text-sm font-medium text-[var(--ink-muted)]">
                        / 10
                      </span>
                    )}
                  </div>
                  <div className="editorial-note mt-2 border-t border-[var(--divider-rule)] pt-2 text-xs text-[var(--ink-muted)]">
                    Claims + authorship + depth
                  </div>
                </div>

                <div className="wire-card-solid flex flex-col justify-between p-5 sm:p-6">
                  <div className="flex items-center justify-between gap-2">
                    <span className="sui-spec-label text-[var(--solid-fg)]">TOP 30% SHORTLIST</span>
                    <span className="sui-spec-label border border-[var(--solid-fg)] px-1.5 py-0.5 text-[var(--solid-fg)]">
                      [MCP READY]
                    </span>
                  </div>
                  <div className="display-heading mt-5 text-4xl font-bold tabular-nums text-[var(--solid-fg)]">
                    {shortlistedCount}
                  </div>
                  <div className="editorial-note mt-2 border-t border-[var(--solid-fg)]/30 pt-2 text-xs text-[var(--solid-fg)]/80">
                    Qualified candidates (≥ 6.0)
                  </div>
                </div>

                <div className="wire-card flex flex-col justify-between p-5 sm:p-6">
                  <span className="sui-spec-label text-[var(--ink-primary)]">ACTIVE ROLES</span>
                  <div className="display-heading mt-5 text-4xl font-bold tabular-nums text-[var(--ink-primary)]">
                    {jobs.length}
                  </div>
                  <div className="editorial-note mt-2 border-t border-[var(--divider-rule)] pt-2 text-xs text-[var(--ink-muted)]">
                    Open job rubrics
                  </div>
                </div>

                <div className="wire-card flex flex-col justify-between p-5 sm:p-6">
                  <span className="sui-spec-label text-[var(--ink-primary)]">RESUMES VETTED</span>
                  <div className="display-heading mt-5 text-4xl font-bold tabular-nums text-[var(--ink-primary)]">
                    {applications.length}
                  </div>
                  <div className="editorial-note mt-2 border-t border-[var(--divider-rule)] pt-2 text-xs text-[var(--ink-muted)]">
                    {inFlightCount > 0 ? `${inFlightCount} active in queue` : "All evaluations settled"}
                  </div>
                </div>
              </div>

              <div className="lg:col-span-5">
                <ScoreHistogramCard applications={applications} />
              </div>
            </section>
          )}

          {showJobs && (
            <JobsPanel
              jobs={jobs}
              selectedJobId={selectedJobId}
              onSelectJob={setSelectedJobId}
              onCreateJob={handleCreateJob}
            />
          )}

          {showCandidates && (
            <ApplicationsTable
              applications={applications}
              shortlistedOnly={shortlistedOnly}
              onToggleShortlistedOnly={setShortlistedOnly}
              onInspectEvidence={setInspectingApp}
              onReEvaluate={handleReEvaluate}
              onOpenSubmit={() => setSubmitModalOpen(true)}
              canSubmit={jobs.length > 0}
            />
          )}

          {showSearch && (
            <CodeSearchPanel
              apiKey={apiKey}
              applications={applications}
              selectedApplicationId={searchAppId}
              onSelectApplicationId={setSearchAppId}
              query={searchQuery}
              onQueryChange={setSearchQuery}
            />
          )}
        </main>
      ) : (
        <main className="mx-auto max-w-6xl px-4 py-10 sm:px-8 lg:py-14">
          <RoleAuthPortal
            providers={providers}
            onRecruiterAuthenticated={handleRecruiterAuthenticated}
            onApplicantAuthenticated={handleApplicantAuthenticated}
          />
        </main>
      )}

      <SubmitCandidateModal
        open={submitModalOpen}
        onClose={() => setSubmitModalOpen(false)}
        jobs={jobs}
        defaultJobId={selectedJobId}
        onSubmit={handleSubmitCandidate}
      />

      <EvidenceDialog
        application={inspectingApp}
        onClose={() => setInspectingApp(null)}
        onSearchFile={handleSearchFile}
      />

      <McpConfigDialog
        open={mcpModalOpen}
        onClose={() => setMcpModalOpen(false)}
        apiKey={apiKey}
        onApiKeyGenerated={(newKey) => {
          localStorage.setItem(STORAGE_KEY, newKey);
          setApiKey(newKey);
        }}
      />
    </div>
  );
}

export default App;

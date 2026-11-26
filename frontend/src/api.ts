import type {
  ApplicantApplication,
  ApplicantProfile,
  Application,
  ApplicationEvidenceOptions,
  AuthProviders,
  CodeSearchResponse,
  Company,
  CompanyCreateResponse,
  ConfirmClaimEvidenceItem,
  HealthStatus,
  Job,
  PublicJob,
  RecruiterProfile,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  apiKey?: string
): Promise<T> {
  const headers = new Headers(options.headers);
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (!headers.has("Content-Type") && options.body && !isFormData) {
    headers.set("Content-Type", "application/json");
  }
  if (apiKey) {
    headers.set("X-API-Key", apiKey);
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    headers,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      // ignore non-JSON error body
    }
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthStatus>("/health"),

  auth: {
    providers: () => request<AuthProviders>("/api/v1/auth/providers"),
    logoutAll: () => request<{ status: string }>("/api/v1/auth/logout-all", { method: "POST" }),

    requestMagicLink: (email: string, companyName?: string, inviteToken?: string) =>
      request<{ message: string; dev_magic_link: string | null }>(
        "/api/v1/auth/recruiter/magic-link/request",
        {
          method: "POST",
          body: JSON.stringify({
            email,
            company_name: companyName || undefined,
            invite_token: inviteToken || undefined,
          }),
        }
      ),

    verifyMagicLink: (token: string) =>
      request<RecruiterProfile>(
        `/api/v1/auth/recruiter/magic-link/verify?token=${encodeURIComponent(token)}`,
        { method: "POST" }
      ),

    getRecruiterMe: (apiKey?: string) =>
      request<RecruiterProfile>("/api/v1/auth/recruiter/me", {}, apiKey),

    rotateMcpKey: (apiKey?: string) =>
      request<{ api_key: string; company_slug: string }>(
        "/api/v1/auth/recruiter/mcp-key",
        { method: "POST" },
        apiKey
      ),

    getApplicantMe: () => request<ApplicantProfile>("/api/v1/auth/applicant/me"),

    devGitHubLogin: (payload: { github_handle: string; full_name: string; email: string }) =>
      request<ApplicantProfile>("/api/v1/auth/applicant/dev-github", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  },

  applicant: {
    listPublicJobs: () => request<PublicJob[]>("/api/v1/applicant/jobs"),
    listMyApplications: () => request<ApplicantApplication[]>("/api/v1/applicant/applications"),
    submitResume: (payload: {
      job_id: string;
      resume_text?: string;
      resume_file?: File | null;
      interactive_evidence?: boolean;
    }) => {
      if (payload.resume_file) {
        const form = new FormData();
        form.append("job_id", payload.job_id);
        form.append("resume_file", payload.resume_file);
        if (payload.resume_text?.trim()) {
          form.append("resume_text", payload.resume_text.trim());
        }
        if (payload.interactive_evidence) {
          form.append("interactive_evidence", "true");
        }
        return request<ApplicantApplication>("/api/v1/applicant/applications/upload", {
          method: "POST",
          body: form,
        });
      }
      return request<ApplicantApplication>("/api/v1/applicant/applications", {
        method: "POST",
        body: JSON.stringify({
          job_id: payload.job_id,
          resume_text: payload.resume_text ?? "",
          interactive_evidence: Boolean(payload.interactive_evidence),
        }),
      });
    },
    getEvidenceOptions: (applicationId: string) =>
      request<ApplicationEvidenceOptions>(
        `/api/v1/applicant/applications/${applicationId}/evidence-options`
      ),
    confirmEvidence: (applicationId: string, claims: ConfirmClaimEvidenceItem[]) =>
      request<ApplicantApplication>(
        `/api/v1/applicant/applications/${applicationId}/confirm-evidence`,
        {
          method: "POST",
          body: JSON.stringify({ claims }),
        }
      ),
  },

  createCompany: (name: string, slug?: string) =>
    request<CompanyCreateResponse>("/api/v1/companies", {
      method: "POST",
      body: JSON.stringify({ name, slug: slug || undefined }),
    }),

  getMyCompany: (apiKey?: string) =>
    request<Company>("/api/v1/companies/me", {}, apiKey),

  listJobs: (apiKey?: string) =>
    request<Job[]>("/api/v1/jobs", {}, apiKey),

  createJob: (apiKey: string | undefined, title: string, description: string) =>
    request<Job>(
      "/api/v1/jobs",
      {
        method: "POST",
        body: JSON.stringify({ title, description, extract_rubric_now: true, is_public: true }),
      },
      apiKey
    ),

  listApplications: (apiKey?: string, jobId?: string, shortlistedOnly = false) => {
    const params = new URLSearchParams();
    if (jobId) params.set("job_id", jobId);
    if (shortlistedOnly) params.set("shortlisted_only", "true");
    const qs = params.toString();
    return request<Application[]>(`/api/v1/applications${qs ? `?${qs}` : ""}`, {}, apiKey);
  },

  submitResumeApplication: (
    apiKey: string | undefined,
    payload: {
      job_id: string;
      full_name: string;
      email: string;
      resume_text?: string;
      resume_file?: File | null;
    }
  ) => {
    if (payload.resume_file) {
      const form = new FormData();
      form.append("job_id", payload.job_id);
      form.append("full_name", payload.full_name);
      form.append("email", payload.email);
      form.append("resume_file", payload.resume_file);
      if (payload.resume_text?.trim()) {
        form.append("resume_text", payload.resume_text.trim());
      }
      return request<Application>(
        "/api/v1/applications/upload",
        { method: "POST", body: form },
        apiKey
      );
    }

    return request<Application>(
      "/api/v1/applications",
      {
        method: "POST",
        body: JSON.stringify({
          job_id: payload.job_id,
          full_name: payload.full_name,
          email: payload.email,
          resume_text: payload.resume_text ?? "",
        }),
      },
      apiKey
    );
  },

  reEvaluateApplication: (apiKey: string | undefined, applicationId: string) =>
    request<Application>(
      `/api/v1/applications/${encodeURIComponent(applicationId)}/re-evaluate`,
      { method: "POST" },
      apiKey
    ),

  searchCandidateCode: (
    apiKey: string | undefined,
    applicationId: string,
    query: string,
    topK = 6
  ) =>
    request<CodeSearchResponse>(
      `/api/v1/applications/${encodeURIComponent(applicationId)}/search`,
      {
        method: "POST",
        body: JSON.stringify({ query, top_k: topK }),
      },
      apiKey
    ),
};

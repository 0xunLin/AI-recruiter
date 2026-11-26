export interface RubricCriterion {
  name: string;
  description: string;
  weight: number;
}

export interface RubricOutput {
  criteria: RubricCriterion[];
}

export interface CriterionEvaluation {
  criterion_name: string;
  score: number;
  justification: string;
  referenced_files: string[];
}

export interface ScoreBreakdown {
  claim_verification_score: number;
  authorship_score: number;
  technical_depth_score: number;
  total_score_out_of_10: number;
  total_claims: number;
  verified_claims: number;
  partial_claims: number;
  failed_or_dead_claims: number;
}

export interface ToolCallLogEntry {
  step: "initialize" | "plan" | "gather" | "analyse" | "format_and_seal";
  iteration: number;
  criterion_name: string | null;
  tool: string;
  target: string;
  char_offset: number;
  char_length: number;
  truncated: boolean;
  chunks_returned: number;
  note: string;
  timestamp: string;
}

export interface InterviewProbe {
  project_or_area: string;
  file_path: string | null;
  question: string;
  what_to_listen_for: string;
  risk_flag: "single_commit_dump" | "complexity" | "edge_case" | "authorship";
}

export interface EvaluationReport {
  overall_score: number;
  score_out_of_10?: number;
  score_breakdown?: ScoreBreakdown | null;
  summary: string;
  model_id?: string;
  prompt_template_version?: string;
  evidence_hash?: string | null;
  criteria_evaluations: CriterionEvaluation[];
  interview_probes?: InterviewProbe[];
}

export interface Company {
  id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface CompanyCreateResponse extends Company {
  api_key: string;
}

export interface Job {
  id: string;
  company_id: string;
  title: string;
  description: string;
  rubric: RubricOutput | null;
  status: string;
  created_at: string;
}

export interface CandidateSummary {
  id: string;
  full_name: string;
  email: string;
  github_url: string;
}

export interface RepositorySummary {
  id: string;
  repo_url: string;
  link_kind?: string;
  default_branch: string | null;
  commit_sha: string | null;
  author_identities?: string[] | null;
  status: string;
  chunk_count: number;
  ingested_at: string | null;
}

export interface ResumeSummary {
  id: string;
  filename: string;
  raw_text: string;
  extracted_links: string[] | null;
  created_at: string;
}

export interface ResumeClaim {
  id: string;
  project_title: string;
  claimed_contribution: string;
  target_url: string | null;
  link_kind: string;
  verification_status: "pending" | "verified" | "partial" | "unverified" | "dead_link";
  claim_score: number | null;
  authorship_verified: boolean;
  authorship_note: string | null;
  rationale: string | null;
  referenced_files: string[] | null;
  provenance_tier?: string;
  selected_commits?: string[] | null;
  selected_files?: string[] | null;
  ownership_question?: string | null;
  ownership_answer?: string | null;
}

export type ApplicationStatus =
  | "awaiting_evidence"
  | "pending"
  | "ingesting"
  | "evaluating"
  | "completed"
  | "failed";

export interface Application {
  id: string;
  company_id: string;
  job_id: string;
  candidate_id: string;
  status: ApplicationStatus;
  overall_score: number | null;
  score_out_of_10: number | null;
  score_breakdown: ScoreBreakdown | null;
  percentile_rank: number | null;
  is_shortlisted: boolean;
  evaluation_report: EvaluationReport | null;
  tool_call_log: ToolCallLogEntry[] | null;
  evidence_hash: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  candidate: CandidateSummary | null;
  repository: RepositorySummary | null;
  repositories?: RepositorySummary[];
  resume?: ResumeSummary | null;
  claims?: ResumeClaim[];
  job_title: string | null;
}

export interface CodeChunkMatch {
  chunk_id: string;
  file_path: string;
  symbol_name: string;
  symbol_type: string;
  language: string;
  start_line: number;
  end_line: number;
  content: string;
  similarity: number;
}

export interface CodeSearchResponse {
  application_id: string;
  query: string;
  matches: CodeChunkMatch[];
}

export interface HealthStatus {
  status: string;
  database: string;
  redis: string;
}

export interface AuthProviders {
  magic_link_enabled: boolean;
  google_oauth_enabled: boolean;
  github_oauth_enabled: boolean;
  dev_mode: boolean;
}

export interface RecruiterProfile {
  id: string;
  email: string;
  full_name: string;
  auth_provider: string;
  company: Company;
}

export interface ApplicantProfile {
  id: string;
  full_name: string;
  email: string;
  github_handle: string | null;
  github_url: string;
  verified_emails: string[];
}

export interface PublicJob {
  id: string;
  company_name: string;
  title: string;
  description: string;
  created_at: string;
}

export interface ApplicantClaimStatus {
  project_title: string;
  target_url: string | null;
  link_kind: string;
  link_status: "pending" | "accessible" | "dead_link" | "missing_link";
}

export interface ApplicantApplication {
  id: string;
  job_id: string;
  job_title: string;
  company_name: string;
  status: ApplicationStatus;
  created_at: string;
  claims: ApplicantClaimStatus[];
}

export interface CommitOption {
  sha: string;
  message: string;
  date: string;
  author: string;
}

export interface ClaimEvidenceOptions {
  claim_id: string;
  project_title: string;
  target_url: string | null;
  link_kind: string;
  provenance_tier: string;
  is_single_commit_dump: boolean;
  commits: CommitOption[];
  file_tree: string[];
  ownership_question: string;
}

export interface ApplicationEvidenceOptions {
  application_id: string;
  status: string;
  claims: ClaimEvidenceOptions[];
}

export interface ConfirmClaimEvidenceItem {
  claim_id: string;
  selected_commits: string[];
  selected_files: string[];
  ownership_answer: string;
}

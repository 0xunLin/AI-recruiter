import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Resume Extraction & Claim Verification Schemas
# ---------------------------------------------------------------------------


class ExtractedProjectClaim(BaseModel):
    """Project and contribution claim extracted from a candidate's resume."""

    project_title: str = Field(..., min_length=2, max_length=255)
    claimed_contribution: str = Field(
        ..., min_length=8, max_length=1500, description="What the candidate claims they built/contributed."
    )
    github_url: str | None = Field(
        default=None, max_length=500, description="GitHub repo, PR, or commit URL associated with this project."
    )


class ResumeExtractionOutput(BaseModel):
    """Structured extraction of project claims from untrusted resume text."""

    projects: list[ExtractedProjectClaim] = Field(default_factory=list, max_length=12)
    github_profile_url: str | None = Field(default=None, max_length=500)


class ClaimVerificationOutput(BaseModel):
    """LangGraph verdict for one resume project claim vs. actual repository/PR code."""

    verdict: Literal["verified", "partial", "unverified", "dead_link"]
    match_score: int = Field(..., ge=1, le=5, description="1=missing/contradicted, 5=fully matches claim")
    technical_depth: int = Field(..., ge=1, le=5, description="1=trivial stub, 5=production-grade architecture & tests")
    rationale: str = Field(
        ...,
        min_length=15,
        max_length=700,
        description="Two concise human-language sentences citing file paths without pasting source code.",
    )
    referenced_files: list[str] = Field(default_factory=list)
    needs_more_evidence: bool = Field(default=False)
    follow_up_hint: str | None = Field(default=None, max_length=300)


class ScoreBreakdown(BaseModel):
    """Calibrated 0-10 score breakdown preventing raw link-count gaming."""

    claim_verification_score: float = Field(..., ge=0.0, le=4.0, description="Verified claim integrity (/4.0)")
    authorship_score: float = Field(..., ge=0.0, le=2.0, description="Git commit/PR authorship proof (/2.0)")
    technical_depth_score: float = Field(..., ge=0.0, le=4.0, description="JD alignment & code depth (/4.0)")
    total_score_out_of_10: float = Field(..., ge=0.0, le=10.0)
    total_claims: int
    verified_claims: int
    partial_claims: int
    failed_or_dead_claims: int


# ---------------------------------------------------------------------------
# LangGraph Structured Output Schemas (Strict Pydantic Contracts)
# ---------------------------------------------------------------------------


class RubricCriterion(BaseModel):
    """Single criterion inside the 5-point technical evaluation rubric."""

    name: str = Field(..., min_length=3, max_length=120, description="Short technical criterion title")
    description: str = Field(..., min_length=10, max_length=500, description="What concrete code evidence to look for")
    weight: float = Field(default=0.2, ge=0.05, le=1.0, description="Normalized importance weight (sum ~= 1.0)")


class RubricOutput(BaseModel):
    """Exactly 5 criteria extracted from a Job Description."""

    criteria: list[RubricCriterion] = Field(..., min_length=5, max_length=5)

    @field_validator("criteria")
    @classmethod
    def validate_five_criteria(cls, v: list[RubricCriterion]) -> list[RubricCriterion]:
        if len(v) != 5:
            raise ValueError("Rubric must contain exactly 5 technical criteria.")
        return v


class PlanAction(BaseModel):
    """Structured planner decision in Node 2 (Plan) of the LangGraph loop."""

    action: Literal["semantic_search", "read_file", "ready_to_analyse"] = Field(
        ..., description="Next evidence-gathering action or ready_to_analyse when sufficient code has been read."
    )
    query: str | None = Field(
        default=None, max_length=300, description="Semantic search query when action == semantic_search."
    )
    file_path: str | None = Field(
        default=None, max_length=500, description="Exact file path from file_tree when action == read_file."
    )
    char_offset: int = Field(default=0, ge=0, description="Character offset for paginated reads past 15k cap.")
    reason: str = Field(default="", max_length=300, description="Short reason for this step.")


class CriterionAnalysis(BaseModel):
    """Structured evaluator decision in Node 4 (Analyse) with loop control."""

    criterion_name: str = Field(..., min_length=2, max_length=120)
    score: int = Field(..., ge=1, le=5, description="Evidence-backed score from 1 (missing) to 5 (exemplary)")
    justification: str = Field(
        ...,
        min_length=15,
        max_length=700,
        description="Two concise human-language sentences citing file paths/lines without pasting raw code.",
    )
    referenced_files: list[str] = Field(
        default_factory=list,
        description="Explicit file paths from retrieved code chunks supporting the score.",
    )
    needs_more_evidence: bool = Field(
        default=False,
        description="True if an imported file was not read yet or a [TRUNCATED] cutoff hid decisive code.",
    )
    follow_up_hint: str | None = Field(
        default=None,
        max_length=300,
        description="What specific file or character slice should be inspected next if needs_more_evidence is True.",
    )


class CriterionEvaluation(BaseModel):
    """Strict structured output persisted per criterion after guardrails."""

    criterion_name: str = Field(..., min_length=2, max_length=120)
    score: int = Field(..., ge=1, le=5, description="Evidence-backed score from 1 (missing) to 5 (exemplary)")
    justification: str = Field(
        ...,
        min_length=15,
        max_length=700,
        description="Exactly two concise sentences citing concrete code behavior and quality.",
    )
    referenced_files: list[str] = Field(
        default_factory=list,
        description="Explicit file paths from retrieved code chunks supporting the score.",
    )


class ToolCallLogEntry(BaseModel):
    """Single audit-trail card in the sealed LangGraph evidence bundle."""

    step: Literal["initialize", "plan", "gather", "analyse", "format_and_seal"]
    iteration: int
    criterion_name: str | None = None
    tool: str
    target: str
    char_offset: int = 0
    char_length: int = 0
    truncated: bool = False
    chunks_returned: int = 0
    note: str = ""
    timestamp: str


class InterviewProbe(BaseModel):
    """Code-grounded technical screen question generated to test authentic engineering ownership."""

    project_or_area: str = Field(..., min_length=2, max_length=255)
    file_path: str | None = Field(default=None, max_length=500)
    question: str = Field(..., min_length=10, max_length=500)
    what_to_listen_for: str = Field(..., min_length=10, max_length=500)
    risk_flag: Literal["single_commit_dump", "complexity", "edge_case", "authorship"] = "edge_case"


class InterviewProbesOutput(BaseModel):
    """Structured batch of anti-vibe-coding interview probes."""

    probes: list[InterviewProbe] = Field(default_factory=list, max_length=6)


class EvaluationReport(BaseModel):
    """Full evaluation report persisted to Application.evaluation_report."""

    overall_score: float = Field(..., ge=1.0, le=5.0)
    score_out_of_10: float = Field(default=0.0, ge=0.0, le=10.0)
    score_breakdown: ScoreBreakdown | None = None
    summary: str
    model_id: str = "deterministic-fallback"
    prompt_template_version: str = "v5-anti-vibe-verifier"
    evidence_hash: str | None = None
    criteria_evaluations: list[CriterionEvaluation]
    interview_probes: list[InterviewProbe] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# REST API Schemas
# ---------------------------------------------------------------------------


class CompanyCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    slug: str | None = Field(default=None, min_length=2, max_length=120)

    @field_validator("slug")
    @classmethod
    def sanitize_slug(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = re.sub(r"[^a-z0-9-]+", "-", v.lower()).strip("-")
        if len(cleaned) < 2:
            raise ValueError("Slug must contain at least 2 alphanumeric characters.")
        return cleaned


class CompanyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class CompanyCreateResponse(CompanyResponse):
    api_key: str = Field(..., description="Store securely; shown only at creation time.")


class JobCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    description: str = Field(..., min_length=20, max_length=20000)
    extract_rubric_now: bool = Field(default=True)
    is_public: bool = Field(default=True)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    title: str
    description: str
    rubric: RubricOutput | None = None
    is_public: bool = True
    status: str
    created_at: datetime


class PublicJobResponse(BaseModel):
    """Applicant-safe job listing (exposes zero internal rubric or candidate data)."""

    id: uuid.UUID
    company_name: str
    title: str
    description: str
    created_at: datetime


class AuthProvidersResponse(BaseModel):
    magic_link_enabled: bool = True
    google_oauth_enabled: bool
    github_oauth_enabled: bool
    dev_mode: bool


class MagicLinkRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    company_name: str | None = Field(default=None, min_length=2, max_length=200)
    invite_token: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def validate_email_addr(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if "@" not in cleaned or "." not in cleaned.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return cleaned


class MagicLinkResponse(BaseModel):
    message: str
    dev_magic_link: str | None = None


class RecruiterProfileResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    auth_provider: str
    company: CompanyResponse


class RecruiterInviteRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)

    @field_validator("email")
    @classmethod
    def validate_invite_email(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if "@" not in cleaned or "." not in cleaned.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return cleaned


class RecruiterInviteResponse(BaseModel):
    invite_id: uuid.UUID
    invited_email: str
    invite_token: str


class ApplicantProfileResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    github_handle: str | None = None
    github_url: str
    verified_emails: list[str] = Field(default_factory=list)


class ApplicantClaimStatusResponse(BaseModel):
    """Applicant-safe claim status (shows dead-link warnings without exposing internal scores/rubrics)."""

    project_title: str
    target_url: str | None = None
    link_kind: str
    link_status: Literal["pending", "accessible", "dead_link", "missing_link"]


class ApplicantApplicationResponse(BaseModel):
    """Applicant-safe application summary (withholds internal /10 scores and top-30% shortlist flags)."""

    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    company_name: str
    status: Literal["awaiting_evidence", "pending", "ingesting", "evaluating", "completed", "failed"]
    created_at: datetime
    claims: list[ApplicantClaimStatusResponse] = Field(default_factory=list)


class CommitOptionResponse(BaseModel):
    sha: str
    message: str
    date: str = ""
    author: str = ""


class ClaimEvidenceOptionsResponse(BaseModel):
    claim_id: uuid.UUID
    project_title: str
    target_url: str | None = None
    link_kind: str
    provenance_tier: str = "unknown"
    is_single_commit_dump: bool = False
    commits: list[CommitOptionResponse] = Field(default_factory=list)
    file_tree: list[str] = Field(default_factory=list)
    ownership_question: str


class ApplicationEvidenceOptionsResponse(BaseModel):
    application_id: uuid.UUID
    status: str
    claims: list[ClaimEvidenceOptionsResponse] = Field(default_factory=list)


class ConfirmClaimEvidenceItem(BaseModel):
    claim_id: uuid.UUID
    selected_commits: list[str] = Field(default_factory=list, max_length=10)
    selected_files: list[str] = Field(default_factory=list, max_length=15)
    ownership_answer: str = Field(default="", max_length=2500)


class ConfirmEvidenceRequest(BaseModel):
    claims: list[ConfirmClaimEvidenceItem] = Field(default_factory=list)


class DevGitHubLoginRequest(BaseModel):
    github_handle: str = Field(..., min_length=2, max_length=100)
    full_name: str = Field(..., min_length=2, max_length=200)
    email: str = Field(..., min_length=5, max_length=320)


class ApplicationCreateRequest(BaseModel):
    job_id: uuid.UUID
    full_name: str = Field(..., min_length=2, max_length=200)
    email: str = Field(..., min_length=5, max_length=320)
    resume_text: str = Field(..., min_length=30, max_length=80000)
    repo_url: str | None = Field(default=None, max_length=500)

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if "@" not in cleaned or "." not in cleaned.split("@")[-1]:
            raise ValueError("Invalid email address.")
        return cleaned

    @field_validator("repo_url")
    @classmethod
    def validate_optional_github_url(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        cleaned = v.strip().rstrip("/")
        if not re.match(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(\.git)?$", cleaned):
            raise ValueError("Repository URL must be a valid public https://github.com/<owner>/<repo> URL.")
        return cleaned


class RepositorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repo_url: str
    link_kind: str = "repo"
    default_branch: str | None = None
    commit_sha: str | None = None
    author_identities: list[str] | None = None
    provenance_tier: str = "unknown"
    commit_count: int | None = None
    status: str
    chunk_count: int
    ingested_at: datetime | None = None


class ResumeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    raw_text: str
    extracted_links: list[str] | None = None
    created_at: datetime


class ResumeClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_title: str
    claimed_contribution: str
    target_url: str | None = None
    link_kind: str
    verification_status: str
    claim_score: float | None = None
    authorship_verified: bool
    authorship_note: str | None = None
    rationale: str | None = None
    referenced_files: list[str] | None = None
    provenance_tier: str = "unknown"
    selected_commits: list[str] | None = None
    selected_files: list[str] | None = None
    ownership_question: str | None = None
    ownership_answer: str | None = None


class CandidateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    github_url: str


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    status: Literal["awaiting_evidence", "pending", "ingesting", "evaluating", "completed", "failed"]
    overall_score: float | None = None
    score_out_of_10: float | None = None
    score_breakdown: ScoreBreakdown | None = None
    percentile_rank: float | None = None
    is_shortlisted: bool = False
    evaluation_report: EvaluationReport | None = None
    tool_call_log: list[ToolCallLogEntry] | None = None
    evidence_hash: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    candidate: CandidateSummary | None = None
    repository: RepositorySummary | None = None
    repositories: list[RepositorySummary] = Field(default_factory=list)
    resume: ResumeSummary | None = None
    claims: list[ResumeClaimResponse] = Field(default_factory=list)
    job_title: str | None = None


class CodeSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)


class CodeChunkMatch(BaseModel):
    chunk_id: uuid.UUID
    file_path: str
    symbol_name: str
    symbol_type: str
    language: str
    start_line: int
    end_line: int
    content: str
    similarity: float


class CodeSearchResponse(BaseModel):
    application_id: uuid.UUID
    query: str
    matches: list[CodeChunkMatch]


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str

import os
import logging
from typing import TypedDict
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END

from app.database import SessionLocal
from app.models import Job, Application
from app.retrieval import search_candidate_code

from app.rate_limiter import acquire_rate_limit

load_dotenv()
logger = logging.getLogger(__name__)

# Flagship production model on GroqCloud supporting strict json_schema outputs
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# ==========================================
# 1. PYDANTIC STRUCTURED OUTPUT SCHEMAS
# ==========================================

class RubricExtraction(BaseModel):
    """5-point technical rubric extracted from a raw Job Description."""
    criteria: list[str] = Field(
        description="Exactly 5 specific, code-verifiable technical criteria extracted from the Job Description."
    )


class CriterionEvaluation(BaseModel):
    """Strict evaluation output for a single rubric criterion backed by file evidence."""
    score: int = Field(
        ge=1,
        le=5,
        description="Integer score from 1 (no evidence/poor) to 5 (strong production-grade evidence in code)."
    )
    justification: str = Field(
        description="A concise, 2-sentence technical justification explaining the score based strictly on the retrieved code."
    )
    referenced_files: list[str] = Field(
        description="List of exact file_path strings from the retrieved code chunks used as evidence."
    )

# ==========================================
# 2. LANGGRAPH STATE DEFINITION
# ==========================================

class EvaluationState(TypedDict):
    company_id: int
    job_id: int
    candidate_id: int
    job_description: str
    rubric: list[str]
    current_index: int
    evaluations: list[dict]
    final_score: int


def _get_llm() -> ChatGroq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "gsk_your_actual_groq_key_here":
        raise ValueError("GROQ_API_KEY is missing or invalid in your .env file!")
    return ChatGroq(
        model=GROQ_MODEL,
        temperature=0.0,  # Deterministic grading
        api_key=api_key,
    )


# ==========================================
# 3. LANGGRAPH NODES
# ==========================================

def extract_rubric_node(state: EvaluationState) -> dict:
    """
    Node 1: Extracts a 5-point technical rubric from the Job Description,
    or reuses the cached rubric if the Job row already has one stored.
    """
    if state.get("rubric") and len(state["rubric"]) == 5:
        logger.info("Reusing existing 5-point rubric from Job record.")
        return {"current_index": 0, "evaluations": []}

    llm = _get_llm()
    structured_llm = llm.with_structured_output(
        RubricExtraction,
        method="json_schema",
        strict=True,
    )

    messages = [
        SystemMessage(
            content=(
                "You are a Staff Software Engineer creating an evidence-based code grading rubric. "
                "Extract exactly 5 distinct, code-verifiable technical requirements from the Job Description. "
                "Phrase each criterion so it can be searched against a GitHub repository's source code."
            )
        ),
        HumanMessage(content=f"Job Description:\n{state['job_description']}"),
    ]

    # Groq free developer tier allows 30 RPM; keep safety margin at 25 RPM / 15,000 TPM
    acquire_rate_limit("groq", rpm_limit=25, tpm_limit=15_000, estimated_tokens=1200)

    result: RubricExtraction = structured_llm.invoke(messages)
    criteria = result.criteria[:5]

    return {
        "rubric": criteria,
        "current_index": 0,
        "evaluations": [],
    }


def evaluate_criterion_node(state: EvaluationState) -> dict:
    """
    Node 2: Queries pgvector for the current rubric criterion (enforcing tenant isolation)
    and grades the retrieved AST chunks using structured output.
    """
    idx = state["current_index"]
    criterion = state["rubric"][idx]
    logger.info(f"Evaluating criterion [{idx + 1}/{len(state['rubric'])}]: {criterion}")

    # 1. Retrieve top relevant AST code chunks via our tenant-isolated SQL + pgvector search
    db = SessionLocal()
    try:
        chunks = search_candidate_code(
            db=db,
            company_id=state["company_id"],
            job_id=state["job_id"],
            candidate_id=state["candidate_id"],
            query_text=criterion,
            top_k=4,
        )
    finally:
        db.close()

    # 2. Format retrieved code evidence for the LLM
    if not chunks:
        evidence_block = "No relevant code chunks found in candidate repositories."
    else:
        evidence_block = "\n\n---\n\n".join(
            f"File Path: {c.file_path} (Cosine Similarity: {c.similarity})\n{c.content}"
            for c in chunks
        )

    # 3. Grade with Groq using strict JSON Schema output
    llm = _get_llm()
    structured_llm = llm.with_structured_output(
        CriterionEvaluation,
        method="json_schema",
        strict=True,
    )

    messages = [
        SystemMessage(
            content=(
                "You are an objective, evidence-based technical code evaluator. "
                "Evaluate the candidate's actual source code against the specified rubric criterion. "
                "Rules:\n"
                "1. Score from 1 to 5 strictly based on the provided code chunks.\n"
                "2. Write a concise, 2-sentence technical justification citing specific functions, classes, or patterns.\n"
                "3. Only include file paths in 'referenced_files' that actually appear in the retrieved evidence."
            )
        ),
        HumanMessage(
            content=(
                f"Rubric Criterion ({idx + 1}/5): {criterion}\n\n"
                f"Retrieved Candidate Code Evidence:\n{evidence_block}"
            )
        ),
    ]

    # Groq free developer tier allows 30 RPM; keep safety margin at 25 RPM / 15,000 TPM
    acquire_rate_limit("groq", rpm_limit=25, tpm_limit=15_000, estimated_tokens=1200)
    
    eval_result: CriterionEvaluation = structured_llm.invoke(messages)

    updated_evaluations = list(state["evaluations"])
    updated_evaluations.append(
        {
            "criterion": criterion,
            "score": eval_result.score,
            "justification": eval_result.justification,
            "referenced_files": eval_result.referenced_files,
        }
    )

    return {
        "evaluations": updated_evaluations,
        "current_index": idx + 1,
    }


def aggregate_score_node(state: EvaluationState) -> dict:
    """
    Node 3: Calculates the final percentage score (0-100) from the five 1-5 rubric scores.
    Each criterion is worth up to 5 points (max 25 points total -> scaled to 100).
    """
    evals = state["evaluations"]
    if not evals:
        return {"final_score": 0}

    total_points = sum(item["score"] for item in evals)
    max_points = len(evals) * 5
    scaled_score = round((total_points / max_points) * 100)

    return {"final_score": scaled_score}

# ==========================================
# 4. CONDITIONAL ROUTING & GRAPH COMPILATION
# ==========================================

def should_continue(state: EvaluationState) -> str:
    """Loops back to evaluate_criterion_node until all 5 rubric items are graded."""
    if state["current_index"] < len(state["rubric"]):
        return "evaluate_criterion"
    return "aggregate_score"


workflow = StateGraph(EvaluationState)
workflow.add_node("extract_rubric", extract_rubric_node)
workflow.add_node("evaluate_criterion", evaluate_criterion_node)
workflow.add_node("aggregate_score", aggregate_score_node)

workflow.set_entry_point("extract_rubric")
workflow.add_edge("extract_rubric", "evaluate_criterion")
workflow.add_conditional_edges(
    "evaluate_criterion",
    should_continue,
    {
        "evaluate_criterion": "evaluate_criterion",
        "aggregate_score": "aggregate_score",
    },
)
workflow.add_edge("aggregate_score", END)

# Compile into a reusable runnable graph
evaluator_graph = workflow.compile()


# ==========================================
# 5. DATABASE ORCHESTRATION HELPER
# ==========================================

def run_candidate_evaluation(application_id: int) -> dict:
    """
    Loads the Application, Job, and Company context from Postgres,
    executes the LangGraph evaluation loop, and persists the rubric & score.
    """
    db = SessionLocal()
    try:
        app_record = db.query(Application).filter(Application.id == application_id).first()
        if not app_record:
            raise ValueError(f"Application ID {application_id} not found.")

        job = db.query(Job).filter(Job.id == app_record.job_id).first()

        initial_state: EvaluationState = {
            "company_id": job.company_id,
            "job_id": job.id,
            "candidate_id": app_record.candidate_id,
            "job_description": job.description,
            "rubric": job.rubric if isinstance(job.rubric, list) else [],
            "current_index": 0,
            "evaluations": [],
            "final_score": 0,
        }

        final_state = evaluator_graph.invoke(initial_state)

        # Persist the extracted rubric on the Job (if not already saved) and the score on the Application
        if not job.rubric:
            job.rubric = final_state["rubric"]
        app_record.evaluation_score = final_state["final_score"]
        app_record.evaluation_report = final_state["evaluations"]
        db.commit()
        
        return {
            "application_id": application_id,
            "final_score": final_state["final_score"],
            "rubric": final_state["rubric"],
            "evaluations": final_state["evaluations"],
        }
    finally:
        db.close()
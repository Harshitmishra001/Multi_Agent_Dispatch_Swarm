from typing import List, Optional
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import PydanticOutputParser

from backend.schemas.models import DispatchPlan, VerifiedNeed, EvaluationResult, UrgencyLevel
from backend.config.model_router import get_llm
from backend.config.settings import settings

class LLMEvaluation(BaseModel):
    fairness_score: float = Field(ge=0.0, le=1.0, description="A score from 0.0 to 1.0 assessing if resources are fairly distributed geographically.")
    passed: bool = Field(description="True if the plan is acceptable and can be released. False if it needs revision.")
    rationale: str = Field(description="Explanation of the evaluation.")
    revision_notes: Optional[str] = Field(description="If passed is False, specific instructions to the Resource Matcher on how to fix the plan. You MUST use the exact need_id for any needs you mention.")

class EvaluatorAgent:
    def __init__(self):
        # Uses the "strong" tier as defined in the spec, pointing to local for now
        self.llm = get_llm("strong", temperature=0.1)
        self.parser = PydanticOutputParser(pydantic_object=LLMEvaluation)
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a senior emergency dispatcher evaluating an allocation plan.
You have the final say on whether a plan is released to the field or sent back for revision.

{format_instructions}"""),
            ("user", "Plan Narrative:\n{narrative}\n\nMetrics:\nCoverage: {coverage_pct}%\nCritical Unmet Needs: {critical_unmet}")
        ])
        
        self.chain = self.prompt | self.llm | self.parser

    def process(self, plan: DispatchPlan, all_needs: List[VerifiedNeed]) -> EvaluationResult:
        # 1. Deterministic Calculations (Ground Truth)
        total_qty_needed = sum(n.quantity_estimate for n in all_needs)
        total_qty_allocated = sum(a.quantity_allocated for a in plan.allocations)
        
        coverage_pct = 0.0
        if total_qty_needed > 0:
            coverage_pct = round((total_qty_allocated / total_qty_needed) * 100.0, 1)
            
        critical_unmet_count = 0
        unmet_need_ids = set(plan.unmet_needs)
        for n in all_needs:
            if n.need_id in unmet_need_ids and n.urgency == UrgencyLevel.CRITICAL:
                critical_unmet_count += 1
                
        # 2. Qualitative LLM Call
        try:
            llm_eval = self.chain.invoke({
                "narrative": plan.narrative,
                "coverage_pct": coverage_pct,
                "critical_unmet": critical_unmet_count,
                "format_instructions": self.parser.get_format_instructions()
            })
            try:
                from backend.metrics import LLM_REQUESTS
                LLM_REQUESTS.labels(tier="strong", status="success").inc()
            except Exception:
                pass
            
            # If there are critical unmet needs but overall coverage is low, we might 
            # allow it because of physical lack of resources, but the LLM decides.
            
            return EvaluationResult(
                plan_id=plan.plan_id,
                coverage_pct=coverage_pct,
                critical_unmet_count=critical_unmet_count,
                fairness_score=llm_eval.fairness_score,
                passed=llm_eval.passed,
                rationale=llm_eval.rationale,
                revision_notes=llm_eval.revision_notes
            )
            
        except Exception as e:
            # Fallback for LLM failure
            print(f"Evaluator LLM error: {e}")
            try:
                from backend.metrics import LLM_REQUESTS, LLM_FALLBACKS
                LLM_REQUESTS.labels(tier="strong", status="error").inc()
                LLM_FALLBACKS.inc()
            except Exception:
                pass
            passed = critical_unmet_count == 0 # Simplest fallback heuristic
            return EvaluationResult(
                plan_id=plan.plan_id,
                coverage_pct=coverage_pct,
                critical_unmet_count=critical_unmet_count,
                fairness_score=settings.DEFAULT_FAIRNESS_SCORE,
                passed=passed,
                rationale="Fallback evaluation due to system error.",
                revision_notes="Please manually review." if not passed else None
            )

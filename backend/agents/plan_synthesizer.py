import uuid
import re
from datetime import datetime, timezone
from typing import List

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import StrOutputParser

from backend.schemas.models import Allocation, DispatchPlan, VerifiedNeed
from backend.config.model_router import get_llm
from backend.metrics import LLM_REQUESTS

class PlanSynthesizer:
    def __init__(self):
        self.llm = get_llm("local", temperature=0.3)
        self.parser = StrOutputParser()
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a dispatch plan synthesizer.
Your job is to write a human-readable narrative summary of the current allocation plan.
You are given a list of allocations and a list of unmet needs.

CRITICAL CONSTRAINTS:
1. Do NOT hallucinate any need IDs or resource IDs that are not present in the provided lists.
2. Unmet needs MUST be stated plainly, do not minimize or omit them.
3. Keep it professional, concise, and structured.
"""),
            ("user", "Allocations:\n{allocations}\n\nUnmet Needs (Need IDs):\n{unmet_needs}")
        ])
        self.chain = self.prompt | self.llm | self.parser

    def _verify_grounding(self, narrative: str, valid_need_ids: set, valid_resource_ids: set) -> bool:
        """
        Extracts all potential IDs from the narrative and checks if they exist in our valid sets.
        Assuming our IDs start with 'need-' or 'res-', or similar alphanumeric strings.
        For safety, we'll scan for any sequence that looks like an ID if we used a specific format.
        Since we don't strictly enforce ID formats yet, we'll just check that if the narrative explicitly 
        says "need-..." or "res-...", it belongs to the valid sets.
        """
        # Find all words containing hyphens that might be IDs (e.g. need-123, res-456)
        potential_ids = re.findall(r'\b(?:need|res|rpt)-[A-Za-z0-9-]+\b', narrative.lower())
        
        valid_lower = {vid.lower() for set_ids in (valid_need_ids, valid_resource_ids) for vid in set_ids}
        
        for pid in potential_ids:
            if pid not in valid_lower:
                return False
        return True

    def process(self, allocations: List[Allocation], unmet_needs: List[str]) -> DispatchPlan:
        # Build prompt context
        alloc_str = "\n".join([f"- Allocate {a.quantity_allocated} from {a.resource_id} to {a.need_id} (Distance: {a.distance_km}km)" for a in allocations])
        unmet_str = "\n".join([f"- {un}" for un in unmet_needs]) if unmet_needs else "None"
        
        valid_need_ids = set(a.need_id for a in allocations).union(set(unmet_needs))
        valid_resource_ids = set(a.resource_id for a in allocations)
        
        narrative = "Fallback plan summary generated due to error."
        
        for attempt in range(3):
            try:
                result_text = self.chain.invoke({
                    "allocations": alloc_str or "None",
                    "unmet_needs": unmet_str
                })
                LLM_REQUESTS.labels(tier="local", status="success").inc()

                # Check grounding
                if self._verify_grounding(result_text, valid_need_ids, valid_resource_ids):
                    narrative = result_text
                    break
                else:
                    print(f"Grounding failure on attempt {attempt+1}")
            except Exception as e:
                LLM_REQUESTS.labels(tier="local", status="error").inc()
                print(f"LLM failure on attempt {attempt+1}: {e}")
        
        if narrative == "Fallback plan summary generated due to error." and (allocations or unmet_needs):
            # Absolute fallback
            narrative = f"System processed {len(allocations)} allocations. {len(unmet_needs)} needs remain unmet."

        return DispatchPlan(
            plan_id=f"plan-{uuid.uuid4().hex[:8]}",
            generated_at=datetime.now(timezone.utc),
            allocations=allocations,
            unmet_needs=unmet_needs,
            narrative=narrative
        )

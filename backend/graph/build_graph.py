from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3

from backend.graph.state import CoordinatorState
from backend.schemas.models import ResourceRecord

from backend.agents.ingestion_agent import IngestionAgent
from backend.agents.verification_agent import VerificationAgent
from backend.agents.resource_matcher import ResourceMatcher
from backend.agents.plan_synthesizer import PlanSynthesizer
from backend.agents.evaluator_agent import EvaluatorAgent
from backend.utils.logger import get_audit_logger

# Module-level persistent checkpointer — survives server restarts.
# check_same_thread=False is required because FastAPI BackgroundTasks run on
# different threads from the main request thread.
_checkpoint_conn = sqlite3.connect("./langgraph_checkpoints.db", check_same_thread=False)
_checkpointer = SqliteSaver(_checkpoint_conn)

def build_coordinator_graph():
    # Instantiate agents
    ingest_agent = IngestionAgent()
    verify_agent = VerificationAgent()
    match_agent = ResourceMatcher()
    synth_agent = PlanSynthesizer()
    eval_agent = EvaluatorAgent()
    audit_logger = get_audit_logger()
    
    # Node functions
    def ingest_node(state: CoordinatorState):
        extracted = ingest_agent.process(state["raw_report"])
        audit_logger.info("Ingestion complete", extra={"action": "ingest", "report_id": state["raw_report"].report_id})
        return {"extracted_need": extracted}
        
    def verify_node(state: CoordinatorState):
        verified = verify_agent.process(state["extracted_need"], state.get("existing_needs", []))
        audit_logger.info("Verification complete", extra={"action": "verify", "need_id": verified.need_id})
        return {
            "verified_need": verified,
            "requires_human_review": verified.requires_human_review
        }
        
    def human_review_node(state: CoordinatorState):
        # This node acts as a pause point. In a real system, the reviewer updates the state.
        # Here we just clear the flag and pass it through, simulating approval.
        # The actual pause is handled by LangGraph's interrupt mechanism.
        verified = state["verified_need"]
        verified.requires_human_review = False
        return {
            "verified_need": verified,
            "requires_human_review": False
        }
        
    def match_node(state: CoordinatorState):
        # Gather all needs: existing + the newly verified one
        needs = list(state.get("existing_needs", []))
        if state.get("verified_need"):
            needs.append(state["verified_need"])
            
        revision_notes = None
        evaluation = state.get("evaluation")
        if evaluation and not evaluation.passed:
            revision_notes = evaluation.revision_notes
            
        allocs = match_agent.process(needs, state.get("available_resources", []), revision_notes=revision_notes)
        audit_logger.info("Matching complete", extra={"action": "match", "allocations_count": len(allocs)})
        return {"allocations": allocs}
        
    def synth_node(state: CoordinatorState):
        # Calculate unmet needs
        needs = list(state.get("existing_needs", []))
        if state.get("verified_need"):
            needs.append(state["verified_need"])
            
        allocs = state.get("allocations", [])
        allocated_needs = set(a.need_id for a in allocs)
        unmet = [n.need_id for n in needs if n.need_id not in allocated_needs]
        
        plan = synth_agent.process(allocs, unmet)
        return {"plan": plan}
        
    def eval_node(state: CoordinatorState):
        needs = list(state.get("existing_needs", []))
        if state.get("verified_need"):
            needs.append(state["verified_need"])
            
        result = eval_agent.process(state["plan"], needs)
        new_rev_count = state.get("revision_count", 0) + 1
        audit_logger.info("Evaluation complete", extra={"action": "evaluate", "passed": result.passed, "fairness": result.fairness_score})
        return {
            "evaluation": result,
            "revision_count": new_rev_count
        }

    # Edges
    def verify_edges(state: CoordinatorState):
        if state.get("requires_human_review"):
            return "human_review"
        return "match"
        
    def eval_edges(state: CoordinatorState):
        ev = state.get("evaluation")
        rev = state.get("revision_count", 0)
        if not ev.passed and rev < 2:
            return "match"
        return END

    # Graph construction
    workflow = StateGraph(CoordinatorState)
    
    workflow.add_node("ingest", ingest_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("human_review", human_review_node)
    workflow.add_node("match", match_node)
    workflow.add_node("synthesize", synth_node)
    workflow.add_node("evaluate", eval_node)
    
    workflow.set_entry_point("ingest")
    
    workflow.add_edge("ingest", "verify")
    workflow.add_conditional_edges("verify", verify_edges)
    workflow.add_edge("human_review", "match")
    workflow.add_edge("match", "synthesize")
    workflow.add_edge("synthesize", "evaluate")
    workflow.add_conditional_edges("evaluate", eval_edges)
    
    # Use the module-level SqliteSaver so interrupted human-review threads
    # survive server restarts (replaces the old in-memory MemorySaver).
    app = workflow.compile(checkpointer=_checkpointer, interrupt_before=["human_review"])
    
    return app

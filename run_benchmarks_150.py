"""
Full-scale benchmark: 150 synthetic emergency reports (Resumable).
- Auto-resumes human-in-the-loop (HITL) interrupts as a simulated reviewer.
- Tests ILP allocator + Qdrant duplicate detection at scale.
- Saves incrementally to benchmark_results_150.json to allow resuming.
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import asyncio
import time
import uuid
import json
import os
import shutil
from datetime import datetime, timezone
from backend.db.models import SessionLocal, DBResource, init_db
from backend.schemas.models import RawReport, ResourceRecord, NeedType, VerifiedNeed
from backend.graph.build_graph import build_coordinator_graph

# ---------------------------------------------------------------------------
# Seed data helpers
# ---------------------------------------------------------------------------

def get_db_resources():
    db = SessionLocal()
    records = []
    for r in db.query(DBResource).all():
        records.append(ResourceRecord(
            resource_id=r.resource_id,
            resource_type=NeedType(r.resource_type),
            quantity_available=r.quantity_available,
            location=(r.lat, r.lon),
            status=r.status
        ))
    db.close()
    return records


def seed_resources_if_empty():
    init_db()
    db = SessionLocal()
    # Upsert all benchmark depots — adds missing ones, leaves existing untouched
    desired = [
        DBResource(resource_id="res-water-01",   resource_type="water",   quantity_available=500,  lat=34.05,  lon=-118.25, status="available"),
        DBResource(resource_id="res-water-02",   resource_type="water",   quantity_available=200,  lat=34.06,  lon=-118.24, status="available"),
        DBResource(resource_id="res-water-03",   resource_type="water",   quantity_available=300,  lat=34.03,  lon=-118.23, status="available"),
        DBResource(resource_id="res-medical-01", resource_type="medical", quantity_available=50,   lat=34.04,  lon=-118.26, status="available"),
        DBResource(resource_id="res-medical-02", resource_type="medical", quantity_available=75,   lat=34.08,  lon=-118.22, status="available"),
        DBResource(resource_id="res-shelter-01", resource_type="shelter", quantity_available=100,  lat=34.07,  lon=-118.27, status="available"),
        DBResource(resource_id="res-shelter-02", resource_type="shelter", quantity_available=150,  lat=34.09,  lon=-118.28, status="available"),
        DBResource(resource_id="res-food-01",    resource_type="food",    quantity_available=1000, lat=34.055, lon=-118.255, status="available"),
        DBResource(resource_id="res-food-02",    resource_type="food",    quantity_available=500,  lat=34.045, lon=-118.245, status="available"),
        DBResource(resource_id="res-rescue-01",  resource_type="rescue",  quantity_available=20,   lat=34.06,  lon=-118.26, status="available"),
    ]
    existing_ids = {r.resource_id for r in db.query(DBResource).all()}
    new_entries = [r for r in desired if r.resource_id not in existing_ids]
    if new_entries:
        print(f"Adding {len(new_entries)} new resource depots to DB...")
        db.add_all(new_entries)
        db.commit()
    count = db.query(DBResource).count()
    print(f"Resource DB: {count} depots total.")
    db.close()
    return count

# ---------------------------------------------------------------------------
# 150 synthetic report corpus
# ---------------------------------------------------------------------------

CLEAN_TEMPLATES = [
    ("URGENT: {n} people trapped at {loc}. Need water immediately.", "water", "critical"),
    ("Water supply cut off for {n} residents near {loc}. Requesting emergency water.", "water", "high"),
    ("We have {n} patients at {loc} hospital with no clean water.", "water", "critical"),
    ("Flooding at {loc} has contaminated water supply for {n} families.", "water", "high"),
    ("Dehydration risk for {n} elderly at {loc} care home. Water needed.", "water", "high"),
    ("{n} school children at {loc} Elementary without drinking water.", "water", "moderate"),
    ("Water tanker needed at {loc} camp. {n} displaced persons.", "water", "critical"),
    ("Borehole failed at {loc}. {n} villagers have no water source.", "water", "high"),
    ("Medical supplies needed at {loc} Clinic. {n} injured people.", "medical", "critical"),
    ("{n} wounded at {loc}. Requesting paramedics and first aid.", "medical", "critical"),
    ("Shortage of insulin and bandages at {loc} health post. {n} patients affected.", "medical", "high"),
    ("Dialysis unit at {loc} hospital needs emergency supplies for {n} patients.", "medical", "critical"),
    ("Burns cases at {loc}. {n} people need immediate medical attention.", "medical", "critical"),
    ("Maternity ward at {loc} needs blood supply. {n} women in labor.", "medical", "critical"),
    ("{n} elderly people at {loc} need prescription medication refills urgently.", "medical", "high"),
    ("Outbreak suspected at {loc}. {n} people showing symptoms. Medical team needed.", "medical", "high"),
    ("Need shelter for {n} families after the flood on {loc}.", "shelter", "high"),
    ("Fire destroyed {n} homes in {loc}. Families need emergency accommodation.", "shelter", "critical"),
    ("{n} refugees arrived at {loc} border with no shelter.", "shelter", "high"),
    ("Earthquake damaged {n} structures in {loc}. Residents displaced.", "shelter", "critical"),
    ("Winter is severe. {n} homeless people at {loc} need warm shelter.", "shelter", "high"),
    ("Landslide at {loc} destroyed {n} homes overnight.", "shelter", "critical"),
    ("Camp at {loc} is overcrowded. {n} additional people arrived today.", "shelter", "moderate"),
    ("{n} families evacuated from {loc} due to chemical leak. Need temporary shelter.", "shelter", "high"),
    ("Send food for {n} people at {loc} gym. It's critical.", "food", "critical"),
    ("{n} children at {loc} haven't eaten in two days.", "food", "critical"),
    ("Food distribution point at {loc} has run out. {n} people waiting.", "food", "high"),
    ("Elderly residents at {loc} nursing home need meal delivery for {n} people.", "food", "high"),
    ("{n} workers stranded at {loc} construction site need food.", "food", "moderate"),
    ("School feeding program at {loc} suspended. {n} students affected.", "food", "high"),
    ("Bread shortage at {loc}. {n} families queuing with no rations.", "food", "high"),
    ("Pregnant women at {loc} camp need nutrition supplements. Approx {n} people.", "food", "high"),
    ("{n} people trapped under rubble at {loc} after building collapse.", "rescue", "critical"),
    ("Swift water rescue needed at {loc}. {n} people stranded on rooftops.", "rescue", "critical"),
    ("{n} hikers lost in {loc} forest. Search and rescue required.", "rescue", "high"),
    ("Cave-in at {loc} mine. {n} workers trapped underground.", "rescue", "critical"),
    ("{n} people cut off by landslide on {loc} road.", "rescue", "high"),
    ("Boats needed for {n} people stranded at {loc} island after storm.", "rescue", "critical"),
    ("{n} elderly immobile residents at {loc} need evacuation assistance.", "rescue", "high"),
    ("Gas explosion at {loc}. {n} people unaccounted for. Search teams needed.", "rescue", "critical"),
]

LOCATIONS = [
    "Main St Clinic", "Elm Street", "Southside Hospital", "Community Center",
    "High School Gym", "Downtown Area", "Riverside District", "North Station",
    "Oak Avenue", "Harbor View", "Central Park", "Mission District",
    "Westside Campus", "Lakefront Drive", "Valley Road", "Hillcrest",
    "Maple Grove", "Sunset Blvd", "Airport Terminal", "Industrial Zone",
]

QUANTITIES = [10, 15, 20, 25, 30, 40, 50, 60, 75, 100, 120, 150, 200]

AMBIGUOUS = [
    ("We need stuff at the place!", "ambiguous"),
    ("Can someone help us? It's really bad here.", "ambiguous"),
    ("Send whatever you have to the downtown area.", "ambiguous"),
    ("People are hungry and thirsty everywhere.", "ambiguous"),
    ("Help!", "ambiguous"),
    ("Things are getting worse by the minute.", "ambiguous"),
    ("Emergency at the usual spot.", "ambiguous"),
    ("Need help NOW!!!", "ambiguous"),
    ("We called before, still no one came.", "ambiguous"),
    ("The situation here is deteriorating fast.", "ambiguous"),
    ("Can you dispatch someone? You know where we are.", "ambiguous"),
    ("Everything is gone. Please send assistance.", "ambiguous"),
    ("People are suffering. Do something.", "ambiguous"),
    ("We need resources. Urgent.", "ambiguous"),
    ("Someone is hurt, come quick.", "ambiguous"),
]

def build_corpus():
    import random
    rng = random.Random(42)  
    corpus = []
    clean_pool = []
    
    # 60 clean
    for i in range(60):
        template, need_type, urgency = CLEAN_TEMPLATES[i % len(CLEAN_TEMPLATES)]
        loc = LOCATIONS[i % len(LOCATIONS)]
        n   = QUANTITIES[i % len(QUANTITIES)]
        text = template.format(n=n, loc=loc)
        clean_pool.append({"text": text, "type": "clean"})
    corpus.extend(clean_pool)

    # 40 ambiguous
    for i in range(40):
        item = AMBIGUOUS[i % len(AMBIGUOUS)]
        corpus.append({"text": item[0], "type": "ambiguous"})

    # 30 near-duplicates
    paraphrase_transforms = [
        lambda t: t.replace("Need", "Require").replace("need", "require"),
        lambda t: "FOLLOW-UP: " + t,
        lambda t: t.replace("immediately", "ASAP").replace("urgent", "emergency"),
        lambda t: t + " Please respond.",
        lambda t: t.replace("people", "persons").replace("People", "Persons"),
        lambda t: "UPDATE: " + t,
    ]
    for i in range(30):
        base = clean_pool[i % len(clean_pool)]["text"]
        transform = paraphrase_transforms[i % len(paraphrase_transforms)]
        corpus.append({"text": transform(base), "type": "near_duplicate"})

    # 20 exact duplicates
    for i in range(20):
        base = clean_pool[i % len(clean_pool)]["text"]
        corpus.append({"text": base, "type": "exact_duplicate"})

    rng.shuffle(corpus)
    return corpus

def hitl_decision(verified_need, report_type: str):
    if verified_need and verified_need.duplicate_of:
        return "reject"
    return "approve"

async def run_benchmarks():
    CHECKPOINT_FILE = "benchmark_results_150.json"
    corpus = build_corpus()
    total = len(corpus)
    db_size = seed_resources_if_empty()
    resources = get_db_resources()

    if os.path.exists(CHECKPOINT_FILE):
        print(f"Resuming from {CHECKPOINT_FILE}...")
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
        results = saved_data["results"]
        history_needs = [VerifiedNeed(**n) for n in saved_data["history_needs"]]
        start_index = len(results["per_report"])
        print(f"Resuming at index {start_index} with {len(history_needs)} history needs.")
    else:
        print("Starting fresh benchmark. Wiping old Qdrant data to prevent contamination...")
        shutil.rmtree("./qdrant_data", ignore_errors=True)
        start_index = 0
        history_needs = []
        results = {
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
            "model": "smollm3-3b @ LM Studio",
            "total_reports": total,
            "db_resources": db_size,
            "auto_approved": 0,
            "hitl_routed": 0,
            "hitl_approved_by_reviewer": 0,
            "hitl_rejected_by_reviewer": 0,
            "hitl_reasons": {"low_confidence": 0, "duplicate": 0},
            "duplicates_caught": 0,
            "exact_duplicates_in_set": 20,
            "near_duplicates_in_set": 30,
            "errors": 0,
            "latencies_s": [],
            "evaluator_passed_first_try": 0,
            "evaluator_needed_retry": 0,
            "evaluator_hit_max_retries": 0,
            "coverage_scores": [],
            "fairness_scores": [],
            "per_report": [],
        }

    if start_index >= total:
        print("Benchmark already complete.")
        return

    # Build graph AFTER clearing qdrant so it initializes a fresh DB
    graph = build_coordinator_graph()

    print(f"\nProcessing {total - start_index} reports...")
    print("=" * 60)

    for i, report_meta in enumerate(corpus[start_index:], start=start_index):
        report_obj = RawReport(
            report_id=f"bench-{uuid.uuid4().hex[:8]}",
            source_channel="sms",
            raw_text=report_meta["text"],
            submitted_at=datetime.now(timezone.utc)
        )
        config = {"configurable": {"thread_id": report_obj.report_id}}
        state  = {
            "raw_report": report_obj,
            "available_resources": resources,
            "existing_needs": history_needs.copy(),
        }

        record = {
            "index": i + 1,
            "type": report_meta["type"],
            "text_preview": report_meta["text"][:60],
            "outcome": None,
            "hitl_action": None,
            "coverage_pct": None,
            "latency_s": None,
        }

        t0 = time.perf_counter()
        try:
            for _ in graph.stream(state, config, stream_mode="values"):
                pass

            final_state = graph.get_state(config)
            paused_at_hitl = bool(final_state.next and "human_review" in final_state.next)

            if paused_at_hitl:
                results["hitl_routed"] += 1
                verified_need = final_state.values.get("verified_need")

                if verified_need and verified_need.duplicate_of:
                    results["hitl_reasons"]["duplicate"] += 1
                    if report_meta["type"] in ("exact_duplicate", "near_duplicate"):
                        results["duplicates_caught"] += 1
                else:
                    results["hitl_reasons"]["low_confidence"] += 1

                decision = hitl_decision(verified_need, report_meta["type"])
                record["hitl_action"] = decision

                if decision == "reject":
                    results["hitl_rejected_by_reviewer"] += 1
                    record["outcome"] = "hitl_rejected"
                    latency = time.perf_counter() - t0
                    results["latencies_s"].append(latency)
                    record["latency_s"] = round(latency, 3)
                    print(f"[{i+1:>3}/{total}] {report_meta['type']:<16} -> HITL REJECTED  ({latency:.2f}s)")
                    results["per_report"].append(record)
                else:
                    results["hitl_approved_by_reviewer"] += 1
                    for _ in graph.stream(None, config, stream_mode="values"):
                        pass
                    final_state = graph.get_state(config)

            if record["outcome"] != "hitl_rejected":
                latency = time.perf_counter() - t0
                results["latencies_s"].append(latency)
                record["latency_s"] = round(latency, 3)

                verified_need = final_state.values.get("verified_need")
                evaluation    = final_state.values.get("evaluation")
                revision_count = final_state.values.get("revision_count", 0)

                if verified_need:
                    history_needs.append(verified_need)

                if not paused_at_hitl:
                    results["auto_approved"] += 1
                    record["outcome"] = "auto_approved"
                else:
                    record["outcome"] = "hitl_approved_then_processed"

                if evaluation:
                    record["coverage_pct"] = evaluation.coverage_pct
                    results["coverage_scores"].append(evaluation.coverage_pct)
                    results["fairness_scores"].append(evaluation.fairness_score)

                    if evaluation.passed and revision_count <= 1:
                        results["evaluator_passed_first_try"] += 1
                    elif not evaluation.passed:
                        results["evaluator_hit_max_retries"] += 1
                    else:
                        results["evaluator_needed_retry"] += 1

                outcome_label = record["outcome"].upper()
                cov = f"{evaluation.coverage_pct:.1f}%" if evaluation else "N/A"
                print(f"[{i+1:>3}/{total}] {report_meta['type']:<16} -> {outcome_label:<30} cov={cov:>7}  ({latency:.2f}s)")

        except Exception as e:
            results["errors"] += 1
            record["outcome"] = f"error: {str(e)[:80]}"
            latency = time.perf_counter() - t0
            record["latency_s"] = round(latency, 3)
            print(f"[{i+1:>3}/{total}] {report_meta['type']:<16} -> ERROR: {str(e)[:60]}")

        if record["outcome"] != "hitl_rejected" and "per_report" not in [k for k in results]:
            pass # already appended in reject block
        if record["outcome"] != "hitl_rejected":
            results["per_report"].append(record)

        # SAVE CHECKPOINT AFTER EVERY REPORT
        saved_data = {
            "results": results,
            "history_needs": [n.model_dump(mode='json') for n in history_needs]
        }
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(saved_data, f, indent=2)

    # --- Summary ---
    lat = results["latencies_s"]
    cov = results["coverage_scores"]
    fair = results["fairness_scores"]

    avg_lat  = sum(lat) / len(lat)   if lat  else 0
    max_lat  = max(lat)              if lat  else 0
    avg_cov  = sum(cov) / len(cov)   if cov  else 0
    avg_fair = sum(fair) / len(fair) if fair else 0

    results["summary"] = {
        "avg_latency_s": round(avg_lat, 2),
        "max_latency_s": round(max_lat, 2),
        "avg_coverage_pct": round(avg_cov, 2),
        "avg_fairness_score": round(avg_fair, 3),
        "duplicate_recall_pct": round(
            results["duplicates_caught"] / (results["exact_duplicates_in_set"] + results["near_duplicates_in_set"]) * 100, 1
        ),
        "auto_approval_rate_pct": round(results["auto_approved"] / total * 100, 1),
        "hitl_rate_pct": round(results["hitl_routed"] / total * 100, 1),
        "error_rate_pct": round(results["errors"] / total * 100, 1),
    }

    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS — 150 REPORT RUN")
    print("=" * 60)
    print(f"Total Reports          : {total}")
    print(f"Avg Latency            : {avg_lat:.2f}s")
    print("-" * 40)
    print(f"Auto-Approved          : {results['auto_approved']}")
    print(f"Routed to HITL         : {results['hitl_routed']}")
    print(f"Duplicates Caught      : {results['duplicates_caught']} / 50")
    print(f"Duplicate Recall       : {results['summary']['duplicate_recall_pct']}%")
    print("-" * 40)
    print(f"Avg Coverage           : {avg_cov:.2f}%")
    print("=" * 60)

    # Final save with summary
    saved_data = {
        "results": results,
        "history_needs": [n.model_dump(mode='json') for n in history_needs]
    }
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(saved_data, f, indent=2)

if __name__ == "__main__":
    asyncio.run(run_benchmarks())

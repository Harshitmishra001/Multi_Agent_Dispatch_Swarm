import math
import pulp
from typing import List
from backend.schemas.models import VerifiedNeed, ResourceRecord, Allocation, UrgencyLevel

def haversine_distance(coord1, coord2):
    if not coord1 or not coord2:
        return 9999.0 # Unknown distance, penalize
        
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 6371.0 # Earth radius in km

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

class ResourceMatcher:


    def _urgency_weight(self, urgency: UrgencyLevel) -> int:
        weights = {
            UrgencyLevel.CRITICAL: 4000,
            UrgencyLevel.HIGH: 3000,
            UrgencyLevel.MODERATE: 2000,
            UrgencyLevel.LOW: 1000
        }
        return weights.get(urgency, 1000)

    def process(self, needs: List[VerifiedNeed], resources: List[ResourceRecord], revision_notes: str = None) -> List[Allocation]:
        allocations = []
        
        available_resources = {r.resource_id: r for r in resources if r.status == "available" and r.quantity_available > 0}
        active_needs = [n for n in needs if n.quantity_estimate > 0]
        
        if not available_resources or not active_needs:
            return []
            
        prob = pulp.LpProblem("Disaster_Resource_Allocation", pulp.LpMaximize)
        
        # Variables: x[need_id][res_id] = integer quantity allocated
        x_vars = {}
        for n in active_needs:
            x_vars[n.need_id] = {}
            for r in available_resources.values():
                if r.resource_type == n.need_type:
                    # Create integer variable bounded by 0 and min(need, available)
                    upper = min(n.quantity_estimate, r.quantity_available)
                    x_vars[n.need_id][r.resource_id] = pulp.LpVariable(
                        f"x_{n.need_id}_{r.resource_id}", 
                        lowBound=0, 
                        upBound=upper, 
                        cat=pulp.LpInteger
                    )

        # Objective function: maximize (urgency * 1000 - distance) * quantity
        objective_terms = []
        for n in active_needs:
            for r in available_resources.values():
                if r.resource_type == n.need_type:
                    var = x_vars[n.need_id][r.resource_id]
                    dist = haversine_distance(n.coordinates, r.location)
                    urgency_w = self._urgency_weight(n.urgency)
                    
                    # Base value is urgency weight. We subtract distance to prefer closer resources.
                    # As long as distance penalty < 1000, it won't override a higher urgency category.
                    weight = urgency_w - min(dist, 999.0)
                    
                    # If evaluator flagged this need for revision, massively boost it
                    if revision_notes and n.need_id in revision_notes:
                        weight += 500000.0
                        
                    objective_terms.append(weight * var)
                    
        prob += pulp.lpSum(objective_terms)

        # Constraints: 
        # 1. Total allocated to each need <= quantity requested
        for n in active_needs:
            need_vars = []
            for r in available_resources.values():
                if r.resource_type == n.need_type:
                    need_vars.append(x_vars[n.need_id][r.resource_id])
            if need_vars:
                prob += (pulp.lpSum(need_vars) <= n.quantity_estimate, f"NeedLimit_{n.need_id}")

        # 2. Total taken from each resource <= quantity available
        for r in available_resources.values():
            res_vars = []
            for n in active_needs:
                if r.resource_type == n.need_type:
                    res_vars.append(x_vars[n.need_id][r.resource_id])
            if res_vars:
                prob += (pulp.lpSum(res_vars) <= r.quantity_available, f"ResLimit_{r.resource_id}")

        # Solve with best available solver
        solver = None
        for candidate in [pulp.PULP_CBC_CMD(msg=0), pulp.COIN_CMD(msg=0)]:
            if candidate.available():
                solver = candidate
                break
        try:
            if solver:
                prob.solve(solver)
            else:
                prob.solve(pulp.PULP_CBC_CMD(msg=0))
        except Exception:
            try:
                prob.solve()
            except Exception:
                pass
        
        # Build allocations from results
        for n in active_needs:
            for r in available_resources.values():
                if r.resource_type == n.need_type:
                    var = x_vars[n.need_id][r.resource_id]
                    if var.varValue and var.varValue > 0:
                        alloc_qty = int(var.varValue)
                        dist = haversine_distance(n.coordinates, r.location)
                        allocations.append(Allocation(
                            need_id=n.need_id,
                            resource_id=r.resource_id,
                            quantity_allocated=alloc_qty,
                            distance_km=round(dist, 2),
                            allocation_method="ilp_optimal"
                        ))

        return allocations

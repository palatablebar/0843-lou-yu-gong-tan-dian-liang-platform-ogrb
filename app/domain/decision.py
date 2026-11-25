from app.domain.helpers import D


def decide_rows(items, settlement=None):
    blocked_buildings = set()
    if settlement is not None:
        for building in settlement["buildings"]:
            if building["reasons"]:
                blocked_buildings.add(building["building_id"])
        if settlement["allocation_leak"]:
            blocked_buildings.update(building["building_id"] for building in settlement["buildings"])
    for item in items:
        if item.get("problem"):
            item["verdict"] = "REJECT"
            item["reason"] = item["problem"]
        elif item["label"] in blocked_buildings:
            item["verdict"] = "REJECT"
            item["reason"] = "PUMP_JOINT_REJECT"
        elif sum(row["total"] for row in item["allocations"]) != item["usage_mwh"] + item["common_mwh"]:
            item["verdict"] = "REJECT"
            item["reason"] = "ALLOCATION_LEAK"
        else:
            item["verdict"] = "PASS"
            item["reason"] = "METER_BALANCED"
        item.setdefault("verdict", "PASS")
        item.setdefault("reason", "OK")
    if settlement is not None:
        settlement["verdict"] = "REJECT" if settlement["blockers"] else "PASS"
        settlement["reason"] = "PUMP_JOINT_HELD" if settlement["blockers"] else "PUMP_JOINT_BALANCED"
    return items

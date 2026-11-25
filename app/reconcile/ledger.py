from decimal import Decimal

from app.catalog import SPEC
from app.reconcile.checks import all_checks


def build_ledger(intake, prepared, prepare_issues, results, settlement=None):
    counts = dict(intake["counts"])
    counts["prepared"] = len(prepared)
    counts["prepare_issues"] = len(prepare_issues)
    counts["computed"] = len(results)
    balanced = counts["input"] == counts["accepted"] + counts["isolated"] + counts["duplicates"] + counts["ignored"]
    metric = sum((item.get("metric") for item in results if item.get("metric") is not None), Decimal("0"))
    checks = [
        {"id": "source", "label": "来源行守恒", "ok": balanced},
        {"id": "computed", "label": "计算条目完整", "ok": counts["computed"] == len(results)},
    ]
    pump_checks = []
    if settlement is not None:
        # 泵电分摊之和必须等于泵表读数差（瓦时守恒）。
        pump_checks.append({"id": "pump_allocation", "label": "泵电分摊守恒",
                            "ok": settlement["allocated_pump_mwh"] == settlement["pump_mwh"]})
        # 两栋楼都要与实测总表对平，联合签发，一损俱损。
        for building in settlement["buildings"]:
            pump_checks.append({"id": f"pump_reconcile_{building['building_id']}",
                                "label": f"{building['building_id']} 总表对账",
                                "ok": building["reconciled"]})
        checks.extend(pump_checks)
    return {"counts": counts, "balanced": balanced, "metric_field": SPEC.get("metric_field", "metric"),
            "metric_total": str(metric), "checks": checks, "all_checks": all_checks(checks),
            "pump_joint_ok": None if settlement is None else settlement["joint_ok"]}

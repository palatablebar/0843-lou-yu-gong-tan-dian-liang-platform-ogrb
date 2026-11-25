from app.errors import DomainIssue
from app.evidence.manifest import stable_digest


def _pump_evidence(run):
    settlement = run.get("pump_settlement")
    if settlement is None:
        return None
    return {
        "pump_meter_id": settlement["pump_meter_id"],
        "host_building_id": settlement["host_building_id"],
        # 泵表电量（Wh 与 kWh 双口径，便于与签发单核对）。
        "pump_mwh": settlement["pump_mwh"],
        "pump_kwh": settlement["pump_mwh"] / 1000,
        "pump_start_mwh": settlement["pump_start_mwh"],
        "pump_end_mwh": settlement["pump_end_mwh"],
        "allocated_pump_mwh": settlement["allocated_pump_mwh"],
        "wiring_sha256": settlement["wiring_sha256"],
        "wiring_filename": settlement["wiring_filename"],
        "joint_ok": settlement["joint_ok"],
        "verdict": settlement.get("verdict"),
        "reason": settlement.get("reason"),
        # 各楼实测总表电量与对账结果。
        "buildings": [
            {
                "building_id": building["building_id"],
                "is_host": building["is_host"],
                "main_mwh": building["main_mwh"],
                "main_kwh": building["main_mwh"] / 1000,
                "usage_mwh": building["usage_mwh"],
                "common_inside_mwh": building["common_inside_mwh"],
                "pump_mwh": building["pump_mwh"],
                "reconciled": building["reconciled"],
                "diff_mwh": building["diff_mwh"],
                "reasons": building["reasons"],
            }
            for building in settlement["buildings"]
        ],
        "room_bills": {
            building["building_id"]: building["room_bills"] for building in settlement["buildings"]
        },
    }


def render(run):
    if run is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    if run["status"] != "APPROVED":
        raise DomainIssue("NOT_APPROVED", 409)
    artifact = {
        "schema": "workbench-evidence/v1",
        "run_id": run["run_id"],
        "project": run["project"],
        "rule": run["rule"],
        "profile": run["profile"],
        "source": run["source"],
        "counts": run["counts"],
        "ledger": run["ledger"],
        "summary": run["summary"],
        "pump": _pump_evidence(run),
        "review": {"status": run["status"], "revision": run["revision"], "comment": run["comment"]},
    }
    artifact["artifact_sha256"] = stable_digest(artifact)
    return artifact

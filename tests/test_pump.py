"""共用泵电：防重复计费、联合签发、对账到瓦时、幂等与证据。"""
import json

from app.domain.prepare import prepare_rows
from app.domain.pump import load_wiring
from app.domain.pump_settle import settle_pump
from app.intake.service import load
from app.review.policy import approval_allowed
from app.service import pipeline


def prepared(profile="pump-clean"):
    rows = load(profile)["rows"]
    items, issues = prepare_rows(rows)
    assert issues == []
    return items


def config(profile="pump-clean", items=None):
    cfg, issues = load_wiring(profile, items or prepared(profile))
    assert issues == []
    return cfg


# ---------- 泵电只收一次：宿主楼公摊先扣泵电 ----------

def test_host_common_deducts_full_pump_before_split():
    items = prepared()
    settlement = settle_pump(items, config(items=items))
    host = next(b for b in settlement["buildings"] if b["is_host"])
    # 宿主楼原始公摊 100000 Wh，整只泵表 60000 Wh 先从公摊扣除，楼内公摊只剩 40000 Wh。
    assert host["common_raw_mwh"] == 100_000
    assert settlement["pump_mwh"] == 60_000
    assert host["common_inside_mwh"] == 40_000
    # 宿主楼只承担分摊给本楼受益房间的那部分泵电（其余归 B2 受益房间）。
    assert host["pump_mwh"] == 40_000


def test_pump_is_not_charged_twice():
    """若照旧分（不扣泵电），宿主楼会把泵电再当公摊摊一次。
    正确口径下：宿主楼对账 usage + 楼内公摊 + 本楼分摊泵电 == 实测总表，
    泵电在全楼层面只出现一次，没有重复。"""
    items = prepared()
    settlement = settle_pump(items, config(items=items))
    pump_total = settlement["pump_mwh"]
    for building in settlement["buildings"]:
        billed = sum(room["bill_mwh"] for room in building["room_bills"])
        if building["is_host"]:
            # 宿主楼总表守恒：分表 + 楼内公摊 + 整只泵表 == 实测总表（对账到 Wh）。
            assert (building["usage_mwh"] + building["common_inside_mwh"] + pump_total
                    == building["main_mwh"])
            # 房间账单只含本楼受益房间分摊到的泵电，整只泵没有被再摊一遍。
            assert billed == (building["usage_mwh"]
                              + building["common_inside_mwh"]
                              + building["pump_mwh"])
        else:
            # 邻居楼总表不含泵电，账单比总表多出的恰好是它承担的泵电分摊。
            assert billed == building["main_mwh"] + building["pump_mwh"]
    # 两栋承担的泵电之和严格等于泵表读数差。
    assert sum(b["pump_mwh"] for b in settlement["buildings"]) == pump_total


# ---------- 泵电只由实际受益房间承担，按面积最大余数法且守恒 ----------

def test_pump_allocated_only_to_beneficiaries():
    items = prepared()
    cfg = config(items=items)
    cfg["beneficiary_rooms"] = ["R1", "R4"]  # 仅两户受益
    settlement = settle_pump(items, cfg)
    pump_by_room = {b["building_id"]: b["room_bills"] for b in settlement["buildings"]}
    flat = {room["room_id"]: room["pump_mwh"] for rooms in pump_by_room.values() for room in rooms}
    assert flat["R1"] > 0 and flat["R4"] > 0
    assert flat["R2"] == flat["R3"] == flat["R5"] == 0
    assert sum(flat.values()) == settlement["pump_mwh"]


def test_pump_allocation_conserves_to_watt_hour():
    items = prepared()
    settlement = settle_pump(items, config(items=items))
    assert settlement["allocated_pump_mwh"] == settlement["pump_mwh"] == 60_000
    assert settlement["allocation_leak"] is False


def test_largest_remainder_handles_odd_division():
    # 60001 Wh 在总面积 600（单位 0.01m2 → 60000 权重）下仍要分尽。
    items = prepared()
    cfg = config(items=items)
    cfg["pump_mwh"] = 60_001
    settlement = settle_pump(items, cfg)
    assert sum(room["pump_mwh"] for b in settlement["buildings"] for room in b["room_bills"]) == 60_001


# ---------- 各楼拿实测总表对账到瓦时 ----------

def test_each_building_reconciles_to_main_meter():
    settlement = settle_pump(prepared(), config())
    for building in settlement["buildings"]:
        assert building["reconciled"] is True
        assert building["diff_mwh"] == 0


def test_neighbor_main_meter_excludes_pump():
    # 邻居楼总表不含泵电：usage + 楼内公摊 == main，泵电只进房间账单。
    settlement = settle_pump(prepared(), config())
    neighbor = next(b for b in settlement["buildings"] if not b["is_host"])
    assert neighbor["usage_mwh"] + neighbor["common_inside_mwh"] == neighbor["main_mwh"]
    assert neighbor["pump_mwh"] > 0


# ---------- 两栋联合签发：一栋对不平则整体挂起 ----------

def test_joint_settlement_holds_when_one_building_mismatches():
    data = pipeline("pump-gap")
    settlement = data["pump_settlement"]
    assert settlement["joint_ok"] is False
    assert settlement["verdict"] == "REJECT"
    # B2 本身对平，但因 B1 对不平，联合结算仍阻断，签发门关闭。
    assert any(b["building_id"] == "B1" and not b["reconciled"] for b in settlement["buildings"])
    assert approval_allowed(data) is False


def test_clean_pump_settlement_can_be_approved():
    data = pipeline("pump-clean")
    assert data["pump_settlement"]["joint_ok"] is True
    assert approval_allowed(data) is True


def test_unknown_beneficiary_blocks_joint_settlement(tmp_path):
    rows = load("pump-clean")["rows"]
    items, _ = prepare_rows(rows)
    wiring = tmp_path / "case.wiring.json"
    wiring.write_text(json.dumps({
        "pump_meter_id": "P1", "pump_start": "0", "pump_end": "60",
        "host_building_id": "B1", "beneficiary_rooms": ["R1", "R404"]}), encoding="utf-8")
    cfg, issues = load_wiring("case", items, str(wiring))
    assert any(i["code"] == "PUMP_BENEFICIARY_UNKNOWN" for i in issues)
    assert settle_pump(items, cfg)["joint_ok"] is False


# ---------- 重跑同样读数与接线不重复计费（幂等） ----------

def test_same_readings_and_wiring_share_run_key():
    first = pipeline("pump-clean")
    second = pipeline("pump-clean")
    assert first["run_key"] == second["run_key"]


def test_changed_wiring_changes_run_key():
    base = pipeline("pump-clean")
    other = pipeline("pump-gap")
    assert base["run_key"] != other["run_key"]


def test_rerun_creates_single_run(client):
    first = client.post("/api/runs", json={"profile": "pump-clean"}).get_json()
    second = client.post("/api/runs", json={"profile": "pump-clean"}).get_json()
    assert first["run_id"] == second["run_id"]


def test_pump_gap_run_cannot_be_approved(client):
    run = client.post("/api/runs", json={"profile": "pump-gap"}).get_json()
    response = client.post(f"/api/runs/{run['run_id']}/review",
                           json={"decision": "APPROVED", "comment": "尝试签发", "expected_revision": 0})
    assert response.status_code == 409
    assert response.get_json()["code"] == "GATE_BLOCKED"


def test_pump_clean_run_full_signoff_flow(client):
    run = client.post("/api/runs", json={"profile": "pump-clean"}).get_json()
    review = client.post(f"/api/runs/{run['run_id']}/review",
                         json={"decision": "APPROVED", "comment": "两栋泵电账齐平", "expected_revision": 0})
    assert review.status_code == 200
    evidence = client.get(f"/api/runs/{run['run_id']}/evidence").get_json()
    # 证据里能查到泵表电量和各楼总表电量。
    assert evidence["pump"]["pump_mwh"] == 60_000
    mains = {b["building_id"]: b["main_mwh"] for b in evidence["pump"]["buildings"]}
    assert mains == {"B1": 500_000, "B2": 250_000}
    assert evidence["pump"]["joint_ok"] is True


def test_evidence_absent_without_wiring(client):
    run = client.post("/api/runs", json={"profile": "clean"}).get_json()
    client.post(f"/api/runs/{run['run_id']}/review",
                json={"decision": "APPROVED", "comment": "无泵", "expected_revision": 0})
    evidence = client.get(f"/api/runs/{run['run_id']}/evidence").get_json()
    assert evidence["pump"] is None


def test_catalog_advertises_pump_samples(client):
    catalog = client.get("/api/catalog").get_json()
    assert "pump-clean" in catalog["samples"] and "pump-gap" in catalog["samples"]


def test_wiring_download_and_404(client):
    ok = client.get("/api/examples/pump-clean/wiring")
    try:
        assert ok.status_code == 200
        assert json.loads(ok.data)["pump_meter_id"] == "P1"
    finally:
        ok.close()
    missing = client.get("/api/examples/clean/wiring")
    assert missing.status_code == 404


def test_evidence_digest_is_stable_and_covers_pump(client):
    run = client.post("/api/runs", json={"profile": "pump-clean"}).get_json()
    client.post(f"/api/runs/{run['run_id']}/review",
                json={"decision": "APPROVED", "comment": "签发", "expected_revision": 0})
    first = client.get(f"/api/runs/{run['run_id']}/evidence").get_json()
    second = client.get(f"/api/runs/{run['run_id']}/evidence").get_json()
    assert first["artifact_sha256"] == second["artifact_sha256"]
    assert len(first["artifact_sha256"]) == 64


def test_broken_wiring_does_not_crash_pipeline(tmp_path):
    csv_path = tmp_path / "case.csv"
    csv_path.write_text(load("pump-clean")["path"].read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "case.wiring.json").write_text("{broken", encoding="utf-8")
    from app.service import pipeline as run_pipeline
    payload = run_pipeline("case", str(csv_path))
    assert any(issue["code"] == "WIRING_BAD_JSON" for issue in payload["issues"])
    assert payload["pump_settlement"] is None

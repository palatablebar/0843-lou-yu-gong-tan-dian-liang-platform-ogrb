"""泵表接线记录加载与校验。

接线记录是与房间读数 CSV 配套的主数据：说明共用泵表的起止读数、
泵表接在哪一栋楼的总表底下（宿主楼），以及实际受益的房间清单。
没有接线记录的批次按“无共用泵”处理，保持原有公摊流程不变。
"""
import json
from pathlib import Path

from app.config import SAMPLES
from app.domain.helpers import D
from app.errors import DomainIssue
from app.evidence.manifest import sha256

WIRING_SUFFIX = ".wiring.json"
REQUIRED_FIELDS = ("pump_meter_id", "pump_start", "pump_end", "host_building_id", "beneficiary_rooms")


def wiring_path(profile: str, path: str | None = None) -> Path:
    if path:
        candidate = Path(path)
        return candidate.with_name(candidate.stem.split(".")[0] + WIRING_SUFFIX)
    return SAMPLES / f"{profile}{WIRING_SUFFIX}"


def load_wiring(profile: str, prepared, path: str | None = None):
    """返回 (pump_config, issues)。无接线文件时 pump_config 为 None。"""
    sample = wiring_path(profile, path)
    if not sample.is_file():
        return None, []
    raw = sample.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, [{"line": 0, "key": "", "code": "WIRING_BAD_JSON"}]
    if not isinstance(data, dict):
        return None, [{"line": 0, "key": "", "code": "WIRING_BAD_SHAPE"}]
    issues = []
    for field in REQUIRED_FIELDS:
        if field not in data:
            issues.append({"line": 0, "key": str(data.get("pump_meter_id", "")), "code": "WIRING_FIELD_MISSING"})
    if issues:
        return None, issues
    meter_id = str(data["pump_meter_id"]).strip()
    if not meter_id:
        issues.append({"line": 0, "key": "", "code": "WIRING_PUMP_ID"})
    try:
        start = D(data["pump_start"], "WIRING_BAD_READING")
        end = D(data["pump_end"], "WIRING_BAD_READING")
    except ValueError as exc:
        return None, [{"line": 0, "key": meter_id, "code": str(exc)}]
    if end < start:
        issues.append({"line": 0, "key": meter_id, "code": "WIRING_BACKWARDS"})
    pump_mwh = max(0, int((end - start) * 1000))
    host = str(data["host_building_id"]).strip()
    rooms = data["beneficiary_rooms"]
    if not isinstance(rooms, list) or not rooms or any(not str(room).strip() for room in rooms):
        issues.append({"line": 0, "key": meter_id, "code": "WIRING_BENEFICIARY_EMPTY"})
        rooms = []
    beneficiaries = [str(room).strip() for room in rooms]
    known_rooms = {item["room_id"] for item in prepared}
    known_buildings = {item["building_id"] for item in prepared}
    if host and host not in known_buildings:
        issues.append({"line": 0, "key": meter_id, "code": "PUMP_HOST_UNKNOWN"})
    unknown = [room for room in beneficiaries if room not in known_rooms]
    if unknown:
        issues.append({"line": 0, "key": meter_id, "code": "PUMP_BENEFICIARY_UNKNOWN"})
    config = {
        "pump_meter_id": meter_id,
        "pump_start_mwh": int(start * 1000),
        "pump_end_mwh": int(end * 1000),
        "pump_mwh": pump_mwh,
        "host_building_id": host,
        "beneficiary_rooms": beneficiaries,
        "unknown_beneficiaries": sorted(set(unknown)),
        "wiring_sha256": sha256(raw),
        "wiring_filename": sample.name,
    }
    return config, issues

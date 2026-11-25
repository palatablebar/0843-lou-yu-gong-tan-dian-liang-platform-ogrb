"""共用泵电的分摊与两栋联合对账。

口径（全部以整数瓦时 Wh 计算，避免浮点漂移）：

1. 每栋楼先按原规则得到：分表合计 usage、实测总表 main、
   原始公摊 common_raw = main - usage。
2. 泵表电量只由接线记录中的实际受益房间承担，按受益房间面积用
   最大余数法分摊，分摊之和严格等于泵表读数差。
3. 宿主楼的总表已包含泵电，因此宿主楼的“楼内公摊”要先扣除泵电：
   common_inside = common_raw - pump_mwh。若扣成负数说明总表
   不足以覆盖泵电，阻断（PUMP_EXCEEDS_COMMON）。
4. 对账到 Wh：
   - 宿主楼：usage + common_inside + pump_mwh == main
   - 邻居楼：usage + common_inside == main（其房间账单另含泵电分摊）
5. 两栋泵电账是一份联合结算，任一栋对不平，整体不可签发。
"""
from app.domain.helpers import largest_remainder


def _group_buildings(items):
    grouped = {}
    for item in items:
        grouped.setdefault(item["building_id"], []).append(item)
    return grouped


def _building_base(rooms):
    usage = sum(room["usage_mwh"] for room in rooms)
    main = rooms[0]["main_mwh"]
    return usage, main, main - usage


def settle_pump(items, config):
    """生成两栋联合泵电结算。config 为 None 时返回 None。"""
    if config is None:
        return None
    grouped = _group_buildings(items)
    pump_mwh = config["pump_mwh"]
    host = config["host_building_id"]
    beneficiary_set = set(config["beneficiary_rooms"])

    # 受益房间按面积跨楼参与泵电分摊（只有真实存在的房间）。
    benefit_items = [item for item in items if item["room_id"] in beneficiary_set]
    areas = [int(item["area_m2"] * 100) for item in benefit_items]
    allocations = largest_remainder(pump_mwh, areas) if benefit_items else []
    pump_by_room = {item["room_id"]: share for item, share in zip(benefit_items, allocations)}

    buildings = []
    blockers = []
    for building_id, rooms in grouped.items():
        usage, main, common_raw = _building_base(rooms)
        is_host = building_id == host
        common_inside = common_raw - pump_mwh if is_host else common_raw
        building_pump = sum(pump_by_room.get(room["room_id"], 0) for room in rooms)
        # 房间账单：分表用量 + 楼内公摊（按面积）+ 泵电分摊。
        inside_weights = [int(room["area_m2"] * 100) for room in rooms]
        inside_shares = largest_remainder(max(0, common_inside), inside_weights)
        room_bills = []
        for room, inside in zip(rooms, inside_shares):
            pump_share = pump_by_room.get(room["room_id"], 0)
            room_bills.append({
                "room_id": room["room_id"],
                "usage_mwh": room["usage_mwh"],
                "common_inside_mwh": inside,
                "pump_mwh": pump_share,
                "bill_mwh": room["usage_mwh"] + inside + pump_share,
            })
        # 对账到瓦时。
        if is_host:
            reconciled = usage + max(0, common_inside) + pump_mwh == main
            accounted = usage + max(0, common_inside) + pump_mwh
        else:
            reconciled = usage + max(0, common_inside) == main
            accounted = usage + max(0, common_inside)
        diff_mwh = main - accounted
        reasons = []
        if common_raw < 0:
            reasons.append("MAIN_UNDER_ROOMS")
        if is_host and common_inside < 0:
            reasons.append("PUMP_EXCEEDS_COMMON")
        if not reconciled:
            reasons.append("PUMP_RECONCILE_GAP")
        if config.get("unknown_beneficiaries"):
            reasons.append("PUMP_BENEFICIARY_UNKNOWN")
        if host not in grouped:
            reasons.append("PUMP_HOST_UNKNOWN")
        if reasons:
            blockers.extend(f"{building_id}:{code}" for code in reasons)
        buildings.append({
            "building_id": building_id,
            "is_host": is_host,
            "main_mwh": main,
            "usage_mwh": usage,
            "common_raw_mwh": common_raw,
            "common_inside_mwh": max(0, common_inside),
            "pump_mwh": building_pump,
            "reconciled": reconciled,
            "diff_mwh": diff_mwh,
            "reasons": reasons,
            "room_bills": room_bills,
        })

    # 泵电分摊守恒：分出去的必须等于泵表读数差。
    allocated_total = sum(pump_by_room.values())
    allocation_leak = allocated_total != pump_mwh
    if allocation_leak:
        blockers.append("PUMP:PUMP_ALLOCATION_LEAK")

    settlement = {
        "pump_meter_id": config["pump_meter_id"],
        "host_building_id": host,
        "pump_mwh": pump_mwh,
        "pump_start_mwh": config["pump_start_mwh"],
        "pump_end_mwh": config["pump_end_mwh"],
        "beneficiary_rooms": config["beneficiary_rooms"],
        "allocated_pump_mwh": allocated_total,
        "allocation_leak": allocation_leak,
        "buildings": buildings,
        "blockers": sorted(set(blockers)),
        "joint_ok": not blockers,
        "wiring_sha256": config["wiring_sha256"],
        "wiring_filename": config["wiring_filename"],
    }
    return settlement

def approval_allowed(payload):
    if int(payload["summary"].get("REJECT", 0)) != 0:
        return False
    settlement = payload.get("pump_settlement")
    # 两栋泵电账联合签发：有一栋对不平就整体挂起。
    if settlement is not None and not settlement.get("joint_ok"):
        return False
    ledger = payload.get("ledger")
    if ledger is not None and not ledger.get("all_checks"):
        return False
    return True

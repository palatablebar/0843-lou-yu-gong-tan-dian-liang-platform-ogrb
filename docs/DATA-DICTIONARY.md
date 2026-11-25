# 字段定义

| 字段 | 类型 | 说明 |
|---|---|---|
| `building_id` | text | 业务字段 |
| `meter_id` | text | 主键 |
| `room_id` | text | 业务字段 |
| `area_m2` | decimal | 业务字段 |
| `start_reading` | decimal | 业务字段 |
| `end_reading` | decimal | 业务字段 |
| `main_kwh` | decimal | 业务字段 |

空字符串、`-`、`NA`、`null` 和 `未提供` 按空值处理。金额字段在整理层转为整数分或整数最小单位；日期按 ISO 日期解析；带时间的字段按本地时间解析。标识字段保持为文本，前导零不会被去除。

## 泵表接线记录 `*.wiring.json`

与读数 CSV 配套的主数据，文件名与样例同名（如 `pump-clean.wiring.json`）。缺省该文件表示本批次无共用泵。

| 字段 | 类型 | 说明 |
|---|---|---|
| `pump_meter_id` | text | 泵表标识，主键语义，不可为空 |
| `pump_start` | decimal | 泵表起码（kWh） |
| `pump_end` | decimal | 泵表止码（kWh），不得小于起码 |
| `host_building_id` | text | 泵表所接总表的楼栋（宿主楼），必须在读数数据中存在 |
| `beneficiary_rooms` | text[] | 实际受益房间 `room_id` 清单，不可为空，且都应在读数数据中存在 |

派生量：`pump_mwh = (pump_end - pump_start) * 1000`（整数 Wh）。读数按定点十进制解析，分摊与对账全部使用整数 Wh，不使用二进制浮点。

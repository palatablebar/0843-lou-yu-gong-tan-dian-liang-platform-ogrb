# 接口

- `GET /`：工作台。
- `GET /api/catalog`：阶段、字段和样例。
- `POST /api/stages/{stage}`：按阶段返回处理结果。
- `POST /api/runs`：执行完整批次并保存草稿。
- `GET /api/runs/{id}`：读取批次。
- `POST /api/runs/{id}/review`：签发或暂缓，提交 `decision`、`comment`、`expected_revision`。
- `GET /api/runs/{id}/evidence`：下载已签发证据。
- `GET /api/examples/{profile}`：下载样例。
- `GET /api/examples/{profile}/wiring`：下载样例配套的泵表接线记录（无接线返回 404）。
- `GET /healthz`：健康检查。

样例 `profile`：`dirty`、`clean`、`pump-clean`（两栋泵电对平可签发）、`pump-gap`（宿主楼总表不足以覆盖泵电，联合挂起）。

# Forza Horizon 6 Telemetry — Design

## Goal

Receive Forza Horizon 6's "Data Out" UDP telemetry, explore it, and build
dashboards. Sub-second live view *and* durable session history. Fully
containerized, runs locally via Docker Compose, with as much off-the-shelf
software and as little bespoke code as possible.

## Architecture

```
                                          ┌─────────────────────────────┐
 FH6 game ──UDP 60Hz──▶ Telegraf ──┬─────▶│ InfluxDB v2  (persistent)   │──▶ Grafana
 (324-byte binary)     (parse)     │      │  volume, retention, history │   historical /
                                   │      └─────────────────────────────┘   session panels
                                   │
                                   └─HTTP line protocol─▶ Grafana Live ──WebSocket──▶ Grafana
                                                          (/api/live/push)            live gauges
                                                                                      (sub-second)
```

Three off-the-shelf containers. The only project-authored artifacts are
declarative config: a Telegraf binary field map, Grafana provisioning, and
two starter dashboards. No custom parser/application code.

### Components

1. **Telegraf** — `inputs.socket_listener` on UDP with `data_format = "binary"`.
   The full 324-byte FH6 packet is described declaratively (field → type →
   sequential read). Telegraf fans out to **two outputs simultaneously**:
   - `outputs.influxdb_v2` → durable storage.
   - `outputs.http` → POSTs InfluxDB line protocol to Grafana Live's push
     endpoint (`/api/live/push/<streamId>`), a documented Grafana integration.
2. **InfluxDB v2** — time-series storage on a named volume, with a retention
   policy. Backs historical / session dashboards via Flux.
3. **Grafana** — two panel styles from one tool:
   - **Live panels** subscribe to a Grafana Live channel over WebSocket →
     true sub-second updates (in-car-gauge feel).
   - **Historical panels** query InfluxDB → scrub past sessions, compare laps.

### Data flow / latency

- Live path has no DB-poll latency: each packet is pushed straight to the
  browser over WebSocket as Telegraf receives it.
- Persistence path writes every packet to InfluxDB in parallel.
- A "session" in v1 is simply a time range selected in Grafana. The game's
  `IsRaceOn` flag (1 = active) is stored as a field/tag so a session can be
  auto-segmented later without building explicit start/stop management now.

### Sessions & filtering

- `is_race_on` is stored. Telegraf drops nothing by default; dashboards filter
  on `is_race_on == 1` to hide paused/menu frames.
- `timestamp_ms` (game clock) is captured as a field; InfluxDB point time uses
  Telegraf receive time (wall clock) so live and historical align.

## FH6 packet layout (verified)

Fixed **324 bytes, little-endian**, sent at the game frame rate. FH6's "Car
Dash" payload is byte-for-byte identical to FH5: the FM "Sled" (bytes 0–231),
a Horizon-specific 12-byte block (232–243), the "Dash" section shifted +12
(244–322), and one padding byte (323).

Cross-check: the moza-bridge project documents input bytes at offsets 315
(throttle), 316 (brake), 319 (gear) — which match this table exactly.

| Offset | Type  | Field |
|-------:|-------|-------|
| 0   | s32 | is_race_on |
| 4   | u32 | timestamp_ms |
| 8   | f32 | engine_max_rpm |
| 12  | f32 | engine_idle_rpm |
| 16  | f32 | current_engine_rpm |
| 20  | f32 | acceleration_x |
| 24  | f32 | acceleration_y |
| 28  | f32 | acceleration_z |
| 32  | f32 | velocity_x |
| 36  | f32 | velocity_y |
| 40  | f32 | velocity_z |
| 44  | f32 | angular_velocity_x |
| 48  | f32 | angular_velocity_y |
| 52  | f32 | angular_velocity_z |
| 56  | f32 | yaw |
| 60  | f32 | pitch |
| 64  | f32 | roll |
| 68  | f32 | norm_suspension_travel_fl |
| 72  | f32 | norm_suspension_travel_fr |
| 76  | f32 | norm_suspension_travel_rl |
| 80  | f32 | norm_suspension_travel_rr |
| 84  | f32 | tire_slip_ratio_fl |
| 88  | f32 | tire_slip_ratio_fr |
| 92  | f32 | tire_slip_ratio_rl |
| 96  | f32 | tire_slip_ratio_rr |
| 100 | f32 | wheel_rotation_speed_fl |
| 104 | f32 | wheel_rotation_speed_fr |
| 108 | f32 | wheel_rotation_speed_rl |
| 112 | f32 | wheel_rotation_speed_rr |
| 116 | s32 | wheel_on_rumble_strip_fl |
| 120 | s32 | wheel_on_rumble_strip_fr |
| 124 | s32 | wheel_on_rumble_strip_rl |
| 128 | s32 | wheel_on_rumble_strip_rr |
| 132 | f32 | wheel_in_puddle_fl |
| 136 | f32 | wheel_in_puddle_fr |
| 140 | f32 | wheel_in_puddle_rl |
| 144 | f32 | wheel_in_puddle_rr |
| 148 | f32 | surface_rumble_fl |
| 152 | f32 | surface_rumble_fr |
| 156 | f32 | surface_rumble_rl |
| 160 | f32 | surface_rumble_rr |
| 164 | f32 | tire_slip_angle_fl |
| 168 | f32 | tire_slip_angle_fr |
| 172 | f32 | tire_slip_angle_rl |
| 176 | f32 | tire_slip_angle_rr |
| 180 | f32 | tire_combined_slip_fl |
| 184 | f32 | tire_combined_slip_fr |
| 188 | f32 | tire_combined_slip_rl |
| 192 | f32 | tire_combined_slip_rr |
| 196 | f32 | suspension_travel_meters_fl |
| 200 | f32 | suspension_travel_meters_fr |
| 204 | f32 | suspension_travel_meters_rl |
| 208 | f32 | suspension_travel_meters_rr |
| 212 | s32 | car_ordinal |
| 216 | s32 | car_class |
| 220 | s32 | car_performance_index |
| 224 | s32 | drivetrain_type |
| 228 | s32 | num_cylinders |
| 232 | u32 | car_group *(Horizon)* |
| 236 | f32 | smashable_vel_diff *(Horizon)* |
| 240 | f32 | smashable_mass *(Horizon)* |
| 244 | f32 | position_x |
| 248 | f32 | position_y |
| 252 | f32 | position_z |
| 256 | f32 | speed *(m/s)* |
| 260 | f32 | power *(W)* |
| 264 | f32 | torque *(Nm)* |
| 268 | f32 | tire_temp_fl |
| 272 | f32 | tire_temp_fr |
| 276 | f32 | tire_temp_rl |
| 280 | f32 | tire_temp_rr |
| 284 | f32 | boost |
| 288 | f32 | fuel |
| 292 | f32 | distance_traveled |
| 296 | f32 | best_lap |
| 300 | f32 | last_lap |
| 304 | f32 | current_lap |
| 308 | f32 | current_race_time |
| 312 | u16 | lap_number |
| 314 | u8  | race_position |
| 315 | u8  | accel *(throttle 0–255)* |
| 316 | u8  | brake |
| 317 | u8  | clutch |
| 318 | u8  | handbrake |
| 319 | u8  | gear |
| 320 | s8  | steer |
| 321 | s8  | normalized_driving_line |
| 322 | s8  | normalized_ai_brake_difference |
| 323 | —   | padding (omit) |

## Deployment

Local `docker-compose.yml`, three services + named volumes. The game points
its Data Out at `<this machine IP>:5300` (UDP). Secrets/ports via `.env`.
Images and config are written so they could later be re-packaged as a Helm
chart, but k8s is out of scope for v1.

## Verification

FH6 is not required to test the pipeline. `tools/send_test_packet.py`
constructs a valid 324-byte packet with known values (and can stream/replay),
so we can confirm end-to-end flow into InfluxDB and Grafana Live before ever
launching the game.

## Out of scope (v1)

- Kubernetes / Helm packaging.
- Explicit session start/stop lifecycle management.
- Authentication hardening beyond local defaults.

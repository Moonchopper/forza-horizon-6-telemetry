# Forza Horizon 6 Telemetry

Explore Forza Horizon 6's "Data Out" UDP telemetry in real time and build
dashboards — using an off-the-shelf, fully containerized stack.

```
 FH6 ──UDP 60Hz──▶ Telegraf ──┬──▶ InfluxDB v2 ──▶ Grafana (history / sessions)
 (324-byte binary) (parse)     └──▶ Grafana Live ─▶ Grafana (sub-second live gauges)
```

- **Telegraf** receives the UDP packets and parses the 324-byte binary format
  *declaratively* (no custom parser code), then a small starlark processor adds
  derived fields (`lateral_g`, `longitudinal_g`, `speed_kmh`, `power_hp`) so both
  sinks carry them — see [telegraf/telegraf.conf](telegraf/telegraf.conf).
- **InfluxDB v2** stores everything durably for session history and lap comparison.
- **Grafana** serves paired dashboards — a **Live** (Grafana Live, sub-second
  WebSocket push) and an **Analysis** (Flux queries against InfluxDB, with
  history + auto race annotations) twin for each function:

  | Function | Live (push) | Analysis (query) |
  |---|---|---|
  | **Cockpit** — gauges, inputs, tire temps, track map | `Forza Cockpit (Live)` | `Forza Cockpit (Analysis)` |
  | **Driver** — friction circle, dyno, slip, suspension | `Forza Driver (Live)` | `Forza Driver (Analysis)` |

  Live dashboards update instantly but show a rolling browser buffer; Analysis
  dashboards query InfluxDB so they retain full history, support any time range,
  and draw race START/STOP annotations from the `is_race_on` field.

Design details and the full verified packet layout: [docs/design.md](docs/design.md).

## Quick start

1. **Configure secrets:**
   ```sh
   cp .env.example .env
   # edit .env and set strong values for INFLUX_TOKEN / passwords
   ```

2. **Start the stack:**
   ```sh
   docker compose up -d
   ```
   Grafana → http://localhost:3000 (login from `.env`).
   Four dashboards are pre-provisioned under the **Forza** folder — a Live and an
   Analysis twin for both Cockpit and Driver (see the table above).

3. **Verify without the game** (recommended first run):
   ```sh
   python tools/send_test_packet.py --host 127.0.0.1 --port 5300
   ```
   You should see the live dashboard move within ~1s and data accumulate in the
   history dashboard. Stop with Ctrl+C.

4. **Point Forza Horizon 6 at it.** In-game: **Settings → HUD / Gameplay → Data Out**
   - Data Out: **ON**
   - Data Out IP Address: the IP of the machine running this stack
     (use `localhost`/`127.0.0.1` only if the game runs on the same machine;
     for Xbox/another PC use this machine's LAN IP, e.g. `192.168.1.x`)
   - Data Out IP Port: **5300** (matches `FORZA_UDP_PORT`)

## How the real-time path works

Telegraf has **two outputs** configured. Alongside writing to InfluxDB, it POSTs
InfluxDB line protocol to Grafana's Live push endpoint (`/api/live/push/forza`).
Grafana republishes that on the channel `stream/forza/forza`, and the live
dashboard panels subscribe to it over WebSocket — so they update as packets
arrive, with no database polling. Flush interval is `100ms` (≈10 Hz UI updates);
tune `interval`/`flush_interval` in [telegraf/telegraf.conf](telegraf/telegraf.conf).

## Exploring the data

- **Live dashboard** — instant gauges: RPM, gear, speed, throttle/brake, tire temps.
- **History dashboard** — scrub any time range, compare laps, plus a track map
  (X/Z position). Filter to active driving with `is_race_on == 1`.
- **Ad-hoc** — use Grafana's **Explore** with the InfluxDB datasource and Flux to
  query any of the ~80 fields. All field names are listed in [docs/design.md](docs/design.md).

## Common tweaks

| Want | Where |
|------|-------|
| Change UDP port | `FORZA_UDP_PORT` in `.env` |
| Keep only N days of data | `INFLUX_RETENTION` in `.env` (e.g. `720h`) |
| Faster/slower live refresh | `flush_interval` in `telegraf.conf` |
| Add a panel/field | edit dashboards in Grafana (UI updates are allowed) |

## Troubleshooting

- **No data?** Check Telegraf is receiving: `docker compose logs -f telegraf`.
  Confirm the game/sender targets the right IP:port and that host firewall allows
  inbound UDP 5300.
- **Live panels blank but history works?** The Grafana Live push (Telegraf
  `outputs.http`) may be failing auth — check `telegraf` logs for non-2xx from
  `/api/live/push`. Credentials come from `GRAFANA_ADMIN_USER/PASSWORD` in `.env`.
- **History blank but live works?** Check the InfluxDB token/org/bucket in `.env`
  match across all three services.

## Stopping / resetting

```sh
docker compose down          # stop, keep data
docker compose down -v       # stop and delete all stored telemetry
```

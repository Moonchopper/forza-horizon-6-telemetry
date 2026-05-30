#!/usr/bin/env python3
"""Send synthetic Forza Horizon 6 "Data Out" UDP packets.

Builds valid 324-byte little-endian packets matching the FH6 layout (see
docs/design.md) with animated values, so the whole Telegraf -> InfluxDB ->
Grafana pipeline can be verified without launching the game.

Usage:
    python send_test_packet.py --host 127.0.0.1 --port 5300 --rate 60 --duration 0
"""
import argparse
import math
import socket
import struct
import time

# Struct format mirrors the field order in telegraf/telegraf.conf exactly.
# Verified: each group lands on its documented byte offset; total = 324 bytes.
PACKET_FMT = (
    "<"
    + "i"        # is_race_on
    + "I"        # timestamp_ms
    + "f" * 3    # engine_max_rpm, engine_idle_rpm, current_engine_rpm
    + "f" * 3    # acceleration x/y/z
    + "f" * 3    # velocity x/y/z
    + "f" * 3    # angular_velocity x/y/z
    + "f" * 3    # yaw, pitch, roll
    + "f" * 4    # norm_suspension_travel fl/fr/rl/rr
    + "f" * 4    # tire_slip_ratio fl/fr/rl/rr
    + "f" * 4    # wheel_rotation_speed fl/fr/rl/rr
    + "i" * 4    # wheel_on_rumble_strip fl/fr/rl/rr
    + "f" * 4    # wheel_in_puddle fl/fr/rl/rr
    + "f" * 4    # surface_rumble fl/fr/rl/rr
    + "f" * 4    # tire_slip_angle fl/fr/rl/rr
    + "f" * 4    # tire_combined_slip fl/fr/rl/rr
    + "f" * 4    # suspension_travel_meters fl/fr/rl/rr
    + "i" * 5    # car_ordinal, car_class, car_performance_index, drivetrain_type, num_cylinders
    + "I"        # car_group
    + "f" * 2    # smashable_vel_diff, smashable_mass
    + "f" * 3    # position x/y/z
    + "f" * 3    # speed, power, torque
    + "f" * 4    # tire_temp fl/fr/rl/rr
    + "f" * 3    # boost, fuel, distance_traveled
    + "f" * 4    # best_lap, last_lap, current_lap, current_race_time
    + "H"        # lap_number
    + "B" * 6    # race_position, accel, brake, clutch, handbrake, gear
    + "b" * 3    # steer, normalized_driving_line, normalized_ai_brake_difference
    + "x"        # padding (byte 323)
)

assert struct.calcsize(PACKET_FMT) == 324, struct.calcsize(PACKET_FMT)


def build_packet(t: float, start_ms: int) -> bytes:
    """Animate a believable lap: oscillating RPM/throttle, circular track path."""
    rpm = 3500 + 3000 * (0.5 + 0.5 * math.sin(t * 2.0))
    speed = 40 + 30 * (0.5 + 0.5 * math.sin(t * 0.7))         # m/s
    throttle = int(127 + 128 * math.sin(t * 2.0))
    brake = max(0, int(-128 * math.sin(t * 2.0)))
    gear = 1 + int((rpm / 8000) * 6)
    # circular track for the XY map
    px = 200.0 * math.cos(t * 0.3)
    pz = 200.0 * math.sin(t * 0.3)
    tire_base = 80 + 15 * (0.5 + 0.5 * math.sin(t * 0.4))
    # G-forces: lateral from cornering, longitudinal from throttle/brake (m/s^2)
    lat_g = 9.0 * math.sin(t * 0.9)
    long_g = (throttle - brake) / 255.0 * 9.0
    # torque curve (Nm), with power kept consistent (W = torque * angular velocity)
    torque = 500.0 + 200.0 * math.sin((rpm / 8000.0) * math.pi)
    power = torque * rpm * 2.0 * math.pi / 60.0
    # rear-wheel wheelspin grows at high throttle
    spin = max(0.0, (throttle - 200) / 55.0) * 0.4
    slip_ang = 0.02 + abs(lat_g) / 200.0

    values = []
    values += [1]                                            # is_race_on
    values += [start_ms + int(t * 1000) & 0xFFFFFFFF]        # timestamp_ms
    values += [8000.0, 800.0, rpm]                           # engine rpms
    values += [lat_g, 9.8, long_g]                           # acceleration x/y/z
    values += [speed, 0.0, 0.0]                              # velocity
    values += [0.0, 0.0, 0.0]                                # angular velocity
    values += [math.sin(t * 0.3), 0.0, 0.0]                  # yaw/pitch/roll
    values += [0.1, 0.1, 0.1, 0.1]                           # norm suspension travel
    values += [0.05, 0.05, 0.05 + spin, 0.05 + spin]         # tire slip ratio (rear spin)
    values += [rpm / 60, rpm / 60, rpm / 60, rpm / 60]       # wheel rotation speed
    values += [0, 0, 0, 0]                                   # wheel on rumble strip
    values += [0.0, 0.0, 0.0, 0.0]                           # wheel in puddle
    values += [0.0, 0.0, 0.0, 0.0]                           # surface rumble
    values += [slip_ang, slip_ang, slip_ang, slip_ang]       # tire slip angle
    values += [0.06, 0.06, 0.06, 0.06]                       # tire combined slip
    values += [0.1, 0.1, 0.1, 0.1]                           # suspension travel meters
    values += [100, 5, 800, 2, 6]                            # ordinal/class/PI/drivetrain/cylinders
    values += [3]                                            # car_group
    values += [0.0, 1500.0]                                  # smashable vel diff/mass
    values += [px, 0.0, pz]                                  # position
    values += [speed, power, torque]                         # speed/power/torque
    values += [tire_base, tire_base, tire_base - 5, tire_base - 5]  # tire temps
    values += [12.5, 0.85, t * speed]                        # boost/fuel/distance
    values += [92.3, 93.1, (t % 90), t]                      # laps
    values += [int(t // 90)]                                 # lap_number
    values += [1, throttle & 0xFF, brake & 0xFF, 0, 0, gear & 0xFF]  # position/inputs
    values += [int(40 * math.sin(t * 1.3)), 0, 0]           # steer/line/ai
    return struct.pack(PACKET_FMT, *values)


def main() -> None:
    ap = argparse.ArgumentParser(description="FH6 synthetic telemetry sender")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5300)
    ap.add_argument("--rate", type=float, default=60.0, help="packets per second")
    ap.add_argument("--duration", type=float, default=0.0, help="seconds; 0 = forever")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    period = 1.0 / args.rate
    start = time.monotonic()
    start_ms = 60_000
    sent = 0
    print(f"Streaming {args.rate:.0f} pkt/s of synthetic FH6 telemetry to "
          f"{args.host}:{args.port} (Ctrl+C to stop)")
    try:
        while True:
            t = time.monotonic() - start
            sock.sendto(build_packet(t, start_ms), (args.host, args.port))
            sent += 1
            if sent % int(args.rate or 1) == 0:
                print(f"\r  sent {sent} packets ({t:.0f}s)", end="", flush=True)
            if args.duration and t >= args.duration:
                break
            time.sleep(period)
    except KeyboardInterrupt:
        pass
    finally:
        print(f"\nDone. Sent {sent} packets.")


if __name__ == "__main__":
    main()

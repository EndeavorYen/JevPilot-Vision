"""Fleet mode benchmark: every car on a ring road drives on the same decision core (#3).

One player plus 14 (town) or 28 (city) traffic cars share a one-lane ring with two
signalized stop lines. With fleet mode off, traffic follows a script (car-following,
stops for red) and only the player asks the decider. With fleet mode on, every car
samples its own trajectories and asks the same decider as the player.

Each car sees the others only as ego-relative boxes (rel_x, rel_z) inside sensor
range, tracked frame to frame. No car reads another car's world position.

Policies are jevpilot_vision.fleet.POLICIES.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.benchmark_jevpilot_hierarchical import advance_plant
from jevpilot_vision.fleet import POLICIES, SENSOR_RANGE_M, agent_state, decide
from jevpilot_vision.surround import track_obstacles
from jevpilot_vision.trajectory_sampler import LANE_HALF_M

logger = logging.getLogger("semif.benchmark.fleet")

RING_M = 600.0
DT = 0.05
DECISION_EVERY = 2
SIGNAL_LOOKAHEAD_M = 60.0
# Stop line position (m along the ring) and phase offset (s).
SIGNALS = ((150.0, 0.0), (450.0, 11.0))
GREEN_S, YELLOW_S, RED_S = 10.0, 2.0, 10.0
CYCLE_S = GREEN_S + YELLOW_S + RED_S
# Same contact rule as JevPilot2Simulator's cut-in check.
CONTACT_AHEAD_M = 3.5
CONTACT_SIDE_M = 1.8
THEMES = {"town": 14, "city": 28}  # the web city's traffic counts


def ring_gap(from_s: float, to_s: float) -> float:
    """Signed along-track distance from from_s to to_s, in (-RING_M/2, RING_M/2]."""
    d = (to_s - from_s) % RING_M
    return d - RING_M if d > RING_M / 2.0 else d


def signal_color(t: float, offset_s: float) -> str:
    phase = (t + offset_s) % CYCLE_S
    if phase < GREEN_S:
        return "green"
    if phase < GREEN_S + YELLOW_S:
        return "yellow"
    return "red"


@dataclass
class Car:
    id: str
    z: float  # metres along the ring; only the simulator reads it
    speed_mps: float
    decides: bool
    x: float = 0.0
    steer_angle: float = 0.0
    prev_accel: float = 0.0
    chosen_vec: List[float] = field(default_factory=list)
    hold_offset_m: Optional[float] = None
    tracks: Optional[List[Dict[str, Any]]] = None
    tracks_t: float = 0.0
    crashed: bool = False
    off_track: bool = False
    red_light_violations: int = 0
    distance_m: float = 0.0
    fail_safe: int = 0
    decisions: int = 0


class FleetSimulator:
    def __init__(
        self,
        n_traffic: int = 14,
        seed: int = 42,
        fleet_mode: bool = True,
        speed_ceiling_mps: float = 13.4,
    ):
        self.rng = random.Random(int(seed))
        self.seed = int(seed)
        self.t = 0.0
        self.speed_ceiling_mps = float(speed_ceiling_mps)
        self.fleet_mode = bool(fleet_mode)
        self.collisions = 0
        n = int(n_traffic) + 1
        spacing = RING_M / n
        self.cars: List[Car] = []
        for i in range(n):
            z = (i * spacing + self.rng.uniform(-0.15, 0.15) * spacing) % RING_M
            self.cars.append(
                Car(
                    id="player" if i == 0 else f"vehicle-{i - 1}",
                    z=z,
                    speed_mps=self.rng.uniform(8.0, 12.0),
                    decides=(i == 0) or self.fleet_mode,
                )
            )

    # ---- what one car can see -------------------------------------------------
    def boxes_seen_by(self, car: Car) -> List[Dict[str, Any]]:
        """Ego-relative boxes inside sensor range. rel_z < 0 is behind."""
        out = []
        for other in self.cars:
            if other is car:
                continue
            rel_z = ring_gap(car.z, other.z)
            rel_x = other.x - car.x
            if math.hypot(rel_x, rel_z) <= SENSOR_RANGE_M:
                out.append({"kind": "vehicle", "rel_x": round(rel_x, 2), "rel_z": round(rel_z, 2)})
        return out

    def next_signal(self, car: Car) -> Optional[Dict[str, Any]]:
        best = None
        for line_z, offset in SIGNALS:
            ahead = (line_z - car.z) % RING_M
            if ahead <= SIGNAL_LOOKAHEAD_M and (best is None or ahead < best[0]):
                best = (ahead, signal_color(self.t, offset))
        if best is None:
            return None
        ahead, color = best
        return {
            "control": "traffic_light",
            "distance_to_line_m": round(ahead, 1),
            "signal": color,
            "stop_completed": ahead <= 1.0 and car.speed_mps < 1.0,
            "already_entered": False,
        }

    def observe(self, car: Car, index: int) -> Dict[str, Any]:
        boxes = self.boxes_seen_by(car)
        if car.tracks is not None:
            boxes = track_obstacles(car.tracks, boxes, self.t - car.tracks_t)
        car.tracks, car.tracks_t = boxes, self.t
        return agent_state(
            speed_mps=car.speed_mps,
            speed_ceiling_mps=self.speed_ceiling_mps,
            obstacles=boxes,
            intersection=self.next_signal(car),
            lateral_offset_m=car.x,
            current_steer=car.steer_angle,
            seed=self.seed + index * 7919 + int(self.t * 20),
        )

    # ---- scripted traffic (fleet mode off) ----------------------------------
    def scripted_speed(self, car: Car) -> float:
        """Car-following with a 1.5 s headway; stop for red and yellow."""
        target = self.speed_ceiling_mps
        lead = min(
            (ring_gap(car.z, o.z) for o in self.cars if o is not car and 0.0 < ring_gap(car.z, o.z)),
            default=None,
        )
        if lead is not None:
            target = min(target, max(0.0, (lead - 6.0) / 1.5))
        signal = self.next_signal(car)
        if signal and signal["signal"] in ("red", "yellow") and signal["distance_to_line_m"] > 1.0:
            braking = car.speed_mps * car.speed_mps / (2.0 * 4.0)
            if signal["distance_to_line_m"] <= braking + 8.0:
                target = min(target, max(0.0, (signal["distance_to_line_m"] - 2.0) / 1.5))
        return target

    # ---- one tick -------------------------------------------------------------
    def step(self) -> None:
        self.t += DT
        before = {car.id: car.z for car in self.cars}
        for car in self.cars:
            if car.crashed or car.off_track:
                car.speed_mps = 0.0
                continue
            if car.decides:
                vec = car.chosen_vec or [car.speed_mps, 0.0]
                speed, steer, hold = vec[0], vec[1], car.hold_offset_m
            else:
                speed, steer, hold = self.scripted_speed(car), 0.0, None
            start = car.z
            advance_plant(car, float(speed), float(steer), 0.0, DT, hold_offset_m=hold)
            car.z %= RING_M
            car.distance_m += max(0.0, ring_gap(start, car.z))
            if abs(car.x) > LANE_HALF_M:
                car.off_track = True
        for car in self.cars:
            for line_z, offset in SIGNALS:
                crossed = 0.0 < ring_gap(before[car.id], line_z) <= ring_gap(before[car.id], car.z)
                if crossed and signal_color(self.t, offset) == "red" and car.speed_mps > 2.0:
                    car.red_light_violations += 1
        for car in self.cars:
            for other in self.cars:
                if other is car or (car.crashed and other.crashed):
                    continue
                gap = ring_gap(car.z, other.z)
                if 0.0 <= gap < CONTACT_AHEAD_M and abs(other.x - car.x) < CONTACT_SIDE_M:
                    self.collisions += 1
                    car.crashed = other.crashed = True


def run_fleet_episode(
    engine: Any,
    policy: str,
    *,
    n_traffic: int = 14,
    seed: int = 42,
    fleet_mode: bool = True,
    seconds: float = 30.0,
) -> Dict[str, Any]:
    if policy not in POLICIES:
        raise ValueError(f"unknown fleet policy {policy!r}")
    sim = FleetSimulator(n_traffic=n_traffic, seed=seed, fleet_mode=fleet_mode)
    latencies: List[float] = []
    ticks = 0
    while sim.t < seconds - 1e-9:
        if ticks % DECISION_EVERY == 0:
            for index, car in enumerate(sim.cars):
                if not car.decides or car.crashed or car.off_track:
                    continue
                picked = decide(engine, policy, sim.observe(car, index))
                latencies.append(picked["latency_ms"])
                car.chosen_vec = picked["vector"]
                car.hold_offset_m = picked["hold_offset_m"]
                car.fail_safe += int(picked["fail_safe"])
                car.decisions += 1
        sim.step()
        ticks += 1
    return fleet_summary(sim, policy, latencies, seconds)


def fleet_summary(sim: FleetSimulator, policy: str, latencies: List[float], seconds: float) -> Dict[str, Any]:
    cars = sim.cars
    deciders = [c for c in cars if c.decides]
    latencies = sorted(latencies)
    incident = [c for c in cars if c.crashed or c.off_track or c.red_light_violations]
    return {
        "policy": policy,
        "fleet_mode": sim.fleet_mode,
        "seed": sim.seed,
        "seconds": seconds,
        "cars": len(cars),
        "deciding_cars": len(deciders),
        "collisions": sim.collisions,
        "crashed_cars": sum(1 for c in cars if c.crashed),
        "off_track_cars": sum(1 for c in cars if c.off_track),
        "red_light_violations": sum(c.red_light_violations for c in cars),
        "clean_car_rate": round(1.0 - len(incident) / len(cars), 3),
        "mean_speed_mps": round(sum(c.distance_m for c in cars) / (len(cars) * seconds), 2),
        "player": {
            "crashed": cars[0].crashed,
            "off_track": cars[0].off_track,
            "red_light_violations": cars[0].red_light_violations,
            "distance_m": round(cars[0].distance_m, 1),
        },
        "decisions": sum(c.decisions for c in cars),
        "fail_safe_vetoes": sum(c.fail_safe for c in cars),
        "latency_p50_ms": round(latencies[len(latencies) // 2], 3) if latencies else 0.0,
    }


def main() -> None:
    from demo.server import DecisionEngine

    parser = argparse.ArgumentParser(description="Fleet mode: every car on one decision core")
    parser.add_argument("--mock", action="store_true", help="Mock scorer (no SemArbiter)")
    parser.add_argument("--arbiter-url", default=None, help="Live SemArbiter URL")
    parser.add_argument("--theme", choices=sorted(THEMES), default="town")
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--seeds", default="42,123,2026")
    parser.add_argument("--policies", default=",".join(POLICIES))
    parser.add_argument("--output", default="results/fleet-benchmark.json")
    args = parser.parse_args()

    kwargs: Dict[str, Any] = {"use_mock": args.mock}
    if args.arbiter_url:
        kwargs["arbiter_url"] = args.arbiter_url
    engine = DecisionEngine(**kwargs)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    report: Dict[str, Any] = {
        "benchmark": "JevPilot fleet mode",
        "scorer": "mock" if args.mock else "live",
        "theme": args.theme,
        "traffic": THEMES[args.theme],
        "seconds": args.seconds,
        "seeds": seeds,
        "runs": [],
    }
    for fleet_mode in (False, True):
        for policy in [p for p in args.policies.split(",") if p]:
            for seed in seeds:
                run = run_fleet_episode(
                    engine,
                    policy,
                    n_traffic=THEMES[args.theme],
                    seed=seed,
                    fleet_mode=fleet_mode,
                    seconds=args.seconds,
                )
                report["runs"].append(run)
                logger.info(
                    "fleet=%s %-9s seed=%d collisions=%d red=%d clean=%.2f speed=%.1f",
                    fleet_mode, policy, seed, run["collisions"], run["red_light_violations"],
                    run["clean_car_rate"], run["mean_speed_mps"],
                )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    main()

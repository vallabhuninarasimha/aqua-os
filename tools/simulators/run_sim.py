"""CLI Entrypoint for running the Aqua OS 20-Pond Simulator.

Usage:
    python tools/simulators/run_sim.py --ponds 20 --interval 2 --seed 42
"""

import argparse
import time
from datetime import datetime, timezone

from tools.simulators.clock import SystemClock
from tools.simulators.generator import PondTelemetryGenerator
from tools.simulators.scenarios import PondScenarioConfig, ScenarioType


def main() -> None:
    parser = argparse.ArgumentParser(description="Aqua OS 20-Pond Telemetry Simulator")
    parser.add_argument(
        "--ponds", type=int, default=20, help="Number of simulated ponds (default: 20)"
    )
    parser.add_argument(
        "--interval", type=float, default=2.0, help="Step interval in seconds (default: 2.0)"
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random number generator seed (default: 42)"
    )
    parser.add_argument(
        "--fault-pond",
        type=str,
        default="pond-03",
        help="Pond ID to inject aerator failure into (default: pond-03)",
    )
    args = parser.parse_args()

    clock = SystemClock()
    generator = PondTelemetryGenerator(
        farm_id="farm-alpha",
        pond_count=args.ponds,
        clock=clock,
        seed=args.seed,
    )

    # Invert pond-03 into aerator failure for live demonstration
    if args.fault_pond:
        generator.set_pond_scenario(
            args.fault_pond,
            PondScenarioConfig(
                pond_id=args.fault_pond,
                scenario_type=ScenarioType.AERATOR_FAILURE,
                duration_hours=6.0,
            ),
        )

    print("=" * 80)
    print(
        f" AQUA OS SIMULATOR: {args.ponds} Ponds Initialized | "
        f"Seed: {args.seed} | Interval: {args.interval}s"
    )
    print(f" Fault Injected: {args.fault_pond} -> Scenario: AERATOR_FAILURE")
    print(" Press Ctrl+C to terminate.")
    print("=" * 80)

    try:
        step_idx = 0
        while True:
            step_idx += 1
            packets = generator.step(dt_seconds=args.interval)
            now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")

            # Print summary of first 4 ponds including fault pond
            summary_parts = []
            for p in packets[:4]:
                do_val = p.metrics[p.metrics.keys().__iter__().__next__()].value
                summary_parts.append(f"{p.pond_id}: DO={do_val:.2f}")

            summary_str = " | ".join(summary_parts)
            print(f"[{now_str}] Step #{step_idx} | {len(packets)} ponds | {summary_str}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nSimulator terminated cleanly.")


if __name__ == "__main__":
    main()

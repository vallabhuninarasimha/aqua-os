"""CLI Entrypoint for running the Aqua OS Edge Sovereign Daemon.

Usage:
    python -m apps.edge.src.run_edge
"""

import time
from datetime import datetime, timezone

from apps.edge.src.config import edge_settings
from apps.edge.src.orchestrator import EdgeRuntime
from apps.edge.src.storage import SQLiteEdgeStorage
from apps.edge.src.transport import HttpSyncTransport, MockSyncTransport
from tools.simulators.clock import SystemClock
from tools.simulators.generator import PondTelemetryGenerator


def main() -> None:
    print("=" * 80)
    print(
        f" AQUA OS EDGE DAEMON: Gateway: {edge_settings.gateway_id} | Farm: {edge_settings.farm_id}"
    )
    print(f" Database WAL: {edge_settings.db_path.absolute()}")
    print(" Sovereign Local Control Active | Independent of Internet Connectivity")
    print(" Press Ctrl+C to terminate.")
    print("=" * 80)

    storage = SQLiteEdgeStorage(
        db_path=edge_settings.db_path,
        max_queue_depth=edge_settings.max_queue_depth,
    )

    # Use HTTP sync if API URL is set, otherwise mock transport
    if edge_settings.api_url:
        transport = HttpSyncTransport(
            endpoint_url=f"{edge_settings.api_url}/telemetry",
            auth_token=edge_settings.api_token,
        )
    else:
        transport = MockSyncTransport(initially_connected=False)

    clock = SystemClock()
    edge = EdgeRuntime(
        storage=storage,
        transport=transport,
        gateway_id=edge_settings.gateway_id,
        farm_id=edge_settings.farm_id,
        clock=clock,
    )

    # Local simulator feed generating 20 ponds for local demonstration
    sim = PondTelemetryGenerator(
        farm_id=edge_settings.farm_id,
        pond_count=20,
        clock=clock,
        seed=101,
    )

    try:
        cycle = 0
        while True:
            cycle += 1
            packets = sim.step(dt_seconds=edge_settings.sync_interval_seconds)

            # 1. Process all 20 ponds locally (sovereign loop)
            alert_count = 0
            for pkt in packets:
                eval_res = edge.process_telemetry(pkt)
                if not eval_res.is_safe:
                    alert_count += 1

            # 2. Attempt sync cycle if connected
            synced = edge.sync_pending(batch_size=edge_settings.batch_size)

            # 3. Report diagnostics
            diag = edge.get_diagnostics()
            now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
            sovereign_label = "OFFLINE-SOVEREIGN" if diag.sovereign_mode_active else "CONNECTED"

            print(
                f"[{now_str}] Cycle #{cycle} | Status: {sovereign_label} | "
                f"Processed: {len(packets)} ponds | Alerts: {alert_count} | "
                f"Synced: {synced} | Queue Depth: {diag.queue_depth}"
            )

            time.sleep(edge_settings.sync_interval_seconds)
    except KeyboardInterrupt:
        print("\nEdge Daemon terminated cleanly.")


if __name__ == "__main__":
    main()

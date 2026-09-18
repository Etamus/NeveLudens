from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import zmq

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from neveludens.flybrain_policy import MaleCNSPolicy


def main() -> int:
    parser = argparse.ArgumentParser(description="MaleCNS v1.0 inference server")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--data", type=Path, default=REPO / ".cache" / "malecns")
    parser.add_argument("--telemetry", type=Path, default=REPO / "out" / "flybrain_telemetry.json")
    parser.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
    args = parser.parse_args()

    print("Carregando MaleCNS v1.0 (166.700 neurônios)...", flush=True)
    policy = MaleCNSPolicy(args.data, telemetry_path=args.telemetry, device=args.device)

    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.bind(f"tcp://*:{args.port}")
    poller = zmq.Poller()
    poller.register(socket, zmq.POLLIN)
    print(f"MaleCNS pronto na porta {args.port}.", flush=True)

    try:
        while True:
            events = dict(poller.poll(timeout=100))
            if socket not in events:
                continue
            request = pickle.loads(socket.recv())
            request_type = request.get("type")
            try:
                if request_type == "reset":
                    policy.reset()
                    response = {"status": "ok"}
                elif request_type == "info":
                    response = {"status": "ok", "info": policy.info()}
                elif request_type == "predict":
                    response = {"status": "ok", "pred": policy.predict(request["image"])}
                else:
                    response = {"status": "error", "message": f"Unknown request type: {request_type}"}
            except Exception as exc:
                print(f"Falha no MaleCNS: {exc}", flush=True)
                response = {"status": "error", "message": str(exc)}
            socket.send(pickle.dumps(response))
    except KeyboardInterrupt:
        return 0
    finally:
        socket.close()
        context.term()


if __name__ == "__main__":
    raise SystemExit(main())

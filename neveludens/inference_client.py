import pickle
import time
from pathlib import Path

import numpy as np
import zmq

from neveludens.stop_control import StopRequested, normalize_stop_file, stop_requested

class ModelClient:
    """Client for model inference server."""
    
    def __init__(self, host="localhost", port=5555, stop_file=None):
        """
        Initialize client connection.
        
        Args:
            host: Server hostname or IP
            port: Server port
        """
        self.host = host
        self.port = port
        self.timeout_ms = 30000
        self.stop_file: Path | None = normalize_stop_file(stop_file)
        self._closed = False

        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.connect(f"tcp://{host}:{port}")
        self.socket.setsockopt(zmq.RCVTIMEO, self.timeout_ms)  # Set receive timeout
        
        print(f"Connected to model server at {host}:{port}")

    def _recv_response(self):
        poller = zmq.Poller()
        poller.register(self.socket, zmq.POLLIN)
        deadline = time.monotonic() + (self.timeout_ms / 1000.0)

        while True:
            if stop_requested(self.stop_file):
                self.close()
                raise StopRequested("Stop requested while waiting for model response")

            remaining_ms = int(max(0.0, deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                raise TimeoutError(f"Model server timed out after {self.timeout_ms} ms")

            events = dict(poller.poll(timeout=min(100, remaining_ms)))
            if self.socket in events and events[self.socket] == zmq.POLLIN:
                return pickle.loads(self.socket.recv())
    
    def predict(self, image: np.ndarray) -> dict:
        """
        Send an image and receive predicted actions.
        
        Args:
            image: numpy array (H, W, 3) in RGB format
            
        Returns:
            List of action dicts, each containing:
                - j_left: [x, y] left joystick position
                - j_right: [x, y] right joystick position  
                - buttons: list of button values
        """
        if stop_requested(self.stop_file):
            self.close()
            raise StopRequested("Stop requested before model prediction")

        request = {
            "type": "predict",
            "image": image
        }
        
        self.socket.send(pickle.dumps(request))
        response = self._recv_response()
        
        if response["status"] != "ok":
            raise RuntimeError(f"Server error: {response.get('message', 'Unknown error')}")
        
        return response["pred"]
    
    def reset(self):
        """Reset the server's session (clear buffers)."""
        if stop_requested(self.stop_file):
            self.close()
            raise StopRequested("Stop requested before model reset")
        request = {"type": "reset"}
        
        self.socket.send(pickle.dumps(request))
        response = self._recv_response()
        
        if response["status"] != "ok":
            raise RuntimeError(f"Server error: {response.get('message', 'Unknown error')}")
        
        print("Session reset")

    def info(self) -> dict:
        """Get session info from the server."""
        if stop_requested(self.stop_file):
            self.close()
            raise StopRequested("Stop requested before model info")
        request = {"type": "info"}
        
        self.socket.send(pickle.dumps(request))
        response = self._recv_response()
        
        if response["status"] != "ok":
            raise RuntimeError(f"Server error: {response.get('message', 'Unknown error')}")
        
        return response["info"]

    def close(self):
        """Close the connection."""
        if self._closed:
            return
        self._closed = True
        try:
            self.socket.close()
        except Exception:
            pass
        try:
            self.context.term()
        except Exception:
            pass
        print("Connection closed")
    
    def __enter__(self):
        """Support for context manager."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close connection when exiting context."""
        self.close()

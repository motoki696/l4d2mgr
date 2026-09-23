import os
import sys
import socket
import struct
from typing import Tuple, Optional

SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0
MIN_PACKET_SIZE = 10
MAX_PACKET_SIZE = 4110


class RconError(Exception):
    """Base exception for RCON errors."""


class RconAuthError(RconError):
    """Raised when authentication fails."""


class RconClient:
    def __init__(self, host: str, port: int, password: str, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._connected = False
        self._next_id = 1

    def connect(self) -> None:
        if self._connected:
            return
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._authenticate()
            self._connected = True
        except RconAuthError:
            self.close()
            raise
        except RconError:
            self.close()
            raise
        except (socket.timeout, OSError) as exc:
            self.close()
            raise RconError(str(exc)) from exc
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None
        self._connected = False

    def __enter__(self) -> "RconClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def command(self, cmd: str) -> str:
        if not self._connected:
            raise RconError("Not connected")
        if any(c in cmd for c in ("\x00", "\r", "\n")):
            raise RconError("Command contains forbidden characters")
        body = cmd.encode("utf-8")
        if len(body) > 1000:
            raise RconError("Command too long")
        try:
            cmd_id = self._next_id
            self._next_id = self._wrap_id(self._next_id + 1)
            echo_id = self._next_id
            self._next_id = self._wrap_id(self._next_id + 1)
            self._send_packet(cmd_id, SERVERDATA_EXECCOMMAND, body)
            self._send_packet(echo_id, SERVERDATA_RESPONSE_VALUE, b"")
            response_chunks: list[bytes] = []
            while True:
                packet_id, packet_type, packet_body = self._recv_packet()
                if packet_id == cmd_id:
                    response_chunks.append(packet_body)
                elif packet_id == echo_id:
                    break
                else:
                    continue
            return b"".join(response_chunks).decode("utf-8", errors="replace")
        except (socket.timeout, OSError) as exc:
            raise RconError("Communication error") from exc

    def _authenticate(self) -> None:
        auth_id = self._next_id
        self._next_id = self._wrap_id(self._next_id + 1)
        self._send_packet(auth_id, SERVERDATA_AUTH, self.password.encode("utf-8"))
        while True:
            pkt_id, pkt_type, _ = self._recv_packet()
            if pkt_type == SERVERDATA_RESPONSE_VALUE:
                continue
            if pkt_type == SERVERDATA_AUTH_RESPONSE:
                if pkt_id == -1:
                    raise RconAuthError("Authentication failed")
                break

    def _send_packet(self, packet_id: int, packet_type: int, body: bytes) -> None:
        size = 4 + 4 + len(body) + 2
        packet = struct.pack("<i", size)
        packet += struct.pack("<i", packet_id)
        packet += struct.pack("<i", packet_type)
        packet += body
        packet += b"\x00\x00"
        try:
            assert self._sock is not None
            self._sock.sendall(packet)
        except (socket.timeout, OSError) as exc:
            raise RconError("Send error") from exc

    def _recv_packet(self) -> Tuple[int, int, bytes]:
        assert self._sock is not None
        raw_size = self._recv_exact(4)
        size, = struct.unpack("<i", raw_size)
        if size < MIN_PACKET_SIZE or size > MAX_PACKET_SIZE:
            raise RconError("Invalid packet size")
        payload = self._recv_exact(size)
        pkt_id, pkt_type = struct.unpack("<ii", payload[:8])
        body = payload[8:-2]
        return pkt_id, pkt_type, body

    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        data = bytearray()
        while len(data) < n:
            chunk = self._sock.recv(n - len(data))
            if not chunk:
                raise RconError("Connection closed unexpectedly")
            data.extend(chunk)
        return bytes(data)

    def _wrap_id(self, value: int) -> int:
        max_int32 = 0x7FFFFFFF
        if value >= max_int32:
            return 1
        return value

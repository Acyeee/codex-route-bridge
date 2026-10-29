"""Read and rewrite Electron asar headers for the isolated compatibility runtime."""
import hashlib
import json
import struct
import subprocess


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_header(stream):
    prefix = struct.unpack("<4I", stream.read(16))
    raw = stream.read(prefix[3])
    return json.loads(raw), 8 + prefix[1], raw


def encode_header(tree):
    raw = json.dumps(tree, ensure_ascii=False, separators=(",", ":")).encode()
    payload = struct.pack("<I", len(raw)) + raw
    payload += bytes((-len(payload)) % 4)
    pickle = struct.pack("<I", len(payload)) + payload
    return struct.pack("<II", 4, len(pickle)) + pickle, raw


def node_check(node, source, output):
    output.write_bytes(source)
    subprocess.run([node, "--check", str(output)], check=True, capture_output=True)

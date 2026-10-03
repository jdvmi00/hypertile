"""Read named wl_output globals on a fresh, bounded Wayland connection.

Only core display/registry/output messages are used; no surfaces, input, or
file descriptors are requested. The small wire client avoids adding a native
build step or a Python binding dependency to the installed display service.
Wire definitions: /usr/share/wayland/wayland.xml (wl_output version 4).
"""
import os
from pathlib import Path
import socket
import struct
import time


def words(*values):
    return struct.pack('=' + 'I' * len(values), *values)


def string(value):
    data = value.encode('utf-8') + b'\0'
    return words(len(data)) + data + b'\0' * (-len(data) % 4)


def read_string(data, offset=0):
    size, = struct.unpack_from('=I', data, offset)
    start = offset + 4
    if not size or start + size > len(data) or data[start + size - 1] != 0:
        raise ValueError('Invalid Wayland string')
    return data[start:start + size - 1].decode('utf-8'), start + ((size + 3) & ~3)


def outputs(timeout=2.0):
    """Return connector names advertised to new clients, or raise on failure.

    Never consume WAYLAND_SOCKET: it may belong to the calling application.
    A separate connection is essential to test what *new* clients can see.
    """
    display = os.environ.get('WAYLAND_DISPLAY', 'wayland-0')
    if not os.path.isabs(display):
        runtime = os.environ.get('XDG_RUNTIME_DIR')
        if not runtime:
            raise OSError('XDG_RUNTIME_DIR is unavailable')
        display = str(Path(runtime) / display)
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise TimeoutError('Wayland output check timed out')
            connection.settimeout(value)

        def send(object_id, opcode, payload):
            remaining()
            connection.sendall(words(object_id, ((8 + len(payload)) << 16) | opcode) + payload)

        def receive(size):
            data = bytearray()
            while len(data) < size:
                remaining()
                part = connection.recv(size - len(data))
                if not part:
                    raise OSError('Wayland disconnected during output check')
                data.extend(part)
            return data

        remaining()
        connection.connect(display)
        # Object IDs must be allocated consecutively, including sync callbacks.
        send(1, 1, words(2))  # wl_display.get_registry
        globals_by_id, bound, names = {}, {}, {}

        def roundtrip(callback):
            send(1, 0, words(callback))  # wl_display.sync
            while True:
                object_id, header = struct.unpack('=II', receive(8))
                size, opcode = header >> 16, header & 0xffff
                if size < 8 or size % 4:
                    raise ValueError('Invalid Wayland message length')
                data = receive(size - 8)
                if object_id == 1 and opcode == 0:  # wl_display.error
                    message, _ = read_string(data, 8)
                    raise OSError('Wayland output check failed: ' + message)
                if object_id == callback and opcode == 0:
                    return
                if object_id == 2 and opcode == 0:  # registry.global
                    global_id, = struct.unpack_from('=I', data)
                    interface, offset = read_string(data, 4)
                    version, = struct.unpack_from('=I', data, offset)
                    if interface == 'wl_output':
                        globals_by_id[global_id] = version
                elif object_id == 2 and opcode == 1:  # registry.global_remove
                    global_id, = struct.unpack('=I', data)
                    globals_by_id.pop(global_id, None)
                elif object_id in bound and opcode == 4:  # wl_output.name (v4)
                    names[bound[object_id]], _ = read_string(data)

        roundtrip(3)
        next_id = 4
        for global_id, version in list(globals_by_id.items()):
            if version < 4:
                raise OSError('Named Wayland outputs require wl_output version 4')
            bound[next_id] = global_id
            send(2, 0, words(global_id) + string('wl_output') + words(4, next_id))
            next_id += 1
        roundtrip(next_id)
        return {name for global_id, name in names.items() if global_id in globals_by_id}

"""Wayland registry protocol and bounded-failure regression tests."""
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'displays'))
from wayland import outputs, string, words
from adapter import Adapter, DisplayError


def message(object_id, opcode, data=b''):
    return words(object_id, ((8 + len(data)) << 16) | opcode) + data


class Tests(unittest.TestCase):
    def serve(self, action):
        directory = tempfile.TemporaryDirectory(prefix='ht-wl-')
        self.addCleanup(directory.cleanup)
        path = str(Path(directory.name) / 'wayland-test')
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(path)
        server.listen(1)
        server.settimeout(2)
        failures = []

        def run():
            try:
                with server.accept()[0] as client:
                    client.settimeout(2)
                    action(client)
            except Exception as error:
                failures.append(error)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        def finish():
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])

        self.addCleanup(finish)
        return patch.dict(os.environ, WAYLAND_DISPLAY=path)

    @staticmethod
    def request(client):
        def receive(n):
            result = b''
            while len(result) < n:
                part = client.recv(n - len(result))
                if not part:
                    raise EOFError()
                result += part
            return result
        object_id, header = struct.unpack('=II', receive(8))
        return object_id, header & 0xffff, receive((header >> 16) - 8)

    def initial(self, client, globals):
        self.assertEqual(self.request(client), (1, 1, words(2)))
        self.assertEqual(self.request(client), (1, 0, words(3)))
        data = b''.join(message(2, 0, words(number) + string(interface) + words(version))
                        for number, interface, version in globals)
        data += message(3, 0, words(0)) + message(1, 1, words(3))
        # Exercise arbitrary stream fragmentation across headers and strings.
        for i in range(0, len(data), 3):
            client.sendall(data[i:i+3])

    def test_named_outputs_and_removed_global(self):
        def action(client):
            self.initial(client, [(40, 'wl_compositor', 6), (50, 'wl_output', 4), (60, 'wl_output', 4)])
            for number, object_id in [(50, 4), (60, 5)]:
                self.assertEqual(self.request(client),
                                 (2, 0, words(number) + string('wl_output') + words(4, object_id)))
            self.assertEqual(self.request(client), (1, 0, words(6)))
            client.sendall(message(4, 4, string('DP-1')) + message(5, 4, string('HDMI-A-1'))
                           + message(2, 1, words(60)) + message(6, 0, words(0)))
        with self.serve(action):
            self.assertEqual(outputs(), {'DP-1'})

    def test_empty_registry_is_not_an_output(self):
        def action(client):
            self.initial(client, [])
            self.assertEqual(self.request(client), (1, 0, words(4)))
            client.sendall(message(4, 0, words(0)))
        with self.serve(action):
            self.assertEqual(outputs(), set())

    def test_protocol_error_is_not_success(self):
        def action(client):
            self.request(client)
            self.request(client)
            client.sendall(message(1, 0, words(1, 0) + string('output vanished')))
        with self.serve(action), self.assertRaisesRegex(OSError, 'output vanished'):
            outputs()

    def test_roundtrip_has_deadline(self):
        with self.serve(lambda client: time.sleep(.15)), self.assertRaises(TimeoutError):
            outputs(timeout=.03)

    def test_guard_checks_connectors_not_just_output_count(self):
        displays = [dict(connector='DP-1', enabled=True), dict(connector='HDMI-A-1', enabled=True, mirror_of='DP-1')]
        with patch('wayland.outputs', return_value={'HDMI-A-1'}), self.assertRaisesRegex(DisplayError, 'Missing: DP-1'):
            Adapter().verify_outputs(displays, timeout=.01)
        with patch('wayland.outputs', return_value={'DP-1'}):
            Adapter().verify_outputs(displays)

    def test_guard_waits_for_delayed_registration(self):
        with patch('wayland.outputs', side_effect=[set(), {'DP-1'}]):
            Adapter().verify_outputs([dict(connector='DP-1', enabled=True)])


if __name__ == '__main__':
    unittest.main()

import ctypes as C
from dataclasses import replace
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mouse_hid as hid


def report(operation=8, address=0x160, count=10):
    value = bytearray(17)
    value[0:6] = bytes((8, operation, 0, address >> 8, address & 255, count))
    value[-1] = (0x55 - sum(value)) & 255
    return bytes(value)


class FakeNative:
    """Exercise overlapped lifetime/order without loading a Windows DLL."""
    def __init__(self, responses=None, fail_write=False, pending_write=False, short_read=False, acknowledge_cancel=True):
        self.responses = list(responses or [])
        self.fail_write = fail_write
        self.pending_write = pending_write
        self.short_read = short_read
        self.acknowledge_cancel = acknowledge_cancel
        self.code = 997
        self.events = {}
        self.next_event = 1000
        self.pending_read = None
        self.activity = []
        self.closed = []
        self.written = False
        self.cancelled = []
        self.types = {}

    def last_error(self):
        return self.code

    def CreateFileW(self, *args):
        return 100

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True

    def CreateEventW(self, *args):
        self.next_event += 1
        self.events[self.next_event] = False
        return self.next_event

    def ResetEvent(self, event):
        self.events[event] = False
        return True

    def HidD_FlushQueue(self, handle):
        self.activity.append("flush")
        return True

    def ReadFile(self, handle, buffer, length, transferred, overlapped):
        event = overlapped._obj.hEvent
        self.types[event] = "read"
        self.activity.append("read")
        self.pending_read = (buffer, event)
        if self.written:
            self.deliver()
        return self.events[event]

    def WriteFile(self, handle, buffer, length, transferred, overlapped):
        self.activity.append("write")
        self.types[overlapped._obj.hEvent] = "write"
        if self.fail_write:
            self.code = 5
            return False
        self.written = True
        if self.pending_write:
            self.code = 997
            return False
        self.events[overlapped._obj.hEvent] = True
        self.deliver()
        return True

    def deliver(self):
        if self.pending_read is not None and self.responses:
            buffer, event = self.pending_read
            C.memmove(buffer, self.responses.pop(0), 17)
            self.events[event] = True
            self.pending_read = None

    def WaitForSingleObject(self, event, timeout):
        return 0 if self.events[event] else 258

    def GetOverlappedResult(self, handle, overlapped, transferred, wait):
        if wait:
            raise AssertionError("Unbounded native waits are forbidden")
        transferred._obj.value = 16 if self.short_read and self.types[overlapped._obj.hEvent] == "read" else 17
        return True

    def CancelIoEx(self, handle, overlapped):
        self.cancelled.append(overlapped._obj.hEvent)
        if self.acknowledge_cancel:
            self.events[overlapped._obj.hEvent] = True
        return True


class HidMetadataTests(unittest.TestCase):
    def device(self):
        return hid.DeviceInfo(r"\\?\hid#vid_3554&pid_f55e&mi_01&col05#device",
                              0x3554, 0xF55E, 0xFF00, 1, 17, 17, 0, "Redragon")

    def test_import_is_portable_and_lazy(self):
        if os.name != "nt":
            self.assertIsNone(hid._native)
            with self.assertRaisesRegex(OSError, "somente no Windows"):
                hid.enumerate_devices()
            self.assertIsNone(hid._native)

    def test_native_structures_have_windows_layout(self):
        self.assertEqual(C.sizeof(hid.DWORD), 4)
        self.assertEqual(C.sizeof(hid.GUID), 16)
        self.assertEqual(C.sizeof(hid.HIDD_ATTRIBUTES), 12)
        self.assertEqual(C.sizeof(hid.HIDP_CAPS), 64)
        self.assertEqual(C.sizeof(hid.SP_DEVICE_INTERFACE_DATA), 32 if C.sizeof(C.c_void_p) == 8 else 28)
        self.assertEqual(C.sizeof(hid.OVERLAPPED), 32 if C.sizeof(C.c_void_p) == 8 else 20)

    def test_compatibility_is_exact(self):
        original = self.device()
        self.assertTrue(original.compatible)
        self.assertTrue(replace(original, path=original.path.upper()).compatible)
        self.assertTrue(replace(original, product_id=0xF5D5).compatible)
        for changed in (replace(original, vendor_id=0x25A7), replace(original, product_id=0xFFFF),
                        replace(original, input_report_length=64), replace(original, output_report_length=0),
                        replace(original, path=original.path.replace("mi_01", "mi_00")),
                        replace(original, path=original.path.replace("col05", "col04")),
                        replace(original, path=original.path.replace("col05", "col050"))):
            with self.subTest(changed=changed):
                self.assertFalse(changed.compatible)

    def test_captured_report_validation(self):
        request = bytes.fromhex("08 08 00 01 60 0a 00 00 00 00 00 00 00 00 00 00 da")
        response = bytes.fromhex("08 08 00 01 60 0a 04 80 01 00 81 06 00 41 06 00 87")
        self.assertTrue(hid._valid_report(request))
        self.assertTrue(hid._matches_response(request, response))
        self.assertFalse(hid._matches_response(report(address=0x180), response))
        self.assertFalse(hid._matches_response(report(operation=7), response))
        self.assertFalse(hid._valid_report(response[:-1] + b"\0"))

    def test_prearm_read_and_skip_unrelated_input_without_resend(self):
        request = report()
        native = FakeNative([report(address=0x180), request])
        with patch.object(hid, "_get_native", return_value=native), patch.object(hid, "_query_device", return_value=self.device()):
            with hid.WindowsHid(self.device().path) as device:
                self.assertEqual(device.byte_exchange(request), request)
        self.assertEqual(native.activity, ["flush", "read", "write", "read"])
        self.assertEqual(len(native.closed), 3)  # one device and two event handles
        self.assertEqual(native.cancelled, [])

    def test_timeout_cancels_pending_read_and_releases_storage(self):
        native = FakeNative()
        with patch.object(hid, "_get_native", return_value=native), patch.object(hid, "_query_device", return_value=self.device()):
            with hid.WindowsHid(self.device().path) as device:
                with self.assertRaises(TimeoutError):
                    device.byte_exchange(report(), 1)
        self.assertEqual(len(native.cancelled), 1)
        self.assertEqual(len(native.closed), 3)
        self.assertEqual(native.activity.count("write"), 1)

    def test_failed_send_never_attempts_fallback_or_retry(self):
        native = FakeNative(fail_write=True)
        with patch.object(hid, "_get_native", return_value=native), patch.object(hid, "_query_device", return_value=self.device()):
            with hid.WindowsHid(self.device().path) as device:
                with self.assertRaises(hid.HidError):
                    device.byte_exchange(report())
        self.assertEqual(native.activity, ["flush", "read", "write"])
        self.assertEqual(len(native.cancelled), 1)
        self.assertEqual(len(native.closed), 3)

    def test_pending_write_timeout_cancels_both_operations(self):
        native = FakeNative(pending_write=True)
        with patch.object(hid, "_get_native", return_value=native), patch.object(hid, "_query_device", return_value=self.device()):
            with hid.WindowsHid(self.device().path) as device:
                with self.assertRaises(TimeoutError):
                    device.byte_exchange(report(), 1)
        self.assertEqual(native.activity.count("write"), 1)
        self.assertEqual(len(native.cancelled), 2)
        self.assertEqual(len(native.closed), 3)

    def test_short_response_is_rejected(self):
        native = FakeNative([report()], short_read=True)
        with patch.object(hid, "_get_native", return_value=native), patch.object(hid, "_query_device", return_value=self.device()):
            with hid.WindowsHid(self.device().path) as device:
                with self.assertRaisesRegex(hid.HidError, "tamanho inesperado: 16"):
                    device.byte_exchange(report())
        self.assertEqual(len(native.closed), 3)

    def test_stuck_cancellation_retains_native_memory_and_closes_connection(self):
        native = FakeNative(pending_write=True, acknowledge_cancel=False)
        retired_before = set(hid._retired_operations)
        # Leave daemon startup pending so the test controls completion deterministically.
        with patch.object(hid, "_get_native", return_value=native), patch.object(hid, "_query_device", return_value=self.device()), patch.object(hid.threading.Thread, "start"):
            with hid.WindowsHid(self.device().path) as device:
                with self.assertRaises(TimeoutError):
                    device.byte_exchange(report(), 1)
                self.assertIsNone(device._handle)
                with self.assertRaisesRegex(hid.HidError, "conexão USB está fechada"):
                    device.byte_exchange(report())
        retired = hid._retired_operations - retired_before
        self.assertEqual(len(retired), 2)
        self.assertEqual(native.closed, [100])  # live OVERLAPPED events/buffers not freed
        for operation in retired:
            self.assertEqual(C.sizeof(operation.buffer), 17)
            self.assertEqual(C.sizeof(operation.transferred), 4)
            native.events[operation.event] = True
            operation._release_when_complete()
        self.assertEqual(hid._retired_operations, retired_before)
        self.assertEqual(len(native.closed), 3)


if __name__ == "__main__":
    unittest.main()

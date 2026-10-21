"""Captured report fixtures and failure semantics without a USB device."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from mouse_protocol import (
    CONFIG_SIZE, SHORTCUT_SIZE, IdentityError, ProfileChangedError, Protocol,
    ProtocolError, Snapshot, build_report, checksum, hardware_index, key_address,
    key_record, matches_report, shortcut, shortcut_address, valid_report,
)


class FakeTransport:
    def __init__(self):
        self.active = 1
        self.memory = {i: bytearray([i * 11] * 0x300) for i in range(4)}
        for memory in self.memory.values():
            for address in range(0x60, 0xA0, 4):
                memory[address:address + 4] = key_record(0)
        self.identity = bytes.fromhex("f6 18 30 eb 17 29 02 00")
        self.identity_count = 8
        self.calls = []
        self.writes = []
        self.corrupt_write = False
        self.bad_write_ack = False
        self.flip_after_write = None
        self.flip_after_read = None
        self.fail_read = None
        self.fail_select = None
        self.primary = OSError("simulated primary read failure")

    def byte_exchange(self, request, timeout_ms=2000):
        assert valid_report(request)
        assert timeout_ms == 2000
        self.calls.append(bytes(request))
        op, address, count = request[1], int.from_bytes(request[3:5], "big"), request[5]
        if op == 1:
            return build_report(op, count=self.identity_count, data=self.identity[:self.identity_count])
        if op == 2:
            return request
        if op == 0x0E:
            return build_report(op, count=1, data=bytes((self.active,)))
        if op == 0x0F:
            if request[6] == self.fail_select:
                raise OSError("simulated restore selection failure")
            self.active = request[6]
            return request
        if op == 0x12:
            return build_report(op, count=2, data=b"\x04\x01")
        if op == 8:
            if self.fail_read == self.active:
                self.fail_read = None
                self.fail_select = 1
                raise self.primary
            result = build_report(op, address, count, self.memory[self.active][address:address + count])
            if self.flip_after_read is not None:
                self.active, self.flip_after_read = self.flip_after_read, None
            return result
        if op == 7:
            self.writes.append((self.active, address, request[6:6 + count]))
            self.memory[self.active][address:address + count] = request[6:6 + count]
            if self.corrupt_write:
                self.memory[self.active][address] ^= 1
            if self.flip_after_write is not None:
                self.active, self.flip_after_write = self.flip_after_write, None
            return bytes(REPORT_SIZE) if self.bad_write_ack else request
        raise AssertionError(f"Unknown fake op {op}")


REPORT_SIZE = 17


class CodecTests(unittest.TestCase):
    def test_captured_report_frames_are_exact(self):
        cases = [
            ((8, 0x160, 10), "08 08 00 01 60 0a 00 00 00 00 00 00 00 00 00 00 da"),
            ((7, 0x220, 8, bytes.fromhex("02 82 b5 00 42 b5 00 25")), "08 07 00 02 20 08 02 82 b5 00 42 b5 00 25 00 00 c7"),
            ((7, 0x0C, 4, bytes.fromhex("14 14 00 2d")), "08 07 00 00 0c 04 14 14 00 2d 00 00 00 00 00 00 e1"),
            ((0x0F, 0, 1, b"\x01"), "08 0f 00 00 00 01 01 00 00 00 00 00 00 00 00 00 3c"),
        ]
        for arguments, captured in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(build_report(*arguments), bytes.fromhex(captured))

    def test_bad_checksum_and_stale_address_are_rejected(self):
        response = bytes.fromhex("08 08 00 01 60 0a 04 80 01 00 81 06 00 41 06 00 87")
        self.assertTrue(valid_report(response))
        self.assertTrue(matches_report(build_report(8, 0x160, 10), response))
        self.assertFalse(matches_report(build_report(8, 0x180, 10), response))
        self.assertFalse(valid_report(response[:-1] + bytes((response[-1] ^ 1,))))

    def test_shortcuts_match_captured_and_decompiled_encodings(self):
        cases = [
            ((1, 6), "04 80 01 00 81 06 00 41 06 00 40 01 00 c1"),
            ((8, 0x19), "04 80 08 00 81 19 00 41 19 00 40 08 00 8d"),
            ((8, 0x1E), "04 80 08 00 81 1e 00 41 1e 00 40 08 00 83"),
            ((0, 0x46), "02 81 46 00 41 46 00 05"),
        ]
        for arguments, captured in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(shortcut(*arguments), bytes.fromhex(captured))

    def test_physical_buttons_use_manufacturer_drawing(self):
        self.assertEqual([(hardware_index(i), key_address(i), shortcut_address(i)) for i in (4, 5, 6, 7)],
                         [(4, 0x70, 0x180), (3, 0x6C, 0x160), (9, 0x84, 0x220), (10, 0x88, 0x240)])
        self.assertEqual(key_record(9), bytes.fromhex("09 00 00 4c"))

    def test_argument_bounds_are_enforced_before_transport(self):
        for call in (lambda: build_report(256), lambda: build_report(8, -1),
                     lambda: build_report(8, count=11), lambda: build_report(7, count=1, data=b"xx"),
                     lambda: shortcut(256, 6), lambda: shortcut(1, 0), lambda: key_address(True),
                     lambda: build_report(8, data=4)):
            with self.subTest(call=call), self.assertRaises((ValueError, TypeError)):
                call()

    def test_raw_snapshot_can_represent_damaged_record_for_recovery(self):
        raw = Snapshot(0, bytes(CONFIG_SIZE), bytes(SHORTCUT_SIZE))
        with self.assertRaises(ValueError):
            raw.validate()
        self.assertEqual(raw.read(0x88, 4), bytes(4))
        with self.assertRaises(ValueError):
            raw.read(0xC0, 1)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.mouse = FakeTransport()
        self.protocol = Protocol(self.mouse)

    def test_identity_sends_fresh_challenge_and_changes_no_profile_or_memory(self):
        before = {i: bytes(data) for i, data in self.mouse.memory.items()}
        with patch("mouse_protocol.os.urandom", return_value=b"test"):
            result = self.protocol.confirm_identity(expected_type=2)
        self.assertEqual(result["cid"], 0x17)
        self.assertEqual(result["mid"], 0x29)
        self.assertEqual(result["device_type"], 2)
        self.assertEqual(self.mouse.calls[0][6:14], b"test" + bytes(4))
        self.assertEqual(before, {i: bytes(data) for i, data in self.mouse.memory.items()})
        self.assertEqual(self.mouse.active, 1)
        self.assertEqual(self.mouse.writes, [])

    def test_receiver_identity_supported_but_type_mismatch_rejected(self):
        self.mouse.identity = self.mouse.identity[:6] + b"\x00\x00"
        self.assertEqual(self.protocol.confirm_identity(expected_type=0)["device_type"], 0)
        with self.assertRaises(IdentityError):
            self.protocol.confirm_identity(expected_type=2)
        for bad in (True, 0.0, 1, "2"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.protocol.confirm_identity(expected_type=bad)

    def test_wrong_model_and_truncated_identity_rejected(self):
        for offset in (4, 5, 6):
            original = self.mouse.identity
            changed = bytearray(original)
            changed[offset] = 99
            self.mouse.identity = bytes(changed)
            with self.subTest(offset=offset), self.assertRaises(IdentityError):
                self.protocol.confirm_identity()
            self.mouse.identity = original
        self.mouse.identity_count = 7
        with self.assertRaises(IdentityError):
            self.protocol.confirm_identity()
        self.assertFalse(self.mouse.writes)

    def test_configuration_mode_and_version_have_captured_semantics(self):
        self.protocol.enter_configuration()
        self.protocol.leave_configuration()
        self.assertEqual(self.mouse.calls[0], build_report(2, count=1, data=b"\x01"))
        self.assertEqual(self.mouse.calls[1], build_report(2, count=1, data=b"\x00"))
        version = self.protocol.read_version()
        self.assertEqual(version[6:8], b"\x04\x01")

    def test_backup_reads_distinct_banks_and_restores_selection_without_memory_writes(self):
        snapshots = self.protocol.read_profiles([0, 1, 3])
        self.assertEqual(list(snapshots), [0, 1, 3])
        self.assertEqual(snapshots[3].config[0], 33)
        self.assertEqual(self.mouse.active, 1)
        self.assertEqual(self.mouse.writes, [])
        for snapshot in snapshots.values():
            snapshot.validate()
            self.assertEqual(len(snapshot.config), CONFIG_SIZE)
            self.assertEqual(len(snapshot.shortcuts), SHORTCUT_SIZE)

    def test_backup_preserves_primary_exception_when_restore_also_fails(self):
        self.mouse.fail_read = 0
        logs = []
        self.protocol.log = logs.append
        with self.assertRaises(OSError) as result:
            self.protocol.read_profiles([0, 1])
        self.assertIs(result.exception, self.mouse.primary)
        self.assertIn("simulated restore selection failure", result.exception.cleanup_errors[0])
        self.assertTrue(logs)
        self.assertEqual(self.mouse.writes, [])

    def test_successful_backup_with_failed_restore_surfaces_restore_failure(self):
        self.mouse.fail_select = 1
        with self.assertRaisesRegex(OSError, "restore selection failure"):
            self.protocol.read_profiles([0])

    def test_memory_write_chunks_and_verifies_without_modifying_other_bytes(self):
        before = bytes(self.mouse.memory[1])
        data = shortcut(8, 0x1E)
        self.protocol.write_memory(0x220, data, expected_profile=1)
        self.assertEqual(self.mouse.writes, [(1, 0x220, data[:10]), (1, 0x22A, data[10:])])
        expected = bytearray(before)
        expected[0x220:0x220 + len(data)] = data
        self.assertEqual(bytes(self.mouse.memory[1]), expected)
        self.assertTrue(any(r[1] == 8 for r in self.mouse.calls))

    def test_write_defaults_to_guarding_initial_bank(self):
        self.mouse.flip_after_write = 2
        before2 = bytes(self.mouse.memory[2])
        with self.assertRaises(ProfileChangedError):
            self.protocol.write_memory(0x220, shortcut(8, 0x1E))
        self.assertEqual(len(self.mouse.writes), 1)
        self.assertEqual(bytes(self.mouse.memory[2]), before2)

    def test_wrong_expected_bank_fails_before_any_write(self):
        with self.assertRaises(ProfileChangedError):
            self.protocol.write_memory(0x88, key_record(9), expected_profile=0)
        self.assertEqual(self.mouse.writes, [])

    def test_no_automatic_retry_after_uncertain_write_ack(self):
        self.mouse.bad_write_ack = True
        with self.assertRaises(ProtocolError):
            self.protocol.write_memory(0x88, key_record(9), expected_profile=1)
        self.assertEqual(len(self.mouse.writes), 1)

    def test_corrupt_write_is_rejected_by_readback(self):
        self.mouse.corrupt_write = True
        with self.assertRaisesRegex(ProtocolError, "releitura"):
            self.protocol.write_memory(0x88, key_record(9), expected_profile=1)
        self.assertEqual(len(self.mouse.writes), 1)

    def test_profile_change_during_snapshot_is_detected(self):
        self.mouse.flip_after_read = 2
        with self.assertRaises(ProfileChangedError):
            self.protocol.read_snapshot()
        self.assertEqual(self.mouse.writes, [])

    def test_invalid_key_checksum_is_rejected_but_raw_read_allows_recovery(self):
        self.mouse.memory[1][0x88] ^= 1
        with self.assertRaises(ValueError):
            self.protocol.read_snapshot()
        raw = self.protocol.read_memory(0x88, 4, expected_profile=1)
        self.assertNotEqual(sum(raw) & 255, 0x55)

    def test_memory_range_rejection_happens_before_transport(self):
        for call in (lambda: self.protocol.read_memory(0xFFFF, 2),
                     lambda: self.protocol.write_memory(-1, b"a"),
                     lambda: self.protocol.select_profile(4),
                     lambda: self.protocol.read_profiles([0, 0])):
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()
        self.assertEqual(self.mouse.calls, [])


if __name__ == "__main__":
    unittest.main()

"""v0.5 changes DPI and its indicator, preserving the working onboard buttons."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from mouse_lighting import dpi_indicator_snapshot
from mouse_protocol import build_report, key_address, key_record, shortcut_address
from mouse_service import Backup, ConfigurationError, EXPECTED_DEVICE, Programmer
from test_lighting import working_device
from test_service import snapshot


# Independent native record boundaries. The implementation's allowlist is not
# used to decide which bytes this test permits it to change.
LED_RECORDS = (tuple((0x2C + 4 * stage, 4) for stage in range(8))
               + ((0x4C, 2), (0x4E, 2), (0x52, 2), (0xA0, 7), (0xA7, 2), (0xB3, 2)))
COLORS = {"macos": bytes.fromhex("ff 00 00 56"), "windows": bytes.fromhex("00 00 ff 56")}
DPI = {"macos": bytes.fromhex("14 14 00 2d"), "windows": bytes.fromhex("15 15 00 2b")}


def records(count):
    return tuple((0x0C + 4 * stage, 4) for stage in range(count)) + LED_RECORDS


def indicator_device(cycle=(0, 1)):
    device = working_device(cycle)
    for index, memory in device.banks.items():
        # Current DPI is deliberately different from both requested targets.
        # Inactive records are also valid, different values and must survive.
        for stage in range(8):
            value = 6 + index + stage
            memory[0x0C + stage * 4:0x10 + stage * 4] = bytes((value, value, 0, (0x55 - value * 2) & 0xFF))
        # A long macro assigned outside the recognized keys must not block or
        # be rewritten by this configuration, which never clones profiles.
        at = key_address(8)
        memory[at:at + 4] = key_record(6, 1)
    return device


class DpiIndicatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def program(self, device, directory=None):
        return Programmer(device.connect, directory or self.directory,
                          dict(EXPECTED_DEVICE), log=lambda _: None)

    def assert_target(self, memory, original, kind):
        count = original[2]
        self.assertEqual(memory[2:6], original[2:6], "DPI stage count and active selection must stay unchanged")
        for stage in range(count):
            at = 0x0C + stage * 4
            self.assertEqual(memory[at:at + 4], DPI[kind])
        self.assertEqual(memory[0x0C + count * 4:0x2C], original[0x0C + count * 4:0x2C])
        for stage in range(8):
            at = 0x2C + stage * 4
            self.assertEqual(memory[at:at + 4], COLORS[kind])
        self.assertEqual(memory[0x4C:0x50], bytes.fromhex("01 54 ff 56"))
        self.assertEqual(memory[0x52:0x54], bytes.fromhex("01 54"))
        self.assertEqual(memory[0xA0], 0, "Main strip must be OFF")
        self.assertEqual(memory[0xA1:0xA6], original[0xA1:0xA6], "Unused main-strip settings are retained")
        self.assertEqual(sum(memory[0xA0:0xA7]) & 0xFF, 0x55)
        self.assertEqual(memory[0xA7:0xA9], bytes.fromhex("00 55"))
        self.assertEqual(memory[0xB3:0xB5], bytes.fromhex("00 55"))
        allowed = {at for start, size in records(count) for at in range(start, start + size)}
        for at, old in enumerate(original):
            if at not in allowed:
                self.assertEqual(memory[at], old, f"Unowned byte changed at 0x{at:04X}")

    def test_helper_sets_explicit_platform_dpi_color_and_main_off_without_other_changes(self):
        device = indicator_device()
        for index, kind in ((0, "macos"), (1, "windows")):
            original = bytes(device.banks[index])
            before = snapshot(index, device.banks[index])
            after = dpi_indicator_snapshot(before)
            self.assertEqual(before, snapshot(index, device.banks[index]), "Helper must not mutate its source")
            combined = after.config + original[0xC0:0x100] + after.shortcuts
            self.assert_target(combined, original, kind)

    def test_one_and_eight_enabled_stages_keep_count_active_and_unused_values(self):
        device = indicator_device()
        for count, active in ((1, 0), (8, 7)):
            with self.subTest(count=count):
                memory = bytearray(device.banks[1])
                memory[2:6] = bytes((count, 0x55 - count, active, 0x55 - active))
                before = bytes(memory)
                after = dpi_indicator_snapshot(snapshot(1, memory))
                self.assert_target(after.config + before[0xC0:0x100] + after.shortcuts, before, "windows")

    def test_four_bank_non_numeric_cycle_is_readonly_until_all_originals_are_durable(self):
        device = indicator_device(cycle=(0, 2, 1, 3))
        original = {index: bytes(memory) for index, memory in device.banks.items()}

        def click(current):
            self.assertFalse(device.writes, "Cycle discovery must not reprogram button 7 or DPI")
            self.assertEqual(device.open_handles, 0)
            device.click(current)

        def durable_before_write(index, address, data):
            journal = Backup.load(next(self.directory.glob("*.json")))
            self.assertEqual(journal.document["operation"], "dpi_indicator")
            self.assertEqual(journal.document["lighting_scope"], "dpi_indicator")
            self.assertEqual(journal.document["cycle"], [0, 2, 1, 3])
            self.assertEqual(set(journal.snapshots()), {0, 1, 2, 3})
            self.assertEqual(set(journal.snapshots("after")), {0, 1, 2, 3})
            for bank, state in journal.snapshots().items():
                self.assertEqual(state.config, original[bank][:0xC0])
                self.assertEqual(state.shortcuts, original[bank][0x100:0x300])
            self.assertIn((address, len(data)), records(original[index][2]))

        device.before_write = durable_before_write
        backup = self.program(device).update_dpi_indicator(click)
        self.assertEqual(backup.document["phase"], "programmed")
        self.assertEqual(device.active, 1)
        self.assertEqual(device.open_handles, 0)
        self.assertEqual(device.clicks, 4)
        for index, kind in ((0, "macos"), (2, "windows"), (1, "macos"), (3, "windows")):
            self.assert_target(device.banks[index], original[index], kind)

    def test_reversed_bindings_choose_windows_2100_blue_at_bank_zero(self):
        device = indicator_device()
        for button in (4, 5, 6):
            at = shortcut_address(button)
            first = bytes(device.banks[0][at:at + 32])
            device.banks[0][at:at + 32] = device.banks[1][at:at + 32]
            device.banks[1][at:at + 32] = first
        original = {index: bytes(memory) for index, memory in device.banks.items()}
        self.program(device).update_dpi_indicator(device.click)
        self.assert_target(device.banks[0], original[0], "windows")
        self.assert_target(device.banks[1], original[1], "macos")
        for index in (2, 3):
            self.assertEqual(bytes(device.banks[index]), original[index])

    def test_invalid_dpi_metadata_or_enabled_checksum_cancels_before_any_memory_write(self):
        defects = ((2, bytes.fromhex("00 55")), (2, bytes.fromhex("09 4c")),
                   (2, bytes.fromhex("03 00")), (4, bytes.fromhex("03 52")),
                   (4, bytes.fromhex("00 00")), (0x0C, bytes.fromhex("14 14 00 00")),
                   (0x14, bytes.fromhex("14 14 00 00")))
        for address, value in defects:
            with self.subTest(address=address, value=value.hex()):
                device = indicator_device()
                device.banks[0][address:address + len(value)] = value
                original = {index: bytes(memory) for index, memory in device.banks.items()}
                with self.assertRaises((ConfigurationError, ValueError)):
                    self.program(device).update_dpi_indicator(device.click)
                self.assertFalse(device.writes)
                self.assertEqual(device.active, 1)
                self.assertEqual({index: bytes(memory) for index, memory in device.banks.items()}, original)

    def test_unused_numeric_dpi_record_is_not_validated_or_rewritten(self):
        device = indicator_device()
        device.banks[1][0x28:0x2C] = bytes.fromhex("de ad be ef")
        original = bytes(device.banks[1])
        result = dpi_indicator_snapshot(snapshot(1, device.banks[1]))
        self.assertEqual(result.config[0x28:0x2C], original[0x28:0x2C])
        self.assert_target(result.config + original[0xC0:0x100] + result.shortcuts, original, "windows")

    def test_known_wire_frames_encode_2100_blue_and_main_off(self):
        self.assertEqual(build_report(7, 0x0C, 4, bytes.fromhex("15 15 00 2b")),
                         bytes.fromhex("08 07 00 00 0c 04 15 15 00 2b 00 00 00 00 00 00 e1"))
        self.assertEqual(build_report(7, 0x2C, 4, bytes.fromhex("00 00 ff 56")),
                         bytes.fromhex("08 07 00 00 2c 04 00 00 ff 56 00 00 00 00 00 00 c1"))
        self.assertEqual(build_report(7, 0xA7, 2, bytes.fromhex("00 55")),
                         bytes.fromhex("08 07 00 00 a7 02 00 55 00 00 00 00 00 00 00 00 48"))

    def test_partial_dpi_or_lighting_writes_restore_all_original_owned_records(self):
        for address in (0x0C, 0x10, 0x2C, 0x4C, 0x4E, 0x52, 0xA0, 0xA7, 0xB3):
            with self.subTest(address=address), tempfile.TemporaryDirectory() as directory:
                device = indicator_device()
                # Exercise disabling a previously enabled main strip as well.
                for memory in device.banks.values():
                    memory[0xA7:0xA9] = bytes.fromhex("01 54")
                original = {index: bytes(memory) for index, memory in device.banks.items()}
                device.failure = lambda _bank, at, _data: at == address
                program = self.program(device, Path(directory))
                with self.assertRaises(ConfigurationError):
                    program.update_dpi_indicator(device.click)
                self.assertTrue(device.failed_once)
                self.assertEqual({index: bytes(memory) for index, memory in device.banks.items()}, original)
                self.assertEqual(device.active, 1)
                self.assertEqual(device.open_handles, 0)
                self.assertTrue(all((at, len(data)) in records(original[index][2]) for index, at, data in device.writes))
                loaded = Backup.load(next(Path(directory).glob("*.json")))
                self.assertEqual(loaded.document["phase"], "restored")
                self.assertEqual(loaded.document["operation"], "dpi_indicator")

    def test_rollback_preserves_late_key_macro_count_and_active_stage_changes(self):
        device = indicator_device()
        original = {index: bytes(memory) for index, memory in device.banks.items()}

        def fail_with_external_change(index, address, _data):
            if address != 0xA0:
                return False
            at = key_address(8)
            device.banks[index][at:at + 4] = key_record(6, 2)
            device.banks[index][shortcut_address(5) + 25] = 0xDE
            device.banks[index][2:6] = bytes.fromhex("04 51 03 52")
            return True

        device.failure = fail_with_external_change
        with self.assertRaises(ConfigurationError):
            self.program(device).update_dpi_indicator(device.click)
        expected = {index: bytearray(memory) for index, memory in original.items()}
        at = key_address(8)
        expected[0][at:at + 4] = key_record(6, 2)
        expected[0][shortcut_address(5) + 25] = 0xDE
        expected[0][2:6] = bytes.fromhex("04 51 03 52")
        self.assertEqual({index: bytes(memory) for index, memory in device.banks.items()},
                         {index: bytes(memory) for index, memory in expected.items()})
        self.assertEqual(device.active, 1)

    def test_manual_restore_saves_current_state_and_only_restores_original_scope(self):
        device = indicator_device()
        original = {index: bytes(memory) for index, memory in device.banks.items()}
        program = self.program(device)
        backup = program.update_dpi_indicator(device.click)
        device.banks[0][2:6] = bytes.fromhex("04 51 03 52")
        device.banks[0][0x18:0x1C] = bytes.fromhex("23 23 00 0f")  # newly enabled stage, outside original scope
        at = key_address(8)
        device.banks[0][at:at + 4] = key_record(6, 2)
        device.banks[1][shortcut_address(6) + 25] = 0xAD
        device.active = 0
        before_restore = {index: bytes(memory) for index, memory in device.banks.items()}
        device.writes.clear()

        def before_write(_index, _address, _data):
            journals = [Backup.load(path) for path in self.directory.glob("*.json") if path != backup.path]
            self.assertEqual(len(journals), 1)
            for bank, state in journals[0].snapshots().items():
                self.assertEqual(state.config, before_restore[bank][:0xC0])
                self.assertEqual(state.shortcuts, before_restore[bank][0x100:0x300])

        device.before_write = before_write
        recovery = program.restore(Backup.load(backup.path))
        expected = {index: bytearray(memory) for index, memory in before_restore.items()}
        for index in device.cycle:
            for address, size in records(original[index][2]):
                expected[index][address:address + size] = original[index][address:address + size]
        self.assertEqual({index: bytes(memory) for index, memory in device.banks.items()},
                         {index: bytes(memory) for index, memory in expected.items()})
        self.assertEqual(device.active, 0)
        self.assertEqual(recovery.document["operation"], "dpi_indicator")
        self.assertEqual(Backup.load(recovery.path).document["phase"], "restore_completed")

    def test_failed_manual_restore_recovers_pre_restore_dpi_and_lighting(self):
        device = indicator_device()
        program = self.program(device)
        backup = program.update_dpi_indicator(device.click)
        current = {index: bytes(memory) for index, memory in device.banks.items()}
        device.failure = lambda _index, address, _data: address == 0x0C
        device.writes.clear()
        with self.assertRaises(ConfigurationError):
            program.restore(backup)
        self.assertTrue(device.failed_once)
        self.assertEqual({index: bytes(memory) for index, memory in device.banks.items()}, current)
        self.assertEqual(device.active, 1)

    def test_legacy_v03_and_v04_restore_never_gain_numeric_dpi_scope(self):
        for legacy_scope in (None, "main_dpi_movement"):
            with self.subTest(scope=legacy_scope), tempfile.TemporaryDirectory() as directory:
                device = indicator_device()
                program = self.program(device, Path(directory))
                backup = program.update_colors(device.click)
                if legacy_scope is None:
                    backup.document.pop("lighting_scope", None)
                    backup.save()
                device.banks[0][0x0C:0x10] = bytes.fromhex("23 23 00 0f")
                current = {index: bytes(memory) for index, memory in device.banks.items()}
                device.writes.clear()
                program.restore(Backup.load(backup.path))
                for index in device.banks:
                    self.assertEqual(device.banks[index][0x0C:0x2C], current[index][0x0C:0x2C])
                    self.assertEqual(device.banks[index][0x60:0xA0], current[index][0x60:0xA0])
                    self.assertEqual(device.banks[index][0x100:0x300], current[index][0x100:0x300])
                self.assertFalse(any(0x0C <= address < 0x2C for _, address, _ in device.writes))

    def test_idempotent_indicator_configuration_does_not_write_memory_again(self):
        device = indicator_device()
        program = self.program(device)
        program.update_dpi_indicator(device.click)
        current = {index: bytes(memory) for index, memory in device.banks.items()}
        device.writes.clear()
        program.update_dpi_indicator(device.click)
        self.assertFalse(device.writes)
        self.assertEqual({index: bytes(memory) for index, memory in device.banks.items()}, current)
        self.assertEqual(device.active, 1)

    def test_physical_verification_reads_dpi_and_restores_active_without_claiming_visual_success(self):
        device = indicator_device(cycle=(0, 2, 1, 3))
        program = self.program(device)
        backup = program.update_dpi_indicator(device.click)
        writes_before = list(device.writes)
        program.verify(backup, observed_disconnect=True, click=device.click)
        self.assertEqual(device.writes, writes_before)
        self.assertEqual(device.active, 1)
        self.assertTrue(backup.document["usb_reconnect_verified"])
        self.assertTrue(backup.document["hardware_cycle_reverified"])
        self.assertFalse(backup.document["visual_color_confirmed"])
        self.assertEqual([item["bank"] for item in backup.document["physical_lighting_reads"]], [2, 1, 3, 0])

    def test_backup_rejects_missing_bad_or_expanded_dpi_scope_metadata(self):
        device = indicator_device()
        backup = self.program(device).update_dpi_indicator(device.click)
        valid = copy.deepcopy(backup.document)
        variants = (
            {"dpi_stage_counts": {}},
            {"dpi_stage_counts": {"0": 3}},
            {"dpi_stage_counts": {"0": 0, "1": 3}},
            {"dpi_stage_counts": {"0": 9, "1": 3}},
            {"dpi_stage_counts": {"0": True, "1": 3}},
            {"dpi_stage_counts": {"0": 3, "1": 3, "2": 3}},
            {"operation": "rgb_only"},
            {"lighting_scope": "main_dpi_movement"},
            {"operation": "unknown_scoped_operation"},
        )
        for modified in variants:
            with self.subTest(metadata=modified):
                backup.document = copy.deepcopy(valid)
                backup.document.update(modified)
                backup.save()
                with self.assertRaises(ConfigurationError):
                    Backup.load(backup.path)

    def test_cross_bank_numeric_alias_is_detected_before_success_and_rolled_back(self):
        device = indicator_device()
        device.banks[1][0x0C:0x2C] = device.banks[0][0x0C:0x2C]
        original = {index: bytes(memory) for index, memory in device.banks.items()}
        write = device.write_memory

        def write_alias(address, data, expected_profile=None):
            write(address, data, expected_profile=expected_profile)
            if device.active == 1 and 0x0C <= address < 0x2C:
                device.banks[0][address:address + len(data)] = data

        device.write_memory = write_alias
        with self.assertRaises(ConfigurationError):
            self.program(device).update_dpi_indicator(device.click)
        self.assertEqual({index: bytes(memory) for index, memory in device.banks.items()}, original)
        self.assertEqual(device.active, 1)
        self.assertEqual(Backup.load(next(self.directory.glob("*.json"))).document["phase"], "restored")

    def test_physical_verification_detects_dpi_change_on_button_and_restores_selection(self):
        device = indicator_device()
        program = self.program(device)
        backup = program.update_dpi_indicator(device.click)
        first_verify_click = device.clicks + 1

        def physical_setting_change(clicks):
            if clicks == first_verify_click:
                device.banks[device.active][0x0C:0x10] = bytes.fromhex("14 14 00 2d")

        device.after_click = physical_setting_change
        writes_before = list(device.writes)
        with self.assertRaises(ConfigurationError):
            program.verify(backup, observed_disconnect=True, click=device.click)
        self.assertEqual(device.writes, writes_before)
        self.assertEqual(device.active, 1)
        self.assertFalse(backup.document["usb_reconnect_verified"])
        self.assertFalse(backup.document["hardware_cycle_reverified"])
        self.assertFalse(backup.document["visual_color_confirmed"])
        self.assertEqual(backup.document["phase"], "verification_failed")


if __name__ == "__main__":
    unittest.main()

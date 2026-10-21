"""RGB-only changes must preserve the already working onboard configuration."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from mouse_lighting import colored_snapshot, profile_kind
from mouse_protocol import key_address, key_record, shortcut, shortcut_address
from mouse_service import Backup, ConfigurationError, EXPECTED_DEVICE, Programmer
from test_service import FakeDevice, snapshot


# Independently confirmed native LedBar record, not an allowlist returned by the
# implementation being tested. B3/move-off and DPI LED records are NOT included.
LED_START = 0xA0
LED_END = 0xA9
RGB = {"macos": (255, 0, 255), "windows": (255, 0, 0)}


def working_device(cycle=(0, 1)):
    """A v0.2 configuration that already works, with no backup file required."""
    device = FakeDevice(cycle=cycle)
    for index, memory in device.banks.items():
        record = bytes((2, 10 + index, 20 + index, 30 + index, 4, 5))
        memory[0xA0:0xA7] = record + bytes(((0x55 - sum(record)) & 0xFF,))
        memory[0xA7:0xA9] = bytes((0, 0x55))
        memory[0xB3:0xB5] = bytes((1, 0x54))  # movement preference must be retained
    for position, index in enumerate(cycle):
        memory = device.banks[index]
        mac = position % 2 == 0
        modifier = 8 if mac else 1
        for button, mod, usage in ((4, modifier, 0x19), (5, modifier, 6),
                                   (6, 8 if mac else 0, 0x1E if mac else 0x46)):
            at = key_address(button)
            memory[at:at + 4] = key_record(5)
            encoded = shortcut(mod, usage)
            at = shortcut_address(button)
            memory[at:at + len(encoded)] = encoded
        memory[key_address(7):key_address(7) + 4] = key_record(9)
        for stage in range(memory[2]):
            memory[0x0C + stage * 4:0x10 + stage * 4] = bytes.fromhex("14 14 00 2d")
    return device


class LightingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def program(self, device):
        return Programmer(device.connect, self.directory, dict(EXPECTED_DEVICE), log=lambda _: None)

    def assert_non_lighting_unchanged(self, device, before):
        for index, memory in device.banks.items():
            for at in range(len(memory)):
                if at not in range(LED_START, LED_END):
                    self.assertEqual(memory[at], before[index][at], f"Bank {index}, non-LED address 0x{at:04X}")

    def assert_led(self, state, kind, old_speed):
        data = state.config[0xA0:0xA7]
        self.assertEqual(tuple(data[:6]), (3, *RGB[kind], old_speed, 9))
        self.assertEqual(sum(data) & 0xFF, 0x55)
        self.assertEqual(state.config[0xA7:0xA9], bytes((1, 0x54)))

    def test_classifier_uses_actual_shortcuts_and_ignores_unused_slot_tails(self):
        device = working_device(cycle=(0, 2, 1, 3))
        for position, index in enumerate(device.cycle):
            for button, mod, usage in ((4, 8 if position % 2 == 0 else 1, 0x19),
                                       (5, 8 if position % 2 == 0 else 1, 6),
                                       (6, 8 if position % 2 == 0 else 0, 0x1E if position % 2 == 0 else 0x46)):
                at = shortcut_address(button) + len(shortcut(mod, usage)) + 1
                device.banks[index][at] ^= 0xAA
            current = snapshot(index, device.banks[index])
            self.assertEqual(profile_kind(current), "macos" if position % 2 == 0 else "windows")
        self.assertEqual(profile_kind(snapshot(1, device.banks[1])), "macos", "Bank number alone must not classify Windows")

    def test_colored_snapshot_changes_only_confirmed_ledbar_fields(self):
        device = working_device()
        for index, kind in ((0, "macos"), (1, "windows")):
            current = snapshot(index, device.banks[index])
            before = copy.deepcopy(current)
            colored = colored_snapshot(current)
            self.assertEqual(current, before)
            self.assertEqual(colored.index, current.index)
            self.assert_led(colored, kind, old_speed=4)
            self.assertEqual(colored.shortcuts, current.shortcuts)
            self.assertEqual(colored.config[:LED_START], current.config[:LED_START])
            self.assertEqual(colored.config[LED_END:], current.config[LED_END:])

    def test_update_measures_existing_cycle_without_any_key_or_preprobe_writes(self):
        device = working_device()
        before = {index: bytes(data) for index, data in device.banks.items()}
        program = self.program(device)

        def click(current):
            self.assertFalse(device.writes, "No memory writes may precede completion of the read-only cycle scan")
            device.click(current)

        backup = program.update_colors(click)
        self.assertEqual(device.clicks, 2)
        self.assertEqual(device.active, 1, "Preserve the user's active profile")
        self.assertEqual(device.open_handles, 0)
        self.assertEqual(backup.document["cycle"], [0, 1])
        self.assertEqual(backup.document["operation"], "rgb_only")
        self.assertEqual(backup.document["initial_profile"], 1)
        self.assertEqual(Backup.load(backup.path).document["cycle"], [0, 1])
        self.assert_non_lighting_unchanged(device, before)
        self.assertEqual(bytes(device.banks[2]), before[2])
        self.assertEqual(bytes(device.banks[3]), before[3])
        self.assertTrue(device.writes)
        self.assertTrue(all((at, len(data)) in ((0xA0, 7), (0xA7, 2)) for _, at, data in device.writes))
        self.assert_led(snapshot(0, device.banks[0]), "macos", old_speed=4)
        self.assert_led(snapshot(1, device.banks[1]), "windows", old_speed=4)

    def test_all_four_banks_are_durable_before_first_led_write_in_real_cycle_order(self):
        device = working_device(cycle=(0, 2, 1, 3))
        before = {index: bytes(data) for index, data in device.banks.items()}
        checks = []

        def before_write(index, address, data):
            paths = list(self.directory.glob("*.json"))
            self.assertEqual(len(paths), 1)
            journal = Backup.load(paths[0])
            self.assertEqual(journal.document["operation"], "rgb_only")
            self.assertEqual(journal.document["cycle"], [0, 2, 1, 3])
            self.assertEqual(set(journal.snapshots()), {0, 1, 2, 3})
            self.assertEqual(set(journal.snapshots("after")), {0, 1, 2, 3})
            for bank, original in journal.snapshots().items():
                self.assertEqual(original.config, before[bank][:0xC0])
                self.assertEqual(original.shortcuts, before[bank][0x100:0x300])
            self.assertIn(address, (0xA0, 0xA7))
            checks.append(index)

        device.before_write = before_write
        backup = self.program(device).update_colors(device.click)
        self.assertEqual(set(checks), {0, 1, 2, 3})
        self.assertEqual(device.active, 1)
        self.assert_non_lighting_unchanged(device, before)
        for position, index in enumerate(backup.document["cycle"]):
            self.assert_led(snapshot(index, device.banks[index]), "macos" if position % 2 == 0 else "windows", old_speed=4)

    def test_rgb_update_preserves_current_dpi_and_macro_tail_instead_of_reapplying_v02(self):
        device = working_device()
        device.banks[0][0x0C:0x10] = bytes.fromhex("23 23 00 0f")  # current 3500 DPI, not an old saved 2000
        device.banks[1][0x0C:0x10] = bytes.fromhex("08 08 00 45")  # current 800 DPI
        device.banks[0][shortcut_address(5) + 25] = 0xDE
        device.banks[1][shortcut_address(6) + 25] = 0xAD
        before = {index: bytes(data) for index, data in device.banks.items()}
        backup = self.program(device).update_colors(device.click)
        self.assert_non_lighting_unchanged(device, before)
        self.assertEqual(backup.snapshots()[0].config[0x0C:0x10], bytes.fromhex("23 23 00 0f"))
        self.assertEqual(device.banks[0][0x0C:0x10], bytes.fromhex("23 23 00 0f"))
        self.assertEqual(device.banks[1][0x0C:0x10], bytes.fromhex("08 08 00 45"))

    def test_unknown_shortcut_mapping_cancels_without_any_color_or_key_writes(self):
        device = working_device()
        device.banks[0][shortcut_address(5) + 5] ^= 1
        before = {index: bytes(data) for index, data in device.banks.items()}
        with self.assertRaises((ConfigurationError, ValueError)):
            self.program(device).update_colors(device.click)
        self.assertFalse(device.writes)
        self.assertEqual(device.active, 1)
        self.assertEqual({index: bytes(data) for index, data in device.banks.items()}, before)

    def test_unknown_button7_is_not_patched_by_the_color_update(self):
        device = working_device()
        device.banks[0][key_address(7):key_address(7) + 4] = key_record(2, 1)
        before = {index: bytes(data) for index, data in device.banks.items()}
        with self.assertRaises((ConfigurationError, ValueError)):
            self.program(device).update_colors(device.click)
        self.assertFalse(device.writes)
        self.assertEqual(device.active, 1)
        self.assertEqual({index: bytes(data) for index, data in device.banks.items()}, before)

    def test_non_alternating_classified_profiles_are_rejected_before_led_writes(self):
        device = working_device()
        for button in (4, 5, 6):
            at = shortcut_address(button)
            device.banks[1][at:at + 32] = device.banks[0][at:at + 32]
        before = {index: bytes(data) for index, data in device.banks.items()}
        with self.assertRaises((ConfigurationError, ValueError)):
            self.program(device).update_colors(device.click)
        self.assertFalse(device.writes)
        self.assertEqual(device.active, 1)
        self.assertEqual({index: bytes(data) for index, data in device.banks.items()}, before)

    def test_physical_button_that_stops_switching_does_not_trigger_any_reconfiguration(self):
        device = working_device()
        device.supported = False
        before = {index: bytes(data) for index, data in device.banks.items()}
        with self.assertRaises((ConfigurationError, ValueError)):
            self.program(device).update_colors(device.click)
        self.assertFalse(device.writes)
        self.assertEqual(device.active, 1)
        self.assertEqual({index: bytes(data) for index, data in device.banks.items()}, before)

    def test_cancel_during_read_only_scan_restores_active_profile_and_changes_nothing(self):
        device = working_device()
        before = {index: bytes(data) for index, data in device.banks.items()}

        def cancel(current):
            self.assertEqual(device.open_handles, 0)
            raise KeyboardInterrupt()

        with self.assertRaises((KeyboardInterrupt, ConfigurationError)):
            self.program(device).update_colors(cancel)
        self.assertFalse(device.writes)
        self.assertEqual(device.active, 1)
        self.assertEqual({index: bytes(data) for index, data in device.banks.items()}, before)

    def check_failed_led_write(self, fail_at):
        device = working_device(cycle=(0, 1, 2, 3))
        before = {index: bytes(data) for index, data in device.banks.items()}
        device.failure = lambda _index, address, _data: address == fail_at
        program = self.program(device)
        with self.assertRaises((ConfigurationError, OSError)):
            program.update_colors(device.click)
        self.assertTrue(device.failed_once)
        self.assertEqual(device.active, 1)
        self.assertEqual(device.open_handles, 0)
        self.assertEqual({index: bytes(data) for index, data in device.banks.items()}, before)
        self.assertTrue(all((at, len(data)) in ((0xA0, 7), (0xA7, 2)) for _, at, data in device.writes))
        journal = Backup.load(next(self.directory.glob("*.json")))
        self.assertEqual(journal.document["cycle"], [0, 1, 2, 3])
        self.assertEqual(journal.document["phase"], "restored")

    def test_partial_color_record_failure_rolls_back_without_touching_working_keys(self):
        self.check_failed_led_write(0xA0)

    def test_partial_led_enable_failure_rolls_back_with_exact_separate_records(self):
        self.check_failed_led_write(0xA7)

    def test_existing_target_colors_are_a_memory_write_noop(self):
        device = working_device()
        for index in device.cycle:
            state = colored_snapshot(snapshot(index, device.banks[index]))
            device.banks[index][:0xC0] = state.config
        before = {index: bytes(data) for index, data in device.banks.items()}
        self.program(device).update_colors(device.click)
        self.assertFalse(device.writes)
        self.assertEqual(device.active, 1)
        self.assertEqual({index: bytes(data) for index, data in device.banks.items()}, before)

    def test_invalid_preserved_led_speed_is_not_silently_reinterpreted(self):
        device = working_device()
        device.banks[0][0xA4] = 10
        body = device.banks[0][0xA0:0xA6]
        device.banks[0][0xA6] = (0x55 - sum(body)) & 0xFF
        before = {index: bytes(data) for index, data in device.banks.items()}
        with self.assertRaises((ConfigurationError, ValueError)):
            self.program(device).update_colors(device.click)
        self.assertFalse(device.writes)
        self.assertEqual(device.active, 1)
        self.assertEqual({index: bytes(data) for index, data in device.banks.items()}, before)

    def test_colors_follow_reversed_platform_bindings_not_bank_number(self):
        device = working_device()
        for button in (4, 5, 6):
            at = shortcut_address(button)
            first = bytes(device.banks[0][at:at + 32])
            device.banks[0][at:at + 32] = device.banks[1][at:at + 32]
            device.banks[1][at:at + 32] = first
        before = {index: bytes(data) for index, data in device.banks.items()}
        self.program(device).update_colors(device.click)
        self.assert_led(snapshot(0, device.banks[0]), "windows", old_speed=4)
        self.assert_led(snapshot(1, device.banks[1]), "macos", old_speed=4)
        self.assert_non_lighting_unchanged(device, before)

    def test_live_change_after_readonly_scan_aborts_before_any_color_writes(self):
        device = working_device()

        def external_change(clicks):
            if clicks == 2:
                device.banks[0][0x0C:0x10] = bytes.fromhex("23 23 00 0f")

        device.after_click = external_change
        with self.assertRaises(ConfigurationError):
            self.program(device).update_colors(device.click)
        self.assertFalse(device.writes)
        self.assertEqual(device.banks[0][0x0C:0x10], bytes.fromhex("23 23 00 0f"))
        self.assertEqual(device.active, 1)
        self.assertEqual(device.open_handles, 0)

    def test_color_failure_rolls_back_only_led_bytes_and_preserves_late_external_dpi(self):
        device = working_device()
        before = {index: bytes(data) for index, data in device.banks.items()}

        def external_change_and_failure(index, address, _data):
            if address != 0xA7:
                return False
            device.banks[index][0x0C:0x10] = bytes.fromhex("23 23 00 0f")
            device.banks[index][shortcut_address(5) + 25] = 0xDE
            return True

        device.failure = external_change_and_failure
        with self.assertRaises(ConfigurationError):
            self.program(device).update_colors(device.click)
        self.assertTrue(device.failed_once)
        self.assertEqual(device.banks[0][0x0C:0x10], bytes.fromhex("23 23 00 0f"))
        self.assertEqual(device.banks[0][shortcut_address(5) + 25], 0xDE)
        expected = {index: bytearray(data) for index, data in before.items()}
        expected[0][0x0C:0x10] = bytes.fromhex("23 23 00 0f")
        expected[0][shortcut_address(5) + 25] = 0xDE
        self.assertEqual({index: bytes(data) for index, data in device.banks.items()},
                         {index: bytes(data) for index, data in expected.items()})
        self.assertTrue(all((at, len(data)) in ((0xA0, 7), (0xA7, 2)) for _, at, data in device.writes))
        self.assertEqual(device.active, 1)
        self.assertEqual(Backup.load(next(self.directory.glob("*.json"))).document["phase"], "restored")

    def test_manual_rgb_restore_preserves_later_nonled_edits_and_current_active_bank(self):
        device = working_device()
        original = {index: bytes(data) for index, data in device.banks.items()}
        program = self.program(device)
        backup = program.update_colors(device.click)
        device.banks[0][0x0C:0x10] = bytes.fromhex("23 23 00 0f")
        device.banks[1][shortcut_address(6) + 25] = 0xAD
        device.active = 0  # This differs from the old backup's initial selection.
        before_restore = {index: bytes(data) for index, data in device.banks.items()}
        device.writes.clear()
        recovery = program.restore(backup)
        self.assert_non_lighting_unchanged(device, before_restore)
        for index in device.cycle:
            self.assertEqual(bytes(device.banks[index][LED_START:LED_END]), original[index][LED_START:LED_END])
        self.assertTrue(all((at, len(data)) in ((0xA0, 7), (0xA7, 2)) for _, at, data in device.writes))
        self.assertEqual(device.active, 0)
        self.assertEqual(recovery.document["operation"], "rgb_only")
        self.assertEqual(Backup.load(recovery.path).document["phase"], "restore_completed")

    def test_rgb_verification_restores_active_bank_after_physical_cycle_success(self):
        device = working_device()
        program = self.program(device)
        backup = program.update_colors(device.click)
        writes_before = list(device.writes)
        program.verify(backup, observed_disconnect=True, click=device.click)
        self.assertEqual(device.active, 1)
        self.assertEqual(device.open_handles, 0)
        self.assertEqual(device.writes, writes_before)
        self.assertTrue(backup.document["usb_reconnect_verified"])
        self.assertTrue(backup.document["hardware_cycle_reverified"])

    def test_rgb_verification_restores_active_bank_even_if_physical_cycle_fails(self):
        device = working_device()
        program = self.program(device)
        backup = program.update_colors(device.click)
        writes_before = list(device.writes)
        device.supported = False
        with self.assertRaises(ConfigurationError):
            program.verify(backup, observed_disconnect=True, click=device.click)
        self.assertEqual(device.active, 1)
        self.assertEqual(device.open_handles, 0)
        self.assertEqual(device.writes, writes_before)
        self.assertFalse(backup.document["usb_reconnect_verified"])
        self.assertFalse(backup.document["hardware_cycle_reverified"])
        self.assertEqual(backup.document["phase"], "verification_failed")


if __name__ == "__main__":
    unittest.main()

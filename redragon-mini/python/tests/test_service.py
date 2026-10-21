"""Safety and user-visible behavior of the complete onboard workflow, without USB."""
from __future__ import annotations

from contextlib import contextmanager
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mouse_protocol import Snapshot, key_address, key_record, shortcut, shortcut_address
from mouse_service import Backup, ConfigurationError, EXPECTED_DEVICE, Programmer, patches, prepare_profiles


def initial_banks() -> dict[int, bytearray]:
    banks = {}
    for index in range(4):
        memory = bytearray((offset + index * 29) % 256 for offset in range(0x300))
        # Three active DPI stages, each deliberately different from 2000. This
        # checks the requested fixed DPI rather than blindly preserving a base
        # profile whose saved DPI may differ from the user's current selection.
        memory[2:4] = bytes((3, 0x52))
        memory[4:6] = bytes((index % 3, 0x55 - index % 3))
        for stage in range(3):
            value = 5 * (index + 1) + stage
            memory[0x0C + stage * 4:0x10 + stage * 4] = bytes((value, value, 0, (0x55 - value * 2) & 0xFF))
        for key in range(16):
            memory[0x60 + key * 4:0x64 + key * 4] = key_record(1, (key + 1) % 32)
        banks[index] = memory
    return banks


def snapshot(index: int, memory: bytearray) -> Snapshot:
    return Snapshot(index, bytes(memory[:0xC0]), bytes(memory[0x100:0x300]))


class FakeDevice:
    """Realistic mutable banks; keyboard clicks only work with no open host handle."""

    def __init__(self, cycle=(0, 1), supported=True):
        self.banks = initial_banks()
        self.active = 1
        self.cycle = list(cycle)
        self.supported = supported
        self.open_handles = 0
        self.clicks = 0
        self.writes = []
        self.before_write = None
        self.after_click = None
        self.failure = None
        self.failed_once = False

    @contextmanager
    def connect(self):
        self.open_handles += 1
        try:
            yield self
        finally:
            self.open_handles -= 1

    def current_profile(self):
        return self.active

    def select_profile(self, index):
        if index not in self.banks:
            raise OSError("Unknown bank")
        self.active = index

    def read_snapshot(self, index=None):
        if index is not None:
            self.select_profile(index)
        result = snapshot(self.active, self.banks[self.active])
        result.validate()
        return result

    def read_profiles(self, indices):
        initial = self.active
        try:
            return {index: self.read_snapshot(index) for index in indices}
        finally:
            self.select_profile(initial)

    def read_memory(self, address, length, expected_profile=None):
        if expected_profile is not None and self.active != expected_profile:
            raise OSError("Unexpected bank during read")
        return bytes(self.banks[self.active][address:address + length])

    def write_memory(self, address, data, expected_profile=None):
        if self.open_handles != 1:
            raise AssertionError("Writes must hold exactly one configured handle")
        if expected_profile != self.active:
            raise AssertionError("Every write must guard its expected bank")
        if self.before_write:
            self.before_write(self.active, address, data)
        self.writes.append((self.active, address, bytes(data)))
        self.banks[self.active][address:address + len(data)] = data
        if self.failure and not self.failed_once and self.failure(self.active, address, data):
            self.failed_once = True
            # A failed write can have partially changed flash; rollback must not
            # assume that an exception means nothing was written.
            self.banks[self.active][address] ^= 1
            raise OSError("Simulated failed write/readback")

    def click(self, expected):
        if self.open_handles:
            raise AssertionError("Physical profile test must run with the host handle closed")
        if expected != self.active:
            raise AssertionError("Wizard asked to click from the wrong bank")
        self.clicks += 1
        value = self.banks[self.active][key_address(7):key_address(7) + 4]
        if self.supported and value == key_record(9):
            position = self.cycle.index(self.active)
            self.active = self.cycle[(position + 1) % len(self.cycle)]
        if self.after_click:
            self.after_click(self.clicks)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def programmer(self, device):
        return Programmer(device.connect, self.directory, dict(EXPECTED_DEVICE), log=lambda _: None)

    def assert_all_memory(self, device, before):
        self.assertEqual({index: bytes(value) for index, value in device.banks.items()}, before)
        self.assertEqual(device.open_handles, 0)

    def assert_platform(self, state, mac):
        modifier = 8 if mac else 1
        for button, mod, usage in ((4, modifier, 0x19), (5, modifier, 6),
                                   (6, 8 if mac else 0, 0x1E if mac else 0x46)):
            self.assertEqual(state.config[key_address(button):key_address(button) + 4], key_record(5))
            encoded = shortcut(mod, usage)
            at = shortcut_address(button) - 0x100
            self.assertEqual(state.shortcuts[at:at + len(encoded)], encoded)
        self.assertEqual(state.config[key_address(7):key_address(7) + 4], key_record(9))
        for stage in range(state.config[2]):
            self.assertEqual(state.config[0x0C + stage * 4:0x10 + stage * 4], bytes.fromhex("14 14 00 2d"))

    def test_two_banks_program_exact_requested_keys_and_leave_no_open_handle(self):
        device = FakeDevice()
        before = {index: bytes(value) for index, value in device.banks.items()}
        program = self.programmer(device)
        backup = program.configure(device.click)
        self.assertEqual(backup.document["cycle"], [0, 1])
        self.assertEqual(backup.document["phase"], "programmed")
        self.assertEqual(device.clicks, 4)  # observe one cycle and independently repeat it
        self.assert_platform(device.read_snapshot(0), True)
        self.assert_platform(device.read_snapshot(1), False)
        for index in (0, 1):
            changed = set(range(key_address(4), key_address(4) + 4))
            changed.update(range(0x0C, 0x0C + 4 * 3))
            for button in (5, 6, 7):
                changed.update(range(key_address(button), key_address(button) + 4))
            for offset in range(0xC0):
                if offset not in changed:
                    self.assertEqual(device.banks[index][offset], before[index][offset])
            self.assertEqual(device.banks[index][0x2C:0x4C], before[index][0x2C:0x4C], "DPI colors must remain unchanged")
        self.assertEqual(bytes(device.banks[2]), before[2])
        self.assertEqual(bytes(device.banks[3]), before[3])
        self.assertEqual(device.open_handles, 0)

    def test_four_bank_cycle_is_measured_and_every_bank_is_durable_before_mutation(self):
        device = FakeDevice(cycle=(0, 2, 1, 3))
        before = {index: bytes(value) for index, value in device.banks.items()}
        program = self.programmer(device)
        audited = []

        def check_backup(index, address, data):
            self.assertIsNotNone(program.last_backup)
            # Read from disk, not the service's in-memory document: this is the
            # important ordering guarantee when a newly discovered bank appears.
            loaded = Backup.load(program.last_backup.path)
            original = loaded.snapshots()[index]
            self.assertEqual(original.config, before[index][:0xC0])
            self.assertEqual(original.shortcuts, before[index][0x100:0x300])
            audited.append(index)

        device.before_write = check_backup
        backup = program.configure(device.click)
        self.assertEqual(backup.document["cycle"], [0, 2, 1, 3])
        self.assertEqual(set(audited), {0, 1, 2, 3})
        self.assertEqual(device.clicks, 8)
        for position, index in enumerate(backup.document["cycle"]):
            self.assert_platform(device.read_snapshot(index), position % 2 == 0)
            self.assertEqual(device.banks[index][0x2C:0x4C], before[position % 2][0x2C:0x4C])
            self.assertEqual(device.banks[index][0x54:0x60], before[index][0x54:0x60])
            self.assertEqual(device.banks[index][0xBB:0xC0], before[index][0xBB:0xC0])

    def test_unsupported_profile_action_cancels_final_mapping_and_restores_everything(self):
        device = FakeDevice(supported=False)
        before = {i: bytes(value) for i, value in device.banks.items()}
        program = self.programmer(device)
        with self.assertRaisesRegex(ConfigurationError, "nao mudou o perfil interno"):
            program.configure(device.click)
        self.assert_all_memory(device, before)
        self.assertEqual(device.active, 1)
        self.assertTrue(device.writes)
        self.assertTrue(all(address == key_address(7) for _, address, _ in device.writes))
        self.assertEqual(program.last_backup.document["phase"], "restored")

    def test_three_bank_cycle_is_rejected_and_restored(self):
        device = FakeDevice(cycle=(0, 1, 2))
        before = {i: bytes(value) for i, value in device.banks.items()}
        program = self.programmer(device)
        with self.assertRaisesRegex(ConfigurationError, "numero impar"):
            program.configure(device.click)
        self.assert_all_memory(device, before)
        self.assertEqual(set(program.last_backup.snapshots()), {0, 1, 2})

    def test_cycle_must_repeat_before_bulk_configuration_is_written(self):
        device = FakeDevice(cycle=(0, 1))
        before = {i: bytes(value) for i, value in device.banks.items()}

        def disturb(clicks):
            if clicks == 3:
                device.active = 0

        device.after_click = disturb
        with self.assertRaisesRegex(ConfigurationError, "ciclo nao se repetiu"):
            self.programmer(device).configure(device.click)
        self.assert_all_memory(device, before)
        self.assertTrue(all(address < 0x100 for _, address, _ in device.writes))

    def test_ctrl_c_during_physical_probe_still_restores_originals(self):
        device = FakeDevice()
        before = {i: bytes(value) for i, value in device.banks.items()}

        def cancel(_):
            self.assertEqual(device.open_handles, 0)
            raise KeyboardInterrupt()

        program = self.programmer(device)
        with self.assertRaises(ConfigurationError):
            program.configure(cancel)
        self.assert_all_memory(device, before)
        self.assertEqual(program.last_backup.document["phase"], "restored")

    def test_failed_write_may_have_changed_data_and_is_fully_rolled_back(self):
        device = FakeDevice(cycle=(0, 1, 2, 3))
        before = {i: bytes(value) for i, value in device.banks.items()}
        device.failure = lambda _index, address, _data: address >= 0x100
        program = self.programmer(device)
        with self.assertRaisesRegex(ConfigurationError, "failed write/readback"):
            program.configure(device.click)
        self.assertTrue(device.failed_once)
        self.assert_all_memory(device, before)
        self.assertEqual(program.last_backup.document["phase"], "restored")

    def test_partial_key_record_failure_can_be_repaired_even_with_bad_current_checksum(self):
        device = FakeDevice()
        before = {i: bytes(value) for i, value in device.banks.items()}
        device.failure = lambda _index, address, _data: address == key_address(7)
        program = self.programmer(device)
        with self.assertRaisesRegex(ConfigurationError, "failed write/readback"):
            program.configure(device.click)
        self.assertTrue(device.failed_once)
        self.assert_all_memory(device, before)
        self.assertEqual(program.last_backup.document["phase"], "restored")

    def test_unrelated_setting_change_aborts_stale_plan_and_restores_originals(self):
        device = FakeDevice()
        before = {i: bytes(value) for i, value in device.banks.items()}

        def disturb(clicks):
            if clicks == 4:
                device.banks[0][0] ^= 1

        device.after_click = disturb
        with self.assertRaisesRegex(ConfigurationError, "Outras configuracoes mudaram"):
            self.programmer(device).configure(device.click)
        self.assert_all_memory(device, before)

    def test_invalid_dpi_metadata_is_rejected_before_final_shortcut_writes(self):
        for broken in ("zero_count", "count_crc", "active_index"):
            with self.subTest(broken=broken):
                device = FakeDevice()
                if broken == "zero_count":
                    device.banks[0][2:4] = bytes((0, 0x55))
                elif broken == "count_crc":
                    device.banks[0][3] ^= 1
                else:
                    device.banks[0][4:6] = bytes((3, 0x52))
                before = {i: bytes(value) for i, value in device.banks.items()}
                with self.assertRaises(ConfigurationError):
                    self.programmer(device).configure(device.click)
                self.assert_all_memory(device, before)
                self.assertTrue(all(address < 0x100 for _, address, _ in device.writes))

    def test_backup_save_failure_prevents_probe_write(self):
        device = FakeDevice()
        before = {i: bytes(value) for i, value in device.banks.items()}
        program = self.programmer(device)
        with mock.patch("mouse_service.os.replace", side_effect=OSError("Disk full")):
            with self.assertRaisesRegex(OSError, "Disk full"):
                program.configure(device.click)
        self.assertFalse(device.writes)
        self.assert_all_memory(device, before)
        self.assertFalse(list(self.directory.glob("*.tmp")))

    def test_newly_discovered_bank_is_not_written_when_its_durable_backup_fails(self):
        device = FakeDevice(cycle=(0, 1, 2, 3))
        before = {i: bytes(value) for i, value in device.banks.items()}
        program = self.programmer(device)
        save = Backup.save
        failed = False

        def fail_new_bank(item):
            nonlocal failed
            if "2" in item.document["originals"] and not failed:
                failed = True
                raise OSError("Disk full while saving new bank")
            save(item)

        with mock.patch.object(Backup, "save", new=fail_new_bank):
            with self.assertRaisesRegex(ConfigurationError, "Disk full while saving new bank"):
                program.configure(device.click)
        self.assertTrue(failed)
        self.assert_all_memory(device, before)
        self.assertFalse(any(index in (2, 3) for index, _, _ in device.writes))

    def test_rollback_failure_keeps_primary_error_backup_and_restores_other_banks(self):
        device = FakeDevice()
        before = {i: bytes(value) for i, value in device.banks.items()}
        program = self.programmer(device)
        write = device.write_memory
        device.failure = lambda _index, address, _data: address >= 0x100

        def fail_later_bank_zero(address, data, expected_profile=None):
            if device.failed_once and device.active == 0:
                raise OSError("Bank zero remains disconnected")
            return write(address, data, expected_profile=expected_profile)

        device.write_memory = fail_later_bank_zero
        with self.assertRaises(ConfigurationError) as caught:
            program.configure(device.click)
        message = str(caught.exception)
        self.assertIn("Simulated failed write/readback", message)
        self.assertIn("Bank zero remains disconnected", message)
        self.assertIn(str(program.last_backup.path), message)
        self.assertEqual(bytes(device.banks[1]), before[1], "Other backed-up banks must still be restored")
        self.assertEqual(program.last_backup.document["phase"], "recovery_incomplete")
        self.assertEqual(Backup.load(program.last_backup.path).snapshots()[0].config, before[0][:0xC0])

    def test_tampered_backup_is_rejected_before_restore_opens_device(self):
        device = FakeDevice()
        backup = self.programmer(device).configure(device.click)
        document = json.loads(backup.path.read_text())
        raw = bytearray.fromhex(document["originals"]["0"]["config"])
        raw[0] ^= 1
        document["originals"]["0"]["config"] = raw.hex()
        backup.path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ConfigurationError, "checksum"):
            Backup.load(backup.path)
        self.assertEqual(device.open_handles, 0)

    def test_missing_original_for_cycle_prepared_or_after_metadata_is_rejected(self):
        device = FakeDevice(cycle=(0, 1, 2, 3))
        backup = self.programmer(device).configure(device.click)
        baseline = json.loads(backup.path.read_text())
        for field in ("cycle", "prepared_banks", "after"):
            with self.subTest(field=field):
                document = copy.deepcopy(baseline)
                del document["originals"]["2"]
                document["cycle"] = []
                document["prepared_banks"] = []
                document["after"] = {}
                if field == "after":
                    document["after"] = {"2": baseline["after"]["2"]}
                else:
                    document[field] = [0, 2]
                path = self.directory / ("missing-original-" + field + ".json")
                path.write_text(json.dumps(document))
                with self.assertRaisesRegex(ConfigurationError, "nao cobre todos os bancos"):
                    Backup.load(path)
        self.assertEqual(device.open_handles, 0)

    def test_interrupted_journal_blocks_new_configuration_until_restore_completes(self):
        for phase in ("probing", "applying", "recovery_incomplete"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(dir=self.directory) as temporary:
                directory = Path(temporary)
                device = FakeDevice()
                program = Programmer(device.connect, directory, dict(EXPECTED_DEVICE), log=lambda _: None)
                original = Backup.create(directory, EXPECTED_DEVICE, initial_profile=1)
                for index in (0, 1):
                    original.add_original(device.read_snapshot(index))
                original.phase(phase, prepared_banks=[0])
                original_snapshots = original.snapshots()
                saved_bytes = original.path.read_bytes()
                device.banks[0][key_address(7):key_address(7) + 4] = key_record(9)
                program.connect = mock.Mock(side_effect=AssertionError("Device must not open before incomplete-journal check"))
                with self.assertRaisesRegex(ConfigurationError, "procedimento interrompido"):
                    program.configure(device.click)
                program.connect.assert_not_called()
                self.assertFalse(device.writes)
                self.assertEqual(original.path.read_bytes(), saved_bytes)
                self.assertEqual(list(directory.glob("*.json")), [original.path])
                program.connect = device.connect
                recovery = program.restore(original)
                self.assertEqual(original.document["phase"], "restored")
                self.assertEqual(recovery.document["phase"], "restore_completed")
                self.assertEqual(original.snapshots(), original_snapshots)
                configured = program.configure(device.click)
                self.assertEqual(configured.document["phase"], "programmed")
                self.assertNotEqual(configured.path, original.path)

    def test_verify_does_not_claim_persistence_when_saved_data_changed(self):
        device = FakeDevice()
        program = self.programmer(device)
        backup = program.configure(device.click)
        device.banks[1][0x100] ^= 1
        with self.assertRaisesRegex(ConfigurationError, "nao persistiram|alterados"):
            program.verify(backup, observed_disconnect=True)
        self.assertNotEqual(backup.document["phase"], "reconnect_verified")
        self.assertFalse(backup.document.get("usb_reconnect_verified", False))

    def test_later_failed_verification_invalidates_previous_success(self):
        device = FakeDevice()
        program = self.programmer(device)
        backup = program.configure(device.click)
        program.verify(backup, observed_disconnect=True, click=device.click)
        self.assertTrue(backup.document["usb_reconnect_verified"])
        self.assertTrue(backup.document["hardware_cycle_reverified"])
        device.banks[0][0x100] ^= 1
        with self.assertRaises(ConfigurationError):
            program.verify(backup, observed_disconnect=True, click=device.click)
        self.assertFalse(backup.document["usb_reconnect_verified"])
        self.assertFalse(backup.document["hardware_cycle_reverified"])
        self.assertEqual(backup.document["phase"], "verification_failed")

    def test_verify_preserves_original_selection_and_leaves_no_open_handle(self):
        device = FakeDevice()
        program = self.programmer(device)
        backup = program.configure(device.click)
        device.active = 1
        program.verify(backup)
        self.assertEqual(device.active, 1)
        self.assertEqual(device.open_handles, 0)
        self.assertFalse(backup.document.get("usb_reconnect_verified", False))

    def test_restore_creates_a_durable_recovery_backup_before_first_write(self):
        device = FakeDevice()
        initial = {i: bytes(value) for i, value in device.banks.items()}
        program = self.programmer(device)
        original = program.configure(device.click)
        programmed = {i: bytes(value) for i, value in device.banks.items()}
        recovery_checks = []

        def check_recovery(index, address, data):
            candidates = [Backup.load(path) for path in self.directory.glob("*.json")]
            recovery = next(item for item in candidates if item.document.get("phase") == "before_restore")
            self.assertEqual(recovery.snapshots()[index].config, programmed[index][:0xC0])
            self.assertEqual(recovery.snapshots()[index].shortcuts, programmed[index][0x100:0x300])
            recovery_checks.append(index)

        device.before_write = check_recovery
        recovery = program.restore(original)
        self.assertTrue(recovery_checks)
        self.assert_all_memory(device, initial)
        self.assertEqual(recovery.document["restored_from"], str(original.path))

    def test_failed_restore_recovers_the_pre_restore_configuration(self):
        device = FakeDevice()
        program = self.programmer(device)
        original = program.configure(device.click)
        programmed = {i: bytes(value) for i, value in device.banks.items()}
        device.failure = lambda _index, address, _data: address >= 0x100
        with self.assertRaisesRegex(ConfigurationError, "restauracao falhou"):
            program.restore(original)
        self.assertTrue(device.failed_once)
        self.assert_all_memory(device, programmed)

    def test_restore_repairs_a_current_bank_with_an_invalid_key_checksum(self):
        device = FakeDevice()
        before = {i: bytes(value) for i, value in device.banks.items()}
        program = self.programmer(device)
        original = program.configure(device.click)
        device.banks[0][key_address(7)] ^= 1
        damaged = bytes(device.banks[0][:0xC0])
        recovery = program.restore(original)
        self.assert_all_memory(device, before)
        self.assertEqual(bytes.fromhex(recovery.document["damaged_current"]["0"]["config"]), damaged)
        self.assertNotIn("0", recovery.document["originals"], "Known-corrupt data cannot become a rollback target")
        self.assertIn("1", recovery.document["originals"])

    def test_failed_repair_preserves_corrupt_journal_without_reintroducing_it(self):
        device = FakeDevice()
        before = {i: bytes(value) for i, value in device.banks.items()}
        program = self.programmer(device)
        original = program.configure(device.click)
        device.banks[0][key_address(7)] ^= 1
        damaged = bytes(device.banks[0][:0xC0])
        writes_before = len(device.writes)
        device.failure = lambda _index, address, _data: address >= 0x100
        with self.assertRaisesRegex(ConfigurationError, "registros invalidos.*Reaplique"):
            program.restore(original)
        self.assertEqual(len(device.writes), writes_before + 1, "Do not write corrupt pre-restore records back automatically")
        records = [json.loads(path.read_text()) for path in self.directory.glob("*.json")]
        recovery = next(doc for doc in records if "damaged_current" in doc)
        self.assertEqual(bytes.fromhex(recovery["damaged_current"]["0"]["config"]), damaged)
        self.assertNotIn("0", recovery["originals"])
        device.failure = None
        program.restore(original)
        self.assert_all_memory(device, before)

    def test_receiver_identity_rejected_before_any_memory_write(self):
        device = FakeDevice()
        meta = dict(EXPECTED_DEVICE, product_id=0xF5D5, device_type=0)
        with self.assertRaisesRegex(ConfigurationError, "cabeado"):
            Programmer(device.connect, self.directory, meta, log=lambda _: None).configure(device.click)
        self.assertFalse(device.writes)
        self.assertFalse(list(self.directory.glob("*.json")))


class PlanTests(unittest.TestCase):
    def test_planning_does_not_mutate_sources_and_orders_shortcut_before_binding(self):
        banks = initial_banks()
        originals = {index: snapshot(index, memory) for index, memory in banks.items()}
        before = copy.deepcopy(originals)
        desired = prepare_profiles(originals, [0, 1, 2, 3])
        self.assertEqual(originals, before)
        for index in desired:
            values = list(patches(originals[index], desired[index]))
            seen_configuration = False
            for address, old, new in values:
                self.assertEqual(len(old), len(new))
                if address < 0x100:
                    seen_configuration = True
                else:
                    self.assertFalse(seen_configuration, "A key cannot point at an incomplete shortcut")

    def test_long_macro_on_replaced_button_does_not_prevent_configuration(self):
        banks = initial_banks()
        banks[0][key_address(4):key_address(4) + 4] = key_record(6, 1)
        originals = {index: snapshot(index, memory) for index, memory in banks.items()}
        desired = prepare_profiles(originals, [0, 1, 2, 3])
        self.assertEqual(desired[2].config[key_address(4)], 5)

    def test_long_macro_on_other_button_prevents_copying_uncopied_general_macro(self):
        banks = initial_banks()
        banks[0][key_address(1):key_address(1) + 4] = key_record(6, 1)
        originals = {index: snapshot(index, memory) for index, memory in banks.items()}
        with self.assertRaisesRegex(ConfigurationError, "macro longa"):
            prepare_profiles(originals, [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()

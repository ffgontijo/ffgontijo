import contextlib
import io
import unittest
from unittest.mock import patch

import configure
from mouse_hid import DeviceInfo
from mouse_service import ConfigurationError


def device(suffix="one", pid=0xF55E):
    return DeviceInfo(r"\\?\hid#vid_3554&pid_" + f"{pid:04x}" + "&mi_01&col05#" + suffix,
                      0x3554, pid, input_report_length=17, output_report_length=17)


class ConnectorTests(unittest.TestCase):
    def connect_fixture(self, **failures):
        events = []

        class Hid:
            def __init__(self, path):
                self.device = device()
                events.append("open")

            def close(self):
                events.append("close")
                if failures.get("close"):
                    raise OSError("close failed")

        class Protocol:
            def __init__(self, hid):
                pass

            def confirm_identity(self, expected_type):
                events.append("identity")
                if failures.get("identity"):
                    raise OSError("wrong identity")

            def enter_configuration(self):
                events.append("enter")
                if failures.get("enter"):
                    raise OSError("lost enter ACK")

            def leave_configuration(self):
                events.append("leave")
                if failures.get("leave"):
                    raise OSError("leave failed")

        return events, Hid, Protocol

    def test_normal_session_leaves_mode_and_closes_handle(self):
        events, hid, protocol = self.connect_fixture()
        with patch.object(configure, "WindowsHid", hid), patch.object(configure, "Protocol", protocol):
            with configure.Connector(device())():
                events.append("body")
        self.assertEqual(events, ["open", "identity", "enter", "body", "leave", "close"])

    def test_wrong_identity_closes_without_entering_configuration(self):
        events, hid, protocol = self.connect_fixture(identity=True)
        with patch.object(configure, "WindowsHid", hid), patch.object(configure, "Protocol", protocol):
            with self.assertRaisesRegex(OSError, "wrong identity"):
                with configure.Connector(device())():
                    self.fail("Wrong device reached the body")
        self.assertEqual(events, ["open", "identity", "close"])

    def test_lost_enter_ack_still_attempts_leave_and_closes(self):
        events, hid, protocol = self.connect_fixture(enter=True)
        with patch.object(configure, "WindowsHid", hid), patch.object(configure, "Protocol", protocol):
            with self.assertRaisesRegex(OSError, "lost enter ACK"):
                with configure.Connector(device())():
                    self.fail("Unconfirmed entry reached the body")
        self.assertEqual(events, ["open", "identity", "enter", "leave", "close"])

    def test_body_failure_survives_both_cleanup_failures(self):
        events, hid, protocol = self.connect_fixture(leave=True, close=True)
        original = OSError("primary operation failed")
        with patch.object(configure, "WindowsHid", hid), patch.object(configure, "Protocol", protocol), patch.object(configure, "say"):
            with self.assertRaises(OSError) as raised:
                with configure.Connector(device())():
                    raise original
        self.assertIs(raised.exception, original)
        self.assertEqual(events[-2:], ["leave", "close"])

    def test_first_cleanup_failure_is_not_replaced_by_close(self):
        events, hid, protocol = self.connect_fixture(leave=True, close=True)
        with patch.object(configure, "WindowsHid", hid), patch.object(configure, "Protocol", protocol), patch.object(configure, "say"):
            with self.assertRaisesRegex(ConfigurationError, "leave failed"):
                with configure.Connector(device())():
                    pass
        self.assertEqual(events[-2:], ["leave", "close"])

    def test_receiver_rejected_before_opening_a_write_session(self):
        with patch.object(configure, "WindowsHid") as opened:
            with self.assertRaises(ConfigurationError):
                with configure.Connector(device(pid=0xF5D5))():
                    self.fail("Receiver reached write session")
            opened.assert_not_called()

    def test_reconnect_requires_real_metadata_disappearance(self):
        first, second = device(), device("reconnected")
        connection = configure.Connector(first)
        with patch.object(configure, "compatible_wired", side_effect=[[first], [], [second]]), \
             patch.object(configure.time, "monotonic", side_effect=[0, 0, 1, 2]), \
             patch.object(configure.time, "sleep"), patch.object(configure, "say"):
            connection.wait_for_reconnect()
        self.assertEqual(connection.device, second)

    def test_never_disconnected_is_not_reported_as_reconnect(self):
        original = device()
        connection = configure.Connector(original)
        with patch.object(configure, "compatible_wired", return_value=[original]), \
             patch.object(configure.time, "monotonic", side_effect=[0, 0, 181]), \
             patch.object(configure.time, "sleep"), patch.object(configure, "say"):
            with self.assertRaises(ConfigurationError):
                connection.wait_for_reconnect()
        self.assertEqual(connection.device, original)

    def test_help_and_non_windows_guard_do_not_touch_hid(self):
        with patch.object(configure, "enumerate_devices") as enumerate_hid, \
             patch.object(configure.sys, "argv", ["configure.py", "--help"]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                configure.main()
            self.assertEqual(raised.exception.code, 0)
            enumerate_hid.assert_not_called()
        with patch.object(configure, "enumerate_devices") as enumerate_hid, \
             patch.object(configure.sys, "argv", ["configure.py", "--inspect"]), \
             patch.object(configure.os, "name", "posix"), patch.object(configure, "say"):
            self.assertEqual(configure.main(), 1)
            enumerate_hid.assert_not_called()

    def test_menu_five_runs_color_only_programming_then_readonly_verification(self):
        with patch.object(configure.os, "name", "nt"), \
             patch.object(configure.sys, "argv", ["configure.py"]), \
             patch("builtins.input", side_effect=["5", "0"]), \
             patch.object(configure, "say"), \
             patch.object(configure, "choose_device", return_value=device()), \
             patch.object(configure, "backup_directory", return_value="backups"), \
             patch.object(configure, "Connector") as connector_class, \
             patch.object(configure, "Programmer") as programmer_class, \
             patch.object(configure, "configure_once") as full_configuration:
            self.assertEqual(configure.main(), 0)
            program = programmer_class.return_value
            program.update_colors.assert_called_once_with(configure.click_button)
            program.configure.assert_not_called()
            full_configuration.assert_not_called()
            connector_class.return_value.wait_for_reconnect.assert_called_once_with()
            program.verify.assert_called_once_with(program.update_colors.return_value,
                                                   observed_disconnect=True,
                                                   click=configure.click_button)


if __name__ == "__main__":
    unittest.main()

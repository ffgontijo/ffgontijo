"""Windows HID I/O using only ctypes; importing this module does not open devices.

The original native driver writes 17-byte report 08 frames with WriteFile.
The HID class driver sends those as output SET_REPORT on the control endpoint.
No feature-report fallback or automatic retransmission is performed here.
"""
from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
import math
import os
import threading
import time

DWORD = C.c_uint32
WORD = C.c_uint16
BYTE = C.c_ubyte
BOOL = C.c_int32
HANDLE = C.c_void_p
ULONG_PTR = C.c_size_t
INVALID_HANDLE_VALUE = C.c_void_p(-1).value
ERROR_NO_MORE_ITEMS = 259
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
INFINITE = 0xFFFFFFFF


class GUID(C.Structure):
    _fields_ = [("Data1", DWORD), ("Data2", WORD), ("Data3", WORD), ("Data4", BYTE * 8)]


class SP_DEVICE_INTERFACE_DATA(C.Structure):
    _fields_ = [("cbSize", DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", DWORD), ("Reserved", ULONG_PTR)]


class HIDD_ATTRIBUTES(C.Structure):
    _fields_ = [("Size", DWORD), ("VendorID", WORD), ("ProductID", WORD), ("VersionNumber", WORD)]


class HIDP_CAPS(C.Structure):
    _fields_ = [("Usage", WORD), ("UsagePage", WORD),
                ("InputReportByteLength", WORD), ("OutputReportByteLength", WORD),
                ("FeatureReportByteLength", WORD), ("Reserved", WORD * 17),
                ("NumberLinkCollectionNodes", WORD), ("NumberInputButtonCaps", WORD),
                ("NumberInputValueCaps", WORD), ("NumberInputDataIndices", WORD),
                ("NumberOutputButtonCaps", WORD), ("NumberOutputValueCaps", WORD),
                ("NumberOutputDataIndices", WORD), ("NumberFeatureButtonCaps", WORD),
                ("NumberFeatureValueCaps", WORD), ("NumberFeatureDataIndices", WORD)]


class OVERLAPPED(C.Structure):
    _fields_ = [("Internal", ULONG_PTR), ("InternalHigh", ULONG_PTR),
                ("Offset", DWORD), ("OffsetHigh", DWORD), ("hEvent", HANDLE)]


@dataclass(frozen=True)
class DeviceInfo:
    path: str
    vendor_id: int
    product_id: int
    usage_page: int = 0
    usage: int = 0
    input_report_length: int = 0
    output_report_length: int = 0
    feature_report_length: int = 0
    product_name: str = ""

    @property
    def compatible(self) -> bool:
        path = self.path.lower()
        return (self.vendor_id == 0x3554 and self.product_id in (0xF55E, 0xF5D5)
                and "&mi_01&col05#" in path
                and self.input_report_length == 17 and self.output_report_length == 17)

    def __str__(self) -> str:
        connection = "cabo USB" if self.product_id == 0xF55E else "receptor USB"
        return (f"{self.product_name or 'Dispositivo HID'} — {connection} "
                f"({self.vendor_id:04X}:{self.product_id:04X}, "
                f"uso {self.usage_page:04X}:{self.usage:04X})")


class HidError(OSError):
    """A native Windows HID operation failed."""


class _Native:
    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("A comunicação USB deste programa funciona somente no Windows.")
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.hid = C.WinDLL("hid", use_last_error=True)
        self.setup = C.WinDLL("setupapi", use_last_error=True)
        p = C.POINTER
        self._bind(self.hid, "HidD_GetHidGuid", None, [p(GUID)])
        self._bind(self.hid, "HidD_GetAttributes", BYTE, [HANDLE, p(HIDD_ATTRIBUTES)])
        self._bind(self.hid, "HidD_GetPreparsedData", BYTE, [HANDLE, p(C.c_void_p)])
        self._bind(self.hid, "HidD_FreePreparsedData", BYTE, [C.c_void_p])
        self._bind(self.hid, "HidP_GetCaps", C.c_int32, [C.c_void_p, p(HIDP_CAPS)])
        self._bind(self.hid, "HidD_GetProductString", BYTE, [HANDLE, C.c_void_p, DWORD])
        self._bind(self.hid, "HidD_FlushQueue", BYTE, [HANDLE])
        self._bind(self.setup, "SetupDiGetClassDevsW", HANDLE,
                   [p(GUID), C.c_wchar_p, HANDLE, DWORD])
        self._bind(self.setup, "SetupDiEnumDeviceInterfaces", BOOL,
                   [HANDLE, C.c_void_p, p(GUID), DWORD, p(SP_DEVICE_INTERFACE_DATA)])
        self._bind(self.setup, "SetupDiGetDeviceInterfaceDetailW", BOOL,
                   [HANDLE, p(SP_DEVICE_INTERFACE_DATA), C.c_void_p, DWORD, p(DWORD), C.c_void_p])
        self._bind(self.setup, "SetupDiDestroyDeviceInfoList", BOOL, [HANDLE])
        self._bind(self.kernel, "CreateFileW", HANDLE,
                   [C.c_wchar_p, DWORD, DWORD, C.c_void_p, DWORD, DWORD, HANDLE])
        self._bind(self.kernel, "CloseHandle", BOOL, [HANDLE])
        self._bind(self.kernel, "CreateEventW", HANDLE,
                   [C.c_void_p, BOOL, BOOL, C.c_wchar_p])
        self._bind(self.kernel, "ResetEvent", BOOL, [HANDLE])
        self._bind(self.kernel, "WaitForSingleObject", DWORD, [HANDLE, DWORD])
        for name in ("ReadFile", "WriteFile"):
            self._bind(self.kernel, name, BOOL,
                       [HANDLE, C.c_void_p, DWORD, p(DWORD), p(OVERLAPPED)])
        self._bind(self.kernel, "GetOverlappedResult", BOOL,
                   [HANDLE, p(OVERLAPPED), p(DWORD), BOOL])
        self._bind(self.kernel, "CancelIoEx", BOOL, [HANDLE, p(OVERLAPPED)])

    def _bind(self, dll, name: str, result, args: list) -> None:
        function = getattr(dll, name)
        function.restype = result
        function.argtypes = args
        setattr(self, name, function)

    @staticmethod
    def last_error() -> int:
        return C.get_last_error()


_native = None
_native_lock = threading.Lock()


def _get_native():
    global _native
    with _native_lock:
        if _native is None:
            _native = _Native()
        return _native


def _error(native, message: str, code: int | None = None) -> HidError:
    if code is None:
        code = native.last_error()
    detail = C.FormatError(code).strip() if os.name == "nt" else f"erro {code}"
    error = HidError(f"{message} (Windows {code}: {detail})")
    error.winerror = code
    return error


def _query_device(native, handle, path: str) -> DeviceInfo | None:
    attributes = HIDD_ATTRIBUTES()
    attributes.Size = C.sizeof(attributes)
    if not native.HidD_GetAttributes(handle, C.byref(attributes)):
        return None
    preparsed = C.c_void_p()
    if not native.HidD_GetPreparsedData(handle, C.byref(preparsed)):
        return None
    try:
        caps = HIDP_CAPS()
        if native.HidP_GetCaps(preparsed, C.byref(caps)) != 0x00110000:
            return None
        product = C.create_unicode_buffer(128)
        name = product.value if native.HidD_GetProductString(handle, product, C.sizeof(product)) else ""
        return DeviceInfo(path, attributes.VendorID, attributes.ProductID,
                          caps.UsagePage, caps.Usage, caps.InputReportByteLength,
                          caps.OutputReportByteLength, caps.FeatureReportByteLength, name)
    finally:
        native.HidD_FreePreparsedData(preparsed)


def enumerate_devices(include_unknown: bool = False) -> list[DeviceInfo]:
    """Read HID metadata; include_unknown never relaxes the write allowlist."""
    native = _get_native()
    guid = GUID()
    native.HidD_GetHidGuid(C.byref(guid))
    device_set = native.SetupDiGetClassDevsW(C.byref(guid), None, None, 0x12)
    if device_set == INVALID_HANDLE_VALUE:
        raise _error(native, "Não foi possível enumerar os dispositivos HID")
    devices = []
    try:
        index = 0
        while True:
            interface = SP_DEVICE_INTERFACE_DATA()
            interface.cbSize = C.sizeof(interface)
            if not native.SetupDiEnumDeviceInterfaces(device_set, None, C.byref(guid), index, C.byref(interface)):
                code = native.last_error()
                if code == ERROR_NO_MORE_ITEMS:
                    break
                raise _error(native, "Não foi possível enumerar uma interface HID", code)
            index += 1
            required = DWORD()
            native.SetupDiGetDeviceInterfaceDetailW(device_set, C.byref(interface), None, 0, C.byref(required), None)
            code = native.last_error()
            if code != ERROR_INSUFFICIENT_BUFFER or required.value < 6:
                continue
            detail = C.create_string_buffer(required.value)
            # W cbSize is 8 on x64 and 6 on x86; the path starts at byte 4.
            C.cast(detail, C.POINTER(DWORD))[0] = 8 if C.sizeof(HANDLE) == 8 else 6
            if not native.SetupDiGetDeviceInterfaceDetailW(device_set, C.byref(interface), detail,
                                                          required.value, C.byref(required), None):
                continue
            path = C.wstring_at(C.addressof(detail) + 4)
            lowered = path.lower()
            if not include_unknown and not ("vid_3554&pid_f55e" in lowered or "vid_3554&pid_f5d5" in lowered):
                continue
            # DesiredAccess=0 opens only for attributes/caps, not report I/O.
            handle = native.CreateFileW(path, 0, 3, None, 3, 0, None)
            if handle in (None, INVALID_HANDLE_VALUE):
                continue
            try:
                info = _query_device(native, handle, path)
                if info is not None and (include_unknown or
                        info.vendor_id == 0x3554 and info.product_id in (0xF55E, 0xF5D5)):
                    devices.append(info)
            finally:
                native.CloseHandle(handle)
    finally:
        native.SetupDiDestroyDeviceInfoList(device_set)
    return devices


def _valid_report(report: bytes) -> bool:
    return (len(report) == 17 and report[0] == 8 and report[2] == 0
            and sum(report) & 255 == 0x55)


def _matches_response(request: bytes, response: bytes) -> bool:
    if not _valid_report(response) or response[1] != request[1]:
        return False
    return request[1] not in (7, 8) or response[3:6] == request[3:6]


# In the exceptional case that a faulty kernel driver does not finish cancellation,
# keep its native memory alive until its completion event signals. A daemon reaper
# avoids an indefinite UI/CLI wait and never frees pending OVERLAPPED storage.
_retired_operations: set = set()
_retired_lock = threading.Lock()


class _Operation:
    def __init__(self, native, handle, output: bytes | None = None):
        self.native = native
        self.handle = handle
        self.output = output
        self.buffer = C.create_string_buffer(17)
        if output is not None:
            C.memmove(self.buffer, output, 17)
        self.event = native.CreateEventW(None, True, False, None)
        if not self.event:
            raise _error(native, "Não foi possível criar o evento de E/S USB")
        self.overlapped = OVERLAPPED()
        self.overlapped.hEvent = self.event
        self.transferred = DWORD()
        self.pending = False

    def start(self) -> None:
        if self.pending:
            raise RuntimeError("Uma operação USB já está em andamento.")
        if not self.native.ResetEvent(self.event):
            raise _error(self.native, "Não foi possível preparar o evento USB")
        self.overlapped = OVERLAPPED()
        self.overlapped.hEvent = self.event
        self.transferred.value = 0
        function = self.native.ReadFile if self.output is None else self.native.WriteFile
        ok = function(self.handle, self.buffer, 17, C.byref(self.transferred), C.byref(self.overlapped))
        if not ok:
            code = self.native.last_error()
            if code != ERROR_IO_PENDING:
                raise _error(self.native, "Não foi possível iniciar a comunicação USB", code)
        self.pending = True

    def wait(self, deadline: float) -> bytes:
        wait_ms = max(0, math.ceil((deadline - time.monotonic()) * 1000))
        result = self.native.WaitForSingleObject(self.event, wait_ms)
        if result == WAIT_TIMEOUT:
            raise TimeoutError("O mouse não respondeu ao comando USB no prazo esperado.")
        if result != WAIT_OBJECT_0:
            raise _error(self.native, "Falha aguardando o evento USB")
        transferred = DWORD()
        ok = self.native.GetOverlappedResult(self.handle, C.byref(self.overlapped), C.byref(transferred), False)
        code = self.native.last_error() if not ok else 0
        self.pending = False  # The signalled completion event permits releasing storage.
        if not ok:
            raise _error(self.native, "A operação USB não foi concluída", code)
        if transferred.value != 17:
            raise HidError(f"O mouse retornou um relatório de tamanho inesperado: {transferred.value}.")
        return self.buffer.raw

    def close(self) -> bool:
        if self.event is None:
            return True
        if self.pending:
            self.native.CancelIoEx(self.handle, C.byref(self.overlapped))
            if self.native.WaitForSingleObject(self.event, 1000) != WAIT_OBJECT_0:
                with _retired_lock:
                    _retired_operations.add(self)
                threading.Thread(target=self._release_when_complete, daemon=True,
                                 name="redragon-hid-cancel").start()
                return False
            self.pending = False
        self.native.CloseHandle(self.event)
        self.event = None
        return True

    def _release_when_complete(self) -> None:
        if self.native.WaitForSingleObject(self.event, INFINITE) == WAIT_OBJECT_0:
            self.pending = False
            self.native.CloseHandle(self.event)
            self.event = None
            with _retired_lock:
                _retired_operations.discard(self)
        # If even the wait fails, retain storage until process termination.


class WindowsHid:
    """Serialised, bounded overlapped output/input exchanges on one HID collection."""

    def __init__(self, path: str):
        if not isinstance(path, str) or not path:
            raise ValueError("Selecione o caminho de um mouse USB.")
        self._lock = threading.RLock()
        self._native = _get_native()
        self._handle = None
        self._broken = False
        handle = self._native.CreateFileW(path, 0xC0000000, 3, None, 3, 0x40000000, None)
        if handle in (None, INVALID_HANDLE_VALUE):
            raise _error(self._native, "Não foi possível abrir o mouse; feche o aplicativo original")
        try:
            device = _query_device(self._native, handle, path)
            if device is None or not device.compatible:
                raise HidError("Interface incompatível: esperado 3554:F55E/F5D5, MI_01/COL05 e relatórios de 17 bytes.")
            self.device = device
            self._handle = handle
        except BaseException:
            self._native.CloseHandle(handle)
            raise

    def byte_exchange(self, request: bytes, timeout_ms: int = 2000) -> bytes:
        request = bytes(request)
        if not _valid_report(request):
            raise ValueError("O comando deve ser um relatório 08 válido de 17 bytes.")
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or not 1 <= timeout_ms <= 30000:
            raise ValueError("timeout_ms deve estar entre 1 e 30000.")
        with self._lock:
            if self._handle is None or self._broken:
                raise HidError("A conexão USB está fechada; reconecte o mouse antes de tentar novamente.")
            if not self._native.HidD_FlushQueue(self._handle):
                raise _error(self._native, "Não foi possível limpar a fila de respostas HID")
            deadline = time.monotonic() + timeout_ms / 1000
            read = None
            write = None
            try:
                read = _Operation(self._native, self._handle)
                write = _Operation(self._native, self._handle, request)
                read.start()  # Arm interrupt input before the output can respond.
                write.start()
                write.wait(deadline)
                while True:
                    response = read.wait(deadline)
                    if _matches_response(request, response):
                        return response
                    read.start()  # Unrelated/corrupted input consumes the same deadline.
            finally:
                clean = True
                for operation in (write, read):
                    if operation is not None and not operation.close():
                        clean = False
                if not clean:
                    self._broken = True
                    self.close()

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._native.CloseHandle(self._handle)
                self._handle = None

    def __enter__(self) -> WindowsHid:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

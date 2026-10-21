"""Captured HID report protocol, independent of Windows and without I/O on import.

The generic button action 9 is encoded here for controlled testing. Its presence
in the original application does not establish support in the mouse firmware.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable, Iterable, Protocol as TransportProtocol

REPORT_SIZE = 17
REPORT_ID = 0x08
CHECKSUM_TOTAL = 0x55
CONFIG_SIZE = 0xC0
SHORTCUT_SIZE = 0x200
TIMEOUT_MS = 2000
HARDWARE_INDICES = {1: 0, 2: 1, 3: 2, 4: 4, 5: 3, 6: 9, 7: 10, 8: 5}


class ProtocolError(OSError):
    """The device did not satisfy the captured protocol's invariants."""


class IdentityError(ProtocolError):
    pass


class ProfileChangedError(ProtocolError):
    pass


class ReportTransport(TransportProtocol):
    def byte_exchange(self, request: bytes, timeout_ms: int = TIMEOUT_MS) -> bytes: ...


def _integer(value: int, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} deve estar entre {low} e {high}.")
    return value


def _bytes(value: bytes, name: str = "dados") -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError(f"{name} deve ser bytes.")
    return bytes(value)


def checksum(data: bytes) -> int:
    return (CHECKSUM_TOTAL - sum(_bytes(data))) & 0xFF


def build_report(op: int, address: int = 0, count: int = 0, data: bytes = b"") -> bytes:
    _integer(op, "operacao", 0, 0xFF)
    _integer(address, "endereco", 0, 0xFFFF)
    _integer(count, "quantidade", 0, 10)
    data = _bytes(data)
    if len(data) > count:
        raise ValueError("Os dados excedem a quantidade do relatorio.")
    report = bytearray(REPORT_SIZE)
    report[0] = REPORT_ID
    report[1] = op
    report[3:5] = address.to_bytes(2, "big")
    report[5] = count
    report[6:6 + len(data)] = data
    report[16] = checksum(report[:16])
    return bytes(report)


def valid_report(report: bytes) -> bool:
    return (isinstance(report, (bytes, bytearray, memoryview))
            and len(report) == REPORT_SIZE and report[0] == REPORT_ID
            and report[2] == 0 and sum(report) & 0xFF == CHECKSUM_TOTAL)


def matches_report(request: bytes, response: bytes) -> bool:
    if not valid_report(request) or not valid_report(response) or response[1] != request[1]:
        return False
    return request[1] not in (7, 8) or response[3:6] == request[3:6]


def hardware_index(button: int) -> int:
    _integer(button, "botao", 1, 8)
    return HARDWARE_INDICES[button]


def key_address(button: int) -> int:
    return 0x60 + hardware_index(button) * 4


def shortcut_address(button: int) -> int:
    return 0x100 + hardware_index(button) * 0x20


def key_record(key_type: int, parameter1: int = 0, parameter2: int = 0) -> bytes:
    for name, value in (("tipo", key_type), ("parametro1", parameter1), ("parametro2", parameter2)):
        _integer(value, name, 0, 0xFF)
    body = bytes((key_type, parameter1, parameter2))
    return body + bytes((checksum(body),))


def shortcut(modifier: int, keyboard_usage: int) -> bytes:
    """Inline shortcut with HID modifier mask and keyboard usage, as in captures."""
    _integer(modifier, "modificador", 0, 0xFF)
    _integer(keyboard_usage, "tecla HID", 1, 0xFF)
    body = bytearray((4 if modifier else 2,))
    if modifier:
        body.extend((0x80, modifier, 0))
    body.extend((0x81, keyboard_usage, 0, 0x41, keyboard_usage, 0))
    if modifier:
        body.extend((0x40, modifier, 0))
    body.append(checksum(body))
    return bytes(body)


PROFILE_CYCLE_RECORD = key_record(9)


@dataclass(frozen=True)
class Snapshot:
    """Two known configuration regions; not a firmware or complete macro dump.

    Construction intentionally permits raw/incomplete device data. Recovery must
    be able to compare a partially written record with a known-good backup.
    Explicit validate() is required before accepting a backup or applying it.
    """
    index: int
    config: bytes
    shortcuts: bytes

    def validate(self) -> None:
        _integer(self.index, "perfil", 0, 3)
        if not isinstance(self.config, bytes) or len(self.config) != CONFIG_SIZE:
            raise ValueError("Snapshot de configuracao incompleto: esperados 192 bytes.")
        if not isinstance(self.shortcuts, bytes) or len(self.shortcuts) != SHORTCUT_SIZE:
            raise ValueError("Snapshot de atalhos incompleto: esperados 512 bytes.")
        for address in range(0x60, 0xA0, 4):
            if sum(self.config[address:address + 4]) & 0xFF != CHECKSUM_TOTAL:
                raise ValueError(f"Registro de tecla invalido em 0x{address:04X} no perfil {self.index + 1}.")

    def read(self, address: int, count: int) -> bytes:
        _integer(address, "endereco", 0, 0xFFFF)
        _integer(count, "quantidade", 0, 0x10000)
        if address + count <= CONFIG_SIZE:
            source, offset = self.config, address
        elif 0x100 <= address and address + count <= 0x300:
            source, offset = self.shortcuts, address - 0x100
        else:
            raise ValueError("Regiao nao incluida no snapshot.")
        result = source[offset:offset + count]
        if len(result) != count:
            raise ValueError("Snapshot incompleto para a regiao solicitada.")
        return result


class Protocol:
    def __init__(self, transport: ReportTransport, log: Callable[[str], None] | None = None):
        if not callable(getattr(transport, "byte_exchange", None)):
            raise TypeError("O transporte deve fornecer byte_exchange().")
        self.transport = transport
        self.log = log

    def exchange(self, op: int, address: int = 0, count: int = 0, data: bytes = b"") -> bytes:
        request = build_report(op, address, count, data)
        response = self.transport.byte_exchange(request, timeout_ms=TIMEOUT_MS)
        if not matches_report(request, response):
            raise ProtocolError("O mouse devolveu um relatorio invalido ou de outro comando.")
        return bytes(response)

    def confirm_identity(self, expected_type: int | None = None) -> dict:
        if expected_type is not None and (type(expected_type) is not int or expected_type not in (0, 2)):
            raise ValueError("Tipo esperado deve ser 0 (receptor) ou 2 (cabo).")
        response = self.exchange(1, count=8, data=os.urandom(4) + bytes(4))
        if (response[5] != 8 or response[10:12] != bytes((0x17, 0x29))
                or response[12] not in (0, 2)
                or expected_type is not None and response[12] != expected_type):
            raise IdentityError("O dispositivo nao confirmou CID 23, MID 41 e o tipo esperado. Nenhuma configuracao foi gravada.")
        return {"cid": response[10], "mid": response[11], "device_type": response[12], "rawhex": response.hex(" ")}

    def enter_configuration(self) -> None:
        response = self.exchange(2, count=1, data=b"\x01")
        if response[5:7] != b"\x01\x01":
            raise ProtocolError("O mouse nao confirmou o modo de configuracao.")

    def leave_configuration(self) -> None:
        response = self.exchange(2, count=1, data=b"\x00")
        if response[5:7] != b"\x01\x00":
            raise ProtocolError("O mouse nao confirmou o encerramento da configuracao.")

    def current_profile(self) -> int:
        response = self.exchange(0x0E)
        if response[5] != 1 or response[6] > 3:
            raise ProtocolError("Indice de perfil inesperado.")
        return response[6]

    def select_profile(self, index: int) -> None:
        _integer(index, "perfil", 0, 3)
        request = build_report(0x0F, count=1, data=bytes((index,)))
        response = self.transport.byte_exchange(request, timeout_ms=TIMEOUT_MS)
        if response != request:
            raise ProtocolError(f"O mouse nao confirmou a selecao do perfil {index + 1}.")
        if self.current_profile() != index:
            raise ProtocolError(f"Nao foi possivel verificar a selecao do perfil {index + 1}.")

    def read_version(self) -> bytes:
        """Return the complete opcode-12 report; this is not a profile-count query."""
        return self.exchange(0x12)

    def _check_profile(self, expected_profile: int | None) -> None:
        if expected_profile is not None:
            _integer(expected_profile, "perfil esperado", 0, 3)
            if self.current_profile() != expected_profile:
                raise ProfileChangedError("O perfil mudou durante a operacao. Nao pressione o botao 7 durante leituras ou gravacoes.")

    @staticmethod
    def _check_memory(address: int, length: int) -> None:
        _integer(address, "endereco", 0, 0xFFFF)
        _integer(length, "comprimento", 0, 0x10000)
        if address + length > 0x10000:
            raise ValueError("A regiao ultrapassa o limite de enderecos.")

    def read_memory(self, address: int, length: int, expected_profile: int | None = None) -> bytes:
        self._check_memory(address, length)
        result = bytearray()
        for offset in range(0, length, 10):
            self._check_profile(expected_profile)
            count = min(10, length - offset)
            response = self.exchange(8, address + offset, count)
            result.extend(response[6:6 + count])
            self._check_profile(expected_profile)
        return bytes(result)

    def write_memory(self, address: int, data: bytes, expected_profile: int | None = None) -> None:
        data = _bytes(data)
        self._check_memory(address, len(data))
        if not data:
            return
        if expected_profile is None:
            expected_profile = self.current_profile()
        _integer(expected_profile, "perfil esperado", 0, 3)
        for offset in range(0, len(data), 10):
            self._check_profile(expected_profile)
            chunk = data[offset:offset + 10]
            request = build_report(7, address + offset, len(chunk), chunk)
            response = self.transport.byte_exchange(request, timeout_ms=TIMEOUT_MS)
            if response != request:
                raise ProtocolError(f"O mouse nao confirmou a gravacao em 0x{address + offset:04X}.")
            self._check_profile(expected_profile)
        actual = self.read_memory(address, len(data), expected_profile=expected_profile)
        if actual != data:
            raise ProtocolError(f"A releitura nao confirmou a gravacao em 0x{address:04X}.")

    def read_snapshot(self, index: int | None = None) -> Snapshot:
        if index is not None:
            self.select_profile(index)
        current = self.current_profile()
        if self.log:
            self.log(f"Lendo perfil {current + 1}...")
        config = self.read_memory(0, CONFIG_SIZE, expected_profile=current)
        shortcuts = self.read_memory(0x100, SHORTCUT_SIZE, expected_profile=current)
        self._check_profile(current)
        snapshot = Snapshot(current, config, shortcuts)
        snapshot.validate()
        return snapshot

    def read_profiles(self, indices: Iterable[int]) -> dict[int, Snapshot]:
        indices = list(indices)
        if not indices or len(set(indices)) != len(indices):
            raise ValueError("Informe perfis distintos e nao vazios.")
        for index in indices:
            _integer(index, "perfil", 0, 3)
        original = self.current_profile()
        primary: BaseException | None = None
        try:
            return {index: self.read_snapshot(index) for index in indices}
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                self.select_profile(original)
            except Exception as cleanup:
                if primary is None:
                    raise
                errors = getattr(primary, "cleanup_errors", [])
                errors.append(f"Restaurar selecao inicial: {cleanup}")
                primary.cleanup_errors = errors
                if self.log:
                    try:
                        self.log(f"Tambem nao foi possivel restaurar o perfil inicial: {cleanup}")
                    except Exception:
                        pass

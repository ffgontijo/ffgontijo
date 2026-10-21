"""One-time onboard configuration. No input hooks or resident process."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import uuid
from datetime import datetime, timezone
from typing import Callable, ContextManager

from mouse_protocol import Protocol, Snapshot, key_address, key_record, shortcut, shortcut_address
from mouse_lighting import (DPI_INDICATOR_SCOPE, INDICATOR_SCOPE, describe_lighting,
                            dpi_indicator_snapshot, enabled_dpi_count, lighting_records,
                            lighting_status, profile_kind, profile_lighting_snapshot)

FORMAT = "redragon-mini-python/1"
EXPECTED_DEVICE = {"vendor_id": 0x3554, "product_id": 0xF55E, "cid": 0x17, "mid": 0x29, "device_type": 2}
SCOPED_OPERATIONS = {"rgb_only", "dpi_indicator"}


class ConfigurationError(RuntimeError):
    pass


def _snapshot_json(snapshot: Snapshot, *, validate: bool = True) -> dict:
    if validate:
        snapshot.validate()
    return {"index": snapshot.index, "config": snapshot.config.hex(), "shortcuts": snapshot.shortcuts.hex(),
            "sha256": hashlib.sha256(snapshot.config + snapshot.shortcuts).hexdigest()}


def _snapshot_from_json(value: dict) -> Snapshot:
    if not isinstance(value, dict) or type(value.get("index")) is not int or value["index"] not in range(4):
        raise ConfigurationError("Indice de perfil invalido no backup.")
    try:
        result = Snapshot(value["index"], bytes.fromhex(value["config"]), bytes.fromhex(value["shortcuts"]))
        result.validate()
    except Exception as error:
        raise ConfigurationError("Backup incompleto ou com dados invalidos.") from error
    digest = hashlib.sha256(result.config + result.shortcuts).hexdigest()
    if digest != value.get("sha256"):
        raise ConfigurationError("O checksum do backup nao confere. Nao sera gravado no mouse.")
    return result


class Backup:
    """Durable journal: each original snapshot is saved before its first mutation."""

    def __init__(self, path: Path, document: dict):
        self.path = Path(path)
        self.document = document

    @classmethod
    def create(cls, directory: Path, device: dict, initial_profile: int) -> "Backup":
        if any(device.get(name) != value for name, value in EXPECTED_DEVICE.items()):
            raise ConfigurationError("Gravacao permitida somente no mouse cabeado identificado pelas capturas.")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        name = "mouse-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8] + ".json"
        result = cls(directory / name, {
            "format": FORMAT, "created_utc": datetime.now(timezone.utc).isoformat(), "device": dict(device),
            "initial_profile": initial_profile, "phase": "prepared", "originals": {}, "after": {},
            "prepared_banks": [], "cycle": [], "history": [], "usb_reconnect_verified": False,
        })
        result.save()
        return result

    @classmethod
    def load(cls, path: Path) -> "Backup":
        path = Path(path)
        if path.stat().st_size > 256 * 1024:
            raise ConfigurationError("Arquivo de backup grande demais.")
        with path.open(encoding="utf-8") as file:
            document = json.load(file)
        if not isinstance(document, dict) or document.get("format") != FORMAT:
            raise ConfigurationError("Este arquivo nao e um backup da versao Python.")
        operation = document.get("operation")
        if operation is not None and (type(operation) is not str or operation not in {"profiles", *SCOPED_OPERATIONS}):
            raise ConfigurationError("Operacao desconhecida no backup. O escopo nao sera ampliado por aproximacao.")
        device = document.get("device", {})
        if not isinstance(device, dict) or any(type(device.get(k)) is not int or device[k] != v for k, v in EXPECTED_DEVICE.items()):
            raise ConfigurationError("O backup pertence a outro protocolo ou modelo.")
        if type(document.get("initial_profile")) is not int or document["initial_profile"] not in range(4):
            raise ConfigurationError("Perfil inicial invalido no backup.")
        for field in ("originals", "after"):
            values = document.get(field)
            if not isinstance(values, dict) or len(values) > 4:
                raise ConfigurationError("Lista de perfis invalida no backup.")
            for name, value in values.items():
                snapshot = _snapshot_from_json(value)
                if name != str(snapshot.index):
                    raise ConfigurationError("Indices fora de ordem no backup.")
        if not document["originals"]:
            raise ConfigurationError("O backup nao possui perfis originais.")
        cycle = document.get("cycle", [])
        if not isinstance(cycle, list) or any(type(i) is not int or i not in range(4) for i in cycle) or len(set(cycle)) != len(cycle):
            raise ConfigurationError("Ciclo invalido no backup.")
        original_indices = {int(i) for i in document["originals"]}
        prepared = document.get("prepared_banks", [])
        if (not isinstance(prepared, list) or any(type(i) is not int or i not in original_indices for i in prepared)
                or len(set(prepared)) != len(prepared) or not set(cycle).issubset(original_indices)
                or not {int(i) for i in document["after"]}.issubset(original_indices)):
            raise ConfigurationError("O backup nao cobre todos os bancos registrados.")
        if document["after"] and set(map(int, document["after"])) != set(cycle):
            raise ConfigurationError("A configuracao final e o ciclo registrado nao correspondem.")
        if document.get("operation") in SCOPED_OPERATIONS:
            try:
                scope = document.get("lighting_scope", "main")
                lighting_records(scope)
                if (document["operation"] == "dpi_indicator") != (scope == DPI_INDICATOR_SCOPE):
                    raise ValueError("O escopo nao corresponde a operacao do backup.")
                if document["operation"] == "dpi_indicator":
                    counts = document.get("dpi_stage_counts")
                    if (not isinstance(counts, dict) or set(counts) != set(document["originals"])
                            or any(type(count) is not int or not 1 <= count <= 8 for count in counts.values())):
                        raise ValueError("O backup nao registra as etapas DPI originais de todos os bancos.")
                    for field in ("originals", "after"):
                        for value in document[field].values():
                            enabled_dpi_count(_snapshot_from_json(value))
            except ValueError as error:
                raise ConfigurationError(str(error)) from error
        return cls(path, document)

    def save(self) -> None:
        data = json.dumps(self.document, indent=2, ensure_ascii=False).encode("utf-8")
        temporary = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def add_original(self, snapshot: Snapshot) -> None:
        values = self.document["originals"]
        key = str(snapshot.index)
        if key not in values:
            values[key] = _snapshot_json(snapshot)
            self.save()

    def snapshots(self, field: str = "originals") -> dict[int, Snapshot]:
        return {int(key): _snapshot_from_json(value) for key, value in self.document[field].items()}

    def phase(self, value: str, **fields) -> None:
        self.document.update(fields)
        self.document["phase"] = value
        self.save()


def prepare_profiles(originals: dict[int, Snapshot], cycle: list[int]) -> dict[int, Snapshot]:
    """Two logical configurations, repeated in the actual measured cycle order."""
    if len(cycle) not in (2, 4) or len(set(cycle)) != len(cycle) or cycle[0] != 0:
        raise ConfigurationError("O ciclo observado nao permite alternar estritamente dois perfis.")
    if not {0, 1, *cycle}.issubset(originals):
        raise ConfigurationError("Faltam backups dos perfis de base ou dos bancos observados.")
    result = {}
    for position, index in enumerate(cycle):
        source = originals[position % 2]
        destination = originals[index]
        source.validate()
        destination.validate()
        config, keys = bytearray(source.config), bytearray(source.shortcuts)
        # Preserve bytes whose role is not established by the original parser.
        config[0x54:0x60] = destination.config[0x54:0x60]
        config[0xBB:0xC0] = destination.config[0xBB:0xC0]
        count, active = config[2], config[4]
        if (sum(config[2:4]) & 0xFF) != 0x55 or (sum(config[4:6]) & 0xFF) != 0x55 or not 1 <= count <= 8 or active >= count:
            raise ConfigurationError("Quantidade ou indice de etapas DPI invalido. Nao sera aplicada uma codificacao por aproximacao.")
        # Sensor 8960 / captured model: 0x14 == 2000 DPI. Do not copy the
        # captured macOS profile's 3500 DPI into the new configuration.
        for stage in range(count):
            config[0x0C + stage * 4:0x10 + stage * 4] = bytes.fromhex("14 14 00 2d")
        modifier = 8 if position % 2 == 0 else 1
        for button, mod, usage in ((4, modifier, 0x19), (5, modifier, 6),
                                   (6, 8 if position % 2 == 0 else 0, 0x1E if position % 2 == 0 else 0x46)):
            encoded = shortcut(mod, usage)
            address = shortcut_address(button) - 0x100
            keys[address:address + len(encoded)] = encoded
            address = key_address(button)
            config[address:address + 4] = key_record(5)
        config[key_address(7):key_address(7) + 4] = key_record(9)
        if index != source.index and any(config[0x60 + i * 4] == 6 for i in range(16)):
            raise ConfigurationError("Um outro botao usa macro longa. A copia de bancos nao pode replicar essas macros nesta versao.")
        target = Snapshot(index, bytes(config), bytes(keys))
        target.validate()
        result[index] = target
    return result


def patches(before: Snapshot, after: Snapshot):
    """Write shortcut records before binding keys; preserve every unchanged byte."""
    if before.index != after.index:
        raise ConfigurationError("Bancos diferentes em um plano de gravacao.")
    # The original serializer writes the main LED record as 7 bytes at A0,
    # followed by the independent enable/checksum pair at A7. Keep those
    # boundaries during both updates and recovery.
    sections = ((0x100, before.shortcuts, after.shortcuts, 32),
                (0, before.config[:0x4C], after.config[:0x4C], 4),
                (0x4C, before.config[0x4C:0x60], after.config[0x4C:0x60], 2),
                (0x60, before.config[0x60:0xA0], after.config[0x60:0xA0], 4),
                (0xA0, before.config[0xA0:0xA7], after.config[0xA0:0xA7], 7),
                (0xA7, before.config[0xA7:], after.config[0xA7:], 2))
    for address, old, new, unit in sections:
        for offset in range(0, len(old), unit):
            a, b = old[offset:offset + unit], new[offset:offset + unit]
            if a != b:
                yield address + offset, a, b


class Programmer:
    """The connector must verify identity and close PC-driver mode at each exit."""

    def __init__(self, connect: Callable[[], ContextManager[Protocol]], directory: Path,
                 device: dict, log: Callable[[str], None] = print):
        self.connect = connect
        self.directory = Path(directory)
        self.device = dict(device)
        self.log = log
        self.last_backup: Backup | None = None

    def _write_snapshot(self, protocol: Protocol, target: Snapshot, *, scoped: bool = False,
                        lighting_scope: str = "main", dpi_count: int | None = None) -> None:
        target.validate()
        protocol.select_profile(target.index)
        # A failed write may leave an invalid key checksum. Recovery must be able
        # to read that raw preimage and repair it from a known-good snapshot.
        before = Snapshot(target.index,
                          protocol.read_memory(0, 0xC0, expected_profile=target.index),
                          protocol.read_memory(0x100, 0x200, expected_profile=target.index))
        if scoped:
            # Recovery replays only the recorded operation's fields, keeping
            # live keys and settings outside that scope even after later edits.
            if lighting_scope == DPI_INDICATOR_SCOPE and dpi_count is None:
                raise ConfigurationError("Falta a quantidade original de etapas DPI para restauracao.")
            config = bytearray(before.config)
            for address, length in lighting_records(lighting_scope, dpi_count=dpi_count):
                config[address:address + length] = target.config[address:address + length]
            target = Snapshot(target.index, bytes(config), before.shortcuts)
            target.validate()
            if lighting_scope == DPI_INDICATOR_SCOPE:
                enabled_dpi_count(target)
        changes = list(patches(before, target))
        # Check all preimages before writing; every write also checks bank identity.
        for address, old, _ in changes:
            if protocol.read_memory(address, len(old), expected_profile=target.index) != old:
                raise ConfigurationError("O perfil mudou durante a preparacao da gravacao.")
        for address, _, new in changes:
            self.log(f"  Banco {target.index + 1}: gravando 0x{address:04X}")
            protocol.write_memory(address, new, expected_profile=target.index)
        readback = protocol.read_snapshot()
        if readback.config != target.config or readback.shortcuts != target.shortcuts:
            raise ConfigurationError("A verificacao integral do banco gravado nao confere.")

    def _rollback(self, backup: Backup) -> list[str]:
        errors = []
        self.log("Restaurando os dados originais dos bancos incluídos no backup...")
        # Reopen for each bank: one failed connection must not skip other banks.
        for index, target in sorted(backup.snapshots().items(), reverse=True):
            try:
                with self.connect() as protocol:
                    self._write_snapshot(protocol, target, scoped=backup.document.get("operation") in SCOPED_OPERATIONS,
                                         lighting_scope=backup.document.get("lighting_scope", "main"),
                                         dpi_count=backup.document.get("dpi_stage_counts", {}).get(str(index)))
            except Exception as error:
                errors.append(f"Banco {index + 1}: {error}")
        try:
            with self.connect() as protocol:
                protocol.select_profile(backup.document["initial_profile"])
        except Exception as error:
            errors.append("Selecao inicial: " + str(error))
        try:
            backup.phase("recovery_incomplete" if errors else "restored", recovery_errors=errors)
        except Exception as error:
            errors.append("Registro do backup: " + str(error))
        return errors

    def _click_and_read(self, current: int, click: Callable[[int], None]) -> int:
        # The context closes both HID handle and PC-driver mode BEFORE the click.
        click(current)
        with self.connect() as protocol:
            return protocol.current_profile()

    def _probe(self, backup: Backup, click: Callable[[int], None]) -> list[int]:
        cycle = []
        current = 0
        with self.connect() as protocol:
            protocol.select_profile(0)
        for _ in range(4):
            with self.connect() as protocol:
                if protocol.current_profile() != current:
                    raise ConfigurationError("O banco ativo mudou fora do clique solicitado.")
                live = protocol.read_snapshot()
                backup.add_original(live)
                cycle.append(current)
                if current not in backup.document["prepared_banks"]:
                    backup.document["prepared_banks"].append(current)
                backup.phase("probing")  # durable BEFORE writing even four bytes
                self.log(f"Testando funcao interna no banco {current + 1}.")
                address = key_address(7)
                if live.config[address:address + 4] != key_record(9):
                    protocol.write_memory(address, key_record(9), expected_profile=current)
            after = self._click_and_read(current, click)
            backup.document["history"].append([current, after])
            backup.save()
            if after == current:
                raise ConfigurationError("O botao 7 nao mudou o perfil interno. A gravacao final foi cancelada; a funcao pode nao existir neste firmware.")
            if after == 0:
                if len(cycle) not in (2, 4):
                    raise ConfigurationError("O ciclo observado tem numero impar de bancos e nao alterna duas configuracoes a cada clique.")
                backup.phase("cycle_observed", cycle=cycle)
                return cycle
            if after in cycle:
                raise ConfigurationError("O botao retornou a um banco intermediario; nao foi observado um ciclo completo.")
            current = after
        raise ConfigurationError("Nao foi possivel fechar o ciclo em ate quatro bancos.")

    def _check_interrupted(self) -> None:
        for path in self.directory.glob("*.json"):
            try:
                previous = Backup.load(path)
            except (OSError, ValueError, ConfigurationError):
                continue
            if previous.document.get("phase") in {"probing", "cycle_observed", "applying", "recovery_incomplete", "before_restore", "restore_incomplete"}:
                raise ConfigurationError("Ha um procedimento interrompido. Restaure esse backup antes de configurar novamente: " + str(path))

    def configure(self, click: Callable[[int], None]) -> Backup:
        self._check_interrupted()
        # No configuration bytes are written until complete originals are durable.
        with self.connect() as protocol:
            initial = protocol.current_profile()
            bases = protocol.read_profiles([0, 1])
        backup = Backup.create(self.directory, self.device, initial)
        self.last_backup = backup
        for snapshot in bases.values():
            backup.add_original(snapshot)
        self.log("Backup: " + str(backup.path))
        try:
            cycle = self._probe(backup, click)
            targets = prepare_profiles(backup.snapshots(), cycle)
            # Repeat the cycle once, with no HID handle held, before bulk writes.
            self._verify_cycle_order(cycle, click)
            # Reject any unrelated setting change since the original backup.
            with self.connect() as protocol:
                for index in cycle:
                    protocol.select_profile(index)
                    live, original = protocol.read_snapshot(), backup.snapshots()[index]
                    expected = bytearray(original.config)
                    expected[key_address(7):key_address(7) + 4] = key_record(9)
                    if live.config != bytes(expected) or live.shortcuts != original.shortcuts:
                        raise ConfigurationError("Outras configuracoes mudaram durante o teste. Nao sera aplicado um plano obsoleto.")
            backup.phase("applying", after={str(i): _snapshot_json(s) for i, s in targets.items()})
            with self.connect() as protocol:
                for index in cycle:
                    self.log(f"Configurando banco {index + 1}: {'macOS' if cycle.index(index) % 2 == 0 else 'Windows'}")
                    self._write_snapshot(protocol, targets[index])
                protocol.select_profile(0)
            backup.phase("programmed")
            self.log("Dados gravados e relidos. A persistencia apos desligar ainda precisa da verificacao seguinte.")
            return backup
        except BaseException as error:
            self.log("Operacao interrompida: " + str(error))
            recovery = self._rollback(backup)
            detail = "Restauracao verificada." if not recovery else "Restauracao incompleta: " + "; ".join(recovery)
            raise ConfigurationError(f"{error}\n{detail}\nBackup: {backup.path}") from error

    def _existing_cycle(self, click: Callable[[int], None]) -> tuple[int, list[int], dict[int, Snapshot]]:
        """Read the working physical cycle without rewriting its buttons."""
        initial, failure = None, None
        try:
            with self.connect() as protocol:
                initial = protocol.current_profile()
                protocol.select_profile(0)
            current, cycle, originals = 0, [], {}
            for _ in range(4):
                with self.connect() as protocol:
                    if protocol.current_profile() != current:
                        raise ConfigurationError("O banco ativo mudou fora do clique solicitado.")
                    live = protocol.read_snapshot()
                    kind = profile_kind(live)
                    originals[current] = live
                    cycle.append(current)
                    self.log(f"Banco {current + 1}: {'macOS' if kind == 'macos' else 'Windows'} identificado pelos atalhos.")
                after = self._click_and_read(current, click)
                if after == 0:
                    if len(cycle) not in (2, 4):
                        raise ConfigurationError("O ciclo existente nao alterna duas configuracoes.")
                    kinds = [profile_kind(originals[i]) for i in cycle]
                    if any(kinds[i] == kinds[(i + 1) % len(kinds)] for i in range(len(kinds))):
                        raise ConfigurationError("Os perfis existentes nao alternam macOS/Windows a cada clique.")
                    return initial, cycle, originals
                if after in cycle:
                    raise ConfigurationError("O botao 7 nao fechou um ciclo completo a partir do primeiro banco.")
                current = after
            raise ConfigurationError("Nao foi possivel fechar o ciclo existente em ate quatro bancos.")
        except BaseException as error:
            failure = error
            raise
        finally:
            if initial is not None:
                try:
                    with self.connect() as protocol:
                        protocol.select_profile(initial)
                except Exception as cleanup:
                    if failure is None:
                        raise
                    self.log("Falha adicional ao restaurar selecao: " + str(cleanup))

    def update_colors(self, click: Callable[[int], None]) -> Backup:
        """Legacy v0.4 behavior, kept for restoring/testing previous settings."""
        return self._update_existing(click, profile_lighting_snapshot, INDICATOR_SCOPE, "rgb_only")

    def update_dpi_indicator(self, click: Callable[[int], None]) -> Backup:
        """Windows 2100/blue, macOS 2000/red, main RGB off; preserve buttons."""
        return self._update_existing(click, dpi_indicator_snapshot, DPI_INDICATOR_SCOPE, "dpi_indicator")

    def _update_existing(self, click: Callable[[int], None], make_target: Callable[[Snapshot], Snapshot],
                         scope: str, operation: str) -> Backup:
        self._check_interrupted()
        initial, cycle, originals = self._existing_cycle(click)
        targets = {index: make_target(originals[index]) for index in cycle}
        counts = {str(i): enabled_dpi_count(originals[i]) for i in cycle} if operation == "dpi_indicator" else {}
        backup = Backup.create(self.directory, self.device, initial)
        self.last_backup = backup
        for original in originals.values():
            backup.add_original(original)
        backup.phase("prepared", operation=operation, lighting_scope=scope, cycle=cycle,
                     dpi_stage_counts=counts,
                     visual_color_confirmed=False,
                     after={str(i): _snapshot_json(s) for i, s in targets.items()})
        self.log("Backup antes dos ajustes: " + str(backup.path))
        started = False
        try:
            with self.connect() as protocol:
                # Reject a stale plan before changing even the first LED.
                for index, live in protocol.read_profiles(cycle).items():
                    if live != originals[index]:
                        raise ConfigurationError("Os perfis mudaram durante o teste. As cores nao serao aplicadas sobre dados diferentes.")
                backup.phase("applying")
                for index in cycle:
                    protocol.select_profile(index)
                    if protocol.read_snapshot() != originals[index]:
                        raise ConfigurationError("O perfil mudou antes da gravacao da cor.")
                    for address, old, new in patches(originals[index], targets[index]):
                        if (address, len(new)) not in lighting_records(scope, dpi_count=counts.get(str(index))):
                            raise ConfigurationError("O plano tentou modificar outra configuracao fora dos ajustes solicitados.")
                        if protocol.read_memory(address, len(old), expected_profile=index) != old:
                            raise ConfigurationError("A iluminacao mudou antes da gravacao.")
                        started = True  # a failed write can already have changed flash
                        protocol.write_memory(address, new, expected_profile=index)
                    if protocol.read_snapshot() != targets[index]:
                        raise ConfigurationError("A releitura integral do perfil com a nova cor nao confere.")
                # Immediate readback alone cannot detect a field shared by all
                # banks: a later bank's write might overwrite an earlier one.
                for index, live in protocol.read_profiles(cycle).items():
                    if live != targets[index]:
                        raise ConfigurationError(f"A iluminacao do banco {index + 1} mudou depois de gravar outro banco. O firmware nao manteve as cores independentes; nao sera informado sucesso.")
                    self.log(describe_lighting(live))
                protocol.select_profile(initial)
            backup.phase("programmed")
            self.log("Ajustes gravados e relidos. Botoes, atalhos e demais dados fora do ajuste foram preservados.")
            return backup
        except BaseException as error:
            if started:
                recovery = self._rollback(backup)
                detail = "Ajustes anteriores restaurados." if not recovery else "Restauracao incompleta: " + "; ".join(recovery)
            else:
                detail = "Nenhum ajuste foi gravado."
                try:
                    with self.connect() as protocol:
                        protocol.select_profile(initial)
                    backup.phase("not_applied")
                except Exception as cleanup:
                    detail += " Falha ao restaurar selecao/registro: " + str(cleanup)
            raise ConfigurationError(f"{error}\n{detail}\nBackup: {backup.path}") from error

    def _verify_cycle_order(self, cycle: list[int], click: Callable[[int], None], *,
                            targets: dict[int, Snapshot] | None = None,
                            observe: Callable[[Snapshot], None] | None = None) -> None:
        with self.connect() as protocol:
            if protocol.current_profile() != cycle[0]:
                raise ConfigurationError("A verificacao do ciclo deve comecar no primeiro banco.")
        for position, current in enumerate(cycle):
            after = self._click_and_read(current, click)
            if after != cycle[(position + 1) % len(cycle)]:
                raise ConfigurationError("O ciclo nao se repetiu. Pressione o botao 7 uma unica vez em cada etapa.")
            if targets is not None:
                # Read the bank selected physically; do not select it from the
                # host first, which could conceal a stale hardware activation.
                with self.connect() as protocol:
                    if protocol.current_profile() != after:
                        raise ConfigurationError("O banco mudou antes da leitura apos o botao 7.")
                    current_snapshot = protocol.read_snapshot()
                if observe is not None:
                    observe(current_snapshot)
                if current_snapshot != targets[after]:
                    raise ConfigurationError(f"Os dados do banco {after + 1} nao conferem depois do clique fisico.")

    def verify(self, backup: Backup, *, observed_disconnect: bool = False,
               click: Callable[[int], None] | None = None) -> None:
        targets = backup.snapshots("after")
        cycle = backup.document.get("cycle", [])
        if not targets or len(cycle) not in (2, 4) or set(targets) != set(cycle):
            raise ConfigurationError("O backup nao registra uma configuracao final completa.")
        backup.phase("verifying", usb_reconnect_verified=False, hardware_cycle_reverified=False,
                     visual_color_confirmed=False)
        with self.connect() as protocol:
            initial = protocol.current_profile()
            try:
                for index, target in targets.items():
                    protocol.select_profile(index)
                    current = protocol.read_snapshot()
                    if current.config != target.config or current.shortcuts != target.shortcuts:
                        backup.phase("verification_failed", last_error=f"Dados divergentes no banco {index + 1}")
                        raise ConfigurationError(f"Os dados do banco {index + 1} nao persistiram ou foram alterados.")
                protocol.select_profile(cycle[0] if click is not None else initial)
            except BaseException as error:
                try:
                    protocol.select_profile(initial)
                except Exception as cleanup:
                    self.log("Falha adicional ao restaurar selecao: " + str(cleanup))
                raise
        if click is not None:
            failure = None
            try:
                if backup.document.get("operation") in SCOPED_OPERATIONS:
                    backup.document["physical_lighting_reads"] = []

                    def observe(snapshot: Snapshot) -> None:
                        backup.document["physical_lighting_reads"].append(lighting_status(snapshot))
                        backup.save()
                        self.log(describe_lighting(snapshot))

                    self._verify_cycle_order(cycle, click, targets=targets, observe=observe)
                else:
                    self._verify_cycle_order(cycle, click)
            except BaseException as error:
                failure = error
                backup.phase("verification_failed", last_error=str(error))
                raise
            finally:
                if backup.document.get("operation") in SCOPED_OPERATIONS:
                    try:
                        with self.connect() as protocol:
                            protocol.select_profile(initial)
                    except Exception as cleanup:
                        if failure is None:
                            backup.phase("verification_failed", last_error=str(cleanup))
                            raise
                        self.log("Falha adicional ao restaurar selecao: " + str(cleanup))
        backup.phase("reconnect_verified" if observed_disconnect else "verified_in_session",
                     usb_reconnect_verified=bool(observed_disconnect), hardware_cycle_reverified=click is not None)
        self.log("Dados conferidos apos desconexao observada." if observed_disconnect else "Dados conferidos nesta sessao; isso ainda nao confirma desligamento.")

    def restore(self, backup: Backup) -> Backup:
        originals = backup.snapshots()
        current, damaged = {}, {}
        with self.connect() as protocol:
            initial = protocol.current_profile()
            failure = None
            try:
                for index in sorted(originals):
                    protocol.select_profile(index)
                    raw = Snapshot(index, protocol.read_memory(0, 0xC0, expected_profile=index),
                                   protocol.read_memory(0x100, 0x200, expected_profile=index))
                    try:
                        raw.validate()
                        if backup.document.get("operation") == "dpi_indicator":
                            enabled_dpi_count(raw)
                    except Exception:
                        damaged[str(index)] = _snapshot_json(raw, validate=False)
                    else:
                        current[index] = raw
            except BaseException as error:
                failure = error
                raise
            finally:
                try:
                    protocol.select_profile(initial)
                except Exception as cleanup:
                    if failure is None:
                        raise
                    self.log("Falha adicional ao restaurar selecao: " + str(cleanup))
        recovery = Backup.create(self.directory, self.device, initial)
        for snapshot in current.values():
            recovery.add_original(snapshot)
        recovery.phase("before_restore", restored_from=str(backup.path), damaged_current=damaged,
                       operation=backup.document.get("operation", "profiles"),
                       lighting_scope=backup.document.get("lighting_scope", "main"),
                       dpi_stage_counts={str(i): backup.document["dpi_stage_counts"][str(i)] for i in current}
                       if backup.document.get("operation") == "dpi_indicator" else {})
        self.log("Backup anterior a restauracao: " + str(recovery.path))
        try:
            with self.connect() as protocol:
                for target in originals.values():
                    self._write_snapshot(protocol, target, scoped=backup.document.get("operation") in SCOPED_OPERATIONS,
                                         lighting_scope=backup.document.get("lighting_scope", "main"),
                                         dpi_count=backup.document.get("dpi_stage_counts", {}).get(str(target.index)))
                protocol.select_profile(initial if backup.document.get("operation") in SCOPED_OPERATIONS
                                        else backup.document["initial_profile"])
            backup.phase("restored")
            recovery.phase("restore_completed")
            return recovery
        except BaseException as error:
            if damaged:
                # Never reintroduce known-corrupt key records as a rollback target.
                message = "O estado anterior ja tinha registros invalidos. Reaplique o backup original para concluir a reparacao: " + str(backup.path)
                backup.phase("restore_incomplete", last_error=str(error))
            else:
                problems = self._rollback(recovery)
                message = "Estado anterior recuperado." if not problems else "Recuperacao incompleta: " + "; ".join(problems)
            raise ConfigurationError(f"A restauracao falhou: {error}\n{message}\nRegistro anterior: {recovery.path}") from error

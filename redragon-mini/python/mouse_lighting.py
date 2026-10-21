"""Main RGB strip records, as serialized by the supplied native mouse library."""
from __future__ import annotations

from mouse_protocol import Snapshot, checksum, key_address, key_record, shortcut, shortcut_address

PROFILE_COLORS = {"macos": (255, 0, 255), "windows": (255, 0, 0)}
LED_ADDRESS = 0xA0
LED_ENABLE_ADDRESS = 0xA7
MAIN_SCOPE = "main"
INDICATOR_SCOPE = "main_dpi_movement"


def lighting_records(scope: str = MAIN_SCOPE) -> tuple[tuple[int, int], ...]:
    """Only known LED records may be restored by a lighting-only backup."""
    main = ((0xA0, 7), (0xA7, 2))
    if scope == MAIN_SCOPE:
        return main  # version 0.3 backups keep their original scope
    if scope == INDICATOR_SCOPE:
        return (tuple((0x2C + 4 * i, 4) for i in range(8))
                + ((0x4C, 2), (0x4E, 2), (0x52, 2)) + main + ((0xB3, 2),))
    raise ValueError("Escopo de iluminacao desconhecido no backup.")


def profile_kind(snapshot: Snapshot) -> str:
    """Recognize the working shortcuts, without interpreting unused slot tails."""
    snapshot.validate()
    address = key_address(7)
    if snapshot.config[address:address + 4] != key_record(9):
        raise ValueError(f"O banco {snapshot.index + 1} nao tem o botao 7 como troca interna de perfil.")
    for kind, modifier, print_modifier, print_usage in (("macos", 8, 8, 0x1E), ("windows", 1, 0, 0x46)):
        matches = True
        for button, mod, usage in ((4, modifier, 0x19), (5, modifier, 6), (6, print_modifier, print_usage)):
            address = key_address(button)
            encoded = shortcut(mod, usage)
            at = shortcut_address(button) - 0x100
            if (snapshot.config[address:address + 4] != key_record(5)
                    or snapshot.shortcuts[at:at + len(encoded)] != encoded):
                matches = False
                break
        if matches:
            return kind
    raise ValueError(f"Os atalhos do banco {snapshot.index + 1} nao correspondem aos perfis macOS/Windows ja configurados. Nenhum botao sera regravado.")


def colored_snapshot(snapshot: Snapshot) -> Snapshot:
    """Change only A0..A8: steady RGB, maximum brightness, lighting enabled."""
    kind = profile_kind(snapshot)
    config = bytearray(snapshot.config)
    speed = config[LED_ADDRESS + 4]
    if not 0 <= speed <= 9:
        raise ValueError(f"Velocidade RGB fora da faixa conhecida no banco {snapshot.index + 1}.")
    # Mode 3 enables custom RGB without animation. Speed is ignored in this
    # mode; retain it. Brightness is 0..9, independently of RGB's 0..255.
    body = bytes((3, *PROFILE_COLORS[kind], speed, 9))
    config[LED_ADDRESS:LED_ENABLE_ADDRESS] = body + bytes((checksum(body),))
    config[LED_ENABLE_ADDRESS:LED_ENABLE_ADDRESS + 2] = bytes((1, 0x54))
    return Snapshot(snapshot.index, bytes(config), snapshot.shortcuts)


def profile_lighting_snapshot(snapshot: Snapshot) -> Snapshot:
    """Align both lighting groups and keep lights on while moving.

    DPI stage colors are separate from DPI values. The original captures use
    red for stage zero in both profiles; version 0.3 retained that table.
    Configure every stage's indicator color so a stage change cannot bring
    back the previous red. Do not alter DPI values/count/index or sleep time.
    """
    kind = profile_kind(snapshot)
    config = bytearray(colored_snapshot(snapshot).config)
    rgb = bytes(PROFILE_COLORS[kind])
    record = rgb + bytes((checksum(rgb),))
    for stage in range(8):
        at = 0x2C + stage * 4
        config[at:at + 4] = record
    # DPI LED mode 1 is steady; brightness uses the original 0..255 scale
    # (ValueConvert.DPIIndexToBrightness(10) == 255), unlike LedBar's 0..9.
    for at, value in ((0x4C, 1), (0x4E, 255), (0x52, 1), (0xB3, 0)):
        config[at:at + 2] = bytes((value, checksum(bytes((value,)))))
    return Snapshot(snapshot.index, bytes(config), snapshot.shortcuts)


def lighting_status(snapshot: Snapshot) -> dict:
    """A diagnostic reading; stored bytes do not establish a visible color."""
    kind = profile_kind(snapshot)
    active = snapshot.config[4]
    at = 0x2C + 4 * active if active < 8 else None
    return {"bank": snapshot.index, "platform": kind,
            "main_mode": snapshot.config[0xA0], "main_rgb": list(snapshot.config[0xA1:0xA4]),
            "main_enabled": snapshot.config[0xA7],
            "dpi_mode": snapshot.config[0x4C], "dpi_enabled": snapshot.config[0x52],
            "dpi_rgb": list(snapshot.config[at:at + 3]) if at is not None else None,
            "move_off_enabled": snapshot.config[0xB3]}


def describe_lighting(snapshot: Snapshot) -> str:
    status = lighting_status(snapshot)
    main = "#" + bytes(status["main_rgb"]).hex().upper()
    dpi = "#" + bytes(status["dpi_rgb"]).hex().upper() if status["dpi_rgb"] is not None else "indice invalido"
    moving = "ATIVADO" if status["move_off_enabled"] else "desativado"
    return (f"Banco {snapshot.index + 1} ({status['platform']}): faixa {main}; "
            f"indicador DPI {dpi}; apagar ao mover {moving}.")

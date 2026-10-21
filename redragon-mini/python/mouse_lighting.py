"""Main RGB strip records, as serialized by the supplied native mouse library."""
from __future__ import annotations

from mouse_protocol import Snapshot, checksum, key_address, key_record, shortcut, shortcut_address

PROFILE_COLORS = {"macos": (255, 0, 255), "windows": (255, 0, 0)}
LED_ADDRESS = 0xA0
LED_ENABLE_ADDRESS = 0xA7


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

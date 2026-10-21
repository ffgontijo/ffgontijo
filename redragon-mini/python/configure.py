#!/usr/bin/env python3
"""Guided Windows-only, one-time onboard mouse configuration."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import time

if sys.version_info < (3, 10):
    raise SystemExit("Este configurador precisa do Python 3.10 ou superior.")

from mouse_hid import WindowsHid, enumerate_devices
from mouse_protocol import Protocol
from mouse_service import Backup, ConfigurationError, Programmer, EXPECTED_DEVICE

ROOT = Path(__file__).resolve().parent


def say(message: str) -> None:
    print(message, flush=True)


def compatible_wired():
    return [d for d in enumerate_devices() if d.compatible and d.product_id == 0xF55E]


def choose_device():
    devices = compatible_wired()
    if not devices:
        show_devices()
        raise ConfigurationError("Nenhuma interface cabeada compativel foi encontrada. Conecte o cabo USB diretamente ao mouse e ao PC. O receptor e Bluetooth nao sao usados para gravar.")
    if len(devices) == 1:
        say("Mouse cabeado encontrado: " + devices[0].product_name)
        return devices[0]
    for number, device in enumerate(devices, 1):
        say(f"{number}. {device.product_name} | {device.path}")
    number = int(input("Qual mouse deseja configurar? "))
    if not 1 <= number <= len(devices):
        raise ConfigurationError("Selecao invalida.")
    return devices[number - 1]


def show_devices() -> None:
    devices = enumerate_devices(include_unknown=True)
    candidates = [d for d in devices if d.vendor_id in (0x3554, 0x25A7, 0x258A, 0x04D9)
                  or "redragon" in d.product_name.lower()]
    say("\nIdentificacao USB somente de leitura:")
    if not candidates:
        say("Nenhuma colecao Redragon candidata apareceu. Verifique o cabo de dados.")
    for device in candidates:
        say(f"{device.vendor_id:04X}:{device.product_id:04X} | {device.product_name} | entrada={device.input_report_length}, saida={device.output_report_length}")
        say("  " + device.path)
        say("  " + ("Protocolo capturado reconhecido." if device.compatible else "Nao autorizado para gravacao por esta versao."))
    say("O nome M719RGB-PRO V2 na etiqueta nao substitui a identificacao USB.")


class Connector:
    def __init__(self, device):
        self.device = device

    @contextmanager
    def __call__(self):
        if not self.device.compatible or self.device.product_id != 0xF55E:
            raise ConfigurationError("A gravacao requer a interface cabeada exata das capturas.")
        hid = WindowsHid(self.device.path)
        protocol = Protocol(hid)
        failure, entered = None, False
        try:
            actual = hid.device
            if actual.product_id != 0xF55E or not actual.compatible:
                raise ConfigurationError("A interface aberta nao corresponde ao mouse cabeado esperado.")
            protocol.confirm_identity(expected_type=2)
            entered = True  # even a lost enter ACK requires a best-effort leave
            protocol.enter_configuration()
            yield protocol
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                if entered:
                    try:
                        protocol.leave_configuration()
                    except Exception as cleanup:
                        if failure is None:
                            failure = ConfigurationError("Nao foi possivel encerrar o modo de configuracao: " + str(cleanup))
                            raise failure from cleanup
                        say("Falha adicional ao encerrar a conexao: " + str(cleanup))
            finally:
                try:
                    hid.close()
                except Exception as cleanup:
                    if failure is not None:
                        say("Falha adicional ao fechar HID: " + str(cleanup))
                    else:
                        raise

    def wait_for_reconnect(self, seconds: float = 180) -> None:
        say("\nVerificacao de memoria, com o cabo:")
        say("1. Desconecte o cabo USB do mouse e coloque a chave inferior em OFF.")
        say("2. Aguarde pelo menos 5 segundos; depois reconecte o cabo ao PC.")
        say("O programa esta observando a desconexao. Ctrl+C cancela somente esta verificacao.")
        start, disconnected = time.monotonic(), False
        old_path = self.device.path.lower()
        while time.monotonic() - start < seconds:
            available = compatible_wired()
            if not disconnected:
                if not any(d.path.lower() == old_path for d in available):
                    disconnected = True
                    say("Desconexao USB detectada. Aguardando reconexao...")
            elif available:
                if len(available) != 1:
                    raise ConfigurationError("Mais de um mouse compativel apareceu. Deixe conectado somente o mouse em teste.")
                self.device = available[0]
                say("Mouse reconectado; conferindo os dados novamente.")
                return
            time.sleep(0.4)
        raise ConfigurationError("A desconexao/reconexao nao foi observada dentro de 3 minutos. Os dados gravados continuam no backup; use Verificar novamente.")


def backup_directory() -> Path:
    preferred = ROOT / "backups"
    try:
        preferred.mkdir(exist_ok=True)
        probe = preferred / (".write-" + str(os.getpid()))
        with probe.open("x") as file:
            file.write("")
        probe.unlink()
        return preferred
    except OSError:
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RedragonMiniPython" / "backups"
        base.mkdir(parents=True, exist_ok=True)
        return base


def choose_backup(directory: Path) -> Backup:
    paths = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for number, path in enumerate(paths[:30], 1):
        try:
            item = Backup.load(path)
            say(f"{number}. {path.name} | {item.document.get('phase', '?')} | {len(item.document['originals'])} bancos")
        except Exception:
            say(f"{number}. {path.name} | incompleto/invalido")
    selected = input("Numero do backup, ou caminho completo do arquivo: ").strip().strip('"')
    if selected.isdigit() and 1 <= int(selected) <= min(len(paths), 30):
        return Backup.load(paths[int(selected) - 1])
    return Backup.load(Path(selected))


def click_button(current: int) -> None:
    say(f"\nBanco ativo antes do teste: {current + 1}.")
    say("A conexao do configurador esta fechada. Pressione UMA vez o botao 7 do mouse.")
    input("Depois pressione Enter aqui (nao pressione outros botoes do mouse): ")


def describe() -> None:
    say("\nREDRAGON MINI PYTHON 0.3 - configuracao unica no Windows")
    say("                 macOS                Windows")
    say("Botao 4:         Command+V            Ctrl+V")
    say("Botao 5:         Command+C            Ctrl+C")
    say("Botao 6:         Command+1            Print Screen")
    say("Botao 7:         alternar as duas configuracoes no proprio mouse")
    say("DPI:             2000 em todas as etapas habilitadas; cores preservadas nesta opcao.")
    say("Para adicionar rosa/macOS e vermelho/Windows aos perfis que ja funcionam, use a opcao 5.")
    say("\nA funcao interna sera testada antes da gravacao final. Se nao funcionar, o programa restaura e para.")
    say("Se o firmware percorrer quatro bancos, os dados serao organizados como Mac/Windows/Mac/Windows na ordem medida.")
    say("Nenhum servico ou remapeador fica instalado. Feche o aplicativo original da Redragon.")


def configure_once() -> None:
    describe()
    connector = Connector(choose_device())
    programmer = Programmer(connector, backup_directory(), EXPECTED_DEVICE, say)
    say("\nNao pressione botoes do mouse durante leituras ou gravacoes; use somente os cliques solicitados.")
    backup = programmer.configure(click_button)
    say("\nConfiguracao gravada. Backup: " + str(backup.path))
    try:
        connector.wait_for_reconnect()
        programmer.verify(backup, observed_disconnect=True, click=click_button)
        say("\nConferencia apos reconexao e ciclo do botao 7 concluidos.")
        say("Pode fechar este programa. Teste copiar/colar/print no Windows e no Mac.")
        say("No Mac, Command+1 precisa continuar definido como seu atalho de captura.")
        say("Teste tambem no receptor e no Bluetooth: a memoria compartilhada entre modos nao foi comprovada pelas capturas.")
    except (KeyboardInterrupt, EOFError):
        say("\nA configuracao foi gravada; a verificacao apos desligar nao foi concluida. Use a opcao Verificar depois.")
    except Exception as error:
        say("\nA gravacao foi relida antes de desconectar, mas a verificacao posterior falhou: " + str(error))
        say("Nao considere a persistencia comprovada. Backup: " + str(backup.path))
        say("Use Verificar ou Restaurar no menu.")


def inspect_device() -> None:
    show_devices()
    devices = compatible_wired()
    if len(devices) == 1:
        with Connector(devices[0])() as protocol:
            identity = protocol.confirm_identity(expected_type=2)
            version = protocol.read_version()
            # Opcode 12 returns bytes 04 01 => v4.01, NOT v1.04.
            say("Identidade confirmada: " + str(identity))
            say("Perfil interno ativo: " + str(protocol.current_profile() + 1))
            say("Resposta de versao (hex): " + version.hex(" "))
    elif len(devices) > 1:
        say("Ha varios mouses compativeis; deixe conectado somente o que sera configurado.")


def update_colors_once() -> None:
    say("\nSomente iluminacao dos perfis existentes:")
    say("macOS: rosa fixo RGB 255, 0, 255. Windows: vermelho fixo RGB 255, 0, 0.")
    say("Botoes 4, 5, 6 e 7, DPI e demais preferencias serao conservados.")
    say("Feche o aplicativo original da Redragon e conecte o mouse pelo cabo USB.")
    say("Primeiro vamos reconhecer os perfis pelos atalhos atuais e pelos cliques solicitados no botao 7.")
    say("Nao pressione botoes durante leituras ou gravacoes; clique somente quando solicitado.")
    connector = Connector(choose_device())
    programmer = Programmer(connector, backup_directory(), EXPECTED_DEVICE, say)
    backup = programmer.update_colors(click_button)
    say("\nCores gravadas. Backup da configuracao anterior: " + str(backup.path))
    try:
        connector.wait_for_reconnect()
        programmer.verify(backup, observed_disconnect=True, click=click_button)
        say("\nCores conferidas na memoria apos reconexao; ciclo do botao 7 conferido.")
        say("Pode fechar o programa. Confira visualmente: macOS rosa, Windows vermelho.")
        say("Teste tambem a nova iluminacao no receptor 2,4 GHz e no Bluetooth.")
    except (KeyboardInterrupt, EOFError):
        say("\nAs cores foram gravadas; a conferencia apos desligar ficou pendente. Use a opcao 3 depois.")
    except Exception as error:
        say("\nAs cores foram relidas antes de desconectar, mas a conferencia posterior falhou: " + str(error))
        say("Backup: " + str(backup.path))
        say("Use a opcao 3 para verificar ou 4 para restaurar a iluminacao anterior.")


def verify_saved() -> None:
    directory = backup_directory()
    backup = choose_backup(directory)
    connector = Connector(choose_device())
    programmer = Programmer(connector, directory, EXPECTED_DEVICE, say)
    connector.wait_for_reconnect()
    programmer.verify(backup, observed_disconnect=True, click=click_button)


def restore_saved() -> None:
    directory = backup_directory()
    backup = choose_backup(directory)
    connector = Connector(choose_device())
    programmer = Programmer(connector, directory, EXPECTED_DEVICE, say)
    programmer.restore(backup)
    say("Dados originais restaurados e relidos. Nenhum programa precisa ficar aberto.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Configuracao unica, por cabo, de perfis internos do mouse no Windows.")
    parser.add_argument("--inspect", action="store_true", help="somente identificar dispositivos e consultar o perfil")
    args = parser.parse_args()
    if os.name != "nt":
        say("O configurador USB desta versao roda no Windows. Depois da gravacao, o objetivo e usar a memoria do mouse em qualquer computador.")
        return 1
    if args.inspect:
        inspect_device()
        return 0
    while True:
        say("\nREDRAGON MINI PYTHON 0.3")
        say("\n1 Configurar os dois perfis (assistente com teste fisico do botao 7)")
        say("2 Identificar mouse, sem gravar configuracoes")
        say("3 Verificar configuracao apos desligar/reconectar")
        say("4 Restaurar backup")
        say("5 Aplicar SOMENTE CORES aos perfis existentes (macOS rosa / Windows vermelho)")
        say("0 Sair")
        try:
            choice = input("Escolha: ").strip()
            if choice == "0":
                return 0
            action = {"1": configure_once, "2": inspect_device, "3": verify_saved,
                      "4": restore_saved, "5": update_colors_once}.get(choice)
            if action is None:
                say("Escolha 0, 1, 2, 3, 4 ou 5.")
                continue
            action()
        except (KeyboardInterrupt, EOFError):
            say("\nOperacao cancelada. Consulte o backup informado antes de qualquer gravacao.")
        except Exception as error:
            say("\nERRO: " + str(error))
            say("Nenhuma protecao do Windows foi alterada. Guarde esta mensagem para diagnostico.")


if __name__ == "__main__":
    raise SystemExit(main())

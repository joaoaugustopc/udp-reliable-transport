import os
import shutil
import time
from client import CLIENT_LOG_DIR, run_client
from server import SERVER_LOG_DIR, run_server
import threading


def test(total_packets=10000, packet_loss_rate=0.0):
    """
    Testa o protocolo UDP confiável com controle de congestionamento.

    Args:
        total_packets: Número de pacotes a enviar (mínimo 10.000)
        packet_loss_rate: Taxa de perda de pacotes (0.0 a 1.0). Ex: 0.1 = 10% de perda
    """
    print("\n" + "=" * 80)
    print("TESTE DO PROTOCOLO UDP CONFIÁVEL")
    print("=" * 80)
    print(f"Pacotes a enviar: {total_packets}")
    print(f"Taxa de perda simulada: {packet_loss_rate * 100:.1f}%")
    print("=" * 80 + "\n")

    # Limpa os logs anteriores
    shutil.rmtree(CLIENT_LOG_DIR, ignore_errors=True)
    shutil.rmtree(SERVER_LOG_DIR, ignore_errors=True)

    # Inicia servidor e cliente em threads separadas
    server_thread = threading.Thread(
        target=run_server, kwargs={"packet_loss_rate": packet_loss_rate}, daemon=True
    )
    client_thread = threading.Thread(
        target=run_client, kwargs={"total_packets": total_packets}
    )

    server_thread.start()
    time.sleep(0.5)  # Aguarda servidor iniciar
    client_thread.start()

    client_thread.join()  # Aguarda cliente terminar

    print("\n[TEST] Cliente finalizou. Aguardando 2s para servidor processar...")
    time.sleep(2)

    print("[TEST] Teste concluído! Verifique os logs em client_logs/ e server_logs/")


if __name__ == "__main__":
    # Teste padrão: 10.000 pacotes com 10% de perda
    test(total_packets=10000, packet_loss_rate=0.1)

    # Exemplos de outros testes:
    # test(total_packets=10000, packet_loss_rate=0.0)   # Sem perdas
    # test(total_packets=10000, packet_loss_rate=0.05)  # 5% de perda
    # test(total_packets=20000, packet_loss_rate=0.15)  # 20k pacotes, 15% perda

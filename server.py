import socket
import struct
import random
from crypto import SimpleCrypto
from logs import save_log

TYPE_DATA = 0
TYPE_ACK = 1
TYPE_NONCE_REQ = 2  # Cliente solicita início do handshake
TYPE_NONCE_RESP = 3  # Servidor responde com seu nonce

HEADER_FMT = "!BIIH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

SERVER_LOG_DIR = "server_logs"


# Empacota os valores e transforma em uma sequência de bytes
def make_ack(expected_seq: int) -> bytes:
    return struct.pack(HEADER_FMT, TYPE_ACK, 0, expected_seq, 0)


def parse_packet(data: bytes):
    if len(data) < HEADER_SIZE:
        return None

    ptype, seq, ack, length = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])

    payload = data[HEADER_SIZE : HEADER_SIZE + length]

    return ptype, seq, ack, payload


def run_server(host="0.0.0.0", port=9000, packet_loss_rate=0.0):
    """
    Servidor UDP com suporte a perda simulada de pacotes.

    Args:
        host: Endereço de IP para bind
        port: Porta para escutar
        packet_loss_rate: Taxa de perda de pacotes (0.0 a 1.0). Ex: 0.1 = 10% de perda
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # IPv4, UDP
    sock.bind((host, port))

    print(f"[server] listening on {host}:{port}")
    print(f"[server] packet loss rate: {packet_loss_rate * 100:.1f}%")
    save_log(SERVER_LOG_DIR, f"Server started on {host}:{port}")
    save_log(SERVER_LOG_DIR, f"Packet loss rate: {packet_loss_rate * 100:.1f}%")

    expected_seq = 0

    buffer = (
        {}
    )  # seq: payload (Serve oara armazenar as sequncias que chegaram fora de ordem)

    client_addr = None
    delivered = 0
    crypto = SimpleCrypto()  # Instância de criptografia

    # Estatísticas
    total_received = 0
    total_dropped = 0

    while True:
        data, addr = sock.recvfrom(
            65535
        )  # Tamanho máximo de um pacote é 65.535 bytes. Pois o campo "total lenght" bo cabeçalho IPv4 tem 16bits.

        client_addr = addr

        parsed = parse_packet(data)
        if not parsed:
            continue

        ptype, seq, ack, payload = parsed

        # Handshake de criptografia
        if ptype == TYPE_NONCE_REQ:
            # Cliente envia seu nonce, servidor responde com o seu
            if len(payload) >= 16:
                client_nonce = payload[:16]
                server_nonce = crypto.generate_nonce()

                # Deriva a chave de sessão - MESMA ORDEM que o cliente
                crypto.derive_session_key(client_nonce, server_nonce)

                # Envia o nonce do servidor de volta
                nonce_resp = (
                    struct.pack(HEADER_FMT, TYPE_NONCE_RESP, 0, 0, len(server_nonce))
                    + server_nonce
                )
                sock.sendto(nonce_resp, addr)
                print(f"[server] crypto handshake completed with {addr}")
                print(f"[server] client_nonce: {client_nonce.hex()[:16]}...")
                print(f"[server] server_nonce: {server_nonce.hex()[:16]}...")
                print(f"[server] session_key:  {crypto.session_key.hex()[:16]}...")
                save_log(SERVER_LOG_DIR, f"Crypto handshake completed with {addr}")
            continue

        if ptype != TYPE_DATA:
            continue

        # Simulação de perda de pacotes (apenas para pacotes de dados)
        total_received += 1
        if random.random() < packet_loss_rate:
            total_dropped += 1
            save_log(
                SERVER_LOG_DIR,
                f"[server] DROPPED packet seq={seq} (total_dropped={total_dropped})",
            )
            continue  # Descarta o pacote

        # Decifra o payload se a criptografia estiver estabelecida
        if crypto.is_established():
            decrypted_payload = crypto.decrypt(payload, seq)
            save_log(SERVER_LOG_DIR, f"[server] decrypted payload seq={seq}")
            save_log(SERVER_LOG_DIR, f"[payload] {payload.hex()[0:7]}", type="payload")
            if decrypted_payload is None:
                # Falha na verificação de integridade
                continue
            payload = decrypted_payload
            save_log(SERVER_LOG_DIR, f"[server] received packet seq={seq}")
            save_log(
                SERVER_LOG_DIR,
                f"[decrypted payload] {decrypted_payload.hex()[0:7]}",
                type="payload",
            )

        # Reordenação + entrega ordenada
        if seq == expected_seq:
            # entrega este e todos os consecutivos do buffer
            delivered += 1
            expected_seq += 1

            while expected_seq in buffer:
                buffer.pop(expected_seq)
                delivered += 1
                expected_seq += 1

        elif seq > expected_seq:
            # guarda se ainda não tinha
            buffer.setdefault(seq, payload)

        else:
            pass

        # ACK cumulativo: sempre diz "próximo que eu quero"
        ack_pkt = make_ack(expected_seq)
        sock.sendto(ack_pkt, client_addr)

        if delivered % 1000 == 0 and delivered > 0:
            loss_rate = (
                (total_dropped / total_received * 100) if total_received > 0 else 0
            )
            print(
                f"[server] delivered={delivered} expected_seq={expected_seq} buffered={len(buffer)} "
                f"received={total_received} dropped={total_dropped} ({loss_rate:.1f}%)"
            )
            save_log(
                SERVER_LOG_DIR,
                f"delivered={delivered} expected_seq={expected_seq} buffered={len(buffer)} "
                f"received={total_received} dropped={total_dropped} ({loss_rate:.1f}%)",
            )


if __name__ == "__main__":
    run_server()

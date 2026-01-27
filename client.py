import socket
import struct
import time
from congestion import CongestionController
from crypto import SimpleCrypto
from logs import save_log


TYPE_DATA = 0  # Igual no server.py
TYPE_ACK = 1  # Igual no server.py
TYPE_NONCE_REQ = 2  # Cliente solicita início do handshake
TYPE_NONCE_RESP = 3  # Servidor responde com seu nonce

HEADER_FMT = "!BIIH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

PAYLOAD_SIZE = 1000
TIMEOUT = 0.2

CLIENT_LOG_DIR = "client_logs"


# Monta bytes do pacote (Header + Payload)
def make_data(seq: int, payload: bytes) -> bytes:
    return struct.pack(HEADER_FMT, TYPE_DATA, seq, 0, len(payload)) + payload


def parse_packet(data: bytes):
    if len(data) < HEADER_SIZE:
        return None
    ptype, seq, ack, length = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
    payload = data[HEADER_SIZE : HEADER_SIZE + length]
    return ptype, seq, ack, payload


def crypto_handshake(sock, server, crypto: SimpleCrypto) -> bool:
    """
    Realiza o handshake de criptografia com o servidor.
    Retorna True se bem-sucedido.
    """
    # Gera nonce do cliente
    client_nonce = crypto.generate_nonce()

    # Envia pedido de handshake com o nonce
    nonce_req = (
        struct.pack(HEADER_FMT, TYPE_NONCE_REQ, 0, 0, len(client_nonce)) + client_nonce
    )
    sock.sendto(nonce_req, server)

    # Aguarda resposta do servidor (com timeout maior para handshake)
    sock.settimeout(2.0)
    try:
        data, _ = sock.recvfrom(65535)
        parsed = parse_packet(data)
        if parsed:
            ptype, seq, ack, payload = parsed
            if ptype == TYPE_NONCE_RESP and len(payload) >= 16:
                server_nonce = payload[:16]
                # Deriva a chave de sessão
                crypto.derive_session_key(client_nonce, server_nonce)
                print("[client] crypto handshake successful")
                print(f"[client] client_nonce: {client_nonce.hex()[:16]}...")
                print(f"[client] server_nonce: {server_nonce.hex()[:16]}...")
                print(f"[client] session_key:  {crypto.session_key.hex()[:16]}...")
                save_log(CLIENT_LOG_DIR, "[client] crypto handshake successful")
                return True
    except socket.timeout:
        print("[client] crypto handshake timeout")
        save_log(CLIENT_LOG_DIR, "[client] crypto handshake timeout")
        return False

    return False


def run_client(server_host="127.0.0.1", server_port=9000, total_packets=10000):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    server = (server_host, server_port)

    # Instância de criptografia
    crypto = SimpleCrypto()

    # Realiza handshake de criptografia
    if not crypto_handshake(sock, server, crypto):
        print("[client] failed to establish crypto session")
        save_log(CLIENT_LOG_DIR, "[client] failed to establish crypto session")
        return

    sock.settimeout(
        0.05
    )  # Cliente não fica travado esperando um ACK. Se nada chegar em 0.05, ele continua executando a lógica de retransmissão e controle

    send_base = 0  # menor seq não-ACKada
    next_seq = 0  # próximo a enviar
    inflight = (
        {}
    )  # seq -> (packet_bytes, send_time) - Pacotes enviados, mas ainda não confirmados. guarda bytes para a retransmissão.

    cc = CongestionController()  # Controlador de congestionamento dinâmico

    start = time.time()

    def send_packet(seq: int):
        payload = (
            bytes([seq % 256]) * PAYLOAD_SIZE
        )  # Byte com valor entre 0 a 255 repetido 1000 vezes. Payload com 1000 bytes repetidos. (Só para teste)

        save_log(CLIENT_LOG_DIR, f"[client] sending packet seq={seq}")
        save_log(CLIENT_LOG_DIR, f"[payload] {payload.hex()[0:7]}", type="payload")

        # Cifra o payload
        encrypted_payload = crypto.encrypt(payload, seq)
        save_log(CLIENT_LOG_DIR, f"[client] encrypted payload seq={seq}")
        save_log(
            CLIENT_LOG_DIR,
            f"[encrypted payload] {encrypted_payload.hex()[0:7]}",
            type="payload",
        )

        pkt = make_data(seq, encrypted_payload)
        sock.sendto(pkt, server)
        inflight[seq] = (pkt, time.time())

    while send_base < total_packets:
        # Envia enquanto houver espaço na janela (usa cwnd dinâmico)
        while next_seq < total_packets and (next_seq - send_base) < int(cc.cwnd):
            send_packet(next_seq)
            next_seq += 1

        # Tenta receber ACK(s)
        try:
            data, _ = sock.recvfrom(65535)
            parsed = parse_packet(data)
            if parsed:
                ptype, seq, ack, payload = parsed
                if ptype == TYPE_ACK:
                    # ACK cumulativo: confirma tudo com seq < ack
                    if ack > send_base:
                        for s in list(inflight.keys()):
                            if s < ack:
                                inflight.pop(s, None)
                        send_base = ack
                        cc.ack_received(
                            ack
                        )  # Notifica o controlador sobre ACK recebido
        # Se não chegar ack, continua o processo
        except socket.timeout:
            pass

        # Timeout simples: se o send_base está pendente há muito tempo, retransmite send_base
        if send_base in inflight:
            pkt, t0 = inflight[send_base]
            if (time.time() - t0) > TIMEOUT:
                sock.sendto(pkt, server)
                inflight[send_base] = (pkt, time.time())
                cc.timeout_occurred()  # Notifica o controlador sobre timeout

        # A cada 1000 pacotes confirmados, calcula throughput médio em Mbps
        if send_base % 1000 == 0 and send_base > 0:
            elapsed = time.time() - start
            mbps = (send_base * PAYLOAD_SIZE * 8) / (elapsed * 1e6)
            print(
                f"[client] acked={send_base}/{total_packets} inflight={len(inflight)} cwnd={cc.cwnd:.2f} ~{mbps:.2f} Mbps"
            )
            save_log(
                CLIENT_LOG_DIR,
                f"acked={send_base}/{total_packets} inflight={len(inflight)} cwnd={cc.cwnd:.2f} ~{mbps:.2f} Mbps",
            )

    # tempo e throuhput total
    elapsed = time.time() - start
    mbps = (total_packets * PAYLOAD_SIZE * 8) / (elapsed * 1e6)
    print(f"[client] done! time={elapsed:.2f}s avg_throughput={mbps:.2f} Mbps")
    save_log(
        CLIENT_LOG_DIR,
        f"[client] done! time={elapsed:.2f}s avg_throughput={mbps:.2f} Mbps",
    )


if __name__ == "__main__":
    run_client(server_host="127.0.0.1", server_port=9000, total_packets=10000)

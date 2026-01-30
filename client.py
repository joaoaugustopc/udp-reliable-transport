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

HEADER_FMT = "!BIIHH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
PAYLOAD_SIZE = 1000
TIMEOUT = 0.2

CLIENT_LOG_DIR = "client_logs"


# Monta bytes do pacote (Header + Payload)
def make_data(seq: int, payload: bytes) -> bytes:
    return struct.pack(HEADER_FMT, TYPE_DATA, seq, 0, 0, len(payload)) + payload

def parse_packet(data: bytes):
    if len(data) < HEADER_SIZE:
        return None
    ptype, seq, ack, rwnd, length = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
    payload = data[HEADER_SIZE:HEADER_SIZE + length]
    return ptype, seq, ack, rwnd, payload


def crypto_handshake(sock, server, crypto: SimpleCrypto) -> bool:
    """
    Realiza o handshake de criptografia com o servidor.
    Retorna True se bem-sucedido.
    """
    # Gera nonce do cliente
    client_nonce = crypto.generate_nonce()

    # Envia pedido de handshake com o nonce
    nonce_req = (
        struct.pack(HEADER_FMT, TYPE_NONCE_REQ, 0, 0, 0, len(client_nonce)) + client_nonce
    )
    sock.sendto(nonce_req, server)

    # Aguarda resposta do servidor (com timeout maior para handshake)
    sock.settimeout(2.0)
    try:
        data, _ = sock.recvfrom(65535)
        parsed = parse_packet(data)
        if parsed:
            ptype, seq, ack, rwnd, payload = parsed
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

    sock.settimeout(0.05)  #Cliente não fica travado esperando um ACK. Se nada chegar em 0.05, ele continua executando a lógica de retransmissão e controle

    peer_rwnd = float("inf")

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

    # Estatísticas
    total_packets_sent = 0  # Total de pacotes enviados (incluindo retransmissões)
    total_retransmissions = 0  # Número de retransmissões
    duplicate_acks_count = 0  # Número de ACKs duplicados
    max_cwnd = 0.0  # Maior cwnd alcançado
    cwnd_history = []  # Histórico de cwnd para análise

    start = time.time()

    def send_packet(seq: int):
        nonlocal total_packets_sent

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
        total_packets_sent += 1

    while send_base < total_packets:
        # Envia enquanto houver espaço na janela (usa cwnd dinâmico)

        effective_window = min(int(cc.cwnd), peer_rwnd)

        # Envia enquanto houver espaço na janela
        while next_seq < total_packets and (next_seq - send_base) < effective_window:
            send_packet(next_seq)
            next_seq += 1

        # Tenta receber ACK(s)
        try:
            data, _ = sock.recvfrom(65535)
            parsed = parse_packet(data)
            if parsed:
                ptype, seq, ack, rwnd, payload = parsed
                if ptype == TYPE_ACK:

                    peer_rwnd = rwnd
                    
                    ## Apenas para teste
                    # old = peer_rwnd
                    # peer_rwnd = rwnd

                    # if peer_rwnd != old:
                    #     print(
                    #         f"[client] rwnd change at ack={ack} | "
                    #         f"{old} -> {peer_rwnd} "
                    #         f"(effective={min(WINDOW, peer_rwnd)})"
                    #     )

                    # ACK cumulativo: confirma tudo com seq < ack
                    if ack > send_base:
                        for s in list(inflight.keys()):
                            if s < ack:
                                inflight.pop(s, None)
                        send_base = ack
                        cc.ack_received(
                            ack
                        )  # Notifica o controlador sobre ACK recebido

                        # Atualiza cwnd máximo
                        if cc.cwnd > max_cwnd:
                            max_cwnd = cc.cwnd
                        cwnd_history.append(cc.cwnd)
                    elif ack == send_base:
                        # ACK duplicado
                        duplicate_acks_count += 1
                        cc.ack_received(ack)
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
                total_retransmissions += 1
                total_packets_sent += 1
                save_log(
                    CLIENT_LOG_DIR,
                    f"[client] RETRANSMISSION seq={send_base} (total={total_retransmissions})",
                )

        # A cada 1000 pacotes confirmados, calcula throughput médio em Mbps
        if send_base % 1000 == 0 and send_base > 0:
            elapsed = time.time() - start
            mbps = (send_base * PAYLOAD_SIZE * 8) / (elapsed * 1e6)
            retrans_rate = (
                (total_retransmissions / total_packets_sent * 100)
                if total_packets_sent > 0
                else 0
            )
            print(
                f"[client] acked={send_base}/{total_packets} inflight={len(inflight)} cwnd={cc.cwnd:.2f} "
                f"~{mbps:.2f} Mbps | sent={total_packets_sent} retrans={total_retransmissions} ({retrans_rate:.1f}%) "
                f"dup_acks={duplicate_acks_count}"
            )
            save_log(
                CLIENT_LOG_DIR,
                f"acked={send_base}/{total_packets} inflight={len(inflight)} cwnd={cc.cwnd:.2f} ~{mbps:.2f} Mbps | "
                f"sent={total_packets_sent} retrans={total_retransmissions} ({retrans_rate:.1f}%) dup_acks={duplicate_acks_count}",
            )

    # tempo e throuhput total
    elapsed = time.time() - start
    mbps = (total_packets * PAYLOAD_SIZE * 8) / (elapsed * 1e6)
    retrans_rate = (
        (total_retransmissions / total_packets_sent * 100)
        if total_packets_sent > 0
        else 0
    )
    avg_cwnd = sum(cwnd_history) / len(cwnd_history) if cwnd_history else 0

    print("\n" + "=" * 80)
    print("[CLIENT] RELATÓRIO FINAL")
    print("=" * 80)
    print(f"Tempo total: {elapsed:.2f}s")
    print(f"Throughput médio: {mbps:.2f} Mbps")
    print(f"Pacotes úteis enviados: {total_packets}")
    print(f"Total de transmissões (incluindo retrans.): {total_packets_sent}")
    print(f"Retransmissões: {total_retransmissions} ({retrans_rate:.2f}%)")
    print(f"ACKs duplicados: {duplicate_acks_count}")
    print(f"Cwnd máximo: {max_cwnd:.2f}")
    print(f"Cwnd médio: {avg_cwnd:.2f}")
    print(f"Estado final: {cc.state}")
    print("=" * 80 + "\n")

    save_log(CLIENT_LOG_DIR, "\n" + "=" * 80)
    save_log(CLIENT_LOG_DIR, "[CLIENT] RELATÓRIO FINAL")
    save_log(CLIENT_LOG_DIR, "=" * 80)
    save_log(CLIENT_LOG_DIR, f"Tempo total: {elapsed:.2f}s")
    save_log(CLIENT_LOG_DIR, f"Throughput médio: {mbps:.2f} Mbps")
    save_log(CLIENT_LOG_DIR, f"Pacotes úteis enviados: {total_packets}")
    save_log(
        CLIENT_LOG_DIR,
        f"Total de transmissões (incluindo retrans.): {total_packets_sent}",
    )
    save_log(
        CLIENT_LOG_DIR, f"Retransmissões: {total_retransmissions} ({retrans_rate:.2f}%)"
    )
    save_log(CLIENT_LOG_DIR, f"ACKs duplicados: {duplicate_acks_count}")
    save_log(CLIENT_LOG_DIR, f"Cwnd máximo: {max_cwnd:.2f}")
    save_log(CLIENT_LOG_DIR, f"Cwnd médio: {avg_cwnd:.2f}")
    save_log(CLIENT_LOG_DIR, f"Estado final: {cc.state}")
    save_log(CLIENT_LOG_DIR, "=" * 80)


if __name__ == "__main__":
    run_client(server_host="127.0.0.1", server_port=9000, total_packets=10000)

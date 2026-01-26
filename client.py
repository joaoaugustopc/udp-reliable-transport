import socket
import struct
import time
from congestion import CongestionController


TYPE_DATA = 0  # Igual no server.py
TYPE_ACK = 1  # Igual no server.py

HEADER_FMT = "!BIIH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

PAYLOAD_SIZE = 1000
TIMEOUT = 0.2


# Monta bytes do pacote (Header + Payload)
def make_data(seq: int, payload: bytes) -> bytes:
    return struct.pack(HEADER_FMT, TYPE_DATA, seq, 0, len(payload)) + payload


def parse_packet(data: bytes):
    if len(data) < HEADER_SIZE:
        return None
    ptype, seq, ack, length = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
    payload = data[HEADER_SIZE : HEADER_SIZE + length]
    return ptype, seq, ack, payload


def run_client(server_host="127.0.0.1", server_port=9000, total_packets=10000):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    sock.settimeout(
        0.05
    )  # Cliente não fica travado esperando um ACK. Se nada chegar em 0.05, ele continua executando a lógica de retransmissão e controle

    server = (server_host, server_port)

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
        pkt = make_data(seq, payload)
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

    # tempo e throuhput total
    elapsed = time.time() - start
    mbps = (total_packets * PAYLOAD_SIZE * 8) / (elapsed * 1e6)
    print(f"[client] done! time={elapsed:.2f}s avg_throughput={mbps:.2f} Mbps")


if __name__ == "__main__":
    run_client(server_host="127.0.0.1", server_port=9000, total_packets=10000)

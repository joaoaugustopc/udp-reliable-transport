import socket
import struct
import random
import time
from crypto import SimpleCrypto
from logs import save_log

TYPE_DATA = 0
TYPE_ACK = 1
TYPE_NONCE_REQ = 2  # Cliente solicita início do handshake
TYPE_NONCE_RESP = 3  # Servidor responde com seu nonce

HEADER_FMT = "!BIIH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

#Define o formato do header
HEADER_FMT = "!BIIHH"  # type(1), seq(4), ack(4), rwnd(2) lenght(2)
HEADER_SIZE = struct.calcsize(HEADER_FMT) # Calcula quantos bytes o header tem no total

RECV_BUFFER_PKTS = 5


#Empacota os valores e transforma em uma sequência de bytes
def make_ack(expected_seq: int, rwnd:int) -> bytes:
    return struct.pack(HEADER_FMT, TYPE_ACK, 0, expected_seq, rwnd, 0)


def parse_packet(data: bytes):
    if len(data) < HEADER_SIZE:
        return None
    
    ptype, seq, ack, rwnd, length = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])

    payload = data[HEADER_SIZE:HEADER_SIZE+length]

    return ptype, seq, ack, rwnd, payload


def run_server(host="0.0.0.0", port=9000):

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # IPv4, UDP
    sock.bind((host, port))

    last_rwnd = None

    print(f"[server] listening on {host}:{port}")
    save_log(SERVER_LOG_DIR, f"Server started on {host}:{port}")

    expected_seq = 0

    buffer = (
        {}
    )  # seq: payload (Serve oara armazenar as sequncias que chegaram fora de ordem)

    client_addr = None
    delivered = 0
    crypto = SimpleCrypto()  # Instância de criptografia

    while True:
        data, addr = sock.recvfrom(65535) #Tamanho máximo de um pacote é 65.535 bytes. Pois o campo "total lenght" bo cabeçalho IPv4 tem 16bits. 
        
        # SIMULAÇÂO servidor lento (processamento demorado)
        # time.sleep(0.005)

        client_addr = addr

        parsed = parse_packet(data)
        if not parsed:
            continue

        ptype, seq, ack, rwnd, payload = parsed 

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


        adv_rwnd = max (RECV_BUFFER_PKTS - len(buffer), 0)

        if adv_rwnd != last_rwnd:
            print(
                f"[server] rwnd change at expected_seq={expected_seq} | "
                f"buffer={len(buffer)} rwnd={adv_rwnd}"
            )
            last_rwnd = adv_rwnd

        # ACK cumulativo: sempre diz "próximo que eu quero"
        ack_pkt = make_ack(expected_seq, adv_rwnd)
        sock.sendto(ack_pkt, client_addr)

        if delivered % 1000 == 0 and delivered > 0:
            print(
                f"[server] delivered={delivered} expected_seq={expected_seq} buffered={len(buffer)}"
            )
            save_log(
                SERVER_LOG_DIR,
                f"delivered={delivered} expected_seq={expected_seq} buffered={len(buffer)}",
            )


if __name__ == "__main__":
    run_server()

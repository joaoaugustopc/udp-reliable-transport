import socket
import struct
import random

TYPE_DATA = 0
TYPE_ACK = 1

#Define o formato do header
HEADER_FMT = "!BIIH"  # type(1), seq(4), ack(4), lenght(2)
HEADER_SIZE = struct.calcsize(HEADER_FMT) # Calcula quantos bytes o header tem no total = 11


#Empacota os valores e transforma em uma sequência de bytes
def make_ack(expected_seq: int) -> bytes:
    return struct.pack(HEADER_FMT, TYPE_ACK, 0, expected_seq, 0)

def parse_packet(data: bytes):
    if len(data) < HEADER_SIZE:
        return None
    
    ptype, seq, ack, length = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])

    payload = data[HEADER_SIZE:HEADER_SIZE+length]

    return ptype, seq, ack, payload

def run_server(host="0.0.0.0", port=9000):

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #IPv4, UDP
    sock.bind((host, port))

    print(f"[server] listening on {host}:{port}")

    expected_seq = 0

    buffer = {}  # seq: payload (Serve oara armazenar as sequncias que chegaram fora de ordem)

    client_addr = None
    delivered = 0  

    while True:
        data, addr = sock.recvfrom(65535) #Tamanho máximo de um pacote é 65.535 bytes. Pois o campo "total lenght" bo cabeçalho IPv4 tem 16bits. 
        
        client_addr = addr

        parsed = parse_packet(data)
        if not parsed:
            continue

        ptype, seq, ack, payload = parsed

        if ptype != TYPE_DATA:
            continue

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
            print(f"[server] delivered={delivered} expected_seq={expected_seq} buffered={len(buffer)}")



if __name__ == "__main__":
    run_server()

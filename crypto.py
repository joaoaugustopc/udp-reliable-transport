import hashlib
import secrets
import struct


class SimpleCrypto:
    """
    Criptografia simples para transporte confiável UDP.
    Usa troca de nonces para derivar chave de sessão e XOR para cifrar dados.
    """

    def __init__(self):
        self.session_key = None
        self.my_nonce = None
        self.peer_nonce = None

    def generate_nonce(self) -> bytes:
        """Gera um nonce aleatório de 16 bytes."""
        self.my_nonce = secrets.token_bytes(16)
        return self.my_nonce

    def derive_session_key(self, my_nonce: bytes, peer_nonce: bytes):
        """
        Deriva uma chave de sessão a partir dos nonces do cliente e servidor.
        Usa SHA-256 para combinar os nonces.
        """
        self.my_nonce = my_nonce
        self.peer_nonce = peer_nonce

        # Concatena os nonces e deriva a chave usando SHA-256
        combined = my_nonce + peer_nonce
        self.session_key = hashlib.sha256(combined).digest()

    def _generate_keystream(self, length: int, counter: int) -> bytes:
        """
        Gera um fluxo de chave usando a session_key e um contador.
        O contador garante que pacotes diferentes tenham fluxos diferentes.
        """
        if not self.session_key:
            raise ValueError("Session key not established")

        keystream = b""
        blocks_needed = (length + 31) // 32  # SHA-256 produz 32 bytes

        for i in range(blocks_needed):
            # Combina session_key + counter + block_index
            data = self.session_key + struct.pack("!QI", counter, i)
            keystream += hashlib.sha256(data).digest()

        return keystream[:length]

    def encrypt(self, plaintext: bytes, seq: int) -> bytes:
        """
        Cifra o payload usando XOR com keystream.
        seq é usado como contador para garantir keystreams únicos.
        """
        if not self.session_key:
            raise ValueError("Session key not established")

        keystream = self._generate_keystream(len(plaintext), seq)
        ciphertext = bytes(p ^ k for p, k in zip(plaintext, keystream))

        # Adiciona hash truncado (8 bytes) para verificação de integridade
        integrity_hash = hashlib.sha256(ciphertext + struct.pack("!Q", seq)).digest()[
            :8
        ]

        return ciphertext + integrity_hash

    def decrypt(self, ciphertext_with_hash: bytes, seq: int) -> bytes:
        """
        Decifra o payload e verifica integridade.
        Retorna None se a verificação de integridade falhar.
        """
        if not self.session_key:
            raise ValueError("Session key not established")

        if len(ciphertext_with_hash) < 8:
            return None

        # Separa ciphertext e hash
        ciphertext = ciphertext_with_hash[:-8]
        received_hash = ciphertext_with_hash[-8:]

        # Verifica integridade
        expected_hash = hashlib.sha256(ciphertext + struct.pack("!Q", seq)).digest()[:8]
        if received_hash != expected_hash:
            return None  # Falha na verificação de integridade

        # Decifra (XOR é simétrico)
        keystream = self._generate_keystream(len(ciphertext), seq)
        plaintext = bytes(c ^ k for c, k in zip(ciphertext, keystream))

        return plaintext

    def is_established(self) -> bool:
        """Verifica se a chave de sessão foi estabelecida."""
        return self.session_key is not None

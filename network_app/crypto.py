import os
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization


def identity():
    key = X25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, public.hex()


def derive(private, public):
    shared = private.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(public)))
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b'network-app-v1').derive(shared)

import hashlib
import json
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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


def seal_password(key, challenge, username, port, password):
    cipher = AESGCM(hashlib.sha256(key + b'login-password-v2').digest())
    context = json.dumps([username, port], separators=(',', ':')).encode()
    return cipher.encrypt(bytes.fromhex(challenge), password.encode(), context).hex()


def open_password(key, challenge, username, port, ciphertext):
    cipher = AESGCM(hashlib.sha256(key + b'login-password-v2').digest())
    context = json.dumps([username, port], separators=(',', ':')).encode()
    try:
        return cipher.decrypt(bytes.fromhex(challenge), bytes.fromhex(ciphertext),
                              context).decode()
    except (InvalidTag, ValueError, TypeError) as error:
        raise ValueError('Invalid encrypted login') from error

import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
key=ec.generate_private_key(ec.SECP256R1())
private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
pub=key.public_key().public_numbers()
public=base64.urlsafe_b64encode(b"\x04"+pub.x.to_bytes(32,"big")+pub.y.to_bytes(32,"big")).rstrip(b"=").decode()
print("VAPID_PRIVATE_KEY (usa il valore PEM completo):\n"+private)
print("VAPID_PUBLIC_KEY:\n"+public)

from cryptography.fernet import Fernet
from typing import Optional
from backend.config.settings import settings

_fernet = Fernet(settings.ENCRYPTION_KEY.encode('utf-8'))

def encrypt_pii(text: Optional[str]) -> Optional[str]:
    """Encrypt a plaintext PII string. Returns None if input is None."""
    if not text:
        return text
    return _fernet.encrypt(text.encode('utf-8')).decode('utf-8')

def decrypt_pii(encrypted_text: Optional[str]) -> Optional[str]:
    """Decrypt an encrypted PII string. Returns None if input is None."""
    if not encrypted_text:
        return encrypted_text
    try:
        return _fernet.decrypt(encrypted_text.encode('utf-8')).decode('utf-8')
    except Exception:
        # If decryption fails (e.g. key rotation, or wasn't encrypted), fallback gracefully
        return encrypted_text

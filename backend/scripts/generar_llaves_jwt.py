"""
Genera el par de llaves RSA (RS256) para JWT.

Uso:
    python scripts/generar_llaves_jwt.py [directorio_de_salida]

El directorio por defecto es backend/secrets (relativo a este archivo).
No sobrescribe llaves existentes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_keys(output_dir: Path) -> tuple[Path, Path]:
    """Genera jwt_private.pem y jwt_public.pem en output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    private_path = output_dir / "jwt_private.pem"
    public_path = output_dir / "jwt_public.pem"

    if private_path.exists() and public_path.exists():
        print(f"Ya existen las llaves en {output_dir}. No se sobrescriben.")
        return private_path, public_path

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path.write_bytes(private_bytes)
    public_path.write_bytes(public_bytes)
    return private_path, public_path


def main() -> None:
    default_dir = Path(__file__).resolve().parents[1] / "secrets"
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default_dir
    priv, pub = generate_keys(target)
    print("Llaves JWT generadas:")
    print(f"  - {priv}")
    print(f"  - {pub}")
    print("IMPORTANTE: no commitear estas llaves (ver .gitignore).")


if __name__ == "__main__":
    main()

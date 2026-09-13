"""run_https.py -- local HTTPS launcher, no third-party tunnel.

Ported from the CIMS project's backend/run_https.py: browsers refuse
getUserMedia on a plain-HTTP LAN origin, so this generates a self-signed
certificate covering both localhost and your LAN IP, and serves the same
FastAPI app (backend.main:app) over HTTPS on port 8443 -- nothing leaves
your network, no external service involved.

Run it instead of `uvicorn backend.main:app`:

    python run_https.py

Then open, on any device on the same WiFi:

    https://<LAN_IP>:8443

Your phone will show a certificate warning on first load (the cert is
self-signed, not from a public CA) -- tap "Advanced" -> "Proceed anyway" (or
equivalent). That's expected and is what makes the page load as HTTPS, which
is what the camera needs; the cert is generated on this machine and never
leaves it.
"""
import argparse
import datetime as dt
import ipaddress
import socket
from pathlib import Path

# Configure storage BEFORE importing anything else (models go to D: drive)
from backend.storage_config import configure_insightface, get_storage_dir
configure_insightface()
print(f"[https] Using D: drive for model storage: {get_storage_dir()}")

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _detect_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return "127.0.0.1"


def _ensure_cert(cert_dir: Path, lan_ip: str) -> tuple[Path, Path]:
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "dev_cert.pem"
    key_path = cert_dir / "dev_key.pem"
    if cert_path.is_file() and key_path.is_file():
        return cert_path, key_path

    print(f"[https] generating self-signed cert at {cert_path}")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Gesture Hold & Transfer Dev"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Local Dev"),
    ])

    san_entries: list = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        x509.IPAddress(ipaddress.IPv6Address("::1")),
    ]
    try:
        san_entries.append(x509.IPAddress(ipaddress.IPv4Address(lan_ip)))
    except Exception:
        pass

    now = dt.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365 * 5))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Local HTTPS server (no tunnel)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument(
        "--cert-dir",
        default=str(Path(__file__).resolve().parent / ".certs"),
        help="Where to keep the self-signed cert (default: ./.certs/)",
    )
    args = parser.parse_args()

    lan_ip = _detect_lan_ip()
    cert_path, key_path = _ensure_cert(Path(args.cert_dir), lan_ip)

    print()
    print("=" * 68)
    print(f"  On this PC:        https://localhost:{args.port}")
    print(f"  On your phone:     https://{lan_ip}:{args.port}")
    print(f"  (accept the self-signed certificate warning on first load)")
    print("=" * 68)
    print()

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

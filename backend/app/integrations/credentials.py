"""Sandbox credential stays outside the repository; Windows storage uses DPAPI."""
import getpass
import os
from pathlib import Path


def secret_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "ThesisGuard" / "sandbox-token.dpapi"


def save_token(token: str) -> None:
    import win32crypt

    token = token.strip().replace("\\_", "_")
    if not token or any(c.isspace() for c in token):
        raise ValueError("Некорректный токен")
    path = secret_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(win32crypt.CryptProtectData(token.encode(), "ThesisGuard sandbox", None, None, None, 0))


def load_token() -> str:
    value = os.getenv("TINVEST_SANDBOX_TOKEN")
    if value:
        return value.strip()
    if os.name == "nt" and secret_path().exists():
        import win32crypt

        return win32crypt.CryptUnprotectData(secret_path().read_bytes(), None, None, None, 0)[1].decode()
    raise ValueError("Токен песочницы не настроен")


def token_configured() -> bool:
    return bool(os.getenv("TINVEST_SANDBOX_TOKEN")) or (os.name == "nt" and secret_path().exists())


if __name__ == "__main__":
    save_token(getpass.getpass("Sandbox token (hidden): "))
    print("Sandbox token saved outside the repository using Windows DPAPI.")

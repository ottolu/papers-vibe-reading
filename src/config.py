"""Configuration management via environment variables."""

import os
from dotenv import load_dotenv
import httpx

# Load .env file if present (for local development)
load_dotenv()


# --- AI Configuration (Gemini) ---
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3-pro-preview")

# --- Paper Configuration ---
PAPERS_TOP_N: int = int(os.getenv("PAPERS_TOP_N", "5"))

# --- Email / SMTP Configuration ---
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
EMAIL_TO: str = os.getenv("EMAIL_TO", "")

# --- Network / Proxy ---
# Set HTTP_PROXY / HTTPS_PROXY if you need to go through a proxy
# e.g. "http://127.0.0.1:7890"  (Clash default)
HTTP_PROXY: str = os.getenv("HTTP_PROXY", "")
HTTPS_PROXY: str = os.getenv("HTTPS_PROXY", "")

# --- Output ---
LANGUAGE: str = os.getenv("LANGUAGE", "zh")
OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "output")


def get_httpx_proxy() -> httpx.Proxy | None:
    """Return an httpx Proxy object if a proxy is configured, else None."""
    proxy_url = HTTPS_PROXY or HTTP_PROXY
    if proxy_url:
        return httpx.Proxy(proxy_url)
    return None


def get_proxy_url() -> str | None:
    """Return the proxy URL string if configured, else None."""
    return (HTTPS_PROXY or HTTP_PROXY) or None

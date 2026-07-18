"""Query latest stable versions from PyPI JSON API for all relevant packages."""
import json
import urllib.request
import urllib.error

# (import name, pip package name)
PACKAGES = [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("aiohttp", "aiohttp"),
    ("websockets", "websockets"),
    ("psutil", "psutil"),
    ("loguru", "loguru"),
    ("yaml", "pyyaml"),
    ("dotenv", "python-dotenv"),
    ("apscheduler", "apscheduler"),
    ("openai", "openai"),
    ("markitdown", "markitdown"),
    ("requests", "requests"),
    ("httpx", "httpx"),
    ("pywin32", "pywin32"),
    ("pyautogui", "pyautogui"),
    ("pytest", "pytest"),
    ("pytest-asyncio", "pytest-asyncio"),
    ("PIL", "Pillow"),
    ("chromadb", "chromadb"),
    ("docx", "python-docx"),
    ("easyocr", "easyocr"),
    ("edge_tts", "edge-tts"),
    ("feedparser", "feedparser"),
    ("markdown", "markdown"),
    ("pytesseract", "pytesseract"),
    ("pywinauto", "pywinauto"),
    ("weasyprint", "weasyprint"),
    ("whisper", "openai-whisper"),
]

PYPI_URL = "https://pypi.org/pypi/{pkg}/json"


def query(pkg):
    try:
        req = urllib.request.Request(PYPI_URL.format(pkg=pkg), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        info = data.get("info", {})
        version = info.get("version", "?")
        is_prerelease = any(c in version for c in ("a", "b", "rc", "dev"))
        requires_python = info.get("requires_python", "")
        return version, is_prerelease, requires_python
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}", False, ""
    except Exception as e:
        return f"ERR {type(e).__name__}", False, ""


def main():
    print(f"{'import':<18} {'pip name':<22} {'latest':<14} {'pre?':<5} requires_python")
    print("-" * 80)
    for imp, pip in PACKAGES:
        v, pre, rp = query(pip)
        print(f"{imp:<18} {pip:<22} {v:<14} {'Y' if pre else 'N':<5} {rp}")


if __name__ == "__main__":
    main()

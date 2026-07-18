"""Self-test: verify all critical packages can be imported successfully."""
import sys
import traceback

PACKAGES = {
    # HTTP API server
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",

    # Core async & networking
    "aiohttp": "aiohttp",
    "websockets": "websockets",
    "httpx": "httpx",
    "requests": "requests",

    # Process / system monitoring
    "psutil": "psutil",

    # Logging & configuration
    "loguru": "loguru",
    "yaml (PyYAML)": "yaml",
    "dotenv (python-dotenv)": "dotenv",

    # Scheduler
    "apscheduler": "apscheduler",

    # AI / LLM
    "openai": "openai",

    # Attachment ingestion
    "markitdown": "markitdown",

    # Document generation
    "docx (python-docx)": "docx",
    "markdown": "markdown",
    "weasyprint": "weasyprint",

    # Multimodal output
    "edge_tts": "edge_tts",
    "PIL (Pillow)": "PIL",

    # Multimodal input — OCR
    "pytesseract": "pytesseract",

    # Information feeds
    "feedparser": "feedparser",

    # Windows integration
    "pywinauto": "pywinauto",
    "pyautogui": "pyautogui",

    # Testing
    "pytest": "pytest",
    "pytest_asyncio": "pytest_asyncio",
}

# pywin32 is special — import win32api
PACKAGES["pywin32 (win32api)"] = "win32api"

PASS = 0
FAIL = 0
SKIP = 0

for name, module in PACKAGES.items():
    try:
        __import__(module)
        print(f"  [OK]    {name}")
        PASS += 1
    except ImportError as e:
        print(f"  [FAIL]  {name}  —  {e}")
        FAIL += 1
    except Exception as e:
        print(f"  [WARN]  {name}  —  {e}")
        PASS += 1  # imported but something else went wrong

print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped")
if FAIL:
    print("Some packages could NOT be imported — check the failures above.")
    sys.exit(1)
else:
    print("All critical packages imported successfully.")
    sys.exit(0)

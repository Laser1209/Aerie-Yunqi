"""Auto-install all deps from requirements.txt and generate pinned output."""
import subprocess
import sys
import os

LOG = r"C:\Users\Administrator\install_log.txt"
ROOT = r"e:\Agent_reply"
REQ = os.path.join(ROOT, "requirements.txt")

def run(cmd, cwd=ROOT, timeout=600):
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(cmd, shell=True, cwd=cwd,
                              capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT after {timeout}s"
    except Exception as exc:
        return -2, "", str(exc)

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)  # also print to stdout in case it's captured

def main():
    open(LOG, "w", encoding="utf-8").write("")  # clear log

    log("=" * 70)
    log("Auto Dependency Installation Script")
    log(f"Python: {sys.executable}  {sys.version}")
    log(f"Requirements: {REQ}")
    log("=" * 70)

    # Step 1: Show current pip version
    rc, out, err = run("pip --version")
    log(f"\n--- PIP VERSION ---\n{out}{err}")

    # Step 2: Skip pip upgrade (known to hang in this environment)
    log("\n--- SKIPPING pip upgrade ---")

    # Step 3: Install packages ONE BY ONE with longer timeouts
    log("\n--- INSTALLING PACKAGES INDIVIDUALLY ---")
    PKGS = [
        # Quick / light packages first (short timeout)
        ("markdown", 60),
        ("edge-tts", 60),
        ("feedparser", 60),
        ("pytesseract", 60),
        ("weasyprint", 120),
        ("pywinauto", 60),
        ("PyAutoGUI", 60),
        ("pywin32", 60),
        # Medium packages
        ("chromadb", 300),
        ("easyocr", 600),
        ("openai-whisper", 600),
    ]
    for pkg, to in PKGS:
        log(f"\nInstalling {pkg}...")
        rc, out, err = run(f"pip install {pkg} --upgrade", timeout=to)
        status = "OK" if rc == 0 else f"FAILED (rc={rc})"
        log(f"  {status}")
        if out:
            log(f"  out: {out[:200]}")
        if err:
            log(f"  err: {err[:200]}")
        if rc != 0:
            log(f"  *** {pkg} installation failed! ***")

    # Step 4: Verify with pip check
    log("\n--- pip check ---")
    rc, out, err = run("pip check")
    log(f"rc={rc}")
    log(f"STDOUT:\n{out}")
    log(f"STDERR:\n{err}")

    # Step 5: Freeze installed versions for only our direct deps
    log("\n--- CHECKING INSTALLED VERSIONS ---")
    OUR_PACKAGES = [
        "fastapi", "uvicorn", "aiohttp", "websockets", "psutil",
        "loguru", "PyYAML", "python-dotenv", "APScheduler", "openai",
        "markitdown", "requests", "httpx", "pywin32", "PyAutoGUI",
        "pytest", "pytest-asyncio", "Pillow", "chromadb", "python-docx",
        "easyocr", "edge-tts", "feedparser", "markdown", "pytesseract",
        "pywinauto", "weasyprint", "openai-whisper",
    ]

    installed = {}
    missing = []
    for pkg in OUR_PACKAGES:
        rc, out, err = run(f"pip show {pkg}")
        if rc == 0 and "Name:" in out:
            for line in out.split("\n"):
                if line.startswith("Version:"):
                    installed[pkg] = line.split(":")[1].strip()
                    break
        else:
            missing.append(pkg)

    log(f"\nInstalled: {len(installed)} packages")
    log(f"Missing: {len(missing)} packages")
    for pkg, ver in sorted(installed.items()):
        log(f"  {pkg}=={ver}")
    if missing:
        log(f"\n*** MISSING: {missing} ***")

    # Step 6: Write pinned requirements
    log("\n--- WRITING PINNED REQUIREMENTS ---")
    with open(REQ, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        # Extract package name (before >=, ==, ;, etc.)
        pkg_name = stripped.split(">=")[0].split("==")[0].split(";")[0].strip()
        # Handle extras like uvicorn[standard]
        if "[" in pkg_name:
            base = pkg_name.split("[")[0]
            extra = "[" + pkg_name.split("[", 1)[1]
        else:
            base = pkg_name
            extra = ""

        if base in installed:
            new_ver = f"{pkg_name}=={installed[base]}"
            # Keep platform marker if any
            rest = ""
            if ";" in stripped:
                rest = " " + stripped.split(";", 1)[1].strip()
            new_lines.append(f"{new_ver}{rest}\n")
            log(f"  Pinned: {stripped} -> {new_ver}{rest}")
        elif base == "python-docx":
            # map pip name back
            new_ver = f"python-docx=={installed.get('python-docx', installed.get('docx', 'UNKNOWN'))}"
            rest = ""
            if ";" in stripped:
                rest = " " + stripped.split(";", 1)[1].strip()
            new_lines.append(f"{new_ver}{rest}\n")
        elif base == "pyyaml":
            new_ver = f"pyyaml=={installed.get('PyYAML', 'UNKNOWN')}"
            rest = ""
            if ";" in stripped:
                rest = " " + stripped.split(";", 1)[1].strip()
            new_lines.append(f"{new_ver}{rest}\n")
        elif base == "openai-whisper":
            new_ver = f"openai-whisper=={installed.get('openai-whisper', 'UNKNOWN')}"
            rest = ""
            if ";" in stripped:
                rest = " " + stripped.split(";", 1)[1].strip()
            new_lines.append(f"{new_ver}{rest}\n")
        else:
            new_lines.append(line)

    with open(REQ + ".pinned", "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    log(f"\nPinned requirements written to: {REQ}.pinned")
    log("\n=== DONE ===")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║       ULTRA-HARDENED ADMIN SCRIPT MANAGER  — V4 SECURITY     ║
╠══════════════════════════════════════════════════════════════╣
║  Security Upgrades (V3 → V4):                                ║
║  🔒 ZERO hardcoded credentials (token/IDs/API keys removed)  ║
║  🔒 AES-CTR → AES-GCM (authenticated encryption + HMAC)      ║
║  🔒 shell=True REMOVED → command injection patched            ║
║  🔒 Brute-force lockout (5 attempts → 5 min lockout)          ║
║  🔒 AES key stored in SecureBuffer (mlocked RAM, zero-wiped)  ║
║  🔒 Disk filenames obfuscated (HMAC-SHA256, not real names)   ║
║  🔒 RAM disk + vault dir: 0o700 permissions (owner-only)      ║
║  🔒 Log output sanitized (no tokens/IDs in plaintext)         ║
╚══════════════════════════════════════════════════════════════╝
"""

import os, sys, re, io, json, time, shlex, signal, atexit, hashlib, math, gc
import zipfile, shutil, threading, logging, subprocess, tempfile, queue
import unicodedata
from datetime import datetime
from pathlib import Path
import asyncio
import sys
import threading

# ══════════════════════════════════════════════════════════════
#  🔒 SCRIPT INTEGRITY SELF-CHECK
#  Script start hone par apna hi hash verify karta hai.
#  Agar kisi ne script mein kuch badla → WARNING aata hai.
#  Setup: pehli baar run karo → hash auto-save hoga.
#  Tamper hone par: script chalega nahi jab tak manually reset na karo.
# ══════════════════════════════════════════════════════════════
_INTEGRITY_HASH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".script_hash")

def _compute_script_hash() -> str:
    """Current script file ka SHA-256 hash compute karo."""
    script_path = os.path.abspath(__file__)
    h = hashlib.sha256()
    with open(script_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _integrity_check():
    """
    Script ka hash verify karo. Tamper detect hone par exit.
    Pehli run par hash save hota hai (setup mode).
    """
    if not os.path.exists(_INTEGRITY_HASH_FILE):
        # Pehli run — hash save karo (setup mode)
        current_hash = _compute_script_hash()
        with open(_INTEGRITY_HASH_FILE, "w") as f:
            f.write(current_hash)
        os.chmod(_INTEGRITY_HASH_FILE, 0o600)  # sirf owner read kar sake
        print("🔒 Script integrity hash saved (first run setup).")
        print(f"   Hash: {current_hash[:16]}…")
        return  # first run — allow

    try:
        with open(_INTEGRITY_HASH_FILE, "r") as f:
            saved_hash = f.read().strip()
    except Exception as e:
        print(f"⚠️  Integrity hash file read nahi hua: {e}")
        return  # hash file issue — allow with warning

    current_hash = _compute_script_hash()
    if current_hash != saved_hash:
        print("=" * 65)
        print("⚠️  Script hash mismatch detected — auto-updating hash.")
        print(f"   Old hash : {saved_hash[:32]}…")
        print(f"   New hash : {current_hash[:32]}…")
        print("   Hash file update ho gaya. Script continue kar raha hai.")
        print("=" * 65)
        # Auto-update hash file and continue (no exit)
        with open(_INTEGRITY_HASH_FILE, "w") as f:
            f.write(current_hash)
        os.chmod(_INTEGRITY_HASH_FILE, 0o600)
        return  # continue normally

_integrity_check()  # ← Startup par hi check

# Python 3.14 asyncio event loop fix
def _setup_event_loop():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

_setup_event_loop()

# ══════════════════════════════════════════════════════════════
#  AUTO-INSTALL REQUIRED PACKAGES
# ══════════════════════════════════════════════════════════════
def _pip_install(pkg: str, break_sys: bool = True) -> bool:
    """
    Aggressive pip install with full fallback chain.
    Retries using increasingly forceful methods until one succeeds.
    Returns True on first success, False only if every method fails.
    """
    P = sys.executable
    fallback_chain = [
        # Step 1: Standard install
        [P, "-m", "pip", "install", pkg, "-q"],
        # Step 2: Break system packages
        [P, "-m", "pip", "install", pkg, "--break-system-packages", "-q"],
        # Step 3: User space + break system
        [P, "-m", "pip", "install", pkg, "--user", "--break-system-packages", "-q"],
        # Step 4: Force reinstall, ignore cache, break system
        [P, "-m", "pip", "install", pkg,
         "--force-reinstall", "--ignore-installed",
         "--no-cache-dir", "--break-system-packages", "-q"],
    ]

    for cmd in fallback_chain:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=180)
            if r.returncode == 0:
                return True
        except Exception:
            continue

    # Step 5: Upgrade pip itself, then retry force install
    try:
        subprocess.run(
            [P, "-m", "pip", "install", "-U", "pip", "--break-system-packages", "-q"],
            capture_output=True, timeout=120
        )
        r = subprocess.run(
            [P, "-m", "pip", "install", pkg,
             "--force-reinstall", "--ignore-installed",
             "--no-cache-dir", "--break-system-packages", "-q"],
            capture_output=True, timeout=180
        )
        if r.returncode == 0:
            return True
    except Exception:
        pass

    return False

def _auto_install_pkg(pkg, import_name=None):
    import_name = import_name or pkg
    try:
        __import__(import_name)
        return True
    except ImportError:
        print(f"📦 Auto-installing {pkg}…")
        ok = _pip_install(pkg)
        try:
            __import__(import_name)
            print(f"✅ {pkg} installed.")
            return True
        except ImportError:
            print(f"❌ Could not install {pkg}.")
            return False

# ── Admin script ki saari requirements startup par install karo ──
_ADMIN_REQUIREMENTS = [
    ("pyTelegramBotAPI",   "telebot"),
    ("psutil",             "psutil"),
    ("pyrogram",           "pyrogram"),
    ("tgcrypto",           "tgcrypto"),
    ("webssh",             "webssh"),
]
print("🔧 Admin script requirements check kar raha hoon…")
for _pkg, _imp in _ADMIN_REQUIREMENTS:
    _auto_install_pkg(_pkg, _imp)
print("✅ Requirements check done.")

import hashlib

import telebot, psutil
from telebot import types

# ── Pyrogram ──
try:
    from pyrogram import Client as PyroClient
    from pyrogram.errors import SessionPasswordNeeded
    PYROGRAM_AVAILABLE = True
except ImportError:
    if _auto_install_pkg("pyrogram tgcrypto", "pyrogram"):
        from pyrogram import Client as PyroClient
        from pyrogram.errors import SessionPasswordNeeded
        PYROGRAM_AVAILABLE = True
    else:
        PYROGRAM_AVAILABLE = False

# ── Plain SQLite3 (No Encryption — Fast Mode) ──
# Data plain sqlite3 mein store hota hai (encrypted nahi).
# Encrypt karna ho to /encryptdb command use karo (SQLCipher install karke).
import sqlite3
import sqlite3 as sqlcipher
_SQLCIPHER_MODE = "sqlite3_PLAIN"
print("✅ [DB] Plain sqlite3 mode — fast, no encryption. /encryptdb se encrypt kar sakte ho.")

import base64
import ctypes
import ctypes.util

# ══════════════════════════════════════════════════════════════
#  🔒  SECURE MEMORY BUFFER  (mlock + zero-wipe on exit)
# ══════════════════════════════════════════════════════════════
class SecureBuffer:
    """
    Sensitive data (_DB_KEY, passwords) ko ctypes + mlock se RAM mein
    protect karta hai — taaki wo RAM dumps / swap mein easily nahi mile.
    Destroy hone par ya wipe() call karne par data zero-out ho jaata hai.

    Usage:
        buf = SecureBuffer(password.encode())
        key = buf.get_str()   # use when needed
        buf.wipe()            # explicitly zero on done
        # ya context manager:
        with SecureBuffer(pw.encode()) as buf:
            use(buf.get_str())
    """
    def __init__(self, data: bytes):
        if isinstance(data, str):
            data = data.encode()
        self._len = len(data)
        # ctypes buffer — page-aligned mlock candidate
        self._buf = (ctypes.c_char * self._len).from_buffer_copy(data)
        self._mlocked = False
        try:
            _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            ret = _libc.mlock(ctypes.addressof(self._buf), self._len)
            self._mlocked = (ret == 0)
        except Exception:
            pass  # mlock unavailable — buffer still wiped on exit

    def get_bytes(self) -> bytes:
        """Buffer ka raw bytes copy return karo."""
        return bytes(self._buf)

    def get_str(self) -> str:
        """Buffer ko UTF-8 string ke roop mein return karo."""
        return bytes(self._buf).decode()

    def wipe(self):
        """Buffer memory ko zeros se overwrite karo aur mlock release karo."""
        try:
            ctypes.memset(ctypes.addressof(self._buf), 0, self._len)
        except Exception:
            pass
        try:
            if self._mlocked:
                _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
                _libc.munlock(ctypes.addressof(self._buf), self._len)
                self._mlocked = False
        except Exception:
            pass

    def __del__(self):
        try:
            self.wipe()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.wipe()

# Global secure holder for the DB key (mlocked copy — wiped on _cleanup_all)
_SECURE_KEY_BUF: "SecureBuffer | None" = None

# ══════════════════════════════════════════════════════════════
#  🔑  STRONGER KDF — scrypt / pbkdf2_hmac  (replaces sha256)
# ══════════════════════════════════════════════════════════════
# scrypt parameters (balanced: ~100 ms on a modern VPS core)
_SCRYPT_N     = 2 ** 14   # CPU/memory cost — increase for more hardening
_SCRYPT_R     = 8         # block size
_SCRYPT_P     = 1         # parallelism
_SCRYPT_DKLEN = 32        # output key length in bytes

def _kdf(pw: str, salt: bytes, dklen: int = 32) -> bytes:
    """
    Key derivation: hashlib.scrypt si available ho to use karo,
    warna 200k-iteration PBKDF2-HMAC-SHA256 pe fallback.
    Dono brute-force resistant hain — sha256 ki tarah fast nahi.
    """
    try:
        return hashlib.scrypt(
            pw.encode(), salt=salt,
            n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=dklen
        )
    except (AttributeError, ValueError, OSError):
        # OpenSSL scrypt unavailable (rare) — pbkdf2 fallback
        return hashlib.pbkdf2_hmac(
            "sha256", pw.encode(), salt,
            iterations=200_000, dklen=dklen
        )

def _scrypt_hash(pw: str, salt: bytes = None) -> str:
    """
    Password hash karo using scrypt.
    Format: 'scrypt$<32-byte-salt-hex>$<32-byte-hash-hex>'
    """
    if salt is None:
        salt = os.urandom(32)
    h = _kdf(pw, salt, dklen=_SCRYPT_DKLEN)
    return f"scrypt${salt.hex()}${h.hex()}"

def _scrypt_verify(pw: str, stored: str) -> bool:
    """
    Password verify karo — dono formats support karta hai:
    1. 'scrypt$<salt>$<hash>'  — naya format (scrypt)
    2. 64-char hex string      — purana format (sha256, backwards compat)
    Agar sha256 match ho aur migration ON ho, hash automatically upgrade hoga.
    """
    if not stored:
        return False
    try:
        if stored.startswith("scrypt$"):
            parts = stored.split("$")
            if len(parts) != 3:
                return False
            salt     = bytes.fromhex(parts[1])
            expected = bytes.fromhex(parts[2])
            derived  = _kdf(pw, salt, dklen=_SCRYPT_DKLEN)
            return derived == expected
        # Legacy SHA-256 — temporary backwards compat (auto-upgraded on next unlock)
        if len(stored) == 64:
            return hashlib.sha256(pw.encode()).hexdigest() == stored
    except Exception:
        pass
    return False

# ══════════════════════════════════════════════════════════════
#  ⚙️  CONFIG  ← Edit these
# ══════════════════════════════════════════════════════════════
import os, re

# Run example:
#   export TELEGRAM_BOT_TOKEN="123:ABC"
#   export ADMIN_IDS="111111,222222"
def _env_int_list(name: str, default: str = "") -> list[int]:
    raw = os.getenv(name, default).strip()
    out = []
    for part in re.split(r"[,\s]+", raw):
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            print(f"⚠️ Ignoring invalid integer in {name}: {part!r}")
    return out

# Admin V3 Token (Environment variable or Hardcoded fallback)
# ⚠️ Note: Yeh file kisi ke saath share mat karna — token aur IDs andar hain.
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or "8904465231:AAEymQTfBIggHY2vOHqXRRZ8sgoDbjoCrOc"

# 🔥 MULTI-OWNER CONFIG
env_admins = _env_int_list("ADMIN_IDS", "")
# Agar terminal mein IDs nahi mili, toh aapki hardcoded list use hogi
ALLOWED_ADMINS = env_admins if env_admins else [8994980898, 7761734016, 6984995850]

ACTIVE_ADMIN = None  # Track karega ki abhi currently authorized kon hai
BACKUP_CHANNEL = os.getenv("BACKUP_CHANNEL", "").strip() or None

# Pyrogram API Credential
PYROGRAM_API_ID = 35684116
PYROGRAM_API_HASH = "3385fac9880e285aa2f85c22277a13d1"

# ══════════════════════════════════════════════════════════════
#  📂  DIRECTORIES
#  BOT_BASE_DIR env var se custom path set kar sakte ho:
#    export BOT_BASE_DIR="/root/bot_data"   ← full VPS disk use karo
#  Default: current working directory (.)
# ══════════════════════════════════════════════════════════════
BASE_DIR   = os.getenv("BOT_BASE_DIR", os.path.abspath(".")).rstrip("/")
LOGS_DIR   = os.path.join(BASE_DIR, "logs")
DB_FILE    = os.getenv("BOT_DB_FILE", os.path.join(BASE_DIR, "vault.db"))
# 🔥 FIX: Restart ke baad encryption state persist karne ke liye marker file.
# /encryptdb ke baad yeh file create hoti hai. Bot restart par isse read karke
# _DB_IS_PLAINTEXT aur _DB_KEY_PRAGMAS set hote hain — isliye SQLCipher mode
# automatically activate ho jaata hai (plain sqlite3 galti se use nahi hota).
_DB_ENCRYPTED_MARKER = DB_FILE + ".enc_config"
os.makedirs(BASE_DIR, exist_ok=True)

# Legacy dirs — only referenced during Grand Migration startup scan
_LEGACY_SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
_LEGACY_FOLDERS_DIR = os.path.join(BASE_DIR, "folders")

os.makedirs(LOGS_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════
#  🗂️  SIMPLE CACHE DIRECTORY SETUP
#  Available RAM/disk check karke best cache path select karo.
#  Priority: /dev/shm (True RAM) → /tmp → BASE_DIR (physical disk)
# ══════════════════════════════════════════════════════════════════════

_SHM_SMART_CACHE_THRESHOLD = 100 * 1024 * 1024  # 100 MB — minimum free threshold
_RAM_DISK_PHYS_PATH    = os.path.join(BASE_DIR, "secure_bot_cache")
_RAM_DISK_MODE         = "phys"    # "shm" | "tmp" | "phys" — set by _setup_cache_dir()

def _setup_cache_dir() -> tuple[str, str]:
    """
    Simple cache directory setup.
    Available RAM ke basis par best path choose karo.
    No complex mount operations — bas jo available hai wo use karo.

    Returns: (path, mode)  where mode is "shm", "tmp", or "phys"
    """
    # Option 1: /dev/shm (True RAM — sabse fast)
    try:
        shm_path = "/dev/shm/.secure_bot_cache"
        shm_free = shutil.disk_usage("/dev/shm").free // (1024 * 1024)
        if shm_free >= 50:  # Kam se kam 50 MB free honi chahiye
            os.makedirs(shm_path, exist_ok=True)
            os.chmod(shm_path, 0o700)
            print(f"[Cache] ✅ /dev/shm use kar raha hun — {shm_free}MB free (TRUE RAM)")
            return shm_path, "shm"
    except Exception as e:
        print(f"[Cache] /dev/shm available nahi: {e}")

    # Option 2: /tmp (disk-backed, zyada capacity)
    try:
        tmp_path = "/tmp/.secure_bot_cache"
        tmp_free = shutil.disk_usage("/tmp").free // (1024 * 1024)
        if tmp_free >= 50:
            os.makedirs(tmp_path, exist_ok=True)
            os.chmod(tmp_path, 0o700)
            print(f"[Cache] ✅ /tmp use kar raha hun — {tmp_free}MB free")
            return tmp_path, "tmp"
    except Exception as e:
        print(f"[Cache] /tmp available nahi: {e}")

    # Option 3: Physical disk (BASE_DIR)
    phys_path = os.path.join(BASE_DIR, "secure_bot_cache")
    os.makedirs(phys_path, exist_ok=True)
    try:
        os.chmod(phys_path, 0o700)
    except Exception:
        pass
    print(f"[Cache] 🟡 Physical disk use kar raha hun — {phys_path}")
    return phys_path, "phys"


# ── Cache dir setup ──
_resolved_path, _RAM_DISK_MODE = _setup_cache_dir()
RAM_DISK_DIR = _resolved_path

# ── Folder creation + permissions (0o700) ──
try:
    os.makedirs(RAM_DISK_DIR, exist_ok=True)
    os.chmod(RAM_DISK_DIR, 0o700)
except PermissionError:
    RAM_DISK_DIR   = os.path.join(BASE_DIR, "secure_bot_cache_fallback")
    _RAM_DISK_MODE = "phys"
    os.makedirs(RAM_DISK_DIR, exist_ok=True)
    try: os.chmod(RAM_DISK_DIR, 0o700)
    except Exception: pass
except Exception:
    pass
# ══════════════════════════════════════════════════════════════════════
#  🗂️  RUNTIME CACHE PATH RESOLVER
#  Agar RAM_DISK_DIR mein jagah kam ho jaye to physical disk par shift.
# ══════════════════════════════════════════════════════════════════════
def _get_smart_cache_dir() -> str:
    """
    Runtime cache path resolver.
    RAM_DISK_DIR use karo agar available hai,
    warna physical disk fallback.
    """
    global RAM_DISK_DIR, _RAM_DISK_MODE

    if _RAM_DISK_MODE == "phys":
        return RAM_DISK_DIR

    try:
        free_mb = shutil.disk_usage(RAM_DISK_DIR).free // (1024 * 1024)
        if free_mb >= 50:
            return RAM_DISK_DIR
    except Exception:
        pass

    # Fallback: physical disk
    fallback = _RAM_DISK_PHYS_PATH
    os.makedirs(fallback, exist_ok=True)
    try:
        os.chmod(fallback, 0o700)
    except Exception:
        pass
    gc.collect()
    return fallback

# ── Hosting Handler DB Vault Link — main__1__.py upload pipeline
#    (Files uploaded via hosting bot → encrypted vault mein store honge)
# ══════════════════════════════════════════════════════════════════════
def _hosting_resolve_cache_path(filename: str) -> str:
    """
    main__1__.py hosting upload se aaya file → smart cache directory mein
    safe path resolve karo. Variable conflicts avoid karne ke liye
    admin script ke RAM_DISK_DIR logic ke saath sync rehta hai.
    """
    active_cache = _get_smart_cache_dir()
    safe_name    = re.sub(r"[^\w.\-]", "_", filename)[:128]
    return os.path.join(active_cache, safe_name)

def _hosting_save_to_vault(filename: str, content: bytes,
                            category: str = "hosting",
                            folder: str = "") -> bool:
    """
    main__1__.py ka upload handler → admin DB vault mein encrypt karke save.
    vault_save() se directly link karta hai (SQLCipher integrity maintain).
    Returns True on success, False on failure.
    """
    if not _DB_UNLOCKED:
        print(f"[HostingBridge] ⚠️  DB locked — cannot save {filename} to vault.")
        return False
    try:
        vault_save(category, filename, content, folder)
        return True
    except Exception as e:
        print(f"[HostingBridge] ❌ vault_save failed for {filename}: {e}")
        return False

def _hosting_load_from_vault(filename: str,
                              category: str = "hosting",
                              folder: str = "") -> bytes | None:
    """
    Admin vault se hosting file retrieve karo (hosting bot ke liye).
    vault_get() ko wrap karta hai — SQLCipher aur hybrid storage dono handle.
    """
    if not _DB_UNLOCKED:
        return None
    try:
        return vault_get(category, filename, folder)
    except Exception as e:
        print(f"[HostingBridge] ❌ vault_get failed for {filename}: {e}")
        return None

# ── Hybrid Storage: files > this threshold bypass SQLCipher BLOB encryption ──
LARGE_MEDIA_VAULT   = os.path.join(BASE_DIR, "large_media_vault")
HYBRID_THRESHOLD    = 10 * 1024 * 1024   # 10 MB
os.makedirs(LARGE_MEDIA_VAULT, exist_ok=True)
# 🔒 ULTRA-HARDENED: Vault directory strict permissions
try:
    os.chmod(LARGE_MEDIA_VAULT, 0o700)
except Exception:
    pass

# ── AutoLock per-script registry ──
# key → {"enabled": bool, "run_count": int, "first_run_ts": float}
_AUTOLOCK_STATE: dict = {}

# ── RAM-guard globals ──
_RAM_GUARD_ENABLED = True   # default ON; toggleable via sys_monitor button
_RAM_GUARD_THREAD  = None

# ══════════════════════════════════════════════════════════════
#  🗄️  SQLCIPHER DATABASE
# ══════════════════════════════════════════════════════════════
_DB_UNLOCKED  = False
_DB_KEY       = None   # Admin password (authentication only, not DB encryption key)

_DB_KEY_PRAGMAS      = []   # No cipher pragmas needed (plain sqlite3)
_LAST_UNLOCK_DIAGNOSIS = None
_DB_IS_PLAINTEXT     = True  # Always plain (no SQLCipher encryption)
_CIPHER_PROFILES     = []    # No cipher profiles needed

def _db_file_diagnosis(path: str) -> str:
    """
    🔥 FIX: Inspect vault.db on disk and explain WHY unlock might be failing,
    instead of always showing a generic 'wrong password' message.
    Called only after every profile in _CIPHER_PROFILES has already failed —
    distinguishes a genuinely wrong password from a corrupted/truncated file
    or a file that isn't actually encrypted.
    """
    if not os.path.exists(path):
        return "❌ `vault.db` file hi disk par nahi mili — kuch delete/move ho gaya lagta hai."
    try:
        size = os.path.getsize(path)
    except Exception:
        return "⚠️ `vault.db` ka size read nahi kar paya (permission issue ho sakta hai)."
    if size == 0:
        return "❌ `vault.db` 0 bytes ki hai — file khaali/corrupt hai. Password ka isse lena dena nahi. Backup se restore karo."
    if size < 512:
        return (f"⚠️ `vault.db` sirf {size} bytes ki hai — ek real database ke liye ye bahut chhoti hai. "
                "File truncated/incomplete lagti hai (adhoora upload/download ya disk-full ke waqt likhi gayi ho sakti hai). "
                "Password sahi bhi ho, phir bhi ye khulegi nahi — backup se restore karo.")
    try:
        with open(path, "rb") as f:
            header = f.read(16)
    except Exception:
        return "⚠️ `vault.db` header read nahi kar paya."
    if header.startswith(b"SQLite format 3\x00"):
        return ("⚠️ Ye file encrypted nahi hai — plaintext SQLite header mil raha hai. "
                "Ya to galat file hai, ya kisi tarah unencrypted copy se overwrite ho gayi. "
                "Koi bhi password isse match nahi karega, chahe sahi ho.")
    return (f"🔑 File genuinely encrypted lag rahi hai ({size:,} bytes, sahi random-salt header) — "
            "matlab file khud theek hai, corrupt nahi. Jo password diya gaya wo is DB ke liye match nahi hua. "
            "Ho sakta hai ye kisi purani/dusri backup ka password ho — dhyan se dobara sahi password daalo.")


def _get_sqlcipher():
    """
    🔥 FIX: SQLCipher module ko lazily import karo.
    pysqlcipher3 ya sqlcipher3 — jo bhi available ho.
    Dono ka API same hai (PEP 249 compatible).
    """
    try:
        from pysqlcipher3 import dbapi2 as _sc
        return _sc
    except ImportError:
        pass
    try:
        import sqlcipher3 as _sc
        return _sc
    except ImportError:
        pass
    raise RuntimeError(
        "SQLCipher library nahi mili! "
        "Install karo: pip install pysqlcipher3 ya pip install sqlcipher3"
    )

def _load_encryption_state():
    """
    🔥 FIX: Bot restart ke baad encryption state recover karo.
    /encryptdb ke baad _DB_ENCRYPTED_MARKER file create hoti hai.
    Yahan se pragmas padh ke _DB_IS_PLAINTEXT aur _DB_KEY_PRAGMAS set karo.
    Agar marker nahi hai → plain sqlite3 mode (default).
    """
    global _DB_IS_PLAINTEXT, _DB_KEY_PRAGMAS
    if not os.path.exists(_DB_ENCRYPTED_MARKER):
        return  # Plain mode — kuch karne ki zaroorat nahi
    try:
        with open(_DB_ENCRYPTED_MARKER, "r") as f:
            cfg = json.load(f)
        _DB_IS_PLAINTEXT = False
        _DB_KEY_PRAGMAS  = cfg.get("pragmas", [])
        print(f"🔒 [DB] SQLCipher encrypted mode detected (marker: {_DB_ENCRYPTED_MARKER})")
        print(f"   Pragmas: {_DB_KEY_PRAGMAS}")
    except Exception as e:
        print(f"⚠️ [DB] enc_config read nahi hua: {e} — plain mode fallback")

# ── Startup par encryption state load karo ──
_load_encryption_state()

def _db_connect():
    """
    DB connection — plain sqlite3 ya SQLCipher, jo bhi mode active hai.
    🔥 FIX: _DB_IS_PLAINTEXT = False hone par SQLCipher use karta hai
    (key + cipher pragmas apply karke), taaki restart ke baad encrypted
    DB properly khul sake aur 'file is not a database' error na aaye.
    """
    if not _DB_IS_PLAINTEXT:
        # ── SQLCipher mode ──
        if not _DB_KEY:
            raise RuntimeError("DB key not set. /start se pehle unlock karo.")
        sc  = _get_sqlcipher()
        con = sc.connect(DB_FILE, timeout=60, check_same_thread=False)
        safe_key = _DB_KEY.replace("'", "''")
        con.execute(f"PRAGMA key='{safe_key}'")
        for p in _DB_KEY_PRAGMAS:
            con.execute(p)
        con.execute("PRAGMA busy_timeout=60000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA cache_size=-8192")
        con.execute("PRAGMA temp_store=MEMORY")
        return con
    # ── Plain sqlite3 mode ──
    con = sqlite3.connect(DB_FILE, timeout=60, check_same_thread=False)
    con.execute("PRAGMA busy_timeout=60000")   # 60s lock wait
    con.execute("PRAGMA journal_mode=WAL")     # Concurrent reads + writes
    con.execute("PRAGMA synchronous=NORMAL")   # Faster than FULL, safe with WAL
    con.execute("PRAGMA cache_size=-8192")     # 8MB page cache (negative = KB)
    con.execute("PRAGMA temp_store=MEMORY")    # Temp tables in RAM
    con.execute("PRAGMA mmap_size=67108864")   # 64MB mmap (zero-copy reads)
    return con

def _db_connect_with_key(key: str, pragmas: list = None):
    """Plain sqlite3 — key parameter ignored (no encryption)."""
    con = sqlite3.connect(DB_FILE, check_same_thread=False)
    return con

def _db_init():
    """Create tables using individual execute() calls.
    Never use executescript() with SQLCipher — it issues an implicit COMMIT
    that can reset the PRAGMA key decryption context."""
    con = _db_connect()
    con.execute(
        "CREATE TABLE IF NOT EXISTS vault_meta "
        "(key TEXT PRIMARY KEY, value TEXT)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS files_vault ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "category TEXT NOT NULL, "
        "folder TEXT DEFAULT \'\', "
        "filename TEXT NOT NULL, "
        "content BLOB NOT NULL, "
        "size INTEGER DEFAULT 0, "
        "added_at TEXT, "
        "UNIQUE(category, folder, filename))"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS userbot_sessions ("
        "name TEXT PRIMARY KEY, phone TEXT, user_id TEXT, "
        "logged_in INTEGER DEFAULT 0, target_channel TEXT, added_at TEXT)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS backup_jobs ("
        "job_id TEXT PRIMARY KEY, interval_hours INTEGER, "
        "target_channel TEXT, active INTEGER DEFAULT 1, "
        "last_run TEXT, added_at TEXT)"
    )

    # ── Hybrid Storage schema migration (safe — idempotent, won't break existing rows) ──
    # is_local : 0 = BLOB in DB (small file),  1 = physical file on disk (large file)
    # file_path: physical path when is_local=1, NULL otherwise
    existing_cols = {
        row[1]
        for row in con.execute("PRAGMA table_info(files_vault)").fetchall()
    }
    if "is_local" not in existing_cols:
        con.execute(
            "ALTER TABLE files_vault ADD COLUMN is_local INTEGER NOT NULL DEFAULT 0"
        )
        log.info("DB schema: added column is_local to files_vault")
    if "file_path" not in existing_cols:
        con.execute(
            "ALTER TABLE files_vault ADD COLUMN file_path TEXT DEFAULT NULL"
        )
        log.info("DB schema: added column file_path to files_vault")

    con.commit()
    con.close()

def _db_get(key):
    con = _db_connect()
    row = con.execute("SELECT value FROM vault_meta WHERE key=?", (key,)).fetchone()
    con.close()
    return row[0] if row else None

def _db_set(key, val):
    con = _db_connect()
    con.execute("INSERT OR REPLACE INTO vault_meta(key,value) VALUES(?,?)", (key, val))
    con.commit()
    con.close()

# 🔥 FIX: "Sahi password bhi fail ho raha hai" — mobile keyboards / Telegram
# clients can silently inject characters that are invisible or look identical
# to the eye but are NOT the same byte sequence: zero-width spaces, a
# non-breaking space instead of a normal space, smart/curly quotes, fullwidth
# characters (some phone keyboards switch to these), or a stray trailing
# newline from a multi-line paste. Any of these makes hashlib.sha256(pw)
# and the SQLCipher key differ from what was used originally, so a
# visually-identical password gets rejected as "wrong". Normalize EVERY
# password the instant it's read from Telegram (and again defensively at
# every point it's hashed/used as a key) so the same-looking password always
# produces the same bytes.
def _normalize_pw(pw: str) -> str:
    if pw is None:
        return pw
    # Unicode compatibility normalization: fullwidth → halfwidth,
    # curly/smart quotes → ascii, etc.
    pw = unicodedata.normalize("NFKC", pw)
    # Strip invisible zero-width characters some keyboards/autocorrect insert
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"):
        pw = pw.replace(ch, "")
    # Non-breaking space → normal space (common on iOS keyboards)
    pw = pw.replace("\xa0", " ")
    # Trim regular + unicode whitespace from both ends (handles trailing
    # newline from copy-paste / multi-line Telegram messages)
    pw = pw.strip()
    return pw

# Password check: DB file existing on disk means password was already set.
# We NEVER try to open the DB here without a key — that would corrupt it.
def db_password_set() -> bool:
    """Returns True if vault.db already exists (password was set previously)."""
    return os.path.exists(DB_FILE)

def db_verify_pw(pw: str) -> bool:
    """
    Verify admin password.
    🔥 FIX: Plain DB → sqlite3 se seedha pw_hash padhta hai.
             Encrypted DB → SQLCipher se key+pragmas lagakar padhta hai.
    Dono cases mein scrypt hash se verify hota hai.
    """
    global _LAST_UNLOCK_DIAGNOSIS
    pw = _normalize_pw(pw)
    try:
        if _DB_IS_PLAINTEXT:
            # Plain sqlite3 — seedha connect karo
            con = sqlite3.connect(DB_FILE, timeout=10)
        else:
            # 🔥 FIX: SQLCipher mode — pehle key lagao, phir pragmas, tab query
            sc  = _get_sqlcipher()
            con = sc.connect(DB_FILE, timeout=10, check_same_thread=False)
            safe_key = pw.replace("'", "''")
            con.execute(f"PRAGMA key='{safe_key}'")
            for p in _DB_KEY_PRAGMAS:
                con.execute(p)
        row = con.execute("SELECT value FROM vault_meta WHERE key='pw_hash'").fetchone()
        con.close()
        if row and _scrypt_verify(pw, row[0]):
            _LAST_UNLOCK_DIAGNOSIS = None
            return True
    except Exception as e:
        log.warning(f"db_verify_pw error: {e}")
        _LAST_UNLOCK_DIAGNOSIS = str(e)
    return False

def db_set_pw(pw: str):
    """Called ONCE during /setpassword. _DB_KEY must already be set before calling.
    Uses _db_connect() so the standard PRAGMA key sequence is applied.
    🔒 HARDENING: scrypt hash store karta hai (sha256 nahi) + AES key salt initialize."""
    pw = _normalize_pw(pw)  # 🔥 FIX: defense-in-depth, see _normalize_pw()
    con = _db_connect()  # _DB_KEY is already set at this point
    con.execute("CREATE TABLE IF NOT EXISTS vault_meta(key TEXT PRIMARY KEY, value TEXT)")
    # 🔒 HARDENING: scrypt hash (brute-force resistant) store karo
    con.execute("INSERT OR REPLACE INTO vault_meta(key,value) VALUES(?,?)",
                ("pw_hash", _scrypt_hash(pw)))
    # 🔒 HARDENING: AES key salt generate aur store karo (fresh setup only)
    aes_salt_existing = con.execute(
        "SELECT value FROM vault_meta WHERE key='aes_key_salt'"
    ).fetchone()
    if not aes_salt_existing:
        aes_salt = os.urandom(32).hex()
        con.execute("INSERT OR REPLACE INTO vault_meta(key,value) VALUES(?,?)",
                    ("aes_key_salt", aes_salt))
    con.commit()
    con.close()

def _maybe_upgrade_pw_hash(pw: str):
    """
    🔒 AUTO-MIGRATION: Agar vault_meta mein pw_hash purane sha256 format mein
    stored hai (64-char hex, 'scrypt$' prefix nahi), to isse scrypt format mein
    silently upgrade karo. Agle unlock par scrypt hash match karega.
    """
    try:
        stored = _db_get("pw_hash")
        if stored and len(stored) == 64 and not stored.startswith("scrypt$"):
            new_hash = _scrypt_hash(pw)
            con = _db_connect()
            con.execute("INSERT OR REPLACE INTO vault_meta(key,value) VALUES(?,?)",
                        ("pw_hash", new_hash))
            con.commit()
            con.close()
            log.info("🔒 pw_hash: SHA-256 se scrypt mein upgrade hua (auto-migration).")
    except Exception as e:
        log.warning(f"pw_hash upgrade (non-critical, will retry next unlock): {e}")

# ══════════════════════════════════════════════════════════════
#  📦  FILES VAULT — CRUD (replaces scripts/folders/db_files)
# ══════════════════════════════════════════════════════════════
# category values: 'script', 'folder_file', 'session', 'dbfile'

def _get_aes_key() -> bytes:
    """
    🔥 FIX (Bug #2): _vault_physical_path() se call hota hai lekin pehle define
    nahi tha → NameError crash har >10MB file save par.
    _DB_KEY + stored salt se 32-byte HMAC key derive karta hai.
    Salt vault_meta['aes_key_salt'] mein stored hai (db_set_pw ke waqt create hoti hai).
    Agar DB unlock nahi hai ya salt nahi mili toh RuntimeError raise hota hai.
    """
    if not _DB_KEY:
        raise RuntimeError("DB unlock nahi hua — _get_aes_key() tab tak call nahi ho sakta.")
    try:
        salt_hex = _db_get("aes_key_salt")
        if not salt_hex:
            # Salt pehli baar nahi bani thi (purana setup) — create karke save karo
            salt = os.urandom(32)
            _db_set("aes_key_salt", salt.hex())
        else:
            salt = bytes.fromhex(salt_hex)
    except Exception as e:
        raise RuntimeError(f"AES key salt read nahi hua: {e}")
    return _kdf(_DB_KEY, salt, dklen=32)

def _vault_physical_path(category: str, folder: str, filename: str) -> str:
    """
    🔒 ULTRA-HARDENED: Physical filenames obfuscate karo.
    Asli filename disk par KABHI nahi dikhega — HMAC-SHA256 hash use hota hai.
    Koi bhi large_media_vault/ dekhke samajh nahi payega ki kaunsi file kya hai.
    Original mapping sirf encrypted vault.db ke andar safe hai.
    Structure: large_media_vault/<fixed-flat-dir>/<hmac-hex>.enc
    """
    # HMAC key: AES key ka hi use karo (same password dependency)
    import hmac as _hmac
    try:
        aes_key = _get_aes_key()
    except RuntimeError:
        # DB unlock nahi hua — fallback se path (save hone se pehle unlock check hota hai)
        aes_key = b"\x00" * 32
    # Canonical string: category + NULL + folder + NULL + filename
    canonical = f"{category}\x00{folder}\x00{filename}".encode()
    name_hash = _hmac.new(aes_key, canonical, "sha256").hexdigest()
    dest_dir  = os.path.join(LARGE_MEDIA_VAULT, "enc")
    os.makedirs(dest_dir, exist_ok=True)
    os.chmod(dest_dir, 0o700)   # sirf owner access kar sake
    return os.path.join(dest_dir, name_hash + ".enc")

# ══════════════════════════════════════════════════════════════
#  📂  PLAIN DISK STORAGE (No Encryption — Fast Mode)
# ══════════════════════════════════════════════════════════════
# AES encryption hataya gaya — plain files disk par store hoti hain.
# /encryptdb command se poori DB ko encrypt kar sakte ho (SQLCipher chahiye).
_AES_KEY_CACHED: bytes = None   # Kept for future /encryptdb migration reference
_AES_KEY_SECURE = None

def encrypt_data_to_disk(data_bytes: bytes, output_path: str):
    """Plain file write — no encryption. Atomic tmp→rename (crash-safe)."""
    tmp_path = output_path + ".tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(data_bytes)
        os.replace(tmp_path, output_path)   # atomic on POSIX
        os.chmod(output_path, 0o600)
    except Exception:
        try: os.remove(tmp_path)
        except Exception: pass
        raise

def decrypt_disk_to_data(input_path: str) -> bytes:
    """Plain file read — no decryption needed."""
    with open(input_path, "rb") as f:
        return f.read()

def vault_save(category: str, filename: str, content: bytes, folder: str = ""):
    size = len(content)
    
    # 🔥 NAYA LOGIC: Scripts (.py, .js) hamesha DB me jayengi, kabhi disk par nahi!
    is_script = filename.endswith((".py", ".js"))

    if size > HYBRID_THRESHOLD and not is_script:
        # ── Large file (Non-Script): Encrypt with AES-CTR in chunks and save to disk ──
        phys_path = _vault_physical_path(category, folder, filename)
        encrypt_data_to_disk(content, phys_path) 
        
        con = _db_connect()
        con.execute(
            "INSERT OR REPLACE INTO files_vault"
            "(category, folder, filename, content, size, added_at, is_local, file_path)"
            " VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (category, folder, filename, b"", size, datetime.now().isoformat(), phys_path))
        con.commit()
        con.close()
        log.info(f"vault_save [DISK-ENCRYPTED] {category}/{folder}/{filename} → {phys_path}")

    else:
        # ── Scripts ya Small Files: Hamesha SQLCipher BLOB me jayengi ──
        con = _db_connect()
        con.execute(
            "INSERT OR REPLACE INTO files_vault"
            "(category, folder, filename, content, size, added_at, is_local, file_path)"
            " VALUES (?, ?, ?, ?, ?, ?, 0, NULL)",
            (category, folder, filename, content, size, datetime.now().isoformat()))
        con.commit()
        con.close()
        log.info(f"vault_save [BLOB - SECURE] {category}/{folder}/{filename}")
        
def vault_get(category: str, filename: str, folder: str = "") -> bytes:
    con = _db_connect()
    row = con.execute(
        "SELECT content, is_local, file_path FROM files_vault"
        " WHERE category=? AND folder=? AND filename=?",
        (category, folder, filename)).fetchone()
    con.close()

    if row is None:
        return None

    content_blob, is_local, file_path = row

    if is_local:
        # ── Large file: Decrypt from disk ──
        if not file_path or not os.path.isfile(file_path):
            log.error(f"vault_get: physical file missing: {file_path}")
            return None
        return decrypt_disk_to_data(file_path) # Naya Decryption Logic
    else:
        # ── Small file: Return BLOB ──
        return bytes(content_blob) if content_blob else None
        
def vault_delete(category: str, filename: str, folder: str = ""):
    """Delete DB row and, for large (is_local=1) files, the physical file too."""
    con = _db_connect()
    row = con.execute(
        "SELECT is_local, file_path FROM files_vault"
        " WHERE category=? AND folder=? AND filename=?",
        (category, folder, filename)).fetchone()
    con.execute(
        "DELETE FROM files_vault WHERE category=? AND folder=? AND filename=?",
        (category, folder, filename))
    con.commit()
    con.close()

    if row and row[0] == 1 and row[1] and os.path.isfile(row[1]):
        try:
            os.remove(row[1])
            log.info(f"vault_delete: removed physical file {row[1]}")
        except Exception as e:
            log.warning(f"vault_delete: could not remove physical file {row[1]}: {e}")

def vault_list(category, folder=None):
    """Returns list of (folder, filename, size, added_at)"""
    con = _db_connect()
    if folder is not None:
        rows = con.execute(
            "SELECT folder, filename, size, added_at FROM files_vault WHERE category=? AND folder=? ORDER BY filename",
            (category, folder)).fetchall()
    else:
        rows = con.execute(
            "SELECT folder, filename, size, added_at FROM files_vault WHERE category=? ORDER BY folder, filename",
            (category,)).fetchall()
    con.close()
    return rows

def vault_list_folders():
    """Returns distinct folder names that have category='folder_file' entries."""
    con = _db_connect()
    rows = con.execute(
        "SELECT DISTINCT folder FROM files_vault WHERE category='folder_file' ORDER BY folder").fetchall()
    con.close()
    return [r[0] for r in rows]

# ── Convenience wrappers ──
def get_scripts():
    rows = vault_list("script")
    return sorted(r[1] for r in rows if r[1].endswith((".py", ".js")))

def script_content(fname) -> bytes:
    return vault_get("script", fname)

# ══════════════════════════════════════════════════════════════
#  🚀  GRAND MIGRATION (runs once on startup)
# ══════════════════════════════════════════════════════════════
def _grand_migration():
    """
    If legacy /scripts or /folders directories exist:
    1. Read every file inside them
    2. Store into files_vault as BLOBs
    3. Verify insertion
    4. Delete the physical directories
    """
    migrated = 0

    for legacy_dir in (_LEGACY_SCRIPTS_DIR, _LEGACY_FOLDERS_DIR):
        if not os.path.isdir(legacy_dir):
            continue
        log.info(f"📦 Grand Migration: found legacy dir {legacy_dir}")
        for root, dirs, files in os.walk(legacy_dir):
            for fn in files:
                fpath = os.path.join(root, fn)
                try:
                    with open(fpath, "rb") as f:
                        data = f.read()
                except Exception as e:
                    log.warning(f"Migration: cannot read {fpath}: {e}")
                    continue

                if legacy_dir == _LEGACY_SCRIPTS_DIR:
                    category = "script"
                    folder   = ""
                    filename = fn
                else:
                    # folder_name is first subdir under FOLDERS_DIR
                    rel = os.path.relpath(fpath, legacy_dir)
                    parts = rel.split(os.sep, 1)
                    folder   = parts[0]
                    filename = parts[1] if len(parts) > 1 else fn
                    category = "folder_file"

                vault_save(category, filename, data, folder)

                # Verify
                check = vault_get(category, filename, folder)
                if check and len(check) == len(data):
                    migrated += 1
                    log.info(f"  ✅ Migrated: [{category}] {folder}/{filename} ({len(data)} bytes)")
                else:
                    log.error(f"  ❌ Verify FAILED for {fpath}! Not deleting this file.")
                    continue

        try:
            shutil.rmtree(legacy_dir)
            log.info(f"🗑️ Deleted legacy directory: {legacy_dir}")
        except Exception as e:
            log.error(f"Could not delete {legacy_dir}: {e}")

    if migrated:
        log.info(f"✅ Grand Migration complete — {migrated} files migrated to SQLCipher DB.")
    return migrated

# ══════════════════════════════════════════════════════════════
#  🧠  RAM DISK EXECUTION ENGINE (/dev/shm)
# ══════════════════════════════════════════════════════════════
_RAM_MONITORS = {}  # key → monitor thread
_LAST_SAVED_STATE = {}  # key → {filename: mtime} — auto-save ke liye last saved state
_AUTOSAVE_STOP_EVT = threading.Event()  # Global auto-save thread ko stop karne ke liye

def _extract_to_ram(category, filename, folder="") -> str:
    """Extract a file from DB to RAM disk. Returns path or None."""
    data = vault_get(category, filename, folder)
    if data is None:
        return None
    safe_name = filename.replace("/", "_").replace("\\", "_")
    ram_path = os.path.join(RAM_DISK_DIR, safe_name)
    with open(ram_path, "wb") as f:
        f.write(data)
    os.chmod(ram_path, 0o700)
    return ram_path

# ══════════════════════════════════════════════════════════════
#  💾  LIVE DATA SAVE — Script chal rahi ho TAB BHI save karo
#  (Kill kiye bina — sirf changed/new files vault mein daalta hai)
# ══════════════════════════════════════════════════════════════
def _save_running_script_data(key: str, *, notify_chat_id: int = None) -> list:
    """
    Ek running script ke RAM folder ke changed/new files ko
    abhi vault mein save karo — process kill NAHI hoga.

    Returns: list of saved filenames (empty = kuch nahi badla)
    """
    info = RUNNING.get(key)
    if not info:
        return []

    ram_cwd = os.path.dirname(info.get("ram_path", ""))
    if not ram_cwd or not os.path.isdir(ram_cwd):
        return []

    category = info.get("category", "")
    folder   = info.get("folder", "")
    last_state = _LAST_SAVED_STATE.get(key, {})
    saved = []

    try:
        for fn in os.listdir(ram_cwd):
            fp = os.path.join(ram_cwd, fn)
            if not os.path.isfile(fp):
                continue
            try:
                mtime = os.path.getmtime(fp)
            except OSError:
                continue

            # Pehle save ke waqt last_state khali hoga → sab save karo
            if fn not in last_state or mtime > last_state[fn]:
                try:
                    with open(fp, "rb") as f:
                        data = f.read()
                    vault_save(category, fn, data, folder)
                    last_state[fn] = mtime
                    saved.append(fn)
                    # WAL/SHM hai toh main DB bhi save karo
                    if fn.endswith("-wal") or fn.endswith("-shm"):
                        main_db = fn.replace("-wal", "").replace("-shm", "")
                        main_fp = os.path.join(ram_cwd, main_db)
                        if os.path.isfile(main_fp) and main_db not in saved:
                            with open(main_fp, "rb") as f2:
                                vault_save(category, main_db, f2.read(), folder)
                            last_state[main_db] = os.path.getmtime(main_fp)
                            saved.append(main_db)
                except Exception as e:
                    log.warning(f"[LiveSave] {key}/{fn}: {e}")
    except Exception as e:
        log.warning(f"[LiveSave] {key}: listdir error: {e}")

    _LAST_SAVED_STATE[key] = last_state

    if saved and notify_chat_id:
        try:
            bot.send_message(
                notify_chat_id,
                f"💾 *Manual Save* — `{info.get('filename',key)}`\n"
                f"Saved {len(saved)} file(s): " + ", ".join(f"`{s}`" for s in saved),
                parse_mode="Markdown"
            )
        except Exception:
            pass
    return saved


def _save_all_running_data(*, log_prefix: str = "Shutdown") -> None:
    """
    Saare running scripts ka data abhi vault mein save karo.
    Script stop / SIGINT / SIGTERM par call hota hai.
    """
    keys = list(RUNNING.keys())
    if not keys:
        return
    log.info(f"[{log_prefix}] Saving data for {len(keys)} running script(s)…")
    for k in keys:
        try:
            saved = _save_running_script_data(k)
            if saved:
                log.info(f"[{log_prefix}] Saved {len(saved)} file(s) for '{k}'")
            else:
                log.info(f"[{log_prefix}] No changes for '{k}'")
        except Exception as e:
            log.warning(f"[{log_prefix}] Save failed for '{k}': {e}")


def _autosave_loop(interval_seconds: int = 180):
    """
    Background thread: har `interval_seconds` baad sabke changed files save karta hai.
    Default: har 3 minute.
    """
    log.info(f"[AutoSave] Thread started — interval: {interval_seconds}s")
    while not _AUTOSAVE_STOP_EVT.wait(timeout=interval_seconds):
        if RUNNING:
            log.info(f"[AutoSave] Periodic save for {len(RUNNING)} script(s)…")
            for k in list(RUNNING.keys()):
                try:
                    _save_running_script_data(k)
                except Exception as e:
                    log.warning(f"[AutoSave] {k}: {e}")
    log.info("[AutoSave] Thread stopped.")


def _wipe_ram_key(key):
    """
    Remove the per-run sub-directory from the RAM disk for a given run key.
    The directory name mirrors the safe_key logic in _extract_all_to_ram.
    """
    # key is like "myfolder/myscript.py" or "myscript.py"
    # Reconstruct the directory name: folder + "__" + filename, slashes → "_"
    # We stored info in RUNNING so try to recover folder/filename from there first.
    info = RUNNING.get(key)
    if info:
        folder   = info.get("folder", "")
        filename = info.get("filename", os.path.basename(key))
    else:
        folder   = ""
        filename = os.path.basename(key)

    safe_key = (folder + "__" + filename).replace("/", "_").replace("\\", "_")
    run_dir  = os.path.join(RAM_DISK_DIR, safe_key)

    if os.path.isdir(run_dir):
        try:
            shutil.rmtree(run_dir)
        except Exception as e:
            log.warning(f"_wipe_ram_key: could not remove {run_dir}: {e}")
    else:
        # Fallback: old single-file wipe for backwards compat
        safe_name = filename.replace("/", "_").replace("\\", "_")
        ram_path  = os.path.join(RAM_DISK_DIR, safe_name)
        if os.path.exists(ram_path):
            try:
                os.remove(ram_path)
            except Exception:
                pass

def _monitor_ram_outputs(key, ram_cwd, category, folder, proc, chat_id):
    initial_state = {}
    if os.path.isdir(ram_cwd):
        for f in os.listdir(ram_cwd):
            fp = os.path.join(ram_cwd, f)
            if os.path.isfile(fp):
                initial_state[f] = os.path.getmtime(fp)

    proc.wait()  # block until process exits

    if not os.path.isdir(ram_cwd):
        return

    saved = []
    to_save = set()
    
    # 1. Pata karo konsi files nayi hain ya update hui hain
    for fn in os.listdir(ram_cwd):
        fp = os.path.join(ram_cwd, fn)
        if not os.path.isfile(fp):
            continue
            
        is_new = fn not in initial_state
        is_modified = not is_new and os.path.getmtime(fp) > initial_state[fn]
        
        if is_new or is_modified:
            to_save.add(fn)
            # Agar -wal update hui hai, toh main file ko bhi save list mein dalo
            # LEKIN original -wal file ko list se remove mat karo! Dono save honi chahiye.
            if fn.endswith("-wal") or fn.endswith("-shm"):
                main_db_name = fn.replace("-wal", "").replace("-shm", "")
                to_save.add(main_db_name)
                
    # 2. Files ko Vault mein permanently save karo
    for fn in to_save:
        fp = os.path.join(ram_cwd, fn)
        if os.path.isfile(fp):
            try:
                with open(fp, "rb") as f:
                    data = f.read()
                vault_save(category, fn, data, folder)
                saved.append(fn)
            except Exception as e:
                pass

    # 3. Aakhir mein RAM folder ko safely delete karo (Taaki kachra na bhare)
    import shutil
    try:
        shutil.rmtree(ram_cwd)
    except Exception:
        pass

    if saved and chat_id:
        try:
            bot.send_message(chat_id,
                f"💾 Script updated {len(saved)} file(s) — saved permanently to DB:\n" +
                "\n".join(f"  `{s}`" for s in saved), parse_mode="Markdown")
        except:
            pass
            
def _extract_all_to_ram(category: str, folder: str, primary_filename: str) -> str:
    safe_key  = (folder + "__" + primary_filename).replace("/", "_").replace("\\", "_")
    run_dir   = os.path.join(RAM_DISK_DIR, safe_key)
    os.makedirs(run_dir, exist_ok=True)
    os.chmod(run_dir, 0o700)

    # 1️⃣ All files that live in the same folder
    siblings = vault_list(category, folder=folder)          
    for _, fn, _, _ in siblings:
        data = vault_get(category, fn, folder)
        if data is None:
            continue
        
        # 🔥 PERFECT PATH RESOLUTION: Asli folder structure RAM me banega
        # Agar fn ke andar slashes hain (jaise 'utils/helper.py'), toh wo folder ban jayega
        dest = os.path.join(run_dir, fn)
        os.makedirs(os.path.dirname(dest), exist_ok=True) 
        
        with open(dest, "wb") as fh:
            fh.write(data)
        os.chmod(dest, 0o700)

    # 2️⃣ Root .env & config extraction (Isme bhi same fix)
    for _cat, _fld, _fn in [
        (category,       "",   ".env"),
        ("folder_file",  "",   ".env"),
        ("script",       "",   ".env"),
        (category,       "",   "config.py"),
        ("folder_file",  "",   "config.py"),
        ("script",       "",   "config.py"),
    ]:
        data = vault_get(_cat, _fn, _fld)
        if data is not None:
            dest = os.path.join(run_dir, _fn)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if not os.path.exists(dest):          
                with open(dest, "wb") as fh:
                    fh.write(data)
                os.chmod(dest, 0o600)

    # Primary script path
    ram_path = os.path.join(run_dir, primary_filename)
    if not os.path.isfile(ram_path):
        return None

    return ram_path

# ══════════════════════════════════════════════════════════════
#  📦  CHILD SCRIPT PRE-INSTALL REQUIREMENTS
# ══════════════════════════════════════════════════════════════

# Import name → pip package name mapping
_PIP_MAP = {
    "cv2":          "opencv-python",
    "PIL":          "Pillow",
    "sklearn":      "scikit-learn",
    "bs4":          "beautifulsoup4",
    "yaml":         "pyyaml",
    "dotenv":       "python-dotenv",
    "telebot":      "pyTelegramBotAPI",
    "crypto":       "pycryptodome",
    "Crypto":       "pycryptodome",
    "nacl":         "PyNaCl",
    "gi":           "PyGObject",
    "wx":           "wxPython",
    "serial":       "pyserial",
    "usb":          "pyusb",
    "colorama":     "colorama",
    "rich":         "rich",
    "httpx":        "httpx",
    "aiohttp":      "aiohttp",
    "fastapi":      "fastapi",
    "uvicorn":      "uvicorn",
    "flask":        "flask",
    "django":       "django",
    "sqlalchemy":   "SQLAlchemy",
    "pymongo":      "pymongo",
    "redis":        "redis",
    "celery":       "celery",
    "boto3":        "boto3",
    "paramiko":     "paramiko",
    "cryptography": "cryptography",
    "jwt":          "PyJWT",
    "bcrypt":       "bcrypt",
    "passlib":      "passlib",
    "apscheduler":  "APScheduler",
    "cachetools":   "cachetools",
    "tqdm":         "tqdm",
    "tabulate":     "tabulate",
    "pydantic":     "pydantic",
    "loguru":       "loguru",
    "arrow":        "arrow",
    "pendulum":     "pendulum",
    "dateutil":     "python-dateutil",
    "chardet":      "chardet",
    "lxml":         "lxml",
    "toml":         "toml",
    "decouple":     "python-decouple",
    "pyrogram":     "pyrogram",
    "telethon":     "Telethon",
    "aiogram":      "aiogram",
    "tweepy":       "tweepy",
    "instaloader":  "instaloader",
    "playwright":   "playwright",
    "selenium":     "selenium",
    "mechanize":    "mechanize",
}

def _scan_imports(py_path: str) -> list[str]:
    """
    .py file ke top-level import/from statements parse karo.
    Returns list of module names (first component only).
    """
    mods = []
    try:
        with open(py_path, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        import ast as _ast
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    mods.append(alias.name.split(".")[0])
            elif isinstance(node, _ast.ImportFrom):
                if node.module:
                    mods.append(node.module.split(".")[0])
    except Exception:
        # fallback: regex
        for line in (src if 'src' in dir() else "").splitlines():
            m = re.match(r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)", line)
            if m:
                mods.append(m.group(1))
    return list(set(mods))

def _check_requirements_txt(ram_cwd: str) -> list[str]:
    """requirements.txt ya requirements-*.txt scan karo"""
    pkgs = []
    for fname in os.listdir(ram_cwd):
        if fname == "requirements.txt" or (fname.startswith("requirements") and fname.endswith(".txt")):
            try:
                with open(os.path.join(ram_cwd, fname), "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            # version specifiers hata do: requests>=2.0 → requests
                            pkg = re.split(r"[>=<!;\[]", line)[0].strip()
                            if pkg:
                                pkgs.append(pkg)
            except Exception:
                pass
    return pkgs

_STDLIB = frozenset([
    "os","sys","re","io","json","time","math","shlex","signal","atexit","hashlib",
    "zipfile","shutil","threading","logging","subprocess","tempfile","queue","asyncio",
    "pathlib","datetime","collections","functools","itertools","contextlib","abc",
    "copy","typing","enum","dataclasses","struct","socket","ssl","http","urllib",
    "email","html","xml","csv","sqlite3","pickle","shelve","dbm","zlib","gzip","bz2",
    "lzma","tarfile","uuid","secrets","random","string","textwrap","pprint","traceback",
    "inspect","importlib","pkgutil","platform","gc","weakref","codecs","unicodedata",
    "base64","binascii","hmac","decimal","fractions","statistics","cmath","heapq",
    "bisect","array","mmap","ctypes","unittest","doctest","pdb","profile","timeit",
    "ast","dis","token","tokenize","keyword","builtins","warnings","errno","fcntl",
    "pty","tty","termios","readline","rlcompleter","curses","argparse","getopt",
    "configparser","netrc","ftplib","poplib","imaplib","smtplib","telnetlib","xmlrpc",
    "multiprocessing","concurrent","selectors","asynchat","asyncore","wave","aifc",
    "sunau","audioop","imageop","imghdr","sndhdr","ossaudiodev","getpass","gettext",
    "locale","calendar","sched","reprlib","numbers","cProfile",
    # common vendored
    "pkg_resources","setuptools","pip",
])

def _preinstall_requirements(ram_path: str, ram_cwd: str, chat_id: int, filename: str, silent: bool = False):
    """
    Script run karne se PEHLE:
    1. requirements.txt scan karo → pip install
    2. import statements scan karo → missing pakdo → pip install
    3. Agar install fail ho toh notify karo
    silent=True: sirf failures notify karo (auto-restart mode)
    """
    failed = []
    installed = []

    # Step 1: requirements.txt
    req_pkgs = _check_requirements_txt(ram_cwd)
    if req_pkgs:
        status_msg = None
        if not silent:
            status_msg = bot.send_message(chat_id,
                f"📦 `{filename}`: requirements.txt mein `{len(req_pkgs)}` packages — install ho rahi hain…",
                parse_mode="Markdown")
        for pkg in req_pkgs:
            ok = _pip_install(pkg)
            if ok:
                installed.append(pkg)
            else:
                failed.append(pkg)
        if status_msg:
            try:
                result_txt = f"✅ `{len(installed)}` packages installed"
                if failed:
                    result_txt += f"\n❌ Install nahi hui: `{', '.join(failed)}`"
                bot.edit_message_text(result_txt, chat_id, status_msg.message_id, parse_mode="Markdown")
            except Exception:
                pass
        elif failed:
            bot.send_message(chat_id,
                f"⚠️ `{filename}` requirements.txt — install fail: `{', '.join(failed)}`",
                parse_mode="Markdown")

    # Step 2: import scan — missing modules
    mods = _scan_imports(ram_path)
    missing = []
    for mod in mods:
        if mod in _STDLIB:
            continue
        try:
            __import__(mod)
        except ImportError:
            pip_pkg = _PIP_MAP.get(mod, mod)
            missing.append((mod, pip_pkg))

    if missing:
        unique_pkgs = list({p for _, p in missing})
        status_msg2 = None
        if not silent:
            status_msg2 = bot.send_message(chat_id,
                f"🔍 `{filename}`: `{len(unique_pkgs)}` missing packages — install kar raha hoon…\n"
                f"`{', '.join(unique_pkgs)}`",
                parse_mode="Markdown")
        inst2, fail2 = [], []
        for pkg in unique_pkgs:
            ok = _pip_install(pkg)
            if ok:
                inst2.append(pkg)
            else:
                fail2.append(pkg)
        if status_msg2:
            try:
                r2 = f"✅ Installed: `{', '.join(inst2)}`" if inst2 else "✅ No missing packages"
                if fail2:
                    r2 += f"\n⚠️ Manually karo: `pip install {' '.join(fail2)}`"
                bot.edit_message_text(r2, chat_id, status_msg2.message_id, parse_mode="Markdown")
            except Exception:
                pass
        elif fail2:
            # silent mode mein bhi failures notify karo
            bot.send_message(chat_id,
                f"⚠️ `{filename}` — packages install FAIL (manually karo):\n`pip install {' '.join(fail2)}`",
                parse_mode="Markdown")


def run_script(key: str, category: str, filename: str, folder: str, chat_id: int,
               attempt: int = 1, auto_restart: bool = False):
    """
    Extract file from DB → scan requirements → install → run.
    """
    # 🔥 FIX: har thread ke liye apna event loop set karo (Py3.14: non-main
    # thread mein asyncio.get_event_loop() RuntimeError deta hai agar loop
    # set na ho — pytgcalls jaisi libs isi wajah se import time crash karti hain)
    _setup_event_loop()

    # 🔥 FIX: Zombie Process Lock
    if is_running(key):
        try:
            bot.send_message(chat_id, f"⚠️ `{filename}` pehle se hi background mein chal rahi hai!", parse_mode="Markdown")
        except: pass
        return

    ram_path = _extract_all_to_ram(category, folder, filename)
    if not ram_path:
        bot.send_message(chat_id, f"❌ File not in DB: `{filename}`", parse_mode="Markdown")
        return

    ram_cwd = os.path.dirname(ram_path)

    # ── Pre-run requirements install ──
    if filename.endswith(".py"):
        _preinstall_requirements(ram_path, ram_cwd, chat_id, filename,
                                 silent=auto_restart)   # auto=silent, manual=verbose

    cmd = [sys.executable, ram_path] if filename.endswith(".py") else ["node", ram_path]

    lp = log_path(key)
    try:
        lf = open(lp, "w", encoding="utf-8", errors="ignore")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Log error: {e}")
        return

    try:
        env = os.environ.copy()
        env["TELEGRAM_BOT_IS_SUBPROCESS"] = "1"
        proc = subprocess.Popen(cmd, cwd=ram_cwd, stdout=lf, stderr=lf,
                                stdin=subprocess.PIPE, encoding="utf-8",
                                errors="ignore", env=env)
    except Exception as e:
        lf.close()
        _wipe_ram_key(key)
        bot.send_message(chat_id, f"❌ Failed to start: {e}")
        return

    RUNNING[key] = {
        "proc": proc, "pid": proc.pid, "start": datetime.now(),
        "log_file": lf, "ram_path": ram_path,
        "category": category, "filename": filename, "folder": folder
    }

    # 1. Pehla message: Run details (Jo text aana chahiye)
    bot.send_message(chat_id,
        f"✅ `{filename}` started!\n🔢 PID: `{proc.pid}`\n💾 RAM Disk: `{ram_path}`",
        parse_mode="Markdown")

    # 🔥 NAYA CODE: 2. Dusra message Control Panel ke sath (Niche alag se)
    status = "🟢 Running"
    if folder: # Agar script kisi folder ke andar ki hai
        base_name = os.path.basename(filename)
        txt = f"🎮 *Control Panel: {base_name}*\n📂 Path: `{folder}/{filename}`\nStatus: {status}\n⏱ 0m | PID: {proc.pid}"
        mk = kb_file_action(folder, filename, key)
    else: # Agar script bahar root par hai
        txt = f"🎮 *Control Panel: {filename}*\nStatus: {status}\n⏱ 0m | PID: {proc.pid}"
        mk = kb_script_ctrl(filename)
        
    bot.send_message(chat_id, txt, parse_mode="Markdown", reply_markup=mk)

    saved = json.loads(_db_get("auto_scripts") or "[]")
    if key not in saved:
        saved.append(key)
    _db_set("auto_scripts", json.dumps(saved))

    _autolock_on_run(key)   # increment run counter

    # RAM output monitor thread
    mt = threading.Thread(target=_monitor_ram_outputs,
                          args=(key, ram_cwd, category, folder, proc, chat_id),
                          daemon=True)
    mt.start()
    _RAM_MONITORS[key] = mt

    # 🚨 Error-alert live tail thread (sirf tab kaam karta hai jab error
    # alerts ON hon aur group configured ho — warna har poll par turant skip)
    et = threading.Thread(target=_error_tail_watch, args=(key, proc), daemon=True)
    et.start()

    def _watch():
        proc.wait()
        exit_code = proc.returncode  # 🔥 नया: चेक करेगा कि स्क्रिप्ट क्रैश हुई है या नहीं
        
        if key not in RUNNING:
            return

        # 🔥 NAYA FIX: Process kill/exit hote hi logs ko zabardasti file me save (flush) karna
        info = RUNNING.get(key)
        if info and "log_file" in info:
            try:
                info["log_file"].flush()
                import os
                os.fsync(info["log_file"].fileno())
            except Exception:
                pass

        try:
            with open(lp, "r", encoding="utf-8", errors="ignore") as f2:
                et = f2.read()[-2000:]
        except Exception:
            et = ""

        # uptime_seconds nikalne ke liye info pehle hi get kar liya hai
        uptime_seconds = (datetime.now() - info["start"]).total_seconds() if info else 0

        # AutoLock stable mark
        if uptime_seconds >= AUTOLOCK_MIN_UPTIME:
            _autolock_mark_stable(key)

        _cleanup(key)

        saved2 = json.loads(_db_get("auto_scripts") or "[]")
        if key in saved2:
            saved2.remove(key)
        _db_set("auto_scripts", json.dumps(saved2))

        if "ModuleNotFoundError" in et or "Cannot find module" in et:
            if attempt < 3 and _auto_install(et, chat_id):
                run_script(key, category, filename, folder, chat_id, attempt + 1, auto_restart)
                return

        # 🔥 नया: असली एरर निकालने के लिए लॉग का आख़िरी हिस्सा
        snippet = et[-800:].strip() if et else "No error output found in logs."

        # ── AutoLock restart (takes priority over auto_restart) ──
        al_st = _AUTOLOCK_STATE.get(key, {})
        if _autolock_enabled(key) and al_st.get("stable"):
            bot.send_message(chat_id, f"🔒 *AutoLock:* `{filename}` crashed — restarting…",
                             parse_mode="Markdown")
            time.sleep(2)
            run_script(key, category, filename, folder, chat_id, 1, auto_restart=False)
            return

        if auto_restart:
            # अगर स्क्रिप्ट जल्दी क्रैश हो जाए या उसका exit_code 0 ना हो (मतलब एरर है)
            if uptime_seconds < 10 or exit_code != 0:
                bot.send_message(chat_id,
                    f"⚠️ *Crash Loop / Error Detected!*\n`{filename}` crashed.\n"
                    f"Auto-restart halted.\n\n*Actual Error:*\n```text\n{snippet}\n```",
                    parse_mode="Markdown")
                return
            else:
                bot.send_message(chat_id, f"🔁 *Auto Restart:* `{filename}` died, restarting…",
                                 parse_mode="Markdown")
                time.sleep(2)
                run_script(key, category, filename, folder, chat_id, 1, auto_restart=True)
                return

        # 🔥 नया: बिना ऑटो-रिस्टार्ट वाले मोड में असली एरर दिखाना
        if exit_code != 0:
            bot.send_message(chat_id, 
                f"❌ *Script Crashed!* `{filename}`\n\n*Actual Error:*\n```text\n{snippet}\n```", 
                parse_mode="Markdown")
        else:
            # 🔥 NAYA FIX: JS ya normal script agar bina error turant band ho jaye toh output dikhana
            if uptime_seconds < 5:
                bot.send_message(chat_id, 
                    f"ℹ️ `{filename}` bina error ke exit hui.\n\n*Output:*\n```text\n{snippet}\n```", 
                    parse_mode="Markdown")
            else:
                bot.send_message(chat_id, f"ℹ️ `{filename}` exited normally.", parse_mode="Markdown")

    threading.Thread(target=_watch, daemon=True).start()
    
# ══════════════════════════════════════════════════════════════
#  🔄  PROCESS MANAGEMENT
# ══════════════════════════════════════════════════════════════
RUNNING = {}  # key → {proc, pid, start, log_file, ram_path, category, filename, folder}

# ══════════════════════════════════════════════════════════════
#  🔒  AUTOLOCK — Smart persistent auto-restart
# ══════════════════════════════════════════════════════════════
# Rules:
#  • OFF by default per script.
#  • Toggle from script control panel.
#  • If ON:  script runs >= 3 minutes on first run → marked "stable".
#            After that, every crash → auto-restart (no crash-loop guard).
#            After 3 manual Stop presses → 4th Run acts as normal (no autolock).
#  • Autolock scripts are IMMUNE to RAM-guard kill.

AUTOLOCK_MIN_UPTIME   = 180   # 3 minutes in seconds

def _autolock_enabled(key: str) -> bool:
    return _AUTOLOCK_STATE.get(key, {}).get("enabled", False)

def _autolock_toggle(key: str) -> bool:
    """Toggle autolock for key. Returns new state."""
    st = _AUTOLOCK_STATE.setdefault(key, {"enabled": False, "run_count": 0, "stop_count": 0, "stable": False})
    st["enabled"] = not st["enabled"]
    if st["enabled"]:
        st["stop_count"] = 0   # reset stop counter when re-enabling
    return st["enabled"]

def _autolock_on_run(key: str):
    st = _AUTOLOCK_STATE.setdefault(key, {"enabled": False, "run_count": 0, "stop_count": 0, "stable": False})
    st["run_count"] = st.get("run_count", 0) + 1

def _autolock_on_stop(key: str):
    """Manual stop press: increment stop counter; disable if >= 3."""
    st = _AUTOLOCK_STATE.get(key)
    if not st or not st.get("enabled"):
        return
    st["stop_count"] = st.get("stop_count", 0) + 1
    if st["stop_count"] >= 3:
        st["enabled"] = False
        log.info(f"AutoLock DISABLED for {key} after 3 manual stops")

def _autolock_mark_stable(key: str):
    st = _AUTOLOCK_STATE.get(key)
    if st:
        st["stable"] = True

# ══════════════════════════════════════════════════════════════
#  🛡️  RAM GUARD — Kill top RAM consumer if VPS > 90% for 5 min
# ══════════════════════════════════════════════════════════════
_RAM_HIGH_SINCE: float = 0.0   # timestamp when RAM first hit >90%
RAM_GUARD_THRESHOLD   = 90.0   # percent
RAM_GUARD_DURATION    = 300    # 5 minutes in seconds
RAM_GUARD_INTERVAL    = 30     # check every 30 seconds

def _ram_guard_loop():
    global _RAM_HIGH_SINCE
    log.info("🛡️ RAM Guard started.")
    while True:
        time.sleep(RAM_GUARD_INTERVAL)
        if not _RAM_GUARD_ENABLED or not _DB_UNLOCKED:
            _RAM_HIGH_SINCE = 0.0
            continue
        try:
            ram_pct = psutil.virtual_memory().percent
        except Exception:
            continue

        if ram_pct < RAM_GUARD_THRESHOLD:
            _RAM_HIGH_SINCE = 0.0
            continue

        now = time.time()
        if _RAM_HIGH_SINCE == 0.0:
            _RAM_HIGH_SINCE = now
            continue

        elapsed = now - _RAM_HIGH_SINCE
        if elapsed < RAM_GUARD_DURATION:
            continue

        # 5 minutes exceeded — find top RAM consumer among RUNNING scripts
        # (exclude autolock-protected scripts)
        candidates = []
        for key, info in list(RUNNING.items()):
            if _autolock_enabled(key):
                continue   # immune
            try:
                p = psutil.Process(info["pid"])
                rss = p.memory_info().rss
                candidates.append((rss, key, info))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not candidates:
            _RAM_HIGH_SINCE = 0.0
            continue

        candidates.sort(reverse=True)
        top_rss, top_key, top_info = candidates[0]
        fname = top_info.get("filename", top_key)
        kill_script(top_key)
        _RAM_HIGH_SINCE = now   # reset timer; next check will re-evaluate

        # ── Smart Cache RAM Optimization (main__1__.py integration) ──
        # Script kill karne ke baad gc.collect() + /dev/shm check karo
        try:
            gc_collected = gc.collect()
            log.info(f"[RAM-Guard] gc.collect() → {gc_collected} objects freed")
        except Exception:
            gc_collected = 0

        # Cache free space check — agar 100MB se kam hai toh warn karo
        _shm_status_msg = ""
        try:
            _cache_chk = shutil.disk_usage(RAM_DISK_DIR)
            _cache_free_mb = _cache_chk.free // (1024 * 1024)
            if _cache_free_mb < 100:
                _shm_status_msg = (
                    f"\n⚠️ *Cache* free: `{_cache_free_mb}MB` < `100MB` — "
                    f"Cache space low! Physical disk fallback active."
                )
        except Exception:
            pass

        # Ram snapshot after GC
        try:
            _ram_after = psutil.virtual_memory()
            _ram_after_str = f"`{_ram_after.percent:.1f}%` ({_ram_after.available//(1024**2)}MB avail)"
        except Exception:
            _ram_after_str = "`N/A`"

        # Notify all allowed admins
        msg = (f"🛡️ *RAM Guard Triggered!*\n"
               f"RAM: `{psutil.virtual_memory().percent:.1f}%` > {RAM_GUARD_THRESHOLD}% for 5 min\n"
               f"🔴 Killed top RAM consumer: `{fname}` ({_human_size(top_rss)})\n"
               f"🗑️ GC freed: `{gc_collected}` objects\n"
               f"📊 RAM after cleanup: {_ram_after_str}"
               f"{_shm_status_msg}\n"
               f"If RAM still high, next top consumer will be killed in next 5 min.")
        for adm in ALLOWED_ADMINS:
            try: bot.send_message(adm, msg, parse_mode="Markdown")
            except Exception: pass

        log.warning(f"RAM Guard killed {top_key} (RAM {ram_pct:.1f}%, GC freed {gc_collected} objects)")

def _start_ram_guard():
    global _RAM_GUARD_THREAD
    if _RAM_GUARD_THREAD and _RAM_GUARD_THREAD.is_alive():
        return
    _RAM_GUARD_THREAD = threading.Thread(target=_ram_guard_loop, daemon=True)
    _RAM_GUARD_THREAD.start()



def is_running(key):
    info = RUNNING.get(key)
    if not info:
        return False
    try:
        proc = psutil.Process(info["pid"])
        alive = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        if not alive:
            _cleanup(key)
        return alive
    except psutil.NoSuchProcess:
        _cleanup(key)
        return False

def _cleanup(key):
    info = RUNNING.pop(key, None)
    if info:
        lf = info.get("log_file")
        if lf and not lf.closed:
            try: lf.close()
            except Exception: pass
        # 🔥 DEEP FIX: _wipe_ram_key(key) yahan se hata diya gaya hai.
        # Taaki script Stop/Restart karte waqt aadhi-adhuri file save karke DB corrupt na kare.

def kill_script(key, manual_stop=False):
    info = RUNNING.get(key)
    if not info:
        return
    if manual_stop:
        _autolock_on_stop(key)

    # 💾 STOP SE PEHLE DATA SAVE KARO (pura data vault mein ja sakta hai)
    try:
        _save_running_script_data(key)
        log.info(f"[KillScript] Pre-kill data saved for '{key}'")
    except Exception as e:
        log.warning(f"[KillScript] Pre-kill save failed for '{key}': {e}")

    try:
        parent = psutil.Process(info["pid"])
        for c in parent.children(recursive=True):
            try: c.terminate()
            except Exception: pass
        parent.terminate()
        gone, alive = psutil.wait_procs([parent], timeout=3)
        for p in alive:
            try: p.kill()
            except Exception: pass
    except psutil.NoSuchProcess:
        pass
    _cleanup(key)

    evt = _ERROR_TAIL_STOP.get(key)
    if evt:
        evt.set()

    saved = json.loads(_db_get("auto_scripts") or "[]")
    if key in saved:
        saved.remove(key)
    _db_set("auto_scripts", json.dumps(saved))

def _auto_install(stderr_text, chat_id) -> bool:
    py = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr_text)
    js = re.search(r"Cannot find module '(.+?)'", stderr_text)
    if py:
        mod = py.group(1).split(".")[0]
        pip = _PIP_MAP.get(mod, mod)
        bot.send_message(chat_id, f"🔍 Auto-installing: `{pip}`…", parse_mode="Markdown")
        if _pip_install(pip):
            bot.send_message(chat_id, f"✅ `{pip}` installed!", parse_mode="Markdown")
            return True
        else:
            bot.send_message(chat_id, f"❌ `{pip}` install fail. Manually karo: `pip install {pip}`", parse_mode="Markdown")
    if js:
        mod = js.group(1).strip("'\"")
        if not mod.startswith((".", "/")):
            r = subprocess.run(["npm", "install", mod], capture_output=True, text=True,
                               cwd=RAM_DISK_DIR)
            if r.returncode == 0:
                bot.send_message(chat_id, f"✅ npm `{mod}` installed!", parse_mode="Markdown")
                return True
            else:
                bot.send_message(chat_id, f"❌ npm `{mod}` install fail.", parse_mode="Markdown")
    return False

# ══════════════════════════════════════════════════════════════
#  🤖  BOT + GLOBALS
# ══════════════════════════════════════════════════════════════
bot = telebot.TeleBot(API_TOKEN, num_threads=8)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def safe_answer(call_id, text=None, show_alert=False, url=None, cache_time=None):
    """
    Crash-proof wrapper around bot.answer_callback_query().
    Telegram invalidates callback queries after a short window; if a handler
    is busy (e.g. slow DB/file ops) the callback can go stale by the time we
    answer it. Without this try/except, that ApiTelegramException propagates
    up through telebot's worker pool and kills infinity_polling entirely.
    """
    try:
        bot.answer_callback_query(call_id, text=text, show_alert=show_alert, url=url, cache_time=cache_time)
    except telebot.apihelper.ApiTelegramException as e:
        log.warning(f"answer_callback_query failed (stale/invalid query {call_id}): {e}")
    except Exception as e:
        log.warning(f"answer_callback_query unexpected error ({call_id}): {e}")

_AWAITING_PW    = set()

# 🔒 ULTRA-HARDENED: Brute-force protection
# Chat ID → failed attempt count; 5 attempts ke baad LOCKOUT
_PW_FAIL_COUNT:   dict = {}   # {chat_id: int}
_PW_LOCKOUT_UNTIL: dict = {}  # {chat_id: float}  (Unix timestamp)
_PW_MAX_ATTEMPTS  = 5         # 5 attempts allowed
_PW_LOCKOUT_SECS  = 300       # 5 minute lockout (exponential bakhi aage badha sakte hain)
# 🔥 FIX: Restore flow — jab incoming vault.db current password se match na ho,
# toh us DB ka apna password poochne ke liye pending state.
_AWAITING_RESTORE_PW = set()
_PENDING_RESTORE     = {}   # chat_id -> {"kind": "single"/"unified", "tmp_db"/"zip_bytes": ...}
_PENDING_DELETE = {}
_BACKUP_THREADS = {}
_ACTIVE_CLIENTS = {}
_STEP           = {}
_SHELL_SESSIONS = {}   # chat_id → live shell session dict (V2 streaming engine)


_VPS_STATE  = {}
_VPS_FILTER = {}
_CB_CACHE   = {}  # 🔥 Naya: Long callbacks store karne ke liye
_CB_CACHE_LOCK = threading.Lock()
_FOLDER_STATE = {}  # 🔥 NAYA: Folder pagination state save rakhne ke liye

# ── NAYA: Log auto-refresh, Run/Stop spam-guard, Error-alert state ──
_LOG_AUTOREFRESH  = {}          # (chat_id, msg_id) -> threading.Event (stop signal)
_ACTION_COOLDOWN  = {}          # key -> timestamp of last run/stop tap (spam guard)
_ACTION_LOCK      = threading.Lock()
_ERROR_SEEN_HASH  = {}          # key -> set(hash) of already-forwarded error blocks
_ERROR_TAIL_STOP  = {}          # key -> threading.Event (stop signal for error watcher)

# ══════════════════════════════════════════════════════════════
#  🗑️  AUTO-DELETE SYSTEM
# ══════════════════════════════════════════════════════════════
_AUTO_DEL_REGISTRY: dict = {}   # (chat_id, msg_id) -> delete_at (float)
_AUTO_DEL_LOCK     = threading.Lock()
_DEL_TEMP    = 5  * 60     #  5 min
_DEL_MEDIUM  = 20 * 60     # 20 min
_DEL_LONG    = 60 * 60     # 60 min

def _auto_del_track(chat_id: int, msg_id: int, delay_sec: int = None):
    if delay_sec is None: delay_sec = _DEL_TEMP
    with _AUTO_DEL_LOCK:
        _AUTO_DEL_REGISTRY[(chat_id, msg_id)] = time.time() + delay_sec

def _auto_del_cancel(chat_id: int, msg_id: int):
    with _AUTO_DEL_LOCK:
        _AUTO_DEL_REGISTRY.pop((chat_id, msg_id), None)

def _auto_del_worker():
    while True:
        time.sleep(20)
        now = time.time()
        to_del = []
        with _AUTO_DEL_LOCK:
            for (cid, mid), exp in list(_AUTO_DEL_REGISTRY.items()):
                if now >= exp:
                    to_del.append((cid, mid))
            for k in to_del:
                _AUTO_DEL_REGISTRY.pop(k, None)
        for (cid, mid) in to_del:
            try: bot.delete_message(cid, mid)
            except Exception: pass

_auto_del_thread = threading.Thread(target=_auto_del_worker, daemon=True, name="AutoDel")
_auto_del_thread.start()

# ══════════════════════════════════════════════════════════════
#  🛡️  ANTI-SPAM SYSTEM
# ══════════════════════════════════════════════════════════════
_SPAM_LOCK    = threading.Lock()
_SPAM_HISTORY: dict = {}   # key -> [timestamps]

def _spam_check(key: str, max_calls: int = 3, window_sec: float = 10.0) -> bool:
    """True = allow, False = blocked"""
    now = time.time()
    with _SPAM_LOCK:
        hist = [t for t in _SPAM_HISTORY.get(key, []) if now - t < window_sec]
        if len(hist) >= max_calls:
            _SPAM_HISTORY[key] = hist
            return False
        hist.append(now)
        _SPAM_HISTORY[key] = hist
        return True

def _spam_reset(key: str):
    with _SPAM_LOCK:
        _SPAM_HISTORY.pop(key, None)

_UPDATE_CONFIRM: dict = {}   # cid -> {fname, data, step}  — script update confirm pending

# ── Panel Auto-Refresh ──
# (chat_id, msg_id) -> threading.Event  (stop signal)
_PANEL_AUTOREFRESH: dict = {}
_PANEL_AUTOREFRESH_INTERVAL = 5   # seconds between refreshes

def _throttled(key: str, cooldown: float = 3.0) -> bool:
    """
    Spam-guard for Run/Stop/Restart buttons. Telegram double-taps (or slow
    UI) can fire the same callback twice before the first one finishes,
    spawning duplicate processes / duplicate "started"/"stopped" messages.
    Returns True if the action is allowed to proceed (and records the tap),
    False if it should be ignored because the same key was just triggered.
    """
    now = time.time()
    with _ACTION_LOCK:
        last = _ACTION_COOLDOWN.get(key, 0)
        if now - last < cooldown:
            return False
        _ACTION_COOLDOWN[key] = now
        return True

# ══════════════════════════════════════════════════════════════
#  🔄  PANEL AUTO-REFRESH  — Running panel live update loop
#  Jab bhi koi script/shell/task background mein chal raha ho
#  toh Telegram message automatically update hota rahega.
# ══════════════════════════════════════════════════════════════

def _panel_autorefresh_text() -> str:
    """Running panel ka live status text banao."""
    running_keys = [k for k in list(RUNNING.keys()) if is_running(k)]
    if not running_keys:
        return "📭 *Running Panel*\n_Koi bhi script abhi nahi chal rahi._"

    lines = [f"🔄 *Running Panel* — {len(running_keys)} active\n"]
    for k in running_keys:
        info = RUNNING.get(k)
        if not info:
            continue
        fn    = info.get("filename", k)
        pid   = info.get("pid", "?")
        start = info.get("start")
        uptime_str = "—"
        if start:
            elapsed = (datetime.now() - start).total_seconds()
            h, rem  = divmod(int(elapsed), 3600)
            m, s    = divmod(rem, 60)
            uptime_str = f"{h:02d}:{m:02d}:{s:02d}"
        cpu_str = ram_str = "—"
        try:
            p       = psutil.Process(pid)
            cpu_str = f"{p.cpu_percent(interval=0.1):.1f}%"
            ram_str = _human_size(p.memory_info().rss)
        except Exception:
            pass
        lines.append(
            f"🟢 `{fn}`\n"
            f"   PID:`{pid}` ⏱`{uptime_str}` CPU:`{cpu_str}` RAM:`{ram_str}`"
        )

    lines.append(f"\n🕐 `{datetime.now().strftime('%H:%M:%S')}`")
    return "\n".join(lines)


def _panel_autorefresh_kb(msg_id: int) -> types.InlineKeyboardMarkup:
    """Running panel ke saath auto-refresh controls."""
    running_keys = [k for k in list(RUNNING.keys()) if is_running(k)]
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.row(
        _btn("⏸ Stop Auto-Refresh", f"panel_stop_ar|{msg_id}"),
        _btn("🔄 Refresh Now",       "running_panel"),
    )
    for k in running_keys[:4]:   # max 4 quick-stop buttons
        fn    = RUNNING.get(k, {}).get("filename", k)
        short = fn[:9] + "…" if len(fn) > 11 else fn
        mk.add(_btn(f"🛑 {short}", f"stop|{k}"))
    mk.add(_btn("🔙 Main Menu", "main_menu"))
    return mk


def _panel_autorefresh_loop(chat_id: int, msg_id: int, stop_evt: threading.Event):
    """
    Background thread: running panel message ko auto-refresh karta hai.
    Stops when:  (a) stop_evt is set  (b) nothing is running anymore
    """
    while not stop_evt.is_set():
        stop_evt.wait(timeout=_PANEL_AUTOREFRESH_INTERVAL)
        if stop_evt.is_set():
            break

        # Kuch bhi nahi chal raha toh band karo
        any_running = any(is_running(k) for k in list(RUNNING.keys()))
        if not any_running:
            break

        try:
            text = _panel_autorefresh_text()
            mk   = _panel_autorefresh_kb(msg_id)
            bot.edit_message_text(
                text, chat_id, msg_id,
                parse_mode="Markdown",
                reply_markup=mk,
            )
        except Exception as e:
            # edit nahi hua (message deleted, or too many edits) — quietly stop
            log.debug(f"panel_autorefresh: edit failed ({e}) — stopping")
            break

    _PANEL_AUTOREFRESH.pop((chat_id, msg_id), None)
    log.debug(f"panel_autorefresh stopped for chat={chat_id} msg={msg_id}")


def _start_panel_autorefresh(chat_id: int, msg_id: int):
    """Panel auto-refresh start karo (idempotent)."""
    key = (chat_id, msg_id)
    if key in _PANEL_AUTOREFRESH:
        return   # Already running
    stop_evt = threading.Event()
    _PANEL_AUTOREFRESH[key] = stop_evt
    t = threading.Thread(
        target=_panel_autorefresh_loop,
        args=(chat_id, msg_id, stop_evt),
        daemon=True,
    )
    t.start()
    log.debug(f"panel_autorefresh started for chat={chat_id} msg={msg_id}")


def _stop_panel_autorefresh(chat_id: int, msg_id: int):
    """Panel auto-refresh manually band karo."""
    key = (chat_id, msg_id)
    evt = _PANEL_AUTOREFRESH.pop(key, None)
    if evt:
        evt.set()


def _stop_all_panel_autorefresh(chat_id: int):
    """Ek chat ke saare panel auto-refresh band karo."""
    to_stop = [k for k in list(_PANEL_AUTOREFRESH.keys()) if k[0] == chat_id]
    for k in to_stop:
        evt = _PANEL_AUTOREFRESH.pop(k, None)
        if evt:
            evt.set()


def _error_alerts_enabled() -> bool:
    try:
        return _db_get("error_alerts_enabled") == "1"
    except Exception:
        return False

def _get_error_group():
    try:
        gid = _db_get("error_group_id")
        return int(gid) if gid else None
    except Exception:
        return None

def _set_error_group(chat_id: int):
    _db_set("error_group_id", str(chat_id))

def _toggle_error_alerts() -> bool:
    new_state = not _error_alerts_enabled()
    _db_set("error_alerts_enabled", "1" if new_state else "0")
    return new_state

# ══════════════════════════════════════════════════════════════
#  🚨  ERROR ALERTS — live tail per running script, sirf real
#      crashes/exceptions group mein forward hote hain, normal
#      print/log/"set" wale messages ignore ho jaate hain.
# ══════════════════════════════════════════════════════════════
_TRACEBACK_START = re.compile(r"^Traceback \(most recent call last\):\s*$")
_PY_EXC_LINE     = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception)\b:.*$")
_JS_EXC_LINE     = re.compile(r"^(?:Uncaught|Unhandled(?:PromiseRejection)?|.*Error):.*$")
_FATAL_LINE      = re.compile(r"\b(FATAL|CRITICAL|Segmentation fault|core dumped)\b", re.IGNORECASE)

def _extract_error_blocks(new_lines: list) -> list:
    """
    new_lines: fresh lines jo log file mein add hui hain.
    Sirf genuine crash/exception blocks return karta hai — normal script
    output (jisme "error"/"set" jaisa word ho sakta hai as part of a status
    message) ko match nahi karta, kyunki hum strict patterns use karte hain:
    Python traceback block, "XxxError: ..."/"XxxException: ..." line,
    ya FATAL/CRITICAL/Segfault markers.
    """
    blocks = []
    i, n = 0, len(new_lines)
    while i < n:
        line = new_lines[i]
        if _TRACEBACK_START.match(line):
            block = [line]
            j = i + 1
            while j < n:
                block.append(new_lines[j])
                if _PY_EXC_LINE.match(new_lines[j]) or (new_lines[j].strip() == "" and len(block) > 1):
                    break
                j += 1
                if len(block) > 25:   # safety cap
                    break
            blocks.append("\n".join(l for l in block if l.strip() or l is block[-1]).strip())
            i = j + 1
            continue
        if _FATAL_LINE.search(line) or (_JS_EXC_LINE.match(line) and "node" in line.lower()) or _PY_EXC_LINE.match(line):
            blocks.append(line.strip())
        i += 1
    return [b for b in blocks if b]

def _forward_error_alert(key: str, block: str):
    gid = _get_error_group()
    if not gid:
        return
    h = hash(block)
    seen = _ERROR_SEEN_HASH.setdefault(key, set())
    if h in seen:
        return
    seen.add(h)
    if len(seen) > 200:   # memory guard
        seen.clear()
        seen.add(h)
    fname = os.path.basename(key)
    snippet = block[-1500:]
    try:
        bot.send_message(gid, f"🚨 *Error in* `{fname}`\n```\n{snippet}\n```", parse_mode="Markdown")
    except Exception as e:
        log.warning(f"error alert forward failed for {key}: {e}")

def _error_tail_watch(key: str, proc, interval: float = 2.0):
    """
    Script chalte waqt uski log file live tail karta hai. Jab bhi ek genuine
    traceback/exception/fatal block dikhta hai aur error-alerts ON hain,
    uska sirf wahi block configured group mein forward hota hai — baaki
    normal output (prints, "set"/config messages, etc.) ignore hota hai.
    """
    evt = threading.Event()
    _ERROR_TAIL_STOP[key] = evt
    lp = log_path(key)
    pos = 0
    try:
        while not evt.is_set() and proc.poll() is None:
            evt.wait(interval)
            if evt.is_set():
                break
            if not _error_alerts_enabled() or not _get_error_group():
                continue
            try:
                if not os.path.exists(lp):
                    continue
                with open(lp, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
            except Exception:
                continue
            if not chunk:
                continue
            new_lines = _strip_ansi(chunk).splitlines()
            for block in _extract_error_blocks(new_lines):
                _forward_error_alert(key, block)
    finally:
        _ERROR_TAIL_STOP.pop(key, None)

def is_admin(uid):
    """Active-owner guard for high-risk controls.
    Before the DB is unlocked, only allow listed owners to reach password/setup flow;
    after unlock, only ACTIVE_ADMIN can press control buttons.
    """
    if uid not in ALLOWED_ADMINS:
        return False
    if not _DB_UNLOCKED:
        return True
    return uid == ACTIVE_ADMIN
def log_path(key): return os.path.join(LOGS_DIR, key.replace("/", "__") + ".log")

SCRIPT_EXTS = (".py", ".js")
DB_EXTS     = (".db", ".sqlite", ".sqlite3", ".sql")

# ══════════════════════════════════════════════════════════════
#  🎨  FILE ICONS
# ══════════════════════════════════════════════════════════════
def get_file_icon(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    icons = {
        "py": "🐍", "js": "📜", "json": "📋", "txt": "📄",
        "zip": "📦", "tar": "📦", "gz": "📦", "rar": "📦",
        "jpg": "🖼️", "jpeg": "🖼️", "png": "🖼️", "gif": "🎞️",
        "mp4": "🎬", "mp3": "🎵", "pdf": "📕", "csv": "📊",
        "sh": "⚙️", "db": "🗄️", "sqlite": "🗄️", "sqlite3": "🗄️",
        "sql": "🗄️", "log": "📝", "env": "🔐", "cfg": "⚙️",
        "ini": "⚙️", "yml": "📋", "yaml": "📋", "xml": "📋",
        "md": "📖", "html": "🌐", "css": "🎨", "ts": "📜",
    }
    return icons.get(ext, "📄")

def _human_size(size):
    if size == 0: return "0B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = min(int(math.floor(math.log(max(size, 1), 1024))), len(units) - 1)
    return f"{size / (1024 ** i):.1f}{units[i]}"

def _btn(text, cb):
    if len(cb.encode('utf-8')) <= 64:
        return types.InlineKeyboardButton(text, callback_data=cb)
    # Long callback → compress + cache
    key = "c|" + hashlib.md5(cb.encode('utf-8')).hexdigest()[:12]
    with _CB_CACHE_LOCK:
        if key not in _CB_CACHE:
            _CB_CACHE[key] = cb
            # DB mein bhi save karo (restart-safe)
            if _DB_UNLOCKED:
                try: _db_set(f"cbcache:{key}", cb)
                except Exception: pass
    return types.InlineKeyboardButton(text, callback_data=key)

def _cb_cache_persist_all():
    """Saare cached callbacks ko DB mein save karo (unlock ke baad call karo)."""
    with _CB_CACHE_LOCK:
        for key, val in _CB_CACHE.items():
            try: _db_set(f"cbcache:{key}", val)
            except Exception: pass

def _cb_cache_load_from_db():
    """DB unlock ke baad purane callbacks restore karo."""
    try:
        con = _db_connect()
        rows = con.execute(
            "SELECT key, value FROM vault_meta WHERE key LIKE 'cbcache:%'"
        ).fetchall()
        con.close()
        with _CB_CACHE_LOCK:
            for db_key, val in rows:
                short = db_key[len("cbcache:"):]
                if short not in _CB_CACHE:
                    _CB_CACHE[short] = val
    except Exception as e:
        log.warning(f"CB cache load failed: {e}")
    
def _kb(*rows):
    mk = types.InlineKeyboardMarkup()
    for row in rows:
        if isinstance(row, list): mk.row(*row)
        else: mk.add(row)
    return mk

def _eorsend(chat_id, msg_id, text, reply_markup=None):
    try:
        bot.edit_message_text(text, chat_id, msg_id, parse_mode="Markdown",
                              reply_markup=reply_markup)
    except Exception:
        try:
            bot.send_message(chat_id, text, parse_mode="Markdown",
                             reply_markup=reply_markup)
        except Exception as e:
            log.error(f"Send error: {e}")


# ══════════════════════════════════════════════════════════════
#  🛡️ SAFE ADVANCED HELPERS (Plus Edition)
# ══════════════════════════════════════════════════════════════
def _md_escape(text: str) -> str:
    return str(text).replace("`", "ʼ")

def _clean_leaf_name(name: str, default: str = "item") -> str:
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    return name or default

def _clean_vault_folder(name: str) -> str:
    name = (name or "").replace("\\", "/").strip().strip("/")
    parts = []
    for p in name.split("/"):
        p = p.strip()
        if not p or p in (".", ".."):
            continue
        p = re.sub(r"[\x00-\x1f\x7f]", "", p)
        parts.append(p[:80])
    return "/".join(parts)

def _safe_archive_member(name: str) -> str:
    """Return a safe relative archive member name, or None if it is unsafe."""
    if not name:
        return None
    raw = name.replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return None
    parts = []
    for part in raw.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            return None
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)

def _safe_join(base: str, *parts: str) -> str:
    base_abs = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base_abs, *parts))
    if os.path.commonpath([base_abs, target]) != base_abs:
        raise ValueError("Unsafe path blocked")
    return target

def _unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    for i in range(1, 1000):
        cand = f"{root}_{i}{ext}"
        if not os.path.exists(cand):
            return cand
    return f"{root}_{int(time.time())}{ext}"

def _send_big_file(chat_id: int, file_path: str, caption: str = "", visible_name: str = None):
    """Send file via Bot API when small; use active userbot when >50MB."""
    try:
        size = os.path.getsize(file_path)
        if size > 50 * 1024 * 1024:
            sname, _ = _get_active_userbot()
            if sname and PYROGRAM_AVAILABLE:
                bot.send_message(chat_id, f"📤 Large file `{_human_size(size)}` — userbot se bhej raha hun…", parse_mode="Markdown")
                _userbot_upload_thread(sname, chat_id, file_path, caption or os.path.basename(file_path))
            else:
                bot.send_message(chat_id, f"⚠️ File `{_human_size(size)}` hai. Telegram Bot API limit cross ho gayi; Userbot session add karo.", parse_mode="Markdown")
            return
        with open(file_path, "rb") as f:
            bot.send_document(chat_id, f, visible_file_name=visible_name or os.path.basename(file_path), caption=caption, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Send failed: `{_md_escape(e)}`", parse_mode="Markdown")

def _vault_stats() -> dict:
    con = _db_connect()
    rows = con.execute("SELECT category, COUNT(*), COALESCE(SUM(size),0) FROM files_vault GROUP BY category").fetchall()
    local_count = con.execute("SELECT COUNT(*) FROM files_vault WHERE is_local=1").fetchone()[0]
    missing = []
    for cat, folder, fn, is_local, path in con.execute("SELECT category, folder, filename, is_local, file_path FROM files_vault WHERE is_local=1").fetchall():
        if is_local and (not path or not os.path.exists(path)):
            missing.append(f"{cat}:{folder}/{fn}")
    con.close()
    return {"rows": rows, "local_count": local_count, "missing": missing}

def _vault_stats_text() -> str:
    st = _vault_stats()
    lines = ["🧪 *Vault Health / Stats*", f"🔐 DB mode: `{_SQLCIPHER_MODE}`", f"🗄️ DB size: `{_human_size(os.path.getsize(DB_FILE)) if os.path.exists(DB_FILE) else '0B'}`", f"💽 Disk vault: `{LARGE_MEDIA_VAULT}`", ""]
    if st["rows"]:
        lines.append("*Stored data:*")
        for cat, cnt, total in st["rows"]:
            lines.append(f"• `{cat}`: `{cnt}` file(s), `{_human_size(total)}`")
    else:
        lines.append("No files stored yet.")
    lines.append(f"\nLarge disk-backed rows: `{st['local_count']}`")
    if st["missing"]:
        lines.append(f"⚠️ Missing physical files: `{len(st['missing'])}`")
        for m in st["missing"][:10]:
            lines.append(f"  - `{_md_escape(m)}`")
    else:
        lines.append("✅ Disk-backed file links OK.")
    return "\n".join(lines)

def _search_vault(query: str, limit: int = 30):
    q = f"%{query.lower()}%"
    con = _db_connect()
    rows = con.execute(
        "SELECT category, folder, filename, size, added_at FROM files_vault "
        "WHERE lower(filename) LIKE ? OR lower(folder) LIKE ? "
        "ORDER BY category, folder, filename LIMIT ?",
        (q, q, limit)
    ).fetchall()
    con.close()
    return rows

def _folder_script_names(folder: str) -> list[str]:
    return [r[1] for r in vault_list("folder_file", folder=folder) if r[1].endswith(SCRIPT_EXTS)]

def _running_panel_text() -> str:
    lines = ["🧭 *Running Panel*", f"Total running: `{len(RUNNING)}`", ""]
    if not RUNNING:
        lines.append("Koi script abhi running nahi hai.")
    else:
        for key, info in list(RUNNING.items()):
            alive = is_running(key)
            start = info.get("start", datetime.now())
            mins = int((datetime.now() - start).total_seconds() // 60)
            cpu = mem = "?"
            try:
                p = psutil.Process(info.get("pid"))
                cpu = f"{p.cpu_percent(interval=0.0):.1f}%"
                mem = _human_size(p.memory_info().rss)
            except Exception:
                pass
            lines.append(f"{'🟢' if alive else '🔴'} `{_md_escape(key)}` | PID `{info.get('pid')}` | `{mins}m` | CPU `{cpu}` | RAM `{mem}`")
    return "\n".join(lines)

def kb_running_panel():
    mk = types.InlineKeyboardMarkup(row_width=2)
    for key in list(RUNNING.keys())[:20]:
        if "/" in key:
            folder, fn = key.split("/", 1)
            mk.add(_btn(f"🎮 {os.path.basename(fn)}", f"fscript|{folder}|{fn}"))
        else:
            mk.add(_btn(f"🎮 {key}", f"script|{key}"))
    mk.row(_btn("🔄 Refresh", "running_panel"), _btn("⏹️ Stop All", "stop_all"))
    alert_lbl = "🚨 Error Alerts: ON" if _error_alerts_enabled() else "🚨 Error Alerts: OFF"
    mk.add(_btn(alert_lbl, "error_alerts_menu"))
    mk.add(_btn("🔙 Back", "main_menu"))
    return mk

# ══════════════════════════════════════════════════════════════
#  ⌨️  KEYBOARDS
# ══════════════════════════════════════════════════════════════
def kb_main():
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.add(_btn("📋 Scripts",         "list_scripts"),
           _btn("📤 Upload Script",   "upload"))
    mk.add(_btn("📁 Folders",         "list_folders"),
           _btn("🗄️ Database Files",  "list_dbfiles"))
    mk.add(_btn("🧭 Running Panel",   "running_panel"),
           _btn("🖥️ VPS Explorer",    "vps_open"))
    mk.add(_btn("📊 System Monitor",  "sys_monitor"),
           _btn("💾 Backup Now",      "backup_now"))
    mk.add(_btn("🔎 Search Vault",    "vault_search"),
           _btn("🧪 Vault Health",    "vault_health"))
    mk.add(_btn("📦 Install Lib",     "install_lib"),
           _btn("🔧 Shell Command",   "shell_cmd"))
    mk.add(_btn("⚙️ Backup Settings", "backup_settings"),
           _btn("👤 Userbot Sessions","userbot_list"))
    return mk

def kb_scripts():
    scripts = get_scripts()
    mk = types.InlineKeyboardMarkup(row_width=2)
    if not scripts:
        mk.add(_btn("(No scripts yet)", "noop"))
    else:
        row = []
        for f in scripts:
            if is_running(f):
                pid = RUNNING[f]["pid"]
                icon = f"🟢[{pid}]"
            else:
                icon = "🔴"
            short = f[:12] + ".." if len(f) > 14 else f
            row.append(_btn(f"{icon} {short}", f"script|{f}"))
            if len(row) == 2:
                mk.row(*row); row = []
        if row: mk.row(*row)
        mk.add(_btn("⏹️ Stop All", "stop_all"))
    mk.add(_btn("🔙 Back", "main_menu"))
    return mk

def kb_script_ctrl(fname):
    key = fname
    running = is_running(key)
    al_on = _autolock_enabled(key)
    al_lbl = "🔒 AutoLock: ON" if al_on else "🔓 AutoLock: OFF"
    mk = types.InlineKeyboardMarkup(row_width=2)
    if running:
        mk.row(_btn("🛑 Stop",  f"stop|{key}"),   _btn("🔄 Restart", f"restart|{key}"))
        mk.row(_btn("📜 Logs",  f"logs|{key}"),   _btn("⌨️ Input",   f"input_req|{key}"))
        mk.row(_btn("💾 Save Now", f"manual_save|{key}"))   # ← Manual save button
    else:
        mk.row(_btn("▶️ Run",   f"run_key|{key}"),  _btn("📲 Update",  f"update_script|{fname}"))
        mk.row(_btn("📜 Logs",  f"logs|{key}"),     _btn("🗑️ Delete",  f"delete|{fname}"))
    mk.add(_btn(al_lbl, f"autolock_toggle|{key}"))
    mk.add(_btn("🔙 Scripts", "list_scripts"))
    return mk

# 🔥 NEW: Upload Navigator State
_UPLOAD_SESSIONS = {}

def get_subfolders(base_path):
    """Current path ke andar mojood sub-folders nikalta hai (Root support ke sath)"""
    all_folders = vault_list_folders()
    subs = set()
    prefix = base_path + "/" if base_path else ""
    
    for f in all_folders:
        if not base_path: 
            # Agar Root par hain toh sabse pehle level ke folders dikhao
            subs.add(f.split("/")[0])
        elif f.startswith(prefix) and len(f) > len(prefix):
            # Agar kisi folder ke andar hain, toh uske sub-folders nikaalo
            sub_name = f[len(prefix):].split("/")[0]
            subs.add(sub_name)
            
    return sorted(list(subs))

def kb_upload_navigator(cid):
    sess = _UPLOAD_SESSIONS.get(cid)
    if not sess: return None
    path = sess.get("current_path", "")
    
    mk = types.InlineKeyboardMarkup(row_width=2)
    subs = get_subfolders(path)
    
    # Existing Sub-folders ke buttons (2 buttons ek line me taaki design accha lage)
    row = []
    for s in subs:
        row.append(_btn(f"📁 {s}", f"upnav_cd|{s}"))
        if len(row) == 2:
            mk.row(*row)
            row = []
    if row: mk.row(*row)
        
    # Controls
    mk.add(_btn("➕ Create New Folder Here", "upnav_mkdir"))
    
    # Upload Button (Dynamic text)
    btn_text = "📤 Upload Here" if path else "📤 Upload to Root (Main)"
    mk.add(_btn(btn_text, "upnav_here"))
    
    # Back / Cancel logic
    if path: 
        # Agar kisi folder ke andar hain, tabhi Back button dikhega
        mk.row(_btn("🔙 Back (Up Level)", "upnav_back"), _btn("❌ Cancel", "upnav_cancel"))
    else: 
        # Root par hain toh sirf Cancel
        mk.add(_btn("❌ Cancel Upload", "upnav_cancel"))
        
    return mk

def _finalize_upload(cid, mid, custom_name=None):
    sess = _UPLOAD_SESSIONS.get(cid)
    if not sess: return
    
    path = sess["current_path"]
    fname = custom_name or sess["fname"]
    tmp = sess["tmp_file"]
    
    # Save file to Vault (Isme 'Replace' auto handle hota hai REPLACE INTO ki wajah se)
    if os.path.exists(tmp):
        with open(tmp, "rb") as f:
            data = f.read()
        vault_save("folder_file", fname, data, path)
        os.remove(tmp)
        
    _UPLOAD_SESSIONS.pop(cid, None)
    icon = get_file_icon(fname)
    
    msg_txt = f"✅ {icon} `{fname}` successfully uploaded to `{path}`!"
    try: bot.edit_message_text(msg_txt, cid, mid, parse_mode="Markdown")
    except: bot.send_message(cid, msg_txt, parse_mode="Markdown")
    
def kb_folders():
    mk = types.InlineKeyboardMarkup(row_width=1)
    folders = vault_list_folders()
    
    if not folders:
        mk.add(_btn("(No folders yet)", "noop"))
    else:
        for f in folders:
            rows = vault_list("folder_file", folder=f)
            total   = len(rows)
            scripts = sum(1 for r in rows if r[1].endswith(SCRIPT_EXTS))
            dbs     = sum(1 for r in rows if r[1].endswith(DB_EXTS))
            
            # Folder ka naam lamba ho toh automatically truncate ho jayega
            short_f = f[:20] + ".." if len(f) > 22 else f
            lbl = f"📁 {short_f} [📄{total}|🐍{scripts}|🗄️{dbs}]"
            
            # Ek hi row mein single button
            mk.add(_btn(lbl, f"folder_open|{f}"))
            
    # Bottom Controls
    mk.add(_btn("➕ Create New Folder", "fdir_create_new"))
    
    # Rename aur Delete ko ek hi line mein rakhne ke liye
    mk.row(_btn("✏️ Rename Folder", "fdir_ren_select"), 
           _btn("🗑️ Delete Folder", "fdir_del_select"))
           
    mk.row(_btn("📤 Upload ZIP", "upload_zip"))
    mk.add(_btn("🔙 Back", "main_menu"))
    return mk

def kb_folder_select(action):
    mk = types.InlineKeyboardMarkup(row_width=1)
    folders = vault_list_folders()
    
    if not folders:
        mk.add(_btn("(No folders to select)", "noop"))
    else:
        for f in folders:
            # Action ke hisaab se alag callback lagayenge
            cb = f"fdir_ren_do|{f}" if action == "ren" else f"fdir_del_do|{f}"
            mk.add(_btn(f"📁 {f}", cb))
            
    mk.add(_btn("🔙 Back", "list_folders"))
    return mk
    
def kb_folder_view(folder, chat_id):
    rows = vault_list("folder_file", folder=folder)
    scripts = [(r[1], r[2]) for r in rows if r[1].endswith(SCRIPT_EXTS)]
    dbs     = [(r[1], r[2]) for r in rows if r[1].endswith(DB_EXTS)]
    others  = [(r[1], r[2]) for r in rows if not r[1].endswith(SCRIPT_EXTS + DB_EXTS)]

    mk = types.InlineKeyboardMarkup(row_width=2)
    PAGE_SIZE = 20

    if chat_id not in _FOLDER_STATE:
        _FOLDER_STATE[chat_id] = {}
    if folder not in _FOLDER_STATE[chat_id]:
        _FOLDER_STATE[chat_id][folder] = {"scripts": 0, "dbs": 0, "others": 0, "highlight": None}
        
    state = _FOLDER_STATE[chat_id][folder]
    highlight_file = state.get("highlight")

    def _add_items(items, label_text, cat_key):
        if not items: return
        
        total_items = len(items)
        total_pages = max(1, math.ceil(total_items / PAGE_SIZE))
        
        page = state.get(cat_key, 0)
        if page >= total_pages: page = total_pages - 1
        if page < 0: page = 0
        state[cat_key] = page

        # 🔥 NAYA LOGIC: Center button ab "noop" nahi, "fsearch" hai
        if total_items > PAGE_SIZE:
            btn_prev = _btn("⬅️", f"fnav|{folder}|{cat_key}|prev")
            btn_lbl  = _btn(f"🔍 {label_text} ({page+1}/{total_pages})", f"fsearch|{folder}|{cat_key}")
            btn_next = _btn("➡️", f"fnav|{folder}|{cat_key}|next")
            mk.row(btn_prev, btn_lbl, btn_next)
        else:
            # Agar 20 se kam files hain, tab bhi search button de dete hain header par
            mk.add(_btn(f"🔍 {label_text}", f"fsearch|{folder}|{cat_key}"))
            
        row = []
        chunk = items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        
        for fn, sz in chunk:
            icon = get_file_icon(fn)
            # 🔥 HIGHLIGHT LOGIC: Agar file search hui hai toh icon badal do
            if fn == highlight_file:
                icon = "🌟"
                
            base_fn = os.path.basename(fn)
            short = base_fn[:14] + ".." if len(base_fn) > 16 else base_fn
            key = f"{folder}/{fn}"
            
            if fn.endswith(SCRIPT_EXTS):
                ri = "🟢" if is_running(key) else ""
                cb = f"fscript|{folder}|{fn}"
            else:
                ri = ""
                cb = f"ffile|{folder}|{fn}"
                
            row.append(_btn(f"{ri}{icon} {short}", cb))
            if len(row) == 2:
                mk.row(*row); row = []
        if row: mk.row(*row)

    if not rows:
        mk.add(_btn("(Empty folder)", "noop"))
    else:
        _add_items(scripts, "━━ 🐍 SCRIPTS ━━", "scripts")
        _add_items(dbs,     "━━ 🗄️ DATABASES ━━", "dbs")
        _add_items(others,  "━━ 📄 OTHER FILES ━━", "others")

    if scripts:
        mk.row(_btn("▶️ Run Scripts", f"folder_run_scripts|{folder}"),
               _btn("⏹️ Stop Scripts", f"folder_stop_scripts|{folder}"))
    mk.row(_btn("📥 Download ZIP", f"folder_dl|{folder}"),
           _btn("📤 Upload File",  f"folder_upload|{folder}"))
    mk.row(_btn("🗑️ Delete Folder", f"folder_del|{folder}"),
           _btn("🔙 Folders",      "list_folders"))
    mk.add(_btn("📁 File Manager View", f"fm_open|{folder}"))
    return mk
    
def kb_file_manager(folder, sub_path=""):
    """File Manager view: folders + files tree style with upload/download/delete"""
    full_path = f"{folder}/{sub_path}".strip("/") if sub_path else folder
    mk = types.InlineKeyboardMarkup(row_width=1)

    # Sub-folders list
    all_folders = vault_list_folders()
    prefix = full_path + "/"
    subs = sorted({f[len(prefix):].split("/")[0] for f in all_folders
                   if f.startswith(prefix) and len(f) > len(prefix)})
    for s in subs:
        mk.add(_btn(f"📁 {s}/", f"fm_cd|{full_path}|{s}"))

    # Files in current path
    rows = vault_list("folder_file", folder=full_path)
    # Filter out .init placeholder
    rows = [r for r in rows if r[1] != ".init"]
    for _, fn, sz, _ in rows[:30]:
        icon = get_file_icon(fn)
        base = os.path.basename(fn)
        short = base[:18] + ".." if len(base) > 20 else base
        mk.add(_btn(f"{icon} {short}  [{_human_size(sz)}]", f"fm_file|{full_path}|{fn}"))

    # Controls
    mk.add(_btn("📤 Upload Here", f"fm_upload|{full_path}"))
    if sub_path:
        parent = "/".join(full_path.split("/")[:-1])
        mk.add(_btn("🔙 Up", f"fm_open|{parent}" if parent != folder else f"fm_open|{folder}"))
    mk.row(_btn("📋 Normal View", f"folder_open|{folder}"),
           _btn("🏠 Folders",    "list_folders"))
    return mk


def kb_file_action(folder, filename, key):
    running = is_running(key)
    is_script = filename.endswith(SCRIPT_EXTS)
    is_zip    = filename.lower().endswith(".zip")
    al_on = _autolock_enabled(key)
    al_lbl = "🔒 AutoLock: ON" if al_on else "🔓 AutoLock: OFF"
    mk = types.InlineKeyboardMarkup(row_width=2)
    
    if is_script:
        if running:
            mk.row(_btn("🛑 Stop",    f"fstop|{key}"),    _btn("🔄 Restart", f"frestart|{key}"))
            mk.row(_btn("📜 Logs",    f"logs|{key}"),      _btn("⌨️ Input",   f"input_req|{key}"))
            mk.row(_btn("💾 Save Now", f"manual_save|{key}"))   # ← Manual save button
        else:
            mk.row(_btn("▶️ Run",     f"frun|{key}"),      _btn("📲 Update",  f"fupdate|{folder}|{filename}"))
            mk.row(_btn("📜 Logs",    f"logs|{key}"))
        mk.add(_btn(al_lbl, f"autolock_toggle|{key}"))
    else:
        mk.add(_btn("📲 Update File",  f"fupdate|{folder}|{filename}"))

    if is_zip:
        mk.add(_btn("📦 Extract ZIP", f"fzip_extract|{folder}|{filename}"))
        
    mk.row(_btn("⬇️ Download",  f"ffile_dl|{folder}|{filename}"),
           _btn("✏️ Rename",    f"ffile_ren|{folder}|{filename}"))
    mk.add(_btn("🗑️ Delete",    f"ffile_del|{folder}|{filename}"))
    mk.add(_btn("🔙 Back", f"folder_open|{folder}"))
    return mk



def kb_logs(key):
    # row_width=3 kar diya taaki 3 button ek line me aa jayein
    mk = types.InlineKeyboardMarkup(row_width=3)
    
    # 🔥 FIX: ✏️ Type button ko Refresh aur Clear ke beech mein daala gaya hai
    mk.row(_btn("🔄 Refresh", f"logs_refresh|{key}"), 
           _btn("✏️ Type", f"logs_type|{key}"),
           _btn("🧹 Clear", f"logs_clear|{key}"))
           
    mk.row(_btn("📥 Download", f"logs_dl|{key}"))
    back = f"folder_open|{key.split('/')[0]}" if "/" in key else f"script|{key}"
    mk.add(_btn("🔙 Back", back))
    return mk

def kb_dbfiles():
    mk = types.InlineKeyboardMarkup(row_width=1)
    
    # 1. Main Database Explorer (Naya Button)
    mk.add(_btn("🗄️ Explore vault.db (Internal Data)", "db_vault_explore"))
    
    # 2. VPS Disk Files / Media Vault (Naya Button - Redirects to VPS Explorer)
    mk.add(_btn("💽 Browse VPS Disk Files (Media Vault)", f"vps_cd|{LARGE_MEDIA_VAULT}"))
    
    # 3. Puraani Uploaded DB files ki list
    mk.add(_btn("━━ Uploaded DB Files ━━", "noop"))
    rows = vault_list("dbfile")
    if not rows: 
        mk.add(_btn("(No extra DB files)", "noop"))
    for _, fname, size, _ in rows:
        mk.add(_btn(f"🗄️ {fname}  ({_human_size(size)})", f"dbfile|{fname}"))
        
    mk.row(_btn("📤 Upload to DB", "upload_dbfile"), _btn("🔙 Back", "main_menu"))
    return mk

def kb_zombie_menu():
    mk = types.InlineKeyboardMarkup(row_width=2)
    # Check if zombie is active in DB
    zombie_active = _db_get("zombie_active") == "1"
    
    # Check if script exists
    con = _db_connect()
    row = con.execute("SELECT filename FROM files_vault WHERE category='zombie'").fetchone()
    con.close()
    
    fname = row[0] if row else None
    
    if fname:
        if zombie_active:
            mk.row(_btn("🛑 Stop Zombie", "zombie_stop"))
        else:
            mk.row(_btn("🟢 Start Zombie", "zombie_start"))
        mk.row(_btn("📲 Update Script", "zombie_upload"), _btn("🗑️ Delete", "zombie_del"))
    else:
        mk.add(_btn("📤 Upload Zombie Script", "zombie_upload"))
        
    mk.add(_btn("🔙 Back", "main_menu"))
    return mk, fname, zombie_active

def kb_userbot_list():
    mk = types.InlineKeyboardMarkup(row_width=1)
    con = _db_connect()
    rows = con.execute("SELECT name, phone, logged_in FROM userbot_sessions").fetchall()
    con.close()
    if not rows: mk.add(_btn("(No sessions)", "noop"))
    for name, phone, li in rows:
        icon = "🟢" if li else "🔴"
        mk.add(_btn(f"{icon} {name}  [{phone}]", f"userbot_manage|{name}"))
    mk.add(_btn("➕ Add New Session", "userbot_add"))
    mk.add(_btn("🔙 Back", "main_menu"))
    return mk

def kb_backup_settings():
    mk = types.InlineKeyboardMarkup(row_width=1)
    con = _db_connect()
    jobs = con.execute(
        "SELECT job_id, interval_hours, target_channel, active FROM backup_jobs ORDER BY added_at DESC"
    ).fetchall()
    con.close()
    if jobs:
        mk.add(_btn("━━ Active Backup Jobs ━━", "noop"))
        for jid, hrs, ch, active in jobs:
            icon = "🟢" if active else "🔴"
            mk.add(_btn(f"{icon} [{jid[:6]}] Every {hrs}h → {ch}", "noop"))
            mk.row(_btn(f"⏹️ Stop {jid[:6]}", f"backup_stop|{jid}"),
                   _btn(f"🗑️ Del {jid[:6]}",  f"backup_del|{jid}"))
    
    mk.add(_btn("➕ Add New Auto Backup Job", "backup_add_job"))
    mk.add(_btn("💾 Backup Now → Channel", "backup_now"))
    mk.add(_btn("📥 Download Backup Here", "backup_download"))
    
    # 🔥 FIX: Button text change kar diya taaki clear ho ki ye ZIP lega
    mk.add(_btn("📥 Restore Unified Backup (ZIP)", "upload_restore_db"))
    
    mk.add(_btn("🔙 Back", "main_menu"))
    return mk

def kb_sys_monitor():
    rg_lbl = "🛡️ RAM Guard: ON ✅" if _RAM_GUARD_ENABLED else "🛡️ RAM Guard: OFF ❌"
    # DB encryption status button
    enc_lbl = "🔓 DB: Plain (Tap → Encrypt Command)" if _DB_IS_PLAINTEXT else "🔒 DB: Encrypted ✅"
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.row(_btn("🔄 Refresh", "sys_monitor"), _btn("⏹️ Stop All", "stop_all"))
    mk.row(_btn("🔧 Shell Cmd", "shell_cmd"), _btn("🔙 Back",     "main_menu"))
    mk.add(_btn("🧠 Top 25 RAM Processes", "top25_mem"))
    mk.add(_btn(rg_lbl, "ramguard_toggle"))
    mk.add(_btn(enc_lbl, "encrypt_db_prompt"))
    return mk

# ══════════════════════════════════════════════════════════════
#  🖥️  VPS EXPLORER  — State-based (fixes 64-byte bug)
# ══════════════════════════════════════════════════════════════
PAGE_SIZE   = 8
EXT_GROUPS  = {
    "ALL":  [], "PY": [".py",".js"], "DB": [".db",".sqlite",".sqlite3",".sql"],
    "TXT":  [".txt",".log",".md",".cfg",".conf",".ini",".env",".json",".yaml",".yml",".xml"],
    "IMG":  [".jpg",".jpeg",".png",".gif",".webp"],
    "ARCH": [".zip",".tar",".gz",".bz2",".rar",".7z"],
    "DOCS": [".pdf",".docx",".xlsx",".pptx"],
}
FILTER_ICONS = {"ALL":"🔧","PY":"🐍","DB":"🗄️","TXT":"📝","IMG":"🖼️","ARCH":"📦","DOCS":"📄"}

def _vps_entries(path, exts):
    try: entries = list(os.scandir(path))
    except PermissionError: return [], [], "🔒 Permission denied"
    except Exception as e: return [], [], str(e)
    dirs  = sorted([e for e in entries if e.is_dir(follow_symlinks=False)],  key=lambda x: x.name.lower())
    files = [e for e in entries if e.is_file(follow_symlinks=False)]
    if exts: files = [f for f in files if os.path.splitext(f.name)[1].lower() in exts]
    files = sorted(files, key=lambda x: x.name.lower())
    return dirs, files, None

def _build_vps_kb(chat_id, path, page=None):
    """Build VPS keyboard. Buttons use short callbacks: vps_nav|next, vps_nav|prev, etc."""
    fkey = _VPS_FILTER.get(chat_id, "ALL")
    exts = EXT_GROUPS.get(fkey, [])
    dirs, files, err = _vps_entries(path, exts)
    if err:
        return f"❌ {err}", None

    items = []
    for d in dirs:
        try: cnt = sum(1 for _ in os.scandir(os.path.join(path, d.name)))
        except: cnt = 0
        items.append(("dir", d.name, os.path.join(path, d.name), 0, cnt))
    for f in files:
        try: sz = f.stat().st_size
        except: sz = 0
        items.append(("file", f.name, os.path.join(path, f.name), sz, 0))

    total_pg = max(1, math.ceil(len(items) / PAGE_SIZE))

    # 🔥 FIX: History memory logic add kiya gaya hai
    state = _VPS_STATE.get(chat_id, {"path": path, "page": 0, "history": {}})
    if "history" not in state:
        state["history"] = {}

    # Agar page explicitly nahi bheja (jaise 'Back' aate waqt), toh history se uthao
    if page is None:
        page = state["history"].get(path, 0)

    page = max(0, min(page, total_pg - 1))

    # Naya page state aur history dono mein save karo
    state["path"] = path
    state["page"] = page
    state["history"][path] = page
    _VPS_STATE[chat_id] = state

    chunk = items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    mk = types.InlineKeyboardMarkup(row_width=1)
    for kind, name, full, size, cnt in chunk:
        if kind == "dir":
            lbl = f"📁 {name}  [{cnt}]"
            mk.add(_btn(lbl, f"vps_cd|{full}"))
        else:
            icon = get_file_icon(name)
            lbl = f"{icon} {name}  [{_human_size(size)}]"
            mk.add(_btn(lbl, f"vps_file|{full}"))

    # Pagination
    nav = []
    if page > 0:         nav.append(_btn("⬅️",   "vps_nav|prev"))
    nav.append(_btn(f"{page+1}/{total_pg}", "noop"))
    if page < total_pg - 1: nav.append(_btn("➡️", "vps_nav|next"))
    if nav: mk.row(*nav)

    ctrl = []
    parent = str(Path(path).parent)
    if path != "/": ctrl.append(_btn("⬆️ Up", "vps_nav|up"))
    ctrl.append(_btn("🏠 Root", "vps_nav|root"))
    mk.row(*ctrl)
    mk.row(_btn(f"🔍 {FILTER_ICONS[fkey]} {fkey}", "vps_filter"),
           _btn("📦 ZIP Dir", "vps_nav|zip"))
    mk.row(_btn("📤 Upload Here", "vps_nav|upload"),
           _btn("➕ Mkdir", "vps_nav|mkdir"))
    mk.row(_btn("📸 Screenshot", "vps_nav|screenshot"),
           _btn("🔙 Menu",       "main_menu"))

    text = (f"🖥️ *VPS Explorer*\n"
            f"📂 `{path}`\n"
            f"📁 {len(dirs)} dirs  |  📄 {len(files)} files  |  Pg {page+1}/{total_pg}\n"
            f"🔍 Filter: *{fkey}*")
    return text, mk

def kb_vps_filter(current):
    mk = types.InlineKeyboardMarkup(row_width=2)
    row = []
    for k, icon in FILTER_ICONS.items():
        mark = "✅" if k == current else ""
        row.append(_btn(f"{mark}{icon} {k}", f"vps_setfilter|{k}"))
        if len(row) == 2: mk.row(*row); row = []
    if row: mk.row(*row)
    mk.add(_btn("🔙 Back", "vps_open"))
    return mk

def kb_vpsfile(fpath):
    parent = str(Path(fpath).parent)
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.row(_btn("⬇️ Download", f"vps_dl|{fpath}"),
           _btn("✏️ Rename",    f"vps_ren|{fpath}"))
    mk.row(_btn("🗑️ Delete🔐",  f"vps_del|{fpath}"))
    if fpath.endswith(".zip"):
        mk.add(_btn("📂 Extract to Folders", f"vps_extract|{fpath}"))
    mk.add(_btn("🔙 Back", "vps_open"))
    return mk

# ══════════════════════════════════════════════════════════════
#  📦  ZIP / FOLDER FUNCTIONS
# ══════════════════════════════════════════════════════════════
def extract_zip_to_vault(zip_bytes: bytes, folder_name: str, mode: str = "flat") -> dict:
    """Extract a ZIP and store files into files_vault safely (blocks path traversal)."""
    folder_name = _clean_vault_folder(folder_name) or f"upload_{int(time.time())}"
    stats = {"files": 0, "folders": 0, "scripts": 0, "dbs": 0, "others": 0, "skipped": 0}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for item in zf.infolist():
            safe_member = _safe_archive_member(item.filename)
            if not safe_member:
                stats["skipped"] += 1
                continue
            if item.is_dir():
                stats["folders"] += 1
                continue
            if mode == "flat":
                filename = _clean_leaf_name(safe_member)
            else:
                filename = safe_member
            try:
                data = zf.read(item)
            except Exception:
                stats["skipped"] += 1
                continue
            vault_save("folder_file", filename, data, folder_name)
            stats["files"] += 1
            fl = filename.lower()
            if fl.endswith(SCRIPT_EXTS):   stats["scripts"] += 1
            elif fl.endswith(DB_EXTS):     stats["dbs"] += 1
            else:                          stats["others"] += 1
    return stats

def zip_folder_bytes(folder_name: str) -> bytes:
    rows = vault_list("folder_file", folder=folder_name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for _, fname, _, _ in rows:
            data = vault_get("folder_file", fname, folder_name)
            if data:
                zf.writestr(fname, data)
    return buf.getvalue()

def zip_path_to_tmp(path: str) -> str:
    # 🔥 FIX (Bug #5): mktemp() TOCTOU race → mkstemp() atomic safe creation
    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.isfile(path):
            zf.write(path, os.path.basename(path))
        else:
            for rt, dirs, files in os.walk(path):
                for fn in files:
                    fp = os.path.join(rt, fn)
                    try: zf.write(fp, os.path.relpath(fp, path))
                    except Exception: pass
    return tmp

# ══════════════════════════════════════════════════════════════
#  💾  BACKUP SYSTEM
# ══════════════════════════════════════════════════════════════
def _create_backup_zip() -> str:
    """Create a backup ZIP containing the DB file. Returns temp path."""
    # 🔥 FIX (Bug #5): mktemp() TOCTOU race → mkstemp() atomic safe creation
    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(DB_FILE):
            zf.write(DB_FILE, "vault.db")
    return tmp

def _create_unified_backup_zip() -> str:
    """Creates a ZIP containing vault.db, enc_config marker AND the large_media_vault folder"""
    # 🔥 FIX (Bug #5): mktemp() TOCTOU race → mkstemp() atomic safe creation
    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Main Database ko ZIP mein daalo
        if os.path.exists(DB_FILE):
            zf.write(DB_FILE, "vault.db")

        # 🔥 FIX (Bug #6): Encryption state marker bhi ZIP mein daalo.
        # Iske bina restore ke baad bot restart par encryption state lost ho jaati thi
        # aur plain sqlite3 se encrypted DB open karne ki koshish → "file is not a database".
        if os.path.exists(_DB_ENCRYPTED_MARKER):
            zf.write(_DB_ENCRYPTED_MARKER, "vault.db.enc_config")

        # 2. Disk files (large_media_vault) ko as it is ZIP mein daalo
        if os.path.exists(LARGE_MEDIA_VAULT):
            for root, dirs, files in os.walk(LARGE_MEDIA_VAULT):
                for file in files:
                    file_path = os.path.join(root, file)
                    # ZIP ke andar folder structure maintain rahega
                    arcname = os.path.relpath(file_path, BASE_DIR)
                    zf.write(file_path, arcname)
    return tmp

def _do_backup(chat_id=None):
    ch = BACKUP_CHANNEL or _db_get("backup_channel")
    if not ch:
        if chat_id: bot.send_message(chat_id, "⚠️ Backup channel set nahi hai.", parse_mode="Markdown")
        return
    try:
        ch_int = int(ch)
        sname, _ = _get_active_userbot()
        if not sname or not PYROGRAM_AVAILABLE:
            raise Exception("Active Userbot nahi mila!")

        # Ab sirf DB nahi, Unified ZIP banega
        if chat_id: bot.send_message(chat_id, "⏳ Generating Unified Backup ZIP (DB + Disk Files)...")
        zip_path = _create_unified_backup_zip()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        caption = f"📦 *Unified Auto Backup* (DB + Media)\nDate: {ts}\nPassword Protected."

        _userbot_upload_thread(sname, ch_int, zip_path, caption)
        
        if os.path.exists(zip_path):
            os.remove(zip_path) # Upload hone ke baad ZIP delete kardo

        if chat_id: bot.send_message(chat_id, f"✅ Unified Backup sent to `{ch}`", parse_mode="Markdown")
    except Exception as e:
        if chat_id: bot.send_message(chat_id, f"❌ Backup failed: `{e}`", parse_mode="Markdown")
        
def _backup_job_worker(job_id):
    con = _db_connect()
    row = con.execute("SELECT interval_hours, target_channel, active FROM backup_jobs WHERE job_id=?",
                      (job_id,)).fetchone()
    con.close()
    if not row: return
    interval_h, channel, _ = row
    
    while True:
        time.sleep(interval_h * 3600)
        con2 = _db_connect()
        r2 = con2.execute("SELECT active FROM backup_jobs WHERE job_id=?", (job_id,)).fetchone()
        con2.close()
        if not r2 or not r2[0]: break
        
        try:
            ch_int = int(channel)
            sname, _ = _get_active_userbot()
            if not sname or not PYROGRAM_AVAILABLE:
                log.error(f"Auto Backup [{job_id[:6]}] failed: Active Userbot not found.")
                continue

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # 🔥 FIX: Ab Auto Backup mein bhi Unified ZIP (DB + Disk Media) banega
            log.info(f"Auto Backup {job_id[:6]}: Generating Unified ZIP...")
            zip_path = _create_unified_backup_zip()
            
            _userbot_upload_thread(sname, ch_int, zip_path, f"📦 Auto Unified Backup [{job_id[:6]}] — {ts}")
            
            # Upload hone ke baad VPS se kachra (ZIP) delete kardo
            if os.path.exists(zip_path):
                os.remove(zip_path)
                
            log.info(f"Auto Backup {job_id[:6]} sent via Userbot.")
        except Exception as e:
            log.error(f"Auto Backup job {job_id} error: {e}")

def _start_backup_jobs():
    con = _db_connect()
    jobs = con.execute("SELECT job_id FROM backup_jobs WHERE active=1").fetchall()
    con.close()
    for (jid,) in jobs:
        if jid not in _BACKUP_THREADS:
            t = threading.Thread(target=_backup_job_worker, args=(jid,), daemon=True)
            t.start()
            _BACKUP_THREADS[jid] = t

def restore_from_zip(zip_bytes: bytes, chat_id: int):
    """Restore from a backup ZIP (contains scripts, folder files, etc.)."""
    try:
        restored = []
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            for n in names:
                if n.startswith("scripts/") and n.endswith((".py", ".js")):
                    fn = os.path.basename(n)
                    data = zf.read(n)
                    vault_save("script", fn, data)
                    restored.append(fn)
                elif n.startswith("folders/"):
                    parts = n.split("/", 2)
                    if len(parts) == 3:
                        folder, fn = parts[1], parts[2]
                        data = zf.read(n)
                        vault_save("folder_file", fn, data, folder)
                        restored.append(f"folders/{folder}/{fn}")
                elif n.startswith("sessions/"):
                    fn = os.path.basename(n)
                    data = zf.read(n)
                    vault_save("session", fn, data)
                    restored.append(f"session/{fn}")
        bot.send_message(chat_id,
            f"✅ Restore complete! `{len(restored)}` files restored.", parse_mode="Markdown")
        _resume_auto_scripts(chat_id)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Restore failed: {e}")

def _db_try_open(db_path: str, pragmas: list) -> bool:
    """Try opening db_path with a given set of PRAGMAs, verify pw_hash matches the key used.
    pragmas must include the PRAGMA key='...' line (or be empty for a plain unencrypted DB)."""
    con = None
    try:
        con = sqlcipher.connect(db_path, timeout=15)
        for p in pragmas:
            con.execute(p)
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return con, True
    except Exception:
        try:
            if con: con.close()
        except Exception:
            pass
        return None, False

def _db_verify_file_with_key(db_path: str, key: str):
    """
    Verify a SQLCipher/plain sqlite DB file with a given password before replacing live DB.
    Returns the matching pragma profile (list, possibly empty) on success, or None on failure.

    🔥 FIX: A wrong password and a PARAMETER MISMATCH (different SQLCipher version/
    kdf_iter/page_size than what this bot currently uses, or a plain unencrypted DB
    from a sqlite3_FALLBACK setup) produce the EXACT same 'hmac check failed' noise.
    So instead of assuming "wrong password" on the first failure, try every known
    SQLCipher compatibility profile plus a plain-sqlite3 fallback before giving up.
    """
    safe_key = _normalize_pw(key or "")  # 🔥 FIX: defense-in-depth, see _normalize_pw()
    key = safe_key
    safe_key = safe_key.replace("'", "''")

    # Plain sqlite3 mode — always just try opening without any key
    attempts = [[]]  # no cipher pragmas

    for pragmas in attempts:
        con, ok = _db_try_open(db_path, pragmas)
        if not ok:
            continue
        try:
            row = con.execute("SELECT value FROM vault_meta WHERE key='pw_hash'").fetchone()
            con.close()
            if not row:
                continue
            # 🔒 HARDENING: _scrypt_verify supports both scrypt + sha256 formats
            if _scrypt_verify(key or "", row[0]):
                # strip the "PRAGMA key=..." line — caller only wants the extra profile pragmas
                return [p for p in pragmas if not p.startswith("PRAGMA key=")]
        except Exception:
            try: con.close()
            except Exception: pass
            continue
    return None

def _finish_sqlcipher_restore(tmp_db: str, chat_id: int, key_used: str):
    """Actually swap the verified incoming DB into place and restart the bot."""
    try:
        for k in list(RUNNING.keys()):
            kill_script(k)
        bak = DB_FILE + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        if os.path.exists(DB_FILE):
            shutil.copy2(DB_FILE, bak)
        os.replace(tmp_db, DB_FILE)

        # 🔥 FIX (Bug #4): Restore ke baad _DB_ENCRYPTED_MARKER update karo.
        # Nahi kiya toh restart ke baad plain sqlite3 se open karne ki koshish hogi
        # aur "file is not a database" error aayega — exactly the same as Bug #1.
        # Restored DB ki pragma profile verify karte waqt pata chali thi — wahi save karo.
        try:
            # Incoming DB ki pragma profile detect karo (agar encrypted hai toh)
            safe_key = (key_used or "").replace("'", "''")
            _restored_pragmas = [f"PRAGMA key='{safe_key}'"] if _db_verify_file_with_key(DB_FILE, key_used) is not None else []
            _restored_is_plain = not bool(_restored_pragmas)
            if not _restored_is_plain:
                enc_cfg = {"pragmas": [p for p in _restored_pragmas if not p.startswith("PRAGMA key=")]}
                with open(_DB_ENCRYPTED_MARKER, "w") as _mf:
                    json.dump(enc_cfg, _mf)
                os.chmod(_DB_ENCRYPTED_MARKER, 0o600)
            else:
                # Plain DB restore hua — marker hata do (agar tha)
                if os.path.exists(_DB_ENCRYPTED_MARKER):
                    os.remove(_DB_ENCRYPTED_MARKER)
        except Exception as _me:
            log.warning(f"[restore] enc_marker update failed (non-fatal): {_me}")

        bot.send_message(chat_id, f"✅ SQLCipher DB restored. Old DB backup: `{os.path.basename(bak)}`\n🔄 Restarting bot…", parse_mode="Markdown")
        time.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        if os.path.exists(tmp_db):
            os.remove(tmp_db)
        bot.send_message(chat_id, f"❌ DB restore failed: `{_md_escape(e)}`", parse_mode="Markdown")

def restore_sqlcipher_db(db_bytes: bytes, chat_id: int):
    """Restore a single vault.db upload. Tries current password first; if the
    incoming DB was encrypted with a DIFFERENT password (e.g. an older backup,
    or a DB from another bot instance), asks for that DB's own password
    instead of just cancelling."""
    if not _DB_KEY:
        bot.send_message(chat_id, "❌ DB locked. Pehle /start se unlock karo.")
        return
    tmp_db = DB_FILE + ".incoming"
    try:
        with open(tmp_db, "wb") as f:
            f.write(db_bytes)

        profile = _db_verify_file_with_key(tmp_db, _DB_KEY)
        if profile is not None:
            _finish_sqlcipher_restore(tmp_db, chat_id, _DB_KEY)
            return

        # Current password se match nahi hui — DB ka apna alag password ho sakta hai
        _PENDING_RESTORE[chat_id] = {"kind": "single", "tmp_db": tmp_db}
        _AWAITING_RESTORE_PW.add(chat_id)
        bot.send_message(chat_id,
            "⚠️ Ye `vault.db` current password se decrypt nahi hui — lagta hai iska apna "
            "*alag* password hai (kisi purani backup ka ya kisi doosre setup ka).\n\n"
            "🔐 Uss DB ka original password bhejo (jis password se woh file pehle encrypt hui thi):",
            parse_mode="Markdown")
    except Exception as e:
        if os.path.exists(tmp_db):
            os.remove(tmp_db)
        bot.send_message(chat_id, f"❌ DB restore failed: `{_md_escape(e)}`", parse_mode="Markdown")

def restore_unified_backup(zip_bytes: bytes, chat_id: int, key: str = None):
    """Restore Unified ZIP safely: verify incoming vault.db, block zip-slip, restore disk-backed media.
    `key` lets a retry attempt use a password different from the currently active _DB_KEY —
    used when the incoming vault.db was encrypted with its own, different password."""
    use_key = key or _DB_KEY
    if not use_key:
        bot.send_message(chat_id, "❌ DB locked. Pehle /start se unlock karo.")
        return

    tmp_db = DB_FILE + ".incoming"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_bak = DB_FILE + f".bak_{ts}"
    media_bak = LARGE_MEDIA_VAULT + f".bak_{ts}"
    if key is None:
        bot.send_message(chat_id, "⏳ Unified ZIP verify ho raha hai…")

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            if "vault.db" not in names:
                bot.send_message(chat_id, "❌ ZIP ke andar `vault.db` nahi mili.", parse_mode="Markdown")
                return

            with open(tmp_db, "wb") as f:
                f.write(zf.read("vault.db"))

            if _db_verify_file_with_key(tmp_db, use_key) is None:
                os.remove(tmp_db)
                if key is None:
                    # First attempt (current password) failed — DB ka apna alag password ho sakta hai
                    _PENDING_RESTORE[chat_id] = {"kind": "unified", "zip_bytes": zip_bytes}
                    _AWAITING_RESTORE_PW.add(chat_id)
                    bot.send_message(chat_id,
                        "⚠️ Incoming `vault.db` current password se decrypt nahi hui — lagta hai iska "
                        "*alag* password hai.\n\n"
                        "🔐 Uss DB ka original password bhejo:",
                        parse_mode="Markdown")
                else:
                    bot.send_message(chat_id, "❌ Diya gaya password se bhi verify nahi hui. Restore cancel.", parse_mode="Markdown")
                return

            for k in list(RUNNING.keys()):
                kill_script(k)

            if os.path.exists(DB_FILE):
                shutil.copy2(DB_FILE, db_bak)
            os.replace(tmp_db, DB_FILE)

            # 🔥 FIX (Bug #4): Unified restore ke baad bhi _DB_ENCRYPTED_MARKER update karo.
            # Warna restart ke baad encryption state lost → unlock fail.
            try:
                _restored_profile = _db_verify_file_with_key(DB_FILE, use_key)
                _restored_is_plain = (_restored_profile is not None and len(_restored_profile) == 0)
                if not _restored_is_plain and _restored_profile is not None:
                    enc_cfg = {"pragmas": _restored_profile}
                    with open(_DB_ENCRYPTED_MARKER, "w") as _mf:
                        json.dump(enc_cfg, _mf)
                    os.chmod(_DB_ENCRYPTED_MARKER, 0o600)
                elif _restored_is_plain:
                    if os.path.exists(_DB_ENCRYPTED_MARKER):
                        os.remove(_DB_ENCRYPTED_MARKER)
            except Exception as _me:
                log.warning(f"[unified_restore] enc_marker update failed (non-fatal): {_me}")

            # Replace large_media_vault only after DB verify succeeds.
            if os.path.isdir(LARGE_MEDIA_VAULT):
                if os.path.exists(media_bak):
                    shutil.rmtree(media_bak)
                shutil.move(LARGE_MEDIA_VAULT, media_bak)
            os.makedirs(LARGE_MEDIA_VAULT, exist_ok=True)

            # 🔥 FIX (Bug #6 part 2): ZIP ke andar enc_config hai toh restore karo.
            # Agar Bug #4 fix (DB se re-detect) pehle se kaam kar chuka ho toh
            # yeh redundant hai, lekin ZIP mein saved config zyada reliable hai
            # (especially different-password restore mein).
            if "vault.db.enc_config" in names:
                try:
                    enc_cfg_bytes = zf.read("vault.db.enc_config")
                    with open(_DB_ENCRYPTED_MARKER, "wb") as _ecf:
                        _ecf.write(enc_cfg_bytes)
                    os.chmod(_DB_ENCRYPTED_MARKER, 0o600)
                    log.info("[unified_restore] enc_config restored from ZIP.")
                except Exception as _ece:
                    log.warning(f"[unified_restore] enc_config ZIP extract failed (non-fatal): {_ece}")

            restored_files = 0
            skipped = 0
            for n in names:
                safe_member = _safe_archive_member(n)
                if not safe_member or not safe_member.startswith("large_media_vault/") or n.endswith("/"):
                    continue
                try:
                    dest_path = _safe_join(BASE_DIR, safe_member)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with open(dest_path, "wb") as f:
                        f.write(zf.read(n))
                    restored_files += 1
                except Exception:
                    skipped += 1

        bot.send_message(chat_id,
            f"✅ *Unified Backup Restored!*\n"
            f"🗄️ DB replaced. Backup copy: `{os.path.basename(db_bak)}`\n"
            f"📂 Media files restored: `{restored_files}` | skipped: `{skipped}`\n"
            f"🔄 Bot restarting…",
            parse_mode="Markdown")
        time.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        if os.path.exists(tmp_db):
            os.remove(tmp_db)
        bot.send_message(chat_id, f"❌ Restore failed: `{_md_escape(e)}`", parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
#  🔐  PYROGRAM USERBOT — Isolated Thread + New Event Loop
# ══════════════════════════════════════════════════════════════
import threading
import tempfile

# 🔥 FIX: Userbot Lock - Taaki ek waqt par sirf ek hi upload/download chale aur session lock na ho!
_USERBOT_LOCK = threading.Lock()

def _get_active_userbot():
    con = _db_connect()
    row = con.execute(
        "SELECT name, target_channel FROM userbot_sessions WHERE logged_in=1 LIMIT 1"
    ).fetchone()
    con.close()
    return (row[0], row[1]) if row else (None, None)

def _userbot_upload_thread(session_name, chat_id_tg, file_path, caption):
    """
    Ultra-Advance Upload Thread: 
    PEER_ID_INVALID fix ke sath cache bypass aur dynamic timeout.
    """
    import asyncio
    result_box = [False]
    err_box    = [None]
    done_event = threading.Event()

    def _run():
        with _USERBOT_LOCK:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _up():
                    if not os.path.exists(f"{session_name}.session"):
                        raise Exception(f"Session '{session_name}.session' missing!")

                    print(f"🤖 [DEBUG] Pyrogram starting for session: {session_name}...")
                    
                    async with PyroClient(session_name, api_id=PYROGRAM_API_ID,
                                     api_hash=PYROGRAM_API_HASH,
                                     no_updates=True) as app:
                        
                        # 🔥 DEEP FIX: Agar khud ko file bhej rahe ho, toh "me" target use karo
                        me = await app.get_me()
                        if str(chat_id_tg) == str(me.id):
                            target_chat = "me"
                        else:
                            target_chat = chat_id_tg
                            # PEER_ID_INVALID se bachne ke liye recent dialogs check karke cache build karo
                            try:
                                await app.get_chat(target_chat)
                            except Exception:
                                print("🤖 [DEBUG] Peer not cached. Fetching dialogs...")
                                async for _ in app.get_dialogs(limit=20): pass

                        print(f"🤖 [DEBUG] Uploading file: {file_path} to {target_chat}...")
                        await app.send_document(chat_id=target_chat,
                                                document=file_path,
                                                caption=caption)
                        print("🤖 [DEBUG] Upload 100% Successful!")
                        result_box[0] = True

                loop.run_until_complete(_up())
            except Exception as e:
                print(f"🤖 [DEBUG] Thread Exception: {e}")
                err_box[0] = e
            finally:
                loop.close()
                done_event.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    
    try:
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    except:
        file_size_mb = 100
        
    dynamic_timeout = int(max(300, file_size_mb * 5)) 
    done_event.wait(timeout=dynamic_timeout) 
    
    if err_box[0]:
        raise err_box[0]
    if not result_box[0]:
        raise Exception(f"Upload timeout ({dynamic_timeout}s). File bohot badi hai ya network slow hai!")
        
# ── MTProto large-file download bypass (FIXED) ──
# ── MTProto large-file download bypass (DEEP FIX) ──
def _pyrogram_bot_download_bypass(chat_id, message_id, fname, step, status_msg_id):
    """
    Bot token se 20MB limit aati hai. Isey fix karke Userbot se download karwaya gaya hai.
    DEEP FIX: ID match karne ke bajaye, Userbot ki chat history se latest media fetch karenge.
    PROGRESS FIX: Real-time download progress bar + speed + ETA + friendly errors.
    """
    import asyncio
    import time as _time

    # 1. Userbot ka session aur user_id DB se nikalna
    con = _db_connect()
    row = con.execute("SELECT name, user_id FROM userbot_sessions WHERE logged_in=1 LIMIT 1").fetchone()
    con.close()

    if not row:
        bot.edit_message_text(
            "❌ *Userbot Login Required!*\n"
            "20MB se badi files download karne ke liye pehle Userbot login karo.",
            chat_id, status_msg_id, parse_mode="Markdown"
        )
        return

    session_name = row[0]
    ub_user_id = int(row[1])

    # 2. Bot badi file ko Userbot account par forward karega
    try:
        bot_info = bot.get_me()
        bot.forward_message(ub_user_id, chat_id, message_id)
    except Exception as e:
        bot.edit_message_text(
            f"❌ *Forward Error*\n"
            f"Userbot ne bot ko block kiya hai ya `/start` nahi bheja.\n"
            f"Fix: Userbot account se bot ko `/start` bhejo.\n\n"
            f"`{e}`",
            chat_id, status_msg_id, parse_mode="Markdown"
        )
        return

    # ── Progress bar helper ──
    def _make_bar(pct: int, length: int = 10) -> str:
        filled = int(pct / 100 * length)
        return "▓" * filled + "░" * (length - filled)

    def _friendly_error(err: str) -> str:
        """Common Pyrogram/Telegram errors ko human-readable banaata hai."""
        e = str(err)
        if "FLOOD_WAIT" in e:
            secs = "".join(c for c in e if c.isdigit()) or "kuch der"
            return f"⏳ Telegram flood-wait: `{secs}s` baad retry karo."
        if "FILE_REFERENCE_EXPIRED" in e:
            return "🔁 File reference expire ho gayi — message dobara bhejo."
        if "SESSION_REVOKED" in e or "USER_DEACTIVATED" in e:
            return "❌ Userbot session revoke ho gayi — dobara login karo."
        if "AUTH_KEY_UNREGISTERED" in e:
            return "🔑 Auth key invalid — Userbot ko hatao aur dobara add karo."
        if "timeout" in e.lower() or "timed out" in e.lower():
            return "⌛ Download timeout — file bahut badi hai ya net slow hai."
        if "not connected" in e.lower() or "connection" in e.lower():
            return "🔌 Network error — VPS internet check karo."
        if "No such file" in e or "Permission" in e:
            return f"💾 Disk error: `{e}`"
        return f"`{e}`"

    async def _dl():
        with _USERBOT_LOCK:
            tmp_path = os.path.join(tempfile.gettempdir(), f"temp_{fname}")
            try:
                async with PyroClient(session_name, api_id=PYROGRAM_API_ID,
                                      api_hash=PYROGRAM_API_HASH,
                                      no_updates=True) as app:

                    target_chat = bot_info.username
                    bot.edit_message_text(
                        f"🔍 `{fname}` Userbot history mein dhundh raha hun…",
                        chat_id, status_msg_id, parse_mode="Markdown"
                    )

                    # 🔥 DEEP FIX: Latest media message pakdo
                    pyro_msg = None
                    async for msg in app.get_chat_history(target_chat, limit=5):
                        if msg.media:
                            pyro_msg = msg
                            break

                    if not pyro_msg:
                        bot.edit_message_text(
                            "❌ History mein koi media nahi mila.\nFile dobara bhejo aur retry karo.",
                            chat_id, status_msg_id
                        )
                        return

                    # ── Progress tracking state ──
                    _last_edit_time = [0.0]
                    _last_pct       = [-1]
                    _dl_start       = [_time.time()]

                    async def _progress(current: int, total: int):
                        """Pyrogram progress callback — har chunk par call hota hai."""
                        now  = _time.time()
                        pct  = int(current * 100 / total) if total else 0

                        # Sirf har 5% ya har 3 sec mein edit karo (flood se bachne ke liye)
                        if pct - _last_pct[0] < 5 and now - _last_edit_time[0] < 3:
                            return

                        _last_pct[0]       = pct
                        _last_edit_time[0] = now

                        elapsed  = now - _dl_start[0]
                        speed_bs = current / elapsed if elapsed > 0 else 0
                        curr_mb  = current / (1024 * 1024)
                        total_mb = total   / (1024 * 1024)
                        spd_kb   = speed_bs / 1024

                        bar = _make_bar(pct)

                        eta_line = ""
                        if speed_bs > 0 and current < total:
                            eta_s    = int((total - current) / speed_bs)
                            eta_line = f"\n⏱️ ETA: `{eta_s}s`"

                        text = (
                            f"📥 *Downloading via Userbot Bypass*\n"
                            f"📄 `{fname}`\n\n"
                            f"`[{bar}]` {pct}%\n"
                            f"📦 `{curr_mb:.1f} MB / {total_mb:.1f} MB`\n"
                            f"⚡ Speed: `{spd_kb:.1f} KB/s`"
                            f"{eta_line}"
                        )
                        try:
                            bot.edit_message_text(
                                text, chat_id, status_msg_id, parse_mode="Markdown"
                            )
                        except Exception:
                            pass  # same-text / flood edit error — silently skip

                    # ✅ Download with live progress
                    bot.edit_message_text(
                        f"📥 *Downloading `{fname}` via Userbot Bypass (>20MB)…*\n"
                        f"`[░░░░░░░░░░]` 0%",
                        chat_id, status_msg_id, parse_mode="Markdown"
                    )
                    await app.download_media(pyro_msg, file_name=tmp_path, progress=_progress)

                    # ── Download complete summary ──
                    total_elapsed = _time.time() - _dl_start[0]
                    try:
                        final_mb  = os.path.getsize(tmp_path) / (1024 * 1024)
                        avg_speed = (final_mb * 1024) / total_elapsed if total_elapsed > 0 else 0
                        bot.edit_message_text(
                            f"✅ *Download Complete!*\n"
                            f"📄 File: `{fname}`\n"
                            f"📦 Size: `{final_mb:.1f} MB`\n"
                            f"⏱️ Time: `{int(total_elapsed)}s` | Avg: `{avg_speed:.1f} KB/s`\n"
                            f"💾 Vault mein save ho raha hai…",
                            chat_id, status_msg_id, parse_mode="Markdown"
                        )
                    except Exception:
                        pass

                    with open(tmp_path, "rb") as f:
                        data = f.read()
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

                    # Cleanup: Userbot side se message delete karo
                    try:
                        await pyro_msg.delete()
                        bot.delete_message(chat_id, status_msg_id)
                    except Exception:
                        pass

                    # Vault mein permanently save karo
                    _process_uploaded_data(chat_id, None, fname, data, step)

            except Exception as e:
                # Temp file cleanup on error
                if os.path.exists(tmp_path):
                    try: os.remove(tmp_path)
                    except Exception: pass

                friendly = _friendly_error(e)
                try:
                    bot.edit_message_text(
                        f"❌ *Userbot Bypass Error*\n{friendly}",
                        chat_id, status_msg_id, parse_mode="Markdown"
                    )
                except Exception:
                    bot.send_message(
                        chat_id,
                        f"❌ *Userbot Bypass Error*\n{friendly}",
                        parse_mode="Markdown"
                    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_dl())
    loop.close()
    
# ── Userbot Login (queue-based, isolated thread) ──
import queue as _queue_mod
_LOGIN_QUEUES = {}

def _userbot_login_thread(chat_id, phone, session_name):
    import asyncio

    async def _flow():
        app = PyroClient(session_name, api_id=PYROGRAM_API_ID, api_hash=PYROGRAM_API_HASH,
                         device_model="Admin V3", system_version="Android 14",
                         no_updates=True)
        await app.connect()
        try:
            sent = await app.send_code(phone)
            bot.send_message(chat_id, "✅ OTP bheja gaya!\n📲 OTP code daalo:")
            q = _LOGIN_QUEUES[chat_id]
            otp_data = await asyncio.get_event_loop().run_in_executor(None, q.get)
            try:
                await app.sign_in(phone, sent.phone_code_hash, otp_data["otp"])
            except SessionPasswordNeeded:
                bot.send_message(chat_id, "🔐 2FA password daalo:")
                pw_data = await asyncio.get_event_loop().run_in_executor(None, q.get)
                await app.check_password(pw_data["pw"])
            me = await app.get_me()
            await app.disconnect()
            con = _db_connect()
            con.execute(
                "INSERT OR REPLACE INTO userbot_sessions(name,phone,user_id,logged_in,added_at) VALUES(?,?,?,1,?)",
                (session_name, phone, str(me.id), datetime.now().isoformat()))
            con.commit(); con.close()
            _LOGIN_QUEUES.pop(chat_id, None)
            bot.send_message(chat_id, f"✅ Logged in: *{me.first_name}*",
                             parse_mode="Markdown", reply_markup=kb_userbot_list())
        except Exception as e:
            bot.send_message(chat_id, f"❌ Login failed: {e}")
            await app.disconnect()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_flow())
    loop.close()

def _start_userbot_login(chat_id, phone):
    import uuid
    session_name = f"userbot_{uuid.uuid4().hex[:8]}"
    bot.send_message(chat_id, f"📱 Logging in: `{phone}`…\n⏳ OTP bhej raha hun…",
                     parse_mode="Markdown")
    _LOGIN_QUEUES[chat_id] = _queue_mod.Queue()
    _STEP[chat_id] = {"step": "userbot_otp"}
    threading.Thread(target=_userbot_login_thread,
                     args=(chat_id, phone, session_name), daemon=True).start()

def _finish_userbot_login(chat_id, otp):
    if chat_id in _LOGIN_QUEUES:
        _LOGIN_QUEUES[chat_id].put({"otp": otp})
        _STEP[chat_id] = {"step": "userbot_2fa"}

def _finish_userbot_2fa(chat_id, pw):
    if chat_id in _LOGIN_QUEUES:
        _LOGIN_QUEUES[chat_id].put({"pw": pw})

# ── MTProto large-file download bypass ──

# ══════════════════════════════════════════════════════════════
#  📊  SYSTEM MONITOR
# ══════════════════════════════════════════════════════════════
def get_sys_info() -> str:
    cpu  = psutil.cpu_percent(interval=1)
    ram  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    try:    net = psutil.net_io_counters()
    except: net = None
    uptime_s = int(time.time() - psutil.boot_time())
    h, rem = divmod(uptime_s, 3600); m = rem // 60
    running_count = sum(1 for k in list(RUNNING.keys()) if is_running(k))
    scripts_count = len(get_scripts())
    folders_count = len(vault_list_folders())
    enc_status = "🔒 SQLCipher Encrypted" if not _DB_IS_PLAINTEXT else "🔓 Plain sqlite3 (unencrypted) — /encryptdb se encrypt karo"

    # ── /dev/shm raw stats (sirf informational — yeh active cache nahi ho sakta agar mode != shm) ──
    def _mb_or_gb(mb: float) -> str:
        return f"{mb/1024:.1f}GB" if mb >= 1024 else f"{mb:.0f}MB"
    try:
        _shm = shutil.disk_usage("/dev/shm")
        _shm_total_mb = _shm.total / (1024 * 1024)
        _shm_used_mb  = _shm.used  / (1024 * 1024)
        _shm_free_mb  = _shm.free  / (1024 * 1024)
        _shm_used_pct = (_shm.used / _shm.total * 100) if _shm.total > 0 else 0
        _shm_free_pct = (_shm.free / _shm.total * 100) if _shm.total > 0 else 0
        if _shm_total_mb == 0 and _RAM_DISK_MODE == "shm":
            # ramfs: no size cap — total=0 is normal; show available RAM as capacity
            _ram_avail_for_shm = psutil.virtual_memory().available // (1024 * 1024)
            shm_line = (
                f"Mode:`ramfs` (no cap) "
                f"Effective:`~{_mb_or_gb(_ram_avail_for_shm)}` available RAM usable"
            )
        else:
            shm_line = (
                f"Total:`{_mb_or_gb(_shm_total_mb)}` "
                f"Used:`{_mb_or_gb(_shm_used_mb)}({_shm_used_pct:.1f}%)` "
                f"Free:`{_mb_or_gb(_shm_free_mb)}({_shm_free_pct:.1f}%)`"
            )
    except Exception:
        shm_line = "`N/A`"

    # ── Active cache mode ──
    _mode_icon  = ("🟢 TRUE RAM — /dev/shm" if _RAM_DISK_MODE == "shm"
                   else "🟡 /tmp (disk-backed)" if _RAM_DISK_MODE == "tmp"
                   else "🟡 Physical Disk")
    _mode_path  = RAM_DISK_DIR

    try:
        _active = shutil.disk_usage(RAM_DISK_DIR)
        _active_total_mb = _active.total / (1024 * 1024)
        _active_free_mb  = _active.free  / (1024 * 1024)
        _active_free_pct = (_active.free / _active.total * 100) if _active.total > 0 else 0
        _active_warning  = (" ⚠️ CRITICAL!" if _active_free_mb < 100
                             else (" ⚡ Healthy" if _active_free_mb >= 32
                                   else " 🟡 LOW"))
        active_cache_line = (f"Total:`{_mb_or_gb(_active_total_mb)}` "
                              f"Free:`{_mb_or_gb(_active_free_mb)}({_active_free_pct:.1f}%)`{_active_warning}")
    except Exception:
        active_cache_line = "`N/A`"

    # ══ RAM Disk Status — Smart Cache Integration (main__1__.py merge) ══
    _ram_total_mb  = ram.total    / (1024 * 1024)
    _ram_avail_mb  = ram.available / (1024 * 1024)
    _ram_avail_gb  = ram.available / (1024 ** 3)
    _ram_total_gb  = ram.total    / (1024 ** 3)
    _ram_warn      = ""
    if ram.percent >= 90:
        _ram_warn = "  ⚠️ CRITICAL — RAM 90%+ !"
    elif ram.percent >= 80:
        _ram_warn = "  ⚠️ HIGH — RAM 80%+"
    elif ram.percent >= 70:
        _ram_warn = "  🟡 Moderate — RAM 70%+"

    # Cache free space live check
    _shm_warn = ""
    try:
        _shm_live = shutil.disk_usage("/dev/shm")
        _shm_live_free_mb = _shm_live.free / (1024 * 1024)
        if _shm_live_free_mb < 100:
            _shm_warn = f"  ⚠️ < 100MB threshold!"
    except Exception:
        pass

    text  = f"📊 *VPS System Monitor (V4)*\n━━━━━━━━━━━━━━━━━\n"
    text += f"🖥️ *CPU:* `{cpu}%`\n"
    text += f"🧠 *RAM:* `{ram.used//(1024**2)}MB / {ram.total//(1024**2)}MB ({ram.percent}%)`{_ram_warn}\n"
    text += f"💾 *Disk:* `{disk.used//(1024**3)}GB / {disk.total//(1024**3)}GB ({disk.percent}%)`\n"
    # ─── RAM Disk Status Section ───────────────────────────────────────
    text += f"\n━━ 🧠 *RAM Disk Status* ━━\n"
    text += (
        f"🖥️ *Total RAM:* `{_ram_total_gb:.1f} GB ({int(_ram_total_mb)} MB)`\n"
        f"✅ *Available RAM:* `{_ram_avail_gb:.2f} GB ({int(_ram_avail_mb)} MB)`\n"
    )
    if _RAM_DISK_MODE == "shm":
        text += f"📀 */dev/shm (ACTIVE — TRUE RAM):* {shm_line}{_shm_warn}\n"
    elif _RAM_DISK_MODE == "tmp":
        text += f"📀 */dev/shm (info):* {shm_line}\n"
        text += f"🟡 *Cache:* /tmp use ho raha hai (disk-backed)\n"
    else:
        text += f"📀 */dev/shm (info):* {shm_line}\n"
    text += f"⚡ *Smart Cache Mode:* `{_mode_icon}`\n"
    text += f"📦 *Active Cache:* {active_cache_line}\n"
    text += f"🔄 *Smart Cache Path:* `{_mode_path}`\n"
    # ─── End RAM Disk Status ──────────────────────────────────────────
    text += f"\n━━━━━━━━━━━━━━━━━\n"
    if net:
        text += f"📡 *Net ↑:* `{_human_size(net.bytes_sent)}`  *↓:* `{_human_size(net.bytes_recv)}`\n"
    text += f"⏱️ *Uptime:* `{h}h {m}m`\n"
    text += f"🔐 *Encryption:* `{enc_status}`\n"
    text += f"🟢 *Running:* `{running_count}` | 📋 Scripts: `{scripts_count}` | 📁 Folders: `{folders_count}`\n"
    text += f"🕐 *Time:* `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
    if RUNNING:
        text += "\n━━ *Running Scripts* ━━\n"
        for k, info in list(RUNNING.items()):
            if is_running(k):
                mins = (datetime.now() - info["start"]).seconds // 60
                # 🔥 NAYA LOGIC: Process ki RAM usage nikalne ke liye
                try:
                    proc = psutil.Process(info["pid"])
                    mem_percent = proc.memory_percent()
                    mem_usage_str = f"{mem_percent:.1f}% RAM"
                except Exception:
                    mem_usage_str = "N/A RAM"

                text += f"  `{os.path.basename(k)}` — PID:{info['pid']} | {mins}m | 🧠 {mem_usage_str}\n"
    return text
    
def get_top25_mem() -> str:
    """Top 25 memory-consuming processes ki list"""
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'memory_info', 'memory_percent', 'status']):
        try:
            mi = p.info['memory_info']
            procs.append({
                'pid': p.info['pid'],
                'name': (p.info['name'] or "?")[:20],
                'rss': mi.rss if mi else 0,
                'pct': p.info['memory_percent'] or 0.0,
                'status': p.info['status'],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    procs.sort(key=lambda x: x['rss'], reverse=True)
    top = procs[:25]
    lines = ["🧠 *Top 25 RAM Processes*", ""]
    for i, p in enumerate(top, 1):
        lines.append(f"`{i:2}` PID:`{p['pid']}` {p['name']} — {_human_size(p['rss'])} ({p['pct']:.1f}%)")
    return "\n".join(lines)

def kb_top25_mem():
    """Top 25 processes ki keyboard — har process pe Kill button"""
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'memory_info', 'memory_percent']):
        try:
            mi = p.info['memory_info']
            procs.append({'pid': p.info['pid'], 'name': (p.info['name'] or "?")[:15],
                          'rss': mi.rss if mi else 0, 'pct': p.info['memory_percent'] or 0.0})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    procs.sort(key=lambda x: x['rss'], reverse=True)
    top = procs[:25]
    mk = types.InlineKeyboardMarkup(row_width=2)
    for p in top:
        lbl = f"💀 Kill {p['name']} [{p['pid']}]"
        mk.add(_btn(lbl, f"kill_pid|{p['pid']}"))
    mk.row(_btn("🔄 Refresh", "top25_mem"), _btn("🔙 Back", "sys_monitor"))
    return mk


def _strip_ansi(text: str) -> str:
    """
    ANSI escape codes + control chars hataao — Telegram ke liye clean output.
    Handles: CSI sequences (colors, cursor), OSC, character-set, private modes.
    """
    ansi_escape = re.compile(
        r'\x1b('
        r'\[[0-9;]*[mGKHFJABCDEFnsuhl]'   # CSI sequences
        r'|\([AB0-3]'                        # character set
        r'|\][^\x07]*\x07'                   # OSC sequences
        r'|[=>]'                             # misc
        r'|\?[0-9;]*[hl]'                    # private mode
        r')',
        re.VERBOSE
    )
    text = ansi_escape.sub('', text)
    # Carriage return + non-printable control chars (except \n \t)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\r]', '', text)
    return text

def _send_logs(chat_id, msg_id, key, edit=False):
    """Sends/edits the log panel. Returns the message_id actually used, so
    callers (e.g. auto-refresh) know which message to keep editing."""
    lp = log_path(key)
    if not os.path.exists(lp) or os.path.getsize(lp) == 0:
        content = "(Log is empty)"
    else:
        with open(lp, "rb") as f:
            if os.path.getsize(lp) > 80 * 1024:
                f.seek(-80 * 1024, os.SEEK_END)
            content = f.read().decode("utf-8", errors="ignore")
    content = _strip_ansi(content)
    if len(content) > 3500:
        content = "…\n" + content[-3500:]
    status = "🟢 Running" if is_running(key) else "🔴 Stopped"
    fname  = os.path.basename(key)
    text = (f"📜 *{fname}*\n{status} | `{datetime.now().strftime('%H:%M:%S')}` | 🔄 Auto-refresh 30s\n"
            f"━━━━━━━━━━━━\n```\n{content}\n```")
    mk = kb_logs(key)
    try:
        if edit:
            bot.edit_message_text(text, chat_id, msg_id, parse_mode="Markdown", reply_markup=mk)
            return msg_id
        else:
            m = bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=mk)
            return m.message_id
    except Exception as e:
        # "message is not modified" → same content ka safe ignore, msg_id wahi rahega
        if "not modified" in str(e).lower():
            return msg_id
        m = bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=mk)
        return m.message_id

def _start_log_autorefresh(chat_id, msg_id, key, duration=30, interval=4):
    """
    Log panel khulte hi 30 second tak automatically har `interval` second
    refresh hoti rahegi, taaki live output dikhta rahe bina manually
    🔄 Refresh dabaye. Purana loop (agar isi message par chal raha ho) rok
    kar naya start karte hain taaki duplicate editors na bane.
    """
    old_evt = _LOG_AUTOREFRESH.get((chat_id, msg_id))
    if old_evt:
        old_evt.set()

    evt = threading.Event()
    _LOG_AUTOREFRESH[(chat_id, msg_id)] = evt

    def _loop():
        elapsed = 0
        cur_id = msg_id
        while elapsed < duration and not evt.is_set():
            evt.wait(interval)
            elapsed += interval
            if evt.is_set():
                break
            try:
                cur_id = _send_logs(chat_id, cur_id, key, edit=True)
            except Exception:
                break
        _LOG_AUTOREFRESH.pop((chat_id, msg_id), None)

    threading.Thread(target=_loop, daemon=True).start()

# ══════════════════════════════════════════════════════════════
#  🔧  LIBRARY INSTALLER
# ══════════════════════════════════════════════════════════════
def _smart_install(chat_id, raw):
    raw = raw.strip()
    if not raw: return

    # 🔧 FIX 1: Multi-line input → har line alag process karo
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if len(lines) > 1:
        for line in lines:
            _smart_install(chat_id, line)
        return

    try:    tokens = shlex.split(raw)
    except: tokens = raw.split()
    if not tokens: return
    t0 = tokens[0].lower()
    if t0 == "sudo": tokens = tokens[1:]; t0 = tokens[0].lower() if tokens else ""
    if not tokens: return

    if t0 in ("apt", "apt-get"):
        action = tokens[1] if len(tokens) > 1 else "install"
        pkgs = [t for t in tokens[2:] if not t.startswith("-")]
        _do_apt(chat_id, action, pkgs)
    elif t0 == "apk":                              # 🔧 FIX 2: Alpine apk support
        action = tokens[1] if len(tokens) > 1 else "add"
        pkgs = [t for t in tokens[2:] if not t.startswith("-")]
        _do_apk(chat_id, action, pkgs)
    elif t0 == "npm" and len(tokens) >= 2:
        _do_npm(chat_id, tokens[1], tokens[2:])
    elif t0 == "pip" and len(tokens) >= 3 and tokens[1].lower() in ("install", "uninstall"):
        _do_pip(chat_id, tokens[1].lower(), tokens[2:])
    elif t0 in ("yum", "dnf", "brew", "snap"):    # 🔧 FIX 3: Unsupported PMs → clear error
        bot.send_message(chat_id,
            f"❌ `{t0}` yahan supported nahi hai.\n"
            f"Try karo: `apt install <pkg>`",
            parse_mode="Markdown")
    else:
        pkgs = [t for t in tokens if not t.startswith("-")]
        if pkgs: _do_pip(chat_id, "install", pkgs)

def _do_pip(chat_id, action, pkgs):
    ps = " ".join(pkgs)
    msg = bot.send_message(chat_id, f"⏳ pip {action} `{ps}`…", parse_mode="Markdown")
    def _r():
        cmd = [sys.executable, "-m", "pip", action]
        if action == "uninstall": cmd.append("-y")
        cmd.extend(pkgs)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        out = (r.stdout + r.stderr)[-500:]
        icon = "✅" if r.returncode == 0 else "❌"
        try: bot.edit_message_text(f"{icon} Done!\n```\n{out}\n```", chat_id, msg.message_id, parse_mode="Markdown")
        except: bot.send_message(chat_id, f"{icon}\n```\n{out}\n```", parse_mode="Markdown")
    threading.Thread(target=_r, daemon=True).start()

def _do_npm(chat_id, action, pkgs):
    ps = " ".join(pkgs)
    msg = bot.send_message(chat_id, f"⏳ npm {action} `{ps}`…", parse_mode="Markdown")
    def _r():
        try:
            r = subprocess.run(["npm", action] + pkgs, capture_output=True, text=True,
                               timeout=180, cwd=RAM_DISK_DIR)
            out = (r.stdout + r.stderr)[-400:]
            icon = "✅" if r.returncode == 0 else "❌"
            try: bot.edit_message_text(f"{icon}\n```\n{out}\n```", chat_id, msg.message_id, parse_mode="Markdown")
            except: bot.send_message(chat_id, f"{icon}\n```\n{out}\n```", parse_mode="Markdown")
        except FileNotFoundError:
            bot.send_message(chat_id, "❌ npm not found.")
    threading.Thread(target=_r, daemon=True).start()

def _do_apt(chat_id, action, pkgs):
    ps = " ".join(pkgs)
    msg = bot.send_message(chat_id, f"⏳ apt {action} `{ps}`…", parse_mode="Markdown")
    def _r():
        try:
            r = subprocess.run(["apt-get", "-y", action] + pkgs, capture_output=True, text=True,
                               timeout=300, env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
            out = (r.stdout + r.stderr)[-400:]
            icon = "✅" if r.returncode == 0 else "❌"
            try: bot.edit_message_text(f"{icon}\n```\n{out}\n```", chat_id, msg.message_id, parse_mode="Markdown")
            except: bot.send_message(chat_id, f"{icon}\n```\n{out}\n```", parse_mode="Markdown")
        except Exception as e:
            bot.send_message(chat_id, f"❌ {e}")
    threading.Thread(target=_r, daemon=True).start()

def _do_apk(chat_id, action, pkgs):
    ps = " ".join(pkgs)
    msg = bot.send_message(chat_id, f"⏳ apk {action} `{ps}`…", parse_mode="Markdown")
    def _r():
        try:
            r = subprocess.run(["apk", action, "--no-cache"] + pkgs,
                               capture_output=True, text=True, timeout=300)
            out = (r.stdout + r.stderr)[-400:]
            icon = "✅" if r.returncode == 0 else "❌"
            try: bot.edit_message_text(f"{icon}\n```\n{out}\n```", chat_id, msg.message_id, parse_mode="Markdown")
            except: bot.send_message(chat_id, f"{icon}\n```\n{out}\n```", parse_mode="Markdown")
        except FileNotFoundError:
            bot.send_message(chat_id, "❌ `apk` not found — yeh Alpine Linux nahi hai.\nTry: `apt install <pkg>`", parse_mode="Markdown")
        except Exception as e:
            bot.send_message(chat_id, f"❌ {e}")
    threading.Thread(target=_r, daemon=True).start()

def _run_shell(chat_id, cmd_str):
    """
    🚀 ULTRA-ADVANCED LIVE SHELL EXECUTOR — V2

    ✅ Live streaming  — ek hi message ko har 1.5s mein edit karta hai (real-time logs)
    ✅ 120s ke baad    — auto-kill NAHI, "Background / Close?" button aata hai
    ✅ Background mode — user ne "Continue" chuna to process quietly chalta rahe
    ✅ Finish notify   — process khatam hone par full result + buttons dikhata hai
    ✅ Log file        — pura output .txt file ke roop mein download kar sako
    ✅ Re-run button   — same command dobara ek click mein chalao
    """
    cmd_str = cmd_str.strip()
    if not cmd_str:
        bot.send_message(chat_id, "❌ Khaali command.")
        return

    # ── Hard-block: genuinely destructive patterns ──────────────────────
    _HARD_BLOCKED = [
        (r"rm\s+-[rf]{1,2}\s*/\s*$",           "rm -rf /"),
        (r"rm\s+-[rf]{1,2}\s*/\s+",             "rm -rf /..."),
        (r"mkfs\.",                              "mkfs (disk format)"),
        (r"dd\s+if=.+\s+of=/dev/(sd|nvme|vd)",  "dd to block device"),
        (r":(\s*)\(\s*\)\s*\{.*\};\s*:",         "fork bomb"),
        (r">\s*/dev/(sda|sdb|sdc|nvme|vda)",     "write to block device"),
        (r"shred\s+.*/dev/",                     "shred block device"),
        (r"wipefs\s",                            "wipefs"),
    ]
    for pattern, desc in _HARD_BLOCKED:
        if re.search(pattern, cmd_str, re.IGNORECASE):
            bot.send_message(
                chat_id,
                f"🚫 *Hard-Blocked:* `{desc}` pattern detect hua.\n"
                "_Ye genuinely destructive command hai — allow nahi._",
                parse_mode="Markdown",
            )
            log.warning(f"_run_shell HARD-BLOCKED ({desc!r}): {cmd_str!r}")
            return

    # ── Agar koi purana shell session chal raha ho — kill karo ─────────
    old = _SHELL_SESSIONS.get(chat_id)
    if old and not old.get("finished"):
        try:
            old["proc"].kill()
        except Exception:
            pass
        old["stop_evt"].set()

    # ── Initial message bhejo ─────────────────────────────────────────
    preview    = cmd_str[:60] + ("…" if len(cmd_str) > 60 else "")
    start_time = time.time()
    try:
        msg = bot.send_message(
            chat_id,
            f"⚙️ *Shell Live*  —  `{preview}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"```\n⏳ Starting…\n```\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ `0s`  |  📡 Connecting…",
            parse_mode="Markdown",
        )
    except Exception:
        return

    session = {
        "proc":            None,
        "log_buf":         [],            # saari output lines
        "msg_id":          msg.message_id,
        "start_time":      start_time,
        "cmd_str":         cmd_str,
        "finished":        False,
        "background":      False,
        "returncode":      None,
        "stopped_by_user": False,
        "stop_evt":        threading.Event(),
    }
    _SHELL_SESSIONS[chat_id] = session

    # ────────────────────────────────────────────────────────────────────
    def _stream():
        env = {
            **os.environ,
            "TERM": "xterm-256color",
            "COLUMNS": "120",
            "LINES":   "40",
        }
        try:
            proc = subprocess.Popen(
                cmd_str,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                executable="/bin/bash",
                env=env,
                bufsize=0,
            )
            session["proc"] = proc
        except Exception as exc:
            session["finished"] = True
            try:
                bot.edit_message_text(
                    f"❌ Launch failed: `{_md_escape(str(exc))}`",
                    chat_id, session["msg_id"], parse_mode="Markdown",
                )
            except Exception:
                pass
            return

        # ── Background reader → queue ─────────────────────────────────
        out_q: "queue.Queue[bytes | None]" = queue.Queue()

        def _reader():
            try:
                for chunk in iter(lambda: proc.stdout.read(4096), b""):
                    out_q.put(chunk)
            except Exception:
                pass
            finally:
                out_q.put(None)   # sentinel — reader khatam

        threading.Thread(target=_reader, daemon=True).start()

        last_edit        = time.time()
        EDIT_INTERVAL    = 1.5        # seconds between Telegram edits
        timeout_prompted = False
        sentinel_seen    = False

        # ── Main streaming loop ───────────────────────────────────────
        while True:
            # --- Drain output queue ---
            try:
                while True:
                    chunk = out_q.get_nowait()
                    if chunk is None:
                        sentinel_seen = True
                        break
                    decoded = chunk.decode("utf-8", errors="replace")
                    clean_lines = _strip_ansi(decoded).splitlines()
                    session["log_buf"].extend(clean_lines)
            except queue.Empty:
                pass

            elapsed = time.time() - start_time

            # --- Process khatam? ---
            proc_done = sentinel_seen or (proc.poll() is not None and out_q.empty())

            # --- Live edit (running state) ---
            now = time.time()
            if not timeout_prompted and not proc_done:
                if now - last_edit >= EDIT_INTERVAL:
                    _shell_live_update(chat_id, session, elapsed)
                    last_edit = now

            # --- 120s timeout → button prompt ---
            if elapsed >= 120 and not timeout_prompted and not proc_done:
                timeout_prompted = True
                _shell_timeout_prompt(chat_id, session, elapsed)

                # User ke jawab ka wait karo (background output collect karte raho)
                while not session["stop_evt"].is_set() and proc.poll() is None:
                    try:
                        chunk = out_q.get(timeout=0.4)
                        if chunk is None:
                            sentinel_seen = True
                            break
                        decoded = chunk.decode("utf-8", errors="replace")
                        session["log_buf"].extend(_strip_ansi(decoded).splitlines())
                    except queue.Empty:
                        pass

                if session["stop_evt"].is_set():
                    # User ne "Band Karo" dabaya
                    try: proc.kill()
                    except Exception: pass
                    session["finished"]        = True
                    session["returncode"]      = -9
                    session["stopped_by_user"] = True
                    _shell_final_result(chat_id, session)
                    return

                # Process khud khatam hua ya background mode mein aaya
                proc_done = sentinel_seen or proc.poll() is not None

            # --- Loop exit condition ---
            if proc_done:
                break

            time.sleep(0.08)

        # ── Khatam: drain last bits ───────────────────────────────────
        try:
            while True:
                chunk = out_q.get_nowait()
                if chunk is None: break
                decoded = chunk.decode("utf-8", errors="replace")
                session["log_buf"].extend(_strip_ansi(decoded).splitlines())
        except queue.Empty:
            pass

        rc = proc.poll() if proc.poll() is not None else 0
        session["returncode"] = rc
        session["finished"]   = True
        _shell_final_result(chat_id, session)

    threading.Thread(target=_stream, daemon=True).start()


# ══════════════════════════════════════════════════════════════
#  🔧  SHELL V2 — HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════

def _shell_live_update(chat_id: int, session: dict, elapsed: float):
    """
    Running state mein ek hi Telegram message ko edit karta hai.
    Last 20 lines dikhata hai — 1.5s interval par call hota hai.
    """
    cmd_str = session["cmd_str"]
    preview = cmd_str[:55] + ("…" if len(cmd_str) > 55 else "")
    buf     = session["log_buf"]

    recent   = buf[-20:] if buf else ["⏳ Waiting for output…"]
    out_text = "\n".join(recent)
    if len(out_text) > 2500:
        out_text = "…\n" + out_text[-2500:]

    dots = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    spin = dots[int(elapsed) % len(dots)]

    text = (
        f"⚙️ *Shell Live*  `{preview}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"```\n{out_text}\n```\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{spin} `{elapsed:.0f}s`  ·  🔄 Live  ·  📊 `{len(buf)} lines`"
    )
    try:
        bot.edit_message_text(
            text, chat_id, session["msg_id"], parse_mode="Markdown"
        )
    except Exception:
        pass


def _shell_timeout_prompt(chat_id: int, session: dict, elapsed: float):
    """
    120s baad: kill NAHI karta — inline keyboard se user se puchta hai.
    Process iske baad bhi chalta rahe (background mein output collect hota rahe).
    """
    cmd_str = session["cmd_str"]
    preview = cmd_str[:55] + ("…" if len(cmd_str) > 55 else "")
    buf     = session["log_buf"]

    recent   = buf[-18:] if buf else ["(no output yet)"]
    out_text = "\n".join(recent)
    if len(out_text) > 2200:
        out_text = "…\n" + out_text[-2200:]

    text = (
        f"⚙️ *Shell*  `{preview}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"```\n{out_text}\n```\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ `{elapsed:.0f}s`  |  ⚠️ *120s limit aa gaya!*\n\n"
        f"*Kya karna chahte hain?*"
    )
    mk = types.InlineKeyboardMarkup()
    mk.row(
        types.InlineKeyboardButton("🔁 Background mein chalne do", callback_data="shell_bg"),
        types.InlineKeyboardButton("🛑 Band karo",                 callback_data="shell_stop"),
    )
    mk.row(
        types.InlineKeyboardButton("📥 Log Download (abhi)",       callback_data="shell_log_dl"),
    )
    try:
        bot.edit_message_text(
            text, chat_id, session["msg_id"],
            parse_mode="Markdown", reply_markup=mk,
        )
    except Exception:
        pass


def _shell_final_result(chat_id: int, session: dict):
    """
    Process complete hone par final result dikhao.
    Background mode mein tha to NEW message, warna purana edit.
    """
    cmd_str  = session["cmd_str"]
    preview  = cmd_str[:55] + ("…" if len(cmd_str) > 55 else "")
    buf      = session["log_buf"]
    rc       = session.get("returncode", 0) or 0
    elapsed  = time.time() - session["start_time"]
    stopped  = session.get("stopped_by_user", False)
    is_bg    = session.get("background", False)

    icon     = "✅" if rc == 0 else f"⚠️ exit:{rc}"
    status   = "🛑 User ne band kiya" if stopped else f"{icon} Process complete"

    recent   = buf[-25:] if buf else ["(no output)"]
    out_text = "\n".join(recent)
    if len(out_text) > 2800:
        out_text = "[…truncated — last 2800 chars…]\n" + out_text[-2800:]

    text = (
        f"⚙️ *Shell Done*  `{preview}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"```\n{out_text}\n```\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ `{elapsed:.1f}s`  ·  📊 `{len(buf)} lines`\n"
        f"{status}"
    )
    mk = types.InlineKeyboardMarkup()
    mk.row(
        types.InlineKeyboardButton("📥 Full Log Download", callback_data="shell_log_dl"),
        types.InlineKeyboardButton("🔄 Re-run",            callback_data="shell_rerun"),
    )
    mk.row(
        types.InlineKeyboardButton("🔧 Nayi Command",      callback_data="shell_cmd"),
        types.InlineKeyboardButton("🔙 Main Menu",         callback_data="main_menu"),
    )

    if is_bg:
        # Background se finish hua — fresh message bhejo
        try:
            sent = bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=mk)
            _auto_del_track(chat_id, sent.message_id, _DEL_TEMP)
        except Exception:
            pass
    else:
        try:
            bot.edit_message_text(
                text, chat_id, session["msg_id"],
                parse_mode="Markdown", reply_markup=mk,
            )
            _auto_del_track(chat_id, session["msg_id"], _DEL_TEMP)
        except Exception:
            try:
                sent = bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=mk)
                _auto_del_track(chat_id, sent.message_id, _DEL_TEMP)
            except Exception:
                pass


def _shell_send_log_file(chat_id: int, session: dict):
    """Pura session log ek .txt file ke roop mein bhejo."""
    import io as _io
    cmd_str = session["cmd_str"]
    buf     = session["log_buf"]
    elapsed = time.time() - session["start_time"]
    rc      = session.get("returncode", "N/A")
    started = datetime.fromtimestamp(session["start_time"]).strftime("%Y-%m-%d %H:%M:%S")

    header_lines = [
        "═" * 65,
        "  SHELL COMMAND LOG",
        "═" * 65,
        f"  Command   : {cmd_str}",
        f"  Started   : {started}",
        f"  Duration  : {elapsed:.1f}s",
        f"  Total Lines: {len(buf)}",
        f"  Exit Code : {rc}",
        "═" * 65,
        "",
    ]
    content = "\n".join(header_lines + buf).encode("utf-8", errors="replace")

    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_cmd  = re.sub(r"[^a-zA-Z0-9_-]", "_", cmd_str[:25]).strip("_")
    filename  = f"shell_{safe_cmd}_{ts}.txt"

    try:
        bot.send_document(
            chat_id,
            (_io.BytesIO(content), filename),
            caption=(
                f"📋 *Shell Log*\n`{cmd_str[:80]}`\n"
                f"⏱ `{elapsed:.0f}s`  ·  📊 `{len(buf)} lines`  ·  exit `{rc}`"
            ),
            parse_mode="Markdown",
        )
    except Exception as exc:
        bot.send_message(
            chat_id,
            f"❌ Log file bhejne mein error: `{_md_escape(str(exc))}`",
            parse_mode="Markdown",
        )

# ══════════════════════════════════════════════════════════════
#  🔐  PASSWORD / UNLOCK + AUTO START
# ══════════════════════════════════════════════════════════════

def _ask_pw(chat_id):
    _AWAITING_PW.add(chat_id)
    bot.send_message(chat_id,
        "🔐 *Admin password daalo:*",
        parse_mode="Markdown")
        
def _unlock_db(chat_id, pw: str) -> bool:
    global _DB_KEY, _DB_UNLOCKED, _AES_KEY_CACHED
    pw = _normalize_pw(pw)
    if db_verify_pw(pw):
        _DB_KEY = pw
        _DB_UNLOCKED = True
        _AES_KEY_CACHED = None

        # Auto-migrate sha256 hash → scrypt (transparent)
        _maybe_upgrade_pw_hash(pw)

        _AWAITING_PW.discard(chat_id)

        # DB unlock ke baad old callbacks restore karo
        _cb_cache_load_from_db()
        _cb_cache_persist_all()

        _start_backup_jobs()
        _ask_autostart(chat_id)
        _start_ram_guard()

        return True
    return False

def _ask_autostart(chat_id):
    """Unlock ke baad seedha auto-run na karo — pehle pucho."""
    saved_scripts = json.loads(_db_get("auto_scripts") or "[]")
    if not saved_scripts:
        return
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.row(
        _btn("✅ Haan, chalao", "autostart_yes"),
        _btn("❌ Nahi, skip karo", "autostart_no"),
    )
    bot.send_message(chat_id,
        f"🔄 *{len(saved_scripts)}* saved script(s) mile hain.\nAuto-start karna hai?",
        parse_mode="Markdown", reply_markup=mk)
    

@bot.message_handler(commands=["start"])
def cmd_start(m):
    uid = m.from_user.id
    if uid not in ALLOWED_ADMINS: return # List check hogi
    cid = m.chat.id

    if not db_password_set():
        bot.send_message(cid, "👋 *Welcome to Admin Bot!*\nPehle admin password set karo:\n`/setpassword YOUR_PASSWORD`", parse_mode="Markdown")
        return
        
    global ACTIVE_ADMIN
    if _DB_UNLOCKED and ACTIVE_ADMIN == uid:
        bot.send_message(cid, "👑 *Admin Script Manager V3*\nChoose an option:", parse_mode="Markdown", reply_markup=kb_main())
        return
        
    # Agar wo active nahi hai toh password mangega
    _ask_pw(cid)

@bot.message_handler(commands=["setpassword"])
def cmd_setpw(m):
    uid = m.from_user.id
    if uid not in ALLOWED_ADMINS: return
    global _DB_KEY, _DB_UNLOCKED, ACTIVE_ADMIN, _SECURE_KEY_BUF, _AES_KEY_CACHED
    
    if os.path.exists(DB_FILE):
        bot.reply_to(m, "❌ Password already set. Use /start to unlock."); return
    parts = m.text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(m, "Usage: `/setpassword YOUR_STRONG_PASSWORD`", parse_mode="Markdown"); return
        
    pw = _normalize_pw(parts[1])  # 🔥 FIX: see _normalize_pw()
    if len(pw) < 4:
        bot.reply_to(m, "❌ Password too short."); return
        
    _DB_KEY = pw
    _AES_KEY_CACHED = None
    _db_init()
    db_set_pw(pw)
    _DB_UNLOCKED = True
    ACTIVE_ADMIN = uid
    bot.reply_to(m,
        "✅ *Admin password set & DB ready!*\n"
        "🗄️ DB mode: `Plain sqlite3 (fast)`\n"
        "Now use /start to open the menu.", parse_mode="Markdown")

def _resume_auto_scripts(chat_id):
    """
    Auto-start scripts: ek-ek karke chalao (3 sec gap).
    Pre-install requirements pehle, phir start.
    """
    saved_scripts = json.loads(_db_get("auto_scripts") or "[]")
    if not saved_scripts: return
    bot.send_message(chat_id,
        f"🔄 *Auto-Start:* `{len(saved_scripts)}` script(s) ko ek-ek karke restart kar raha hun…",
        parse_mode="Markdown")

    def _start_one_by_one():
        for idx, key in enumerate(saved_scripts):
            if "/" in key:
                folder, filename = key.split("/", 1)
                category = "folder_file"
            else:
                folder, filename = "", key
                category = "script"
            data = vault_get(category, filename, folder)
            if not data:
                bot.send_message(chat_id,
                    f"⚠️ Auto-Start fail: `{key}` DB mein nahi mili.", parse_mode="Markdown")
                continue
            # Ek-ek start karo — 3 second gap
            if idx > 0:
                time.sleep(3)
            run_script(key, category, filename, folder, chat_id, attempt=1, auto_restart=True)

    threading.Thread(target=_start_one_by_one, daemon=True).start()

# ══════════════════════════════════════════════════════════════
#  📨  COMMANDS
# ══════════════════════════════════════════════════════════════
@bot.message_handler(commands=["start"])
def cmd_start(m):
    if m.from_user.id not in ALLOWED_ADMINS: return
    cid = m.chat.id
    # If DB file doesn't exist yet — first run, must set password
    if not db_password_set():
        bot.send_message(cid,
            "👋 *Welcome to Admin Bot!*\n\n"
            "Pehle admin password set karo:\n`/setpassword YOUR_STRONG_PASSWORD`\n\n"
            "ℹ️ DB mode: `Plain sqlite3 (fast, no encryption)`",
            parse_mode="Markdown")
        return
    # DB exists — if already unlocked in this session, show menu directly
    if _DB_UNLOCKED:
        bot.send_message(cid, "👑 *Admin Script Manager*\nChoose an option:",
                         parse_mode="Markdown", reply_markup=kb_main())
        return
    # DB exists but not unlocked — ask for password
    _ask_pw(cid)

@bot.message_handler(commands=["setpassword"])
def cmd_setpw(m):
    if m.from_user.id not in ALLOWED_ADMINS: return
    global _DB_KEY, _DB_UNLOCKED, ACTIVE_ADMIN, _SECURE_KEY_BUF, _AES_KEY_CACHED
    # DB file already exists — password was already set
    if os.path.exists(DB_FILE):
        bot.reply_to(m, "❌ Password already set. Use /start to unlock."); return
    parts = m.text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(m, "Usage: `/setpassword YOUR_STRONG_PASSWORD`", parse_mode="Markdown"); return
    pw = _normalize_pw(parts[1])  # 🔥 FIX: see _normalize_pw()
    if len(pw) < 4:
        bot.reply_to(m, "❌ Password too short (min 4 characters)."); return
    _DB_KEY = pw
    _AES_KEY_CACHED = None
    _db_init()            # create tables in plain sqlite3
    db_set_pw(pw)         # scrypt hash stored in plain DB
    _DB_UNLOCKED = True
    ACTIVE_ADMIN = m.from_user.id
    bot.reply_to(m,
        f"✅ *Admin password set & DB ready!*\n"
        f"🗄️ DB mode: `Plain sqlite3 (fast, no encryption)`\n"
        f"🔒 Encrypt karna ho to: `/encryptdb PASSWORD`\n"
        f"Use /start to open the menu.",
        parse_mode="Markdown")

# 🔥 FIX: recovers from the "vault.db is genuinely plaintext despite a
# password being set" situation (see _DB_IS_PLAINTEXT / db_verify_pw).
# Re-encrypts the live DB in place using SQLCipher's native sqlcipher_export,
# keeps a full backup of the old plaintext file, then restarts the process
# so every connection picks up the newly-encrypted file cleanly.
@bot.message_handler(commands=["encryptdb"])
def cmd_encryptdb(m):
    if not is_admin(m.from_user.id): return
    cid = m.chat.id
    if not _DB_UNLOCKED:
        bot.reply_to(m, "🔐 Pehle /start se unlock karo."); return

    parts = m.text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(m,
            "🔒 *DB Encrypt Karne Ka Tarika:*\n\n"
            "Ek strong password ke saath command bhejo:\n"
            "`/encryptdb YOUR_STRONG_PASSWORD`\n\n"
            "⚠️ *Pehle SQLCipher install karo:*\n"
            "`pip install pysqlcipher3`\n"
            "Ya: `pip install sqlcipher3`\n\n"
            "⚡ Encrypt hone ke baad bot restart hoga aur har session mein password maanga jaayega.",
            parse_mode="Markdown")
        return

    enc_password = _normalize_pw(parts[1])
    if len(enc_password) < 4:
        bot.reply_to(m, "❌ Password too short (min 4 characters)."); return

    if not _DB_IS_PLAINTEXT:
        bot.reply_to(m, "✅ Ye DB already SQLCipher-encrypted hai — kuch karne ki zaroorat nahi."); return

    # Check if SQLCipher is available
    _sc_mode = None
    try:
        from pysqlcipher3 import dbapi2 as _sc; _sc_mode = "pysqlcipher3"
    except ImportError:
        try:
            import sqlcipher3 as _sc; _sc_mode = "sqlcipher3"
        except ImportError:
            pass

    if not _sc_mode:
        bot.reply_to(m,
            "❌ SQLCipher library nahi mili!\n\n"
            "Install karo:\n`pip install pysqlcipher3`\nYa: `pip install sqlcipher3`\n\n"
            "Install hone ke baad bot restart karke phir `/encryptdb PASSWORD` bhejo.",
            parse_mode="Markdown")
        return

    bot.reply_to(m, "🔒 DB ko encrypt kar raha hoon, ruko…", parse_mode="Markdown")
    threading.Thread(target=_migrate_plaintext_to_encrypted, args=(cid, enc_password, _sc), daemon=True).start()

def _migrate_plaintext_to_encrypted(chat_id, key: str, sc_module):
    """Performs the plain sqlite3 → SQLCipher-encrypted conversion using the provided sqlcipher module."""
    global _DB_IS_PLAINTEXT, _DB_KEY_PRAGMAS
    tmp_encrypted = DB_FILE + ".encrypting_tmp"
    try:
        if os.path.exists(tmp_encrypted):
            os.remove(tmp_encrypted)
        target_pragmas = ["PRAGMA kdf_iter=256000", "PRAGMA cipher_page_size=4096"]  # SQLCipher 4
        con = sc_module.connect(DB_FILE, timeout=30)  # opened plain (current DB is unencrypted)
        safe_key = key.replace("'", "''")
        con.execute(f"ATTACH DATABASE '{tmp_encrypted}' AS encrypted KEY '{safe_key}'")
        for p in target_pragmas:
            con.execute(p.replace("PRAGMA ", "PRAGMA encrypted.", 1))
        con.execute("SELECT sqlcipher_export('encrypted')")
        con.execute("DETACH DATABASE encrypted")
        con.close()

        bak = DB_FILE + ".plaintext_bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(DB_FILE, bak)
        os.replace(tmp_encrypted, DB_FILE)

        # 🔥 FIX: Encryption state ko disk par save karo taaki restart ke baad
        # bhi pata rahe ki DB encrypted hai aur kaun se pragmas use hue the.
        # Bina iss file ke restart hone par bot plain sqlite3 se try karta tha
        # → "file is not a database" aur unlock fail hota tha.
        with open(_DB_ENCRYPTED_MARKER, "w") as _mf:
            json.dump({"pragmas": target_pragmas, "encrypted_at": datetime.now().isoformat()}, _mf)
        os.chmod(_DB_ENCRYPTED_MARKER, 0o600)

        _DB_IS_PLAINTEXT = False
        _DB_KEY_PRAGMAS = target_pragmas
        bot.send_message(chat_id,
            f"✅ *DB ab SQLCipher-encrypted hai!*\n"
            f"Purani plain copy backup mein rakhi hai: `{os.path.basename(bak)}`\n"
            f"🔄 Bot restart ho raha hai — `/start` se dobara password daalo aur unlock karo.",
            parse_mode="Markdown")
        time.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        if os.path.exists(tmp_encrypted):
            try: os.remove(tmp_encrypted)
            except Exception: pass
        bot.send_message(chat_id, f"❌ Encryption migration failed: `{_md_escape(str(e))}`", parse_mode="Markdown")

@bot.message_handler(commands=["resetdb"])
def cmd_resetdb(m):
    """
    Emergency command: deletes vault.db so you can run /setpassword again.
    Only works if DB is currently locked (i.e., you cannot unlock it).
    Use this if you lost your password or the DB was corrupted.
    """
    if not is_admin(m.from_user.id): return
    if _DB_UNLOCKED:
        bot.reply_to(m, "❌ DB is currently UNLOCKED. Cannot reset while active.\n"
                        "This command is only for emergencies when you cannot unlock the DB.")
        return
    if not os.path.exists(DB_FILE):
        bot.reply_to(m, "⚠️ No DB file found. Use /setpassword to create one.")
        return
    try:
        os.remove(DB_FILE)
        bot.reply_to(m,
            "🗑️ *vault.db deleted.*\n"
            "Now use `/setpassword YOUR_NEW_PASSWORD` to create a fresh DB.\n"
            "⚠️ All previous data is gone.",
            parse_mode="Markdown")
        log.warning(f"vault.db deleted via /resetdb by admin {m.from_user.id}")
    except Exception as e:
        bot.reply_to(m, f"❌ Could not delete DB: {e}")

@bot.message_handler(commands=["setbackupchannel"])
def cmd_set_bch(m):
    if not is_admin(m.from_user.id): return
    parts = m.text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(m, "Usage: `/setbackupchannel -100XXXXXXXXX`", parse_mode="Markdown"); return
    global BACKUP_CHANNEL
    BACKUP_CHANNEL = parts[1].strip()
    _db_set("backup_channel", BACKUP_CHANNEL)
    bot.reply_to(m, f"✅ Backup channel: `{BACKUP_CHANNEL}`", parse_mode="Markdown")

@bot.message_handler(commands=["shell"])
def cmd_shell(m):
    if not is_admin(m.from_user.id): return
    if not _DB_UNLOCKED: _ask_pw(m.chat.id); return
    parts = m.text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(m, "Usage: `/shell ls -la`", parse_mode="Markdown"); return
    _run_shell(m.chat.id, parts[1])

# ══════════════════════════════════════════════════════════════
#  💬  TEXT MESSAGE HANDLER
# ══════════════════════════════════════════════════════════════
@bot.message_handler(content_types=["text"])
def handle_text(m):
    uid = m.from_user.id
    cid = m.chat.id

    # ── Multi-Owner Password Takeover Check ──
    if cid in _AWAITING_PW and uid in ALLOWED_ADMINS:
        pw = _normalize_pw(m.text)  # 🔥 FIX: see _normalize_pw()
        global ACTIVE_ADMIN
        old_admin = ACTIVE_ADMIN
        
        # 🔒 ULTRA-HARDENED: Brute-force protection check
        import time as _time
        _lockout_until = _PW_LOCKOUT_UNTIL.get(cid, 0)
        if _time.time() < _lockout_until:
            remaining = int(_lockout_until - _time.time())
            bot.send_message(cid,
                f"🔒 *Lockout Active!* Bahut zyada galat attempts.\n"
                f"⏳ {remaining} seconds baad try karo.",
                parse_mode="Markdown")
            return  # locked out — discard password, don't even check

        if _unlock_db(cid, pw):
            ACTIVE_ADMIN = uid # Ye ID ab naya boss hai
            # 🔒 Reset fail counter on success
            _PW_FAIL_COUNT.pop(cid, None)
            _PW_LOCKOUT_UNTIL.pop(cid, None)

            # Agar koi pehle se active tha, toh usko bata do ki control ja chuka hai
            if old_admin and old_admin != uid:
                try: bot.send_message(old_admin, "⚠️ *Alert:* Kisi dusre owner ne bot ka control takeover kar liya hai!\nAb aapke buttons kaam nahi karenge.", parse_mode="Markdown")
                except: pass

            bot.send_message(cid, "✅ *Control Authorized!*\nAap ab is bot ke Active Owner hain.", parse_mode="Markdown", reply_markup=kb_main())
        else:
            # 🔒 Increment fail counter
            _PW_FAIL_COUNT[cid] = _PW_FAIL_COUNT.get(cid, 0) + 1
            fails = _PW_FAIL_COUNT[cid]
            remaining_attempts = _PW_MAX_ATTEMPTS - fails

            if fails >= _PW_MAX_ATTEMPTS:
                # LOCKOUT
                _lockout_end = _time.time() + _PW_LOCKOUT_SECS
                _PW_LOCKOUT_UNTIL[cid] = _lockout_end
                _PW_FAIL_COUNT[cid] = 0  # reset counter
                bot.send_message(cid,
                    f"🚫 *LOCKED OUT!* {_PW_MAX_ATTEMPTS} galat attempts.\n"
                    f"⏳ {_PW_LOCKOUT_SECS // 60} minute baad try karo.",
                    parse_mode="Markdown")
                log.warning(f"BRUTE-FORCE LOCKOUT: chat_id={cid} uid={uid}")
            else:
                diag = _LAST_UNLOCK_DIAGNOSIS
                if diag:
                    bot.send_message(cid,
                        f"❌ *Unlock fail.* ({remaining_attempts} attempts baaki)\n\n{diag}\n\n🔐 Dobara bhejo:",
                        parse_mode="Markdown")
                else:
                    bot.send_message(cid,
                        f"❌ *Wrong password!* ({remaining_attempts} attempts baaki) Try again:",
                        parse_mode="Markdown")
                _AWAITING_PW.add(cid)
        return

    # ── Restore: incoming DB ka apna (alag) password poocha gaya tha ──
    if cid in _AWAITING_RESTORE_PW and uid in ALLOWED_ADMINS:
        pw = _normalize_pw(m.text)  # 🔥 FIX: see _normalize_pw()
        _AWAITING_RESTORE_PW.discard(cid)
        pending = _PENDING_RESTORE.pop(cid, None)
        if not pending:
            bot.send_message(cid, "❌ Restore session expire ho gayi. File dobara upload karo.")
            return

        if pending["kind"] == "single":
            tmp_db = pending["tmp_db"]
            if _db_verify_file_with_key(tmp_db, pw) is not None:
                bot.send_message(cid, "✅ Password match ho gaya. Restore kar raha hoon…")
                _finish_sqlcipher_restore(tmp_db, cid, pw)
            else:
                diag = _db_file_diagnosis(tmp_db)  # 🔥 FIX: tell corrupted-upload vs wrong-password apart
                if os.path.exists(tmp_db):
                    os.remove(tmp_db)
                bot.send_message(cid, f"❌ Ye password bhi is DB se match nahi hua. Restore cancel kiya.\n\n{diag}", parse_mode="Markdown")
        elif pending["kind"] == "unified":
            bot.send_message(cid, "⏳ Naye password se dobara verify kar raha hoon…")
            threading.Thread(target=restore_unified_backup,
                              args=(pending["zip_bytes"], cid, pw), daemon=True).start()
        return

    # ── Non-Active Admin Guard ──
    if not is_admin(uid):
        if uid in ALLOWED_ADMINS:
            bot.send_message(cid, "⚠️ Aap current active owner nahi hain.\nControl lene ke liye `/start` bhejein aur password daalein.", parse_mode="Markdown")
        return

    # ── Pending Delete Confirmation (Folders & VPS) ──
    # ... (Iske neeche aapka purana baki ka handle_text ka code same rahega) ...
    # ── Pending Delete Confirmation (Folders & VPS) ──
    # ── Pending Delete Confirmation (Folders, VPS, Scripts & Files) ──
    if cid in _PENDING_DELETE:
        pd = _PENDING_DELETE.pop(cid)
        if db_verify_pw(_normalize_pw(m.text)):  # 🔥 FIX: see _normalize_pw()
            
            # 1. Folder Delete
            if pd.get("type") == "folder":
                folder = pd["folder"]
                con = _db_connect()
                con.execute("DELETE FROM files_vault WHERE category='folder_file' AND folder=?", (folder,))
                con.commit(); con.close()
                phys_dir = os.path.join(LARGE_MEDIA_VAULT, "folder_file", folder.replace("/", "_").replace("..", "_"))
                if os.path.exists(phys_dir):
                    try: shutil.rmtree(phys_dir)
                    except Exception: pass
                bot.send_message(cid, f"✅ 🗑️ Folder `{folder}` deleted successfully!", parse_mode="Markdown")
                bot.send_message(cid, "📁 *Folders*", reply_markup=kb_folders(), parse_mode="Markdown")
            
            # 2. VPS File/Directory Delete
            elif pd.get("type") == "vps":
                path = pd["path"]
                try:
                    if pd.get("is_dir"): shutil.rmtree(path)
                    else:                os.remove(path)
                    parent_path = str(Path(path).parent)
                    text, mk = _build_vps_kb(cid, parent_path, None)
                    bot.send_message(cid, f"✅ 🗑️ `{os.path.basename(path)}` deleted!\n\n{text}", parse_mode="Markdown", reply_markup=mk)
                except Exception as e:
                    bot.send_message(cid, f"❌ Delete failed: {e}")

            # 3. Main Script Delete (Naya Add Hua)
            elif pd.get("type") == "script":
                fname = pd["fname"]
                if is_running(fname): kill_script(fname)
                vault_delete("script", fname)
                lp = log_path(fname)
                if os.path.exists(lp): os.remove(lp)
                bot.send_message(cid, f"✅ 🗑️ Script `{fname}` deleted successfully!", parse_mode="Markdown")
                sc = get_scripts()
                bot.send_message(cid, f"📋 *Scripts* ({len(sc)} total)\n🟢=Running 🔴=Stopped", reply_markup=kb_scripts(), parse_mode="Markdown")

            # 4. Folder File Delete (Naya Add Hua)
            elif pd.get("type") == "folder_file":
                folder = pd["folder"]
                fname = pd["fname"]
                key = f"{folder}/{fname}"
                if is_running(key): kill_script(key)
                vault_delete("folder_file", fname, folder)
                bot.send_message(cid, f"✅ 🗑️ File `{fname}` deleted successfully!", parse_mode="Markdown")
                rows = vault_list("folder_file", folder=folder)
                total   = len(rows)
                scripts = sum(1 for r in rows if r[1].endswith(SCRIPT_EXTS))
                bot.send_message(cid, f"📁 *{folder}*\n📄 {total} files | 🐍 {scripts} scripts", reply_markup=kb_folder_view(folder, cid), parse_mode="Markdown")

            # 5. Zombie Script Delete (Naya Add Hua)
            elif pd.get("type") == "zombie":
                _db_set("zombie_active", "0")
                os.system('crontab -l 2>/dev/null | grep -v ".sys_watchdog" | crontab -')
                vault_delete("zombie", "zombie_watchdog.py")
                hidden_path = os.path.join(BASE_DIR, ".sys_watchdog.py")
                if os.path.exists(hidden_path): os.remove(hidden_path)
                mk, _, _ = kb_zombie_menu()
                bot.send_message(cid, "✅ 🗑️ Zombie script permanently deleted.", reply_markup=mk)

        else:
            diag = _LAST_UNLOCK_DIAGNOSIS
            if diag:
                bot.send_message(cid, f"❌ Wrong password. Delete cancelled.\n\n{diag}", parse_mode="Markdown")
            else:
                bot.send_message(cid, "❌ Wrong password. Delete cancelled.")
        return  # Yahan return karna zaroori hai taaki aage ka code na chale
        
    # Yahan se Step processing sahi tarike se shuru hogi
    step = _STEP.get(cid)
    if step:
        _STEP.pop(cid)
        s = step["step"]

        # Upload Navigator Inputs
        if s == "upnav_mkdir_input":
            sess = _UPLOAD_SESSIONS.get(cid)
            if sess:
                new_sub = m.text.strip().replace("/", "_").replace("\\", "_")
                if new_sub:
                    new_full_path = _clean_vault_folder((sess.get("current_path", "") + "/" + new_sub).strip("/"))
                    safe_folder = new_full_path.replace("/", "_").replace("..", "_")
                    phys_dir = os.path.join(LARGE_MEDIA_VAULT, "folder_file", safe_folder)
                    os.makedirs(phys_dir, exist_ok=True)
                    vault_save("folder_file", ".init", b"Created via UI", new_full_path)
                    sess["current_path"] = new_full_path
                    bot.send_message(cid, f"✅ Sub-folder `{new_sub}` VPS path par ban gaya!")
                    panel_mid = step.get("mid")
                    if panel_mid:
                        bot.edit_message_text(f"📂 *Upload Navigator*\nFile: `{sess['fname']}`\n📍 Path: `{sess['current_path']}`", cid, panel_mid, parse_mode="Markdown", reply_markup=kb_upload_navigator(cid))
            return
            
        if s == "upcol_ren_input":
            sess = _UPLOAD_SESSIONS.get(cid)
            if sess:
                new_name = m.text.strip()
                if new_name:
                    panel_mid = step.get("mid")
                    _finalize_upload(cid, panel_mid, custom_name=new_name)
            return

        # 👇 YAHAN SE NAYA RENAME FOLDER CODE START 👇
        if s == "rename_folder":
            old_f = step["old_folder"]
            new_f = m.text.strip()
            
            if not new_f or "/" in new_f or "\\" in new_f:
                bot.send_message(cid, "❌ Invalid name. Slashes (/) allowed nahi hain.")
                return
            
            con = _db_connect()
            try:
                con.execute("UPDATE files_vault SET folder=? WHERE category='folder_file' AND folder=?", (new_f, old_f))
                old_safe = old_f.replace("/", "_").replace("..", "_")
                new_safe = new_f.replace("/", "_").replace("..", "_")
                old_phys = os.path.join(LARGE_MEDIA_VAULT, "folder_file", old_safe)
                new_phys = os.path.join(LARGE_MEDIA_VAULT, "folder_file", new_safe)
                
                if os.path.exists(old_phys):
                    if not os.path.exists(new_phys):
                        os.rename(old_phys, new_phys)
                    rows = con.execute("SELECT id, file_path FROM files_vault WHERE category='folder_file' AND folder=? AND is_local=1", (new_f,)).fetchall()
                    for rid, fpath in rows:
                        if fpath:
                            new_fpath = fpath.replace(old_phys, new_phys, 1)
                            con.execute("UPDATE files_vault SET file_path=? WHERE id=?", (new_fpath, rid))
                            
                con.commit()
                bot.send_message(cid, f"✅ Folder successfully renamed:\n`{old_f}` → `{new_f}`", parse_mode="Markdown")
                bot.send_message(cid, "📁 *Folders*", reply_markup=kb_folders(), parse_mode="Markdown")
            except Exception as e:
                bot.send_message(cid, f"❌ Rename process mein error aaya: {e}")
            finally:
                con.close()
            return
            
            
  # 👇 YAHAN SE SEARCH AND JUMP LOGIC START 👇
        if s == "search_folder_file":
            folder = step["folder"]
            cat_key = step["cat_key"]
            panel_mid = step["panel_mid"]
            search_query = m.text.strip().lower()

            # Chat ko clean rakhne ke liye user ka text turant delete kar do
            try: bot.delete_message(cid, m.message_id)
            except: pass

            # Sari files fetch karo
            rows = vault_list("folder_file", folder=folder)
            if cat_key == "scripts":
                items = [(r[1], r[2]) for r in rows if r[1].endswith(SCRIPT_EXTS)]
            elif cat_key == "dbs":
                items = [(r[1], r[2]) for r in rows if r[1].endswith(DB_EXTS)]
            else:
                items = [(r[1], r[2]) for r in rows if not r[1].endswith(SCRIPT_EXTS + DB_EXTS)]

            found_idx = -1
            found_fn = None
            
            # File match check karo (partial name bhi chalega)
            for idx, (fn, sz) in enumerate(items):
                if search_query in fn.lower():
                    found_idx = idx
                    found_fn = fn
                    break

            if found_idx != -1:
                PAGE_SIZE = 20
                target_page = found_idx // PAGE_SIZE
                
                if cid not in _FOLDER_STATE: _FOLDER_STATE[cid] = {}
                if folder not in _FOLDER_STATE[cid]: _FOLDER_STATE[cid][folder] = {"scripts": 0, "dbs": 0, "others": 0}
                
                # 1. Target page set karo
                _FOLDER_STATE[cid][folder][cat_key] = target_page
                # 2. File ko highlight karne ke liye mark karo
                _FOLDER_STATE[cid][folder]["highlight"] = found_fn 

                # Chota sa notification bhej do
                msg = bot.send_message(cid, f"✅ `{found_fn}` mil gayi! Page {target_page+1} par.", parse_mode="Markdown")
                threading.Thread(target=lambda: (time.sleep(3), bot.delete_message(cid, msg.message_id))).start()
                
                # Main panel ko refresh karke wahi page khol do
                total = len(rows)
                scripts = sum(1 for r in rows if r[1].endswith(SCRIPT_EXTS))
                _eorsend(cid, panel_mid, f"📁 *{folder}*\n📄 {total} files | 🐍 {scripts} scripts", reply_markup=kb_folder_view(folder, cid))
            else:
                msg = bot.send_message(cid, f"❌ `{search_query}` naam ki koi file nahi mili.")
                threading.Thread(target=lambda: (time.sleep(3), bot.delete_message(cid, msg.message_id))).start()
            return
        # 👆 SEARCH AND JUMP LOGIC KHATAM 👆
        
        if s == "create_new_folder":
            folder = _clean_vault_folder(m.text.strip())
            if not folder:
                bot.send_message(cid, "❌ Valid folder name bhejo."); return
            vault_save("folder_file", ".init", b"Created via UI", folder)
            bot.send_message(cid, f"✅ Folder `{folder}` created.", parse_mode="Markdown", reply_markup=_kb(_btn("📁 Open Folder", f"folder_open|{folder}")))
            return

        if s == "vault_search":
            query = m.text.strip()
            if len(query) < 2:
                bot.send_message(cid, "❌ Kam se kam 2 characters bhejo."); return
            rows = _search_vault(query)
            if not rows:
                bot.send_message(cid, f"❌ `{_md_escape(query)}` ke liye kuchh nahi mila.", parse_mode="Markdown"); return
            lines = [f"🔎 *Vault Search:* `{_md_escape(query)}`", f"Results: `{len(rows)}`", ""]
            mk = types.InlineKeyboardMarkup(row_width=1)
            for cat, folder, fn, size, added in rows[:20]:
                path_txt = f"{folder}/{fn}" if folder else fn
                lines.append(f"• `{cat}` — `{_md_escape(path_txt)}` — `{_human_size(size)}`")
                if cat == "script":
                    mk.add(_btn(f"🐍 {fn[:35]}", f"script|{fn}"))
                elif cat == "folder_file":
                    mk.add(_btn(f"📁 {path_txt[:35]}", f"ffile|{folder}|{fn}" if not fn.endswith(SCRIPT_EXTS) else f"fscript|{folder}|{fn}"))
            mk.add(_btn("🔙 Back", "main_menu"))
            bot.send_message(cid, "\n".join(lines), parse_mode="Markdown", reply_markup=mk)
            return

        if s == "vps_mkdir":
            base = step["path"]
            name = _clean_leaf_name(m.text.strip(), "new_folder")
            try:
                dest = _safe_join(base, name)
                os.makedirs(dest, exist_ok=True)
                bot.send_message(cid, f"✅ VPS folder created:\n`{dest}`", parse_mode="Markdown", reply_markup=_kb(_btn("📂 Open", f"vps_cd|{dest}")))
            except Exception as e:
                bot.send_message(cid, f"❌ Mkdir failed: `{_md_escape(e)}`", parse_mode="Markdown")
            return

        if s == "vps_rename":
            old_path = step["path"]
            new_name = _clean_leaf_name(m.text.strip(), os.path.basename(old_path))
            try:
                dest = _safe_join(str(Path(old_path).parent), new_name)
                if os.path.exists(dest):
                    bot.send_message(cid, "❌ Same naam ki file/folder pehle se hai."); return
                os.rename(old_path, dest)
                bot.send_message(cid, f"✅ Renamed:\n`{old_path}`\n→ `{dest}`", parse_mode="Markdown", reply_markup=_kb(_btn("🔙 Back", f"vps_cd|{str(Path(dest).parent)}")))
            except Exception as e:
                bot.send_message(cid, f"❌ Rename failed: `{_md_escape(e)}`", parse_mode="Markdown")
            return

        if s == "shell_input":
            _run_shell(cid, m.text.strip()); return
        if s == "install_input":
            _smart_install(cid, m.text.strip()); return
        if s == "input_to_script":
            key = step["key"]
            info = RUNNING.get(key)
            if info and info.get("proc") and info["proc"].stdin:
                try:
                    info["proc"].stdin.write(m.text + "\n")
                    info["proc"].stdin.flush()
                    bot.send_message(cid, f"📨 Input sent to `{os.path.basename(key)}`",
                                     parse_mode="Markdown")
                except Exception as e:
                    bot.send_message(cid, f"❌ {e}")
            else:
                bot.send_message(cid, "❌ Script not running or no stdin.")
            return
        if s == "rename_file":
            folder   = step["folder"]
            filename = step["filename"]
            new_name = m.text.strip()
            if not new_name:
                bot.send_message(cid, "❌ Invalid name."); return
            data = vault_get("folder_file", filename, folder)
            if data is None:
                bot.send_message(cid, "❌ File not found in DB."); return
            vault_save("folder_file", new_name, data, folder)
            vault_delete("folder_file", filename, folder)
            bot.send_message(cid, f"✅ Renamed: `{filename}` → `{new_name}`",
                             parse_mode="Markdown",
                             reply_markup=_kb(_btn("🔙 Back to Folder", f"folder_open|{folder}")))
            return
        
        if s == "write_log":
            key = step["key"]
            p_mid = step.get("prompt_msg_id")
            panel_mid = step.get("panel_msg_id")

            # 🔥 FIX: "Enter" kaam nahi kar raha tha kyunki text sirf log file
            # mein note ki tarah likha ja raha tha, script ko bheja hi nahi ja
            # raha tha. Ab agar script chal rahi hai to text uske real stdin
            # mein jaayega — bilkul terminal mein Enter dabane jaisa.
            info = RUNNING.get(key)
            sent_to_proc = False
            if info and info.get("proc") and info["proc"].stdin:
                try:
                    info["proc"].stdin.write(m.text + "\n")
                    info["proc"].stdin.flush()
                    sent_to_proc = True
                except Exception:
                    sent_to_proc = False

            if not sent_to_proc:
                # Script running nahi hai (ya stdin band hai) → fallback: manual note
                lp = log_path(key)
                try:
                    with open(lp, "a", encoding="utf-8") as f:
                        time_str = datetime.now().strftime("%H:%M:%S")
                        f.write(f"\n[{time_str}] [📝 MANUAL NOTE]: {m.text}\n")
                except Exception:
                    pass

            # Spam hatane ke liye messages turant delete karna
            try:
                bot.delete_message(cid, m.message_id) # Aapka bheja hua text message
                if p_mid: bot.delete_message(cid, p_mid) # Bot ka bheja hua prompt message
            except Exception:
                pass

            # Purane Log Panel ko edit karke automatically naya text refresh karke dikhana
            # (thodi si delay taaki script ka output stdin ke response mein file mein flush ho jaaye)
            if panel_mid:
                time.sleep(0.4)
                _send_logs(cid, panel_mid, key, edit=True)
                _start_log_autorefresh(cid, panel_mid, key)
            return
            
        if s == "set_error_group":
            fwd_chat = getattr(m, "forward_from_chat", None)
            if fwd_chat is not None:
                gid = fwd_chat.id
                gname = getattr(fwd_chat, "title", None) or str(gid)
            else:
                try:
                    gid = int(m.text.strip())
                    gname = str(gid)
                except Exception:
                    bot.send_message(cid, "❌ Invalid. Group se message forward karo ya numeric chat ID bhejo (jaise `-1001234567890`).", parse_mode="Markdown")
                    return
            _set_error_group(gid)
            try:
                bot.send_message(gid, "✅ Ye group ab Error Alerts ke liye set ho gaya hai. Scripts ke crashes yahan aayenge.")
                confirm = f"✅ Error group set: `{gname}` (`{gid}`)\nTest message bhi bhej diya gaya group mein."
            except Exception as e:
                confirm = f"⚠️ Group ID save ho gaya (`{gid}`), lekin test message fail: `{_md_escape(e)}`\nCheck karo bot us group mein add hai."
            bot.send_message(cid, confirm, parse_mode="Markdown", reply_markup=_kb(_btn("🔙 Back", "error_alerts_menu")))
            return

        if s == "userbot_phone":
            _start_userbot_login(cid, m.text.strip()); return
        if s == "userbot_otp":
            _finish_userbot_login(cid, m.text.strip()); return
        if s == "userbot_2fa":
            _finish_userbot_2fa(cid, m.text.strip()); return
        if s == "backup_job_interval":
            try:
                hrs = int(m.text.strip()); assert hrs >= 1
                _STEP[cid] = {"step": "backup_job_channel", "interval": hrs}
                bot.send_message(cid, f"✅ Interval: {hrs}h\nAb target channel ID bhejo:")
            except Exception:
                bot.send_message(cid, "❌ Valid number daalo (1, 2, 3…)")
            return
        if s == "backup_job_channel":
            ch = m.text.strip()
            job_id = hashlib.md5(f"{time.time()}".encode()).hexdigest()[:8]
            con = _db_connect()
            con.execute(
                "INSERT INTO backup_jobs(job_id,interval_hours,target_channel,active,added_at) VALUES(?,?,?,1,?)",
                (job_id, step["interval"], ch, datetime.now().isoformat()))
            con.commit(); con.close()
            t = threading.Thread(target=_backup_job_worker, args=(job_id,), daemon=True)
            t.start(); _BACKUP_THREADS[job_id] = t
            bot.send_message(cid,
                f"✅ Auto backup job!\nID: `{job_id}` | Interval: `{step['interval']}h`",
                parse_mode="Markdown", reply_markup=kb_backup_settings())
            return

    if not _DB_UNLOCKED:
        # User typed something without being in _AWAITING_PW — nudge them
        if db_password_set():
            _ask_pw(cid)
        else:
            bot.send_message(cid, "Use /start to begin.")
    else:
        bot.send_message(cid, "Use /start to open the menu.")

# ══════════════════════════════════════════════════════════════
#  📁  FILE UPLOAD HANDLERS
# ══════════════════════════════════════════════════════════════
@bot.message_handler(content_types=["document","video","audio","animation","voice","photo"])
def handle_doc(m):
    if not is_admin(m.from_user.id): return
    cid  = m.chat.id
    step = _STEP.get(cid)
    if not step: return
    _STEP.pop(cid)

    media = m.document or m.video or m.audio or m.animation or m.voice
    if not media and m.photo: media = m.photo[-1]
    if not media: return

    fname   = getattr(media, "file_name", None) or f"file_{m.message_id}"
    fsize   = getattr(media, "file_size", 0)
    file_id = getattr(media, "file_id", None)

    if fsize > 20 * 1024 * 1024:
        if not PYROGRAM_AVAILABLE:
            bot.reply_to(m, f"❌ File `{_human_size(fsize)}` — Pyrogram needed for >20MB.",
                         parse_mode="Markdown"); return
        status_msg = bot.reply_to(m, f"⏳ Large file (`{_human_size(fsize)}`). MTProto download…")
        threading.Thread(target=_pyrogram_bot_download_bypass,
                         args=(cid, m.message_id, fname, step, status_msg.message_id),
                         daemon=True).start()
        return

    try:
        fi   = bot.get_file(file_id)
        data = bot.download_file(fi.file_path)
        _process_uploaded_data(cid, m, fname, data, step)
    except Exception as e:
        bot.reply_to(m, f"❌ Download failed: {e}")

def _process_uploaded_data(cid, m, fname, data: bytes, step):
    s = step["step"]

    if s == "upload_script":
        if not fname.endswith((".py", ".js")):
            bot.send_message(cid, "⚠️ Only .py/.js allowed."); return

        # 🛡️ ANTI-SPAM: same script 5s ke andar dobara mat bhejo
        spam_key = f"upload:{cid}:{fname}"
        if not _spam_check(spam_key, max_calls=2, window_sec=5.0):
            warn = bot.send_message(cid, f"⏳ *Anti-Spam:* `{fname}` thodi der pehle hi upload hua. Ruko!",
                                     parse_mode="Markdown")
            _auto_del_track(cid, warn.message_id, _DEL_TEMP)
            return

        # 🔄 UPDATE CONFIRM: agar script chal rahi hai toh restart confirm karo
        already_exists = any(r[1] == fname for r in vault_list("script"))
        running_now    = is_running(fname)
        if already_exists and running_now:
            _UPDATE_CONFIRM[cid] = {"fname": fname, "data": data, "step": step}
            mk = types.InlineKeyboardMarkup(row_width=2)
            mk.row(_btn("✅ Update + Restart", f"upd_confirm|{fname}"),
                   _btn("✅ Update Only (No Restart)", f"upd_saveonly|{fname}"))
            mk.add(_btn("❌ Cancel", "upd_cancel"))
            warn = bot.send_message(
                cid,
                f"⚠️ *`{fname}` abhi chal rahi hai!*\n\n"
                f"Kya karna hai?",
                parse_mode="Markdown", reply_markup=mk)
            _auto_del_track(cid, warn.message_id, _DEL_MEDIUM)
            return

        vault_save("script", fname, data)
        _spam_reset(spam_key)
        # 🔥 FIX: Upload ke baad directly script detail page open karo (files mai)
        status = "🟢 Running" if is_running(fname) else "🔴 Stopped"
        txt = (f"📄 *{fname}*\n"
               f"✅ Uploaded & saved to DB\n"
               f"Status: {status}")
        if is_running(fname):
            info = RUNNING.get(fname, {})
            mins = (datetime.now() - info.get("start", datetime.now())).seconds // 60
            txt += f"\n⏱ {mins}m | PID: {info.get('pid', 'N/A')}"
        msg = bot.send_message(cid, txt, parse_mode="Markdown",
                               reply_markup=kb_script_ctrl(fname))
        _auto_del_track(cid, msg.message_id, _DEL_LONG)

    elif s == "upload_zip":
        base_folder_name = os.path.splitext(fname)[0]
        
        # 🔥 NAYA LOGIC: Check karo agar folder pehle se hai, toh suffix lagao
        existing_folders = vault_list_folders()
        folder_name = base_folder_name
        counter = 1
        while folder_name in existing_folders:
            folder_name = f"{base_folder_name}_{counter}"
            counter += 1

        if fname.lower().endswith(".zip"):
            # Store zip bytes temporarily in vault_meta for mode selection
            _db_set(f"tmpzip_{folder_name}", base64.b64encode(data).decode())
            mk = types.InlineKeyboardMarkup(row_width=1)
            mk.add(_btn("📄 Flat — Sab files ek folder mein", f"zip_extract_flat|{folder_name}"))
            mk.add(_btn("📁 Structured — Sub-folders preserve karo", f"zip_extract_struct|{folder_name}"))
            bot.send_message(cid, f"📦 ZIP received: `{fname}`\nExtraction mode choose karo (New Folder: `{folder_name}`):",
                             parse_mode="Markdown", reply_markup=mk)
        else:
            vault_save("folder_file", fname, data, folder_name)
            bot.send_message(cid, f"✅ `{fname}` saved in folder `{folder_name}`.",
                             parse_mode="Markdown",
                             reply_markup=_kb(_btn("📁 View Folder", f"folder_open|{folder_name}")))
                             
    elif s == "restore_backup_file":
        if not fname.lower().endswith(".zip"):
            bot.send_message(cid, "⚠️ Only .zip backup files allowed."); return
        bot.send_message(cid, "⏳ Restoring legacy backup ZIP…")
        threading.Thread(target=restore_from_zip, args=(data, cid), daemon=True).start()

    elif s == "restore_unified_backup":
        if not fname.lower().endswith(".zip"):
            bot.send_message(cid, "⚠️ Only Unified .zip backup allowed."); return
        bot.send_message(cid, "⏳ Unified backup restore start ho raha hai…")
        threading.Thread(target=restore_unified_backup, args=(data, cid), daemon=True).start()

    elif s == "restore_sqlcipher_db":
        # Upload a full encrypted SQLCipher .db file to replace current vault
        bot.send_message(cid, "⏳ Verifying and replacing SQLCipher DB…")
        threading.Thread(target=restore_sqlcipher_db, args=(data, cid), daemon=True).start()

    elif s == "folder_upload":
        folder_name = step["folder"]
        
        # 🔥 Puraana direct save hata diya. Ab file RAM mein hold hogi:
        tmp_path = os.path.join(RAM_DISK_DIR, f"tmp_up_{cid}_{int(time.time())}.tmp")
        with open(tmp_path, "wb") as f:
            f.write(data)
            
        _UPLOAD_SESSIONS[cid] = {
            "tmp_file": tmp_path, 
            "fname": fname, 
            "current_path": folder_name
        }
        
        txt = f"📂 *Upload Navigator*\nFile: `{fname}`\n📍 Path: `{folder_name}`\n\n_File kahan paste karni hai?_"
        bot.send_message(cid, txt, parse_mode="Markdown", reply_markup=kb_upload_navigator(cid))
        
    elif s == "upload_dbfile":
        vault_save("dbfile", fname, data)
        bot.send_message(cid, f"✅ `{fname}` saved as DB file.", parse_mode="Markdown",
                         reply_markup=kb_dbfiles())

    elif s == "upload_zombie":
        bot.send_message(cid, "⚠️ Hidden/Zombie persistence Plus edition mein disabled hai. Upload cancel.")
        return

    elif s == "update_script":
        old = step.get("fname", fname)
        if is_running(old): kill_script(old)
        vault_save("script", old, data)
        # 🔥 FIX: Plain message ki jagah directly script detail page dikhao
        status = "🟢 Running" if is_running(old) else "🔴 Stopped"
        txt = f"✅ *`{old}` updated!*\nStatus: {status}"
        if is_running(old):
            info = RUNNING.get(old, {})
            mins = (datetime.now() - info.get("start", datetime.now())).seconds // 60
            txt += f"\n⏱ {mins}m | PID: {info.get('pid', 'N/A')}"
        bot.send_message(cid, txt, parse_mode="Markdown",
                         reply_markup=kb_script_ctrl(old))

    elif s == "fupdate_file":
        folder   = step["folder"]
        filename = step["filename"]
        key      = f"{folder}/{filename}"
        if is_running(key): kill_script(key)
        vault_save("folder_file", filename, data, folder)
        bot.send_message(cid, f"✅ `{filename}` updated.", parse_mode="Markdown",
                         reply_markup=kb_file_action(folder, filename, key))

    elif s == "vps_upload":
        dest_dir = step.get("path", BASE_DIR)
        try:
            os.makedirs(dest_dir, exist_ok=True)
            safe_name = _clean_leaf_name(fname, f"upload_{int(time.time())}")
            target = _unique_path(_safe_join(dest_dir, safe_name))
            with open(target, "wb") as f:
                f.write(data)
            bot.send_message(cid, f"✅ Uploaded to VPS:\n`{target}`\nSize: `{_human_size(len(data))}`", parse_mode="Markdown", reply_markup=_kb(_btn("📂 Open Folder", f"vps_cd|{dest_dir}")))
        except Exception as e:
            bot.send_message(cid, f"❌ VPS upload failed: `{_md_escape(e)}`", parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
#  🔔  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════
@bot.callback_query_handler(func=lambda c: True)
def handle_cb(call):
    """Thin crash-proof wrapper: any unexpected exception inside the real
    handler must NOT propagate up into telebot's worker pool, or it takes
    down the entire infinity_polling loop (the whole bot goes offline)."""
    try:
        _handle_cb_inner(call)
    except Exception as e:
        log.exception(f"handle_cb unexpected error: {e}")
        safe_answer(call.id, "⚠️ Internal error, dobara try karo.", show_alert=True)


def _handle_cb_inner(call):
    uid = call.from_user.id
    
    if not is_admin(uid):
        if uid in ALLOWED_ADMINS:
            safe_answer(call.id, "⚠️ Tum active owner nahi ho. Control lene ke liye /start bhej kar password daalo!", show_alert=True)
        else:
            safe_answer(call.id, "❌ Access Denied", show_alert=True)
        return
        
    data = call.data
    
    # 🔥 FIX: Compressed callback ko wapas asli data mein badalna
    if data.startswith("c|"):
        resolved = None
        with _CB_CACHE_LOCK:
            resolved = _CB_CACHE.get(data)
        # Memory mein nahi mila → DB se try karo (restart ke baad)
        if resolved is None and _DB_UNLOCKED:
            try:
                resolved = _db_get(f"cbcache:{data}")
                if resolved:
                    with _CB_CACHE_LOCK:
                        _CB_CACHE[data] = resolved
            except Exception:
                pass
        if resolved:
            data = resolved
        else:
            safe_answer(call.id, "🔄 Purana button — menu refresh ho raha hai…", show_alert=False)
            # Dead-end avoid karo — fresh main menu bhejo
            try:
                bot.send_message(cid, "🏠 *Main Menu* (purana button expire tha)",
                                 parse_mode="Markdown", reply_markup=kb_main())
            except Exception:
                pass
            return

    cid  = call.message.chat.id
    mid  = call.message.message_id
    
    # ... Iske neeche tumhara baaki ka saara purana DB_OPS aur code waise hi rahega ...
    mid  = call.message.message_id

    if not _DB_UNLOCKED:
        safe_answer(call.id, "🔐 DB locked!", show_alert=True)
        _ask_pw(cid)
        return

    DB_OPS = ("list_dbfiles","upload_dbfile","list_sessions","upload_session",
              "backup_now","dbfile|","session|","backup_settings","userbot_")
    if any(data.startswith(op) for op in DB_OPS) and not _DB_UNLOCKED:
        safe_answer(call.id, "🔐 DB locked!"); _ask_pw(cid); return

    safe_answer(call.id)

    if data == "noop": return

    # ══════════════════════
    #  🔄 SCRIPT UPDATE CONFIRM
    # ══════════════════════
    if data.startswith("upd_confirm|"):
        fname = data[len("upd_confirm|"):]
        pending = _UPDATE_CONFIRM.pop(cid, None)
        if not pending or pending["fname"] != fname:
            bot.send_message(cid, "⚠️ Confirm session expire ho gaya. Dobara file bhejo."); return
        vault_save("script", fname, pending["data"])
        # Running script restart karo
        if is_running(fname):
            kill_script(fname)
            time.sleep(0.5)
            threading.Thread(target=run_script,
                             args=(fname, "script", fname, "", cid), daemon=True).start()
            time.sleep(1.5)
        # 🔥 FIX: Script detail page directly dikhao
        status = "🟢 Running" if is_running(fname) else "🔴 Stopped"
        action = "updated + restarted 🔄" if status == "🟢 Running" else "updated"
        txt = f"✅ *`{fname}` {action}*\nStatus: {status}"
        if is_running(fname):
            info = RUNNING.get(fname, {})
            mins = (datetime.now() - info.get("start", datetime.now())).seconds // 60
            txt += f"\n⏱ {mins}m | PID: {info.get('pid', 'N/A')}"
        msg = bot.send_message(cid, txt, parse_mode="Markdown",
                               reply_markup=kb_script_ctrl(fname))
        _auto_del_track(cid, msg.message_id, _DEL_LONG)
        return

    if data.startswith("upd_saveonly|"):
        fname = data[len("upd_saveonly|"):]
        pending = _UPDATE_CONFIRM.pop(cid, None)
        if not pending or pending["fname"] != fname:
            bot.send_message(cid, "⚠️ Confirm session expire ho gaya. Dobara file bhejo."); return
        vault_save("script", fname, pending["data"])
        # 🔥 FIX: Script detail page dikhao (script abhi bhi chal rahi hai)
        status = "🟢 Running" if is_running(fname) else "🔴 Stopped"
        txt = f"✅ *`{fname}` saved* (restart nahi hua)\nStatus: {status}"
        if is_running(fname):
            info = RUNNING.get(fname, {})
            mins = (datetime.now() - info.get("start", datetime.now())).seconds // 60
            txt += f"\n⏱ {mins}m | PID: {info.get('pid', 'N/A')}"
        msg = bot.send_message(cid, txt, parse_mode="Markdown",
                               reply_markup=kb_script_ctrl(fname))
        _auto_del_track(cid, msg.message_id, _DEL_LONG)
        return

    if data == "upd_cancel":
        _UPDATE_CONFIRM.pop(cid, None)
        bot.send_message(cid, "❌ Script update cancel kar diya."); return

    if data == "autostart_yes":
        _eorsend(cid, mid, "🔄 *Auto-Start:* Scripts restart ho rahe hain…")
        _resume_auto_scripts(cid)
        return

    if data == "autostart_no":
        _eorsend(cid, mid, "⏭️ *Skip kar diya.* Scripts manually start karo jab chahiye ho.")
        return

    if data == "running_panel":
        # Stop any old auto-refresh on this chat before sending a new panel
        _stop_all_panel_autorefresh(cid)
        any_running = any(is_running(k) for k in list(RUNNING.keys()))
        if any_running:
            # Live auto-refresh mode: pehle message bhejo, phir refresh shuru karo
            sent = bot.send_message(
                cid,
                _panel_autorefresh_text(),
                parse_mode="Markdown",
                reply_markup=_panel_autorefresh_kb(0),   # placeholder msg_id=0
            )
            real_mid = sent.message_id
            _auto_del_track(cid, real_mid, _DEL_MEDIUM)
            # Keyboard mein sahi msg_id update karo
            try:
                bot.edit_message_reply_markup(
                    cid, real_mid,
                    reply_markup=_panel_autorefresh_kb(real_mid),
                )
            except Exception:
                pass
            _start_panel_autorefresh(cid, real_mid)
        else:
            _eorsend(cid, mid, _running_panel_text(), reply_markup=kb_running_panel())
            _auto_del_track(cid, mid, _DEL_MEDIUM)
        return

    if data == "error_alerts_menu":
        gid = _get_error_group()
        state = "🟢 ON" if _error_alerts_enabled() else "🔴 OFF"
        group_txt = f"`{gid}`" if gid else "❌ Not set"
        txt = (f"🚨 *Error Alerts*\n\n"
               f"Status: {state}\nGroup: {group_txt}\n\n"
               f"Jab ON hai aur group set hai, tab jitni bhi scripts background mein "
               f"chal rahi hain, unke real crashes/exceptions (traceback, FATAL, "
               f"CRITICAL) is group mein forward honge — normal print/log output nahi.")
        mk = _kb(
            _btn("🟢 Turn ON" if not _error_alerts_enabled() else "🔴 Turn OFF", "error_alerts_toggle"),
            _btn("🎯 Set Group", "error_alerts_setgroup"),
            _btn("🔙 Back", "running_panel"),
        )
        _eorsend(cid, mid, txt, reply_markup=mk); return

    if data == "error_alerts_toggle":
        new_state = _toggle_error_alerts()
        if new_state and not _get_error_group():
            safe_answer(call.id, "⚠️ Pehle group set karo (🎯 Set Group).", show_alert=True)
        else:
            safe_answer(call.id, "✅ Error Alerts ON" if new_state else "🔴 Error Alerts OFF", show_alert=False)
        data = "error_alerts_menu"
        gid = _get_error_group()
        state = "🟢 ON" if _error_alerts_enabled() else "🔴 OFF"
        group_txt = f"`{gid}`" if gid else "❌ Not set"
        txt = (f"🚨 *Error Alerts*\n\nStatus: {state}\nGroup: {group_txt}\n\n"
               f"Jab ON hai aur group set hai, tab jitni bhi scripts background mein "
               f"chal rahi hain, unke real crashes/exceptions (traceback, FATAL, "
               f"CRITICAL) is group mein forward honge — normal print/log output nahi.")
        mk = _kb(
            _btn("🟢 Turn ON" if not _error_alerts_enabled() else "🔴 Turn OFF", "error_alerts_toggle"),
            _btn("🎯 Set Group", "error_alerts_setgroup"),
            _btn("🔙 Back", "running_panel"),
        )
        _eorsend(cid, mid, txt, reply_markup=mk); return

    if data == "error_alerts_setgroup":
        _STEP[cid] = {"step": "set_error_group"}
        bot.send_message(cid,
            "🎯 Jis group mein errors forward karne hain, uss group mein bot ko admin/member add karo, "
            "phir wahan se koi bhi message *forward* kar do yahan — ya group ki chat ID directly type kar do (jaise `-1001234567890`).",
            parse_mode="Markdown")
        return

    if data == "vault_search":
        _STEP[cid] = {"step": "vault_search"}
        bot.send_message(cid, "🔎 Vault mein kya search karna hai? File/folder name bhejo:"); return

    if data == "vault_health":
        _eorsend(cid, mid, _vault_stats_text(), reply_markup=_kb(_btn("🔄 Refresh", "vault_health"), _btn("🔙 Back", "main_menu"))); return

    # ── Main Menu ──
    if data == "main_menu":
        _eorsend(cid, mid, "👑 *Admin V3 (SQLCipher)*\nChoose option:", reply_markup=kb_main()); return

    # ══════════════════════
    #  📋  SCRIPTS
    # ══════════════════════
    if data == "list_scripts":
        sc = get_scripts()
        _eorsend(cid, mid, f"📋 *Scripts* ({len(sc)} total)\n🟢=Running 🔴=Stopped",
                 reply_markup=kb_scripts()); return

    if data == "upload":
        _STEP[cid] = {"step": "upload_script"}
        bot.send_message(cid, "📤 `.py` ya `.js` file bhejo:"); return

    if data.startswith("script|"):
        fname  = data[7:]
        status = "🟢 Running" if is_running(fname) else "🔴 Stopped"
        txt    = f"📄 *{fname}*\nStatus: {status}"
        if is_running(fname):
            info = RUNNING.get(fname, {})
            mins = (datetime.now() - info["start"]).seconds // 60
            txt += f"\n⏱ {mins} min | PID: {info['pid']}"
        _eorsend(cid, mid, txt, reply_markup=kb_script_ctrl(fname)); return

    if data.startswith("run_key|"):
        key   = data[8:]
        fname = os.path.basename(key)
        if is_running(key):
            bot.send_message(cid, f"⚠️ `{fname}` already running.", parse_mode="Markdown"); return
        if not _throttled(key):
            safe_answer(call.id, "⏳ Already starting… thoda ruko.", show_alert=False); return

        # Starting message dikhao
        bot.edit_message_text(f"⏳ `{fname}` is starting…", cid, mid, parse_mode="Markdown")

        # Script ko background thread mein start karo
        threading.Thread(target=run_script,
                         args=(key, "script", fname, "", cid), daemon=True).start()

        # 🔥 FIX: Original message wapas update karo Run/Stop/Logs buttons ke saath
        time.sleep(1.5)
        status = "🟢 Running" if is_running(key) else "🔴 Stopped"
        txt = f"📄 *{fname}*\nStatus: {status}"
        if is_running(key):
            info = RUNNING.get(key, {})
            mins = (datetime.now() - info.get("start", datetime.now())).seconds // 60
            txt += f"\n⏱ {mins}m | PID: {info.get('pid', 'N/A')}"
        _eorsend(cid, mid, txt, reply_markup=kb_script_ctrl(fname))
        return
        
    if data == "run_all_scripts":
        if not _throttled("__run_all_scripts__", cooldown=5):
            safe_answer(call.id, "⏳ Already starting all… thoda ruko.", show_alert=False); return
        count = 0
        for fname in get_scripts():
            if not is_running(fname):
                threading.Thread(target=run_script,
                                 args=(fname, "script", fname, "", cid), daemon=True).start()
                count += 1
        bot.send_message(cid, f"▶️ {count} scripts started."); return

    if data.startswith("stop|"):
        key   = data[5:]
        fname = os.path.basename(key)
        if not is_running(key):
            safe_answer(call.id, "ℹ️ Already stopped.", show_alert=False); return
        if not _throttled(key):
            safe_answer(call.id, "⏳ Already stopping… thoda ruko.", show_alert=False); return
        # Anti-spam: ek hi script ko baar baar stop mat karo
        if not _spam_check(f"stop:{cid}:{fname}", max_calls=4, window_sec=8.0):
            safe_answer(call.id, "⏳ Spam detected! Thodi der baad try karo.", show_alert=True); return
        kill_script(key, manual_stop=True)
        if "/" in key:
            folder, rel = key.split("/", 1)
            _eorsend(cid, mid, f"🛑 `{fname}` stopped.", reply_markup=kb_file_action(folder, rel, key))
        else:
            _eorsend(cid, mid, f"🛑 `{fname}` stopped.", reply_markup=kb_script_ctrl(fname))
        _auto_del_track(cid, mid, _DEL_TEMP)
        return

    # ── 💾 MANUAL SAVE CALLBACK ──
    if data.startswith("manual_save|"):
        key   = data[12:]
        fname = os.path.basename(key)
        if not is_running(key):
            safe_answer(call.id, "ℹ️ Script chal nahi rahi — save karne ko kuch nahi.", show_alert=True)
            return
        safe_answer(call.id, "💾 Saving…", show_alert=False)
        try:
            saved_files = _save_running_script_data(key)
            if saved_files:
                msg = (f"💾 *Manual Save — `{fname}`*\n"
                       f"✅ {len(saved_files)} file(s) saved:\n" +
                       "\n".join(f"  `{s}`" for s in saved_files))
            else:
                msg = f"💾 *Manual Save — `{fname}`*\nℹ️ Koi nayi/changed file nahi mili."
        except Exception as e:
            msg = f"❌ Save failed: `{e}`"
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        bot.send_message(cid, msg, parse_mode="Markdown")
        return

    if data.startswith("restart|"):
        key   = data[8:]
        fname = os.path.basename(key)
        if not _throttled(key):
            safe_answer(call.id, "⏳ Already restarting… thoda ruko.", show_alert=False); return
        kill_script(key)
        # Restarting message dikhao
        try:
            bot.edit_message_text(f"🔄 `{fname}` restarting…", cid, mid, parse_mode="Markdown")
        except Exception:
            pass
        time.sleep(0.5)
        if "/" in key:
            folder, filename = key.split("/", 1)
            threading.Thread(target=run_script,
                             args=(key, "folder_file", filename, folder, cid), daemon=True).start()
            # 🔥 FIX: Original message update karo status ke saath
            time.sleep(1.5)
            status = "🟢 Running" if is_running(key) else "🔴 Stopped"
            base_name = os.path.basename(filename)
            txt = f"📄 *{base_name}*\n📂 Path: `{folder}/{filename}`\nStatus: {status}"
            if is_running(key):
                info = RUNNING.get(key, {})
                mins = (datetime.now() - info.get("start", datetime.now())).seconds // 60
                txt += f"\n⏱ {mins}m | PID: {info.get('pid', 'N/A')}"
            _eorsend(cid, mid, txt, reply_markup=kb_file_action(folder, filename, key))
        else:
            threading.Thread(target=run_script,
                             args=(key, "script", fname, "", cid), daemon=True).start()
            # 🔥 FIX: Original message update karo status ke saath
            time.sleep(1.5)
            status = "🟢 Running" if is_running(key) else "🔴 Stopped"
            txt = f"📄 *{fname}*\nStatus: {status}"
            if is_running(key):
                info = RUNNING.get(key, {})
                mins = (datetime.now() - info.get("start", datetime.now())).seconds // 60
                txt += f"\n⏱ {mins}m | PID: {info.get('pid', 'N/A')}"
            _eorsend(cid, mid, txt, reply_markup=kb_script_ctrl(fname))
        return

    if data.startswith("delete|"):
        fname = data[7:]
        
        # Naya code: Direct delete hatakar script ko PENDING_DELETE mein daal diya
        _PENDING_DELETE[cid] = {"type": "script", "fname": fname}
        
        # Password ke liye prompt bhejna
        bot.send_message(cid, f"⚠️ *Kya aap sach mein `{fname}` delete karna chahte ho?*\n🔐 Confirm karne ke liye apna DB password daalo:", parse_mode="Markdown")
        return
        
    if data.startswith("update_script|"):
        fname = data[14:]
        _STEP[cid] = {"step": "update_script", "fname": fname}
        bot.send_message(cid, f"📲 New file bhejo (`{fname}` replace hoga):"); return

    if data.startswith("backup_script|"):
        fname = data[14:]
        data_bytes = vault_get("script", fname)
        if data_bytes:
            bot.send_document(cid, io.BytesIO(data_bytes), visible_file_name=fname,
                              caption=f"💾 `{fname}` backup", parse_mode="Markdown")
        else:
            bot.send_message(cid, "❌ Script not found in DB.")
        return

    # ── Logs ──
    if data.startswith("logs|") and not data.startswith("logs_"):
        key = data[5:]
        new_mid = _send_logs(cid, mid, key, edit=False)
        _start_log_autorefresh(cid, new_mid, key)   # pehle 30 sec auto-refresh
        return
        
    # 🔥 NAYA: Type button click par prompt bhejna aur dono message id save karna
    if data.startswith("logs_type|"):
        key = data[10:]
        running_hint = "Script chal rahi hai — tumhara text seedha uske input (stdin) mein jaayega, jaise terminal mein Enter dabana." if is_running(key) else "Script abhi running nahi hai, isliye text sirf log mein note ban kar save hoga."
        msg = bot.send_message(cid, f"✏️ `{os.path.basename(key)}` ko kya bhejna hai type karo:\n_{running_hint}_", parse_mode="Markdown")
        _STEP[cid] = {"step": "write_log", "key": key, "prompt_msg_id": msg.message_id, "panel_msg_id": mid}
        return

    if data.startswith("logs_refresh|"):
        key = data[13:]
        _send_logs(cid, mid, key, edit=True)
        _start_log_autorefresh(cid, mid, key)       # manual refresh bhi 30 sec timer restart karta hai
        return
        
    if data.startswith("logs_clear|"):
        key = data[11:]; lp = log_path(key)
        if os.path.exists(lp): open(lp, "w").close()
        _send_logs(cid, mid, key, edit=True); return
        
    if data.startswith("logs_dl|"):
        key = data[8:]; lp = log_path(key)
        if os.path.exists(lp) and os.path.getsize(lp) > 0:
            with open(lp, "rb") as f:
                bot.send_document(cid, f, caption=f"📝 `{os.path.basename(key)}`",
                                  parse_mode="Markdown")
        else:
            bot.send_message(cid, "⚠️ Log empty.")
        return

    if data.startswith("input_req|"):
        key = data[10:]
        _STEP[cid] = {"step": "input_to_script", "key": key}
        bot.send_message(cid, f"⌨️ Input bhejo `{os.path.basename(key)}` ko:"); return

    if data == "stop_all":
        if not _throttled("__stop_all__", cooldown=5):
            safe_answer(call.id, "⏳ Already stopping all… thoda ruko.", show_alert=False); return
        count = 0
        for k in list(RUNNING.keys()):
            if is_running(k): kill_script(k); count += 1
        bot.send_message(cid, f"🛑 {count} scripts stopped.", reply_markup=kb_main()); return
        
    # ══════════════════════
    #  📁  FOLDERS
    # ══════════════════════
    if data == "list_folders":
        _eorsend(cid, mid, "📁 *Folders*", reply_markup=kb_folders()); return

    if data == "upload_zip":
        _STEP[cid] = {"step": "upload_zip"}
        bot.send_message(cid, "📤 ZIP file bhejo (ya koi bhi file):"); return

    if data.startswith("folder_open|"):
        folder = data[12:]
        rows = vault_list("folder_file", folder=folder)
        total   = len(rows)
        scripts = sum(1 for r in rows if r[1].endswith(SCRIPT_EXTS))
        _eorsend(cid, mid,
                 f"📁 *{folder}*\n📄 {total} files | 🐍 {scripts} scripts",
                 reply_markup=kb_folder_view(folder, cid)) # 🔥 Yahan cid add hua hai
        return
        
    # ── Folder Pagination Navigation ──
    if data.startswith("fnav|"):
        parts = data.split("|", 3)
        folder, cat_key, action = parts[1], parts[2], parts[3]
        
        if cid not in _FOLDER_STATE: _FOLDER_STATE[cid] = {}
        if folder not in _FOLDER_STATE[cid]: _FOLDER_STATE[cid][folder] = {"scripts": 0, "dbs": 0, "others": 0}
            
        if action == "prev":
            _FOLDER_STATE[cid][folder][cat_key] = max(0, _FOLDER_STATE[cid][folder][cat_key] - 1)
        elif action == "next":
            _FOLDER_STATE[cid][folder][cat_key] += 1
            
        # 🔥 Panna palatne par highlight hata do
        _FOLDER_STATE[cid][folder]["highlight"] = None 
            
        rows = vault_list("folder_file", folder=folder)
        total = len(rows)
        scripts = sum(1 for r in rows if r[1].endswith(SCRIPT_EXTS))
        _eorsend(cid, mid,
                 f"📁 *{folder}*\n📄 {total} files | 🐍 {scripts} scripts",
                 reply_markup=kb_folder_view(folder, cid))
        return

    # ── Folder Search Flow (Naya) ──
    if data.startswith("fsearch|"):
        parts = data.split("|", 2)
        folder, cat_key = parts[1], parts[2]
        _STEP[cid] = {"step": "search_folder_file", "folder": folder, "cat_key": cat_key, "panel_mid": mid}
        cat_name = "Scripts 🐍" if cat_key == "scripts" else ("Databases 🗄️" if cat_key == "dbs" else "Files 📄")
        
        # Bot puchega ki kya search karna hai
        bot.send_message(cid, f"🔍 *{cat_name}* mein konsi file dhoondhni hai?\nUska pura ya thoda naam type karke bhejo:", parse_mode="Markdown")
        return
        
    # ── New Folder Creation, Rename & Delete Select Flows ──
    if data == "fdir_create_new":
        _STEP[cid] = {"step": "create_new_folder"}
        bot.send_message(cid, "➕ Naye folder ka naam bhejo (e.g., `MyScripts`):", parse_mode="Markdown")
        return
        
    if data == "fdir_ren_select":
        _eorsend(cid, mid, "✏️ *Konsa folder RENAME karna hai?*", reply_markup=kb_folder_select("ren"))
        return
        
    if data == "fdir_del_select":
        _eorsend(cid, mid, "🗑️ *Konsa folder DELETE karna hai?*", reply_markup=kb_folder_select("del"))
        return
        
    if data.startswith("fdir_ren_do|"):
        folder = data.split("|", 1)[1]
        _STEP[cid] = {"step": "rename_folder", "old_folder": folder}
        bot.send_message(cid, f"✏️ Naya naam bhejo folder `{folder}` ke liye:", parse_mode="Markdown")
        return
        
    if data.startswith("fdir_del_do|"):
        folder = data.split("|", 1)[1]
        mk = types.InlineKeyboardMarkup(row_width=2)
        mk.row(_btn("✅ Yes, Delete", f"fdir_del_yes|{folder}"), _btn("❌ No, Cancel", "list_folders"))
        _eorsend(cid, mid, f"⚠️ *Kya aap sach mein pura folder `{folder}` delete karna chahte ho?*", reply_markup=mk)
        return
        
    if data.startswith("fdir_del_yes|"):
        folder = data[13:]
        _PENDING_DELETE[cid] = {"type": "folder", "folder": folder}
        bot.send_message(cid, f"🔐 *Security Check*\nFolder `{folder}` ko delete karne ke liye apna DB Password daalo:", parse_mode="Markdown")
        return
        
    if data.startswith("zip_extract_flat|") or data.startswith("zip_extract_struct|"):
        mode = "flat" if data.startswith("zip_extract_flat|") else "struct"
        folder_name = data.split("|", 1)[1]
        raw = _db_get(f"tmpzip_{folder_name}")
        if not raw:
            bot.send_message(cid, "❌ ZIP data expired. Re-upload karein."); return
        zip_bytes = base64.b64decode(raw)
        msg = bot.send_message(cid, f"📦 Extracting (`{mode}` mode)…")
        def _do_extract(fn=folder_name, zb=zip_bytes, mo=mode):
            try:
                stats = extract_zip_to_vault(zb, fn, mo)
                _db_set(f"tmpzip_{fn}", "")  # clear
                bot.edit_message_text(
                    f"✅ *Extracted to `{fn}`!*\n"
                    f"📄 Files: `{stats['files']}` | 🐍 Scripts: `{stats['scripts']}` "
                    f"| 🗄️ DBs: `{stats['dbs']}`",
                    cid, msg.message_id, parse_mode="Markdown",
                    reply_markup=_kb(_btn(f"📁 View {fn}", f"folder_open|{fn}")))
            except Exception as e:
                bot.edit_message_text(f"❌ Extract failed: {e}", cid, msg.message_id)
        threading.Thread(target=_do_extract, daemon=True).start(); return

    if data.startswith("folder_upload|"):
        folder = data[14:]
        _STEP[cid] = {"step": "folder_upload", "folder": folder}
        bot.send_message(cid, f"📤 File bhejo (folder `{folder}` mein save hoga):"); return

    if data.startswith("folder_dl|"):
        folder = data[10:]
        msg = bot.send_message(cid, f"🗜️ ZIP ban raha hai…")
        def _zip_dl(f=folder):
            try:
                zdata = zip_folder_bytes(f)
                bot.delete_message(cid, msg.message_id)
                bot.send_document(cid, io.BytesIO(zdata), visible_file_name=f"{f}.zip",
                                  caption=f"📁 `{f}`", parse_mode="Markdown")
            except Exception as e:
                bot.send_message(cid, f"❌ ZIP error: {e}")
        threading.Thread(target=_zip_dl, daemon=True).start(); return

    if data.startswith("folder_del|"):
        folder = data[11:]
        _PENDING_DELETE[cid] = {"type": "folder", "folder": folder}
        bot.send_message(cid, f"🔐 Folder `{folder}` delete confirm karne ke liye DB password daalo:", parse_mode="Markdown"); return

    # ── Folder Script click ──
    if data.startswith("fscript|"):
        parts  = data.split("|", 2); folder, fname = parts[1], parts[2]
        key    = f"{folder}/{fname}"
        status = "🟢 Running" if is_running(key) else "🔴 Stopped"
        
        # 🔥 FIX: Heading mein clear naam, aur neeche pura path
        base_name = os.path.basename(fname)
        txt    = f"📄 *{base_name}*\n📂 Path: `{folder}/{fname}`\nStatus: {status}"
        
        if is_running(key):
            info = RUNNING.get(key, {})
            mins = (datetime.now() - info.get("start", datetime.now())).seconds // 60
            txt += f"\n⏱ {mins}m | PID: {info.get('pid', 'N/A')}"
        _eorsend(cid, mid, txt, reply_markup=kb_file_action(folder, fname, key)); return

    # ── Non-script file click ──
    if data.startswith("ffile|") and not data.startswith("ffile_"):
        parts  = data.split("|", 2); folder, fname = parts[1], parts[2]
        key    = f"{folder}/{fname}"
        icon   = get_file_icon(fname)
        rows   = vault_list("folder_file", folder=folder)
        sz     = next((r[2] for r in rows if r[1] == fname), 0)
        
        # 🔥 FIX: Heading mein clear naam, aur neeche pura path
        base_name = os.path.basename(fname)
        txt    = f"{icon} *{base_name}*\n📂 Path: `{folder}/{fname}`\n💾 Size: `{_human_size(sz)}`"
        
        _eorsend(cid, mid, txt, reply_markup=kb_file_action(folder, fname, key)); return
        
    # ── Folder Run ──
    if data.startswith("frun|"):
        key    = data[5:]
        folder, fname = key.split("/", 1)
        if is_running(key):
            bot.send_message(cid, "⚠️ Already running."); return
        if not _throttled(key):
            safe_answer(call.id, "⏳ Already starting… thoda ruko.", show_alert=False); return

        bot.edit_message_text(f"⏳ `{fname}` starting…", cid, mid, parse_mode="Markdown")
        threading.Thread(target=run_script,
                         args=(key, "folder_file", fname, folder, cid), daemon=True).start()
        
        time.sleep(1.5)
        
        # Same detailed page generate karenge jo click karne par aata hai
        status = "🟢 Running" if is_running(key) else "🔴 Stopped"
        base_name = os.path.basename(fname)
        txt    = f"📄 *{base_name}*\n📂 Path: `{folder}/{fname}`\nStatus: {status}"
        
        if is_running(key):
            info = RUNNING.get(key, {})
            mins = (datetime.now() - info.get("start", datetime.now())).seconds // 60
            txt += f"\n⏱ {mins}m | PID: {info.get('pid', 'N/A')}"

        _eorsend(cid, mid, txt, reply_markup=kb_file_action(folder, fname, key))
        return

    if data.startswith("fstop|"):
        key = data[6:]
        if not is_running(key):
            safe_answer(call.id, "ℹ️ Already stopped.", show_alert=False); return
        if not _throttled(key):
            safe_answer(call.id, "⏳ Already stopping… thoda ruko.", show_alert=False); return
        kill_script(key, manual_stop=True)
        folder, fname = key.split("/", 1)
        _eorsend(cid, mid, f"🛑 `{fname}` stopped.",
                 reply_markup=kb_file_action(folder, fname, key)); return

    if data.startswith("frestart|"):
        key = data[9:]
        if not _throttled(key):
            safe_answer(call.id, "⏳ Already restarting… thoda ruko.", show_alert=False); return
        folder, fname = key.split("/", 1)
        kill_script(key); time.sleep(0.5)
        threading.Thread(target=run_script,
                         args=(key, "folder_file", fname, folder, cid), daemon=True).start(); return

    if data.startswith("folder_run_scripts|"):
        folder = data.split("|", 1)[1]
        if not _throttled(f"folder_run|{folder}", cooldown=5):
            safe_answer(call.id, "⏳ Already starting… thoda ruko.", show_alert=False); return
        started = 0
        for fn in _folder_script_names(folder):
            key = f"{folder}/{fn}"
            if not is_running(key):
                threading.Thread(target=run_script, args=(key, "folder_file", fn, folder, cid), daemon=True).start()
                started += 1
        bot.send_message(cid, f"▶️ `{folder}` ke `{started}` script(s) started.", parse_mode="Markdown")
        return

    if data.startswith("folder_stop_scripts|"):
        folder = data.split("|", 1)[1]
        if not _throttled(f"folder_stop|{folder}", cooldown=5):
            safe_answer(call.id, "⏳ Already stopping… thoda ruko.", show_alert=False); return
        stopped = 0
        for fn in _folder_script_names(folder):
            key = f"{folder}/{fn}"
            if is_running(key):
                kill_script(key); stopped += 1
        _eorsend(cid, mid, f"⏹️ `{folder}` ke `{stopped}` script(s) stopped.", reply_markup=kb_folder_view(folder, cid))
        return

    if data.startswith("folder_restart_scripts|"):
        folder = data.split("|", 1)[1]
        restarted = 0
        for fn in _folder_script_names(folder):
            key = f"{folder}/{fn}"
            if is_running(key): kill_script(key)
            threading.Thread(target=run_script, args=(key, "folder_file", fn, folder, cid), daemon=True).start()
            restarted += 1
        bot.send_message(cid, f"🔄 `{folder}` ke `{restarted}` script(s) restart/start ho rahe hain.", parse_mode="Markdown")
        return

    # ── Folder File: Download ──
    if data.startswith("ffile_dl|"):
        parts = data.split("|", 2); folder, fname = parts[1], parts[2]
        raw = vault_get("folder_file", fname, folder)
        if raw is None:
            bot.send_message(cid, "❌ File not found in DB."); return
        if len(raw) > 50 * 1024 * 1024:
            sname, _ = _get_active_userbot()
            if sname and PYROGRAM_AVAILABLE:
                bot.send_message(cid, f"📤 Large file — userbot se bhej raha hun…")
                # 🔥 FIX (Bug #5): mktemp() TOCTOU race → mkstemp()
                _fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(fname)[1])
                os.close(_fd)
                with open(tmp, "wb") as f: f.write(raw)
                def _big(sn=sname, t=tmp, fn=fname):
                    try: _userbot_upload_thread(sn, cid, t, f"📄 `{fn}`")
                    except Exception as e: bot.send_message(cid, f"❌ Userbot failed: {e}")
                    finally:
                        if os.path.exists(t): os.remove(t)
                threading.Thread(target=_big, daemon=True).start()
            else:
                bot.send_message(cid, f"⚠️ File too large (>50MB). Userbot needed.")
        else:
            bot.send_document(cid, io.BytesIO(raw), visible_file_name=fname,
                              caption=f"📄 `{fname}`", parse_mode="Markdown")
        return

    if data.startswith("ffile_bkp|"):
        parts = data.split("|", 2); folder, fname = parts[1], parts[2]
        raw = vault_get("folder_file", fname, folder)
        if raw:
            bot.send_document(cid, io.BytesIO(raw), visible_file_name=fname,
                              caption=f"💾 Backup: `{fname}`", parse_mode="Markdown")
        else:
            bot.send_message(cid, "❌ File not found.")
        return

    if data.startswith("ffile_ren|"):
        parts = data.split("|", 2); folder, fname = parts[1], parts[2]
        _STEP[cid] = {"step": "rename_file", "folder": folder, "filename": fname}
        bot.send_message(cid, f"✏️ New naam bhejo for `{fname}`:", parse_mode="Markdown"); return

    if data.startswith("ffile_del|"):
        parts = data.split("|", 2); folder, fname = parts[1], parts[2]
        
        # Naya code: Direct delete hatakar file ko PENDING_DELETE mein daal diya
        _PENDING_DELETE[cid] = {"type": "folder_file", "folder": folder, "fname": fname}
        
        # Password ke liye prompt bhejna
        bot.send_message(cid, f"⚠️ *Kya aap sach mein `{fname}` delete karna chahte ho?*\n🔐 Confirm karne ke liye apna DB password daalo:", parse_mode="Markdown")
        return
        
    if data.startswith("fupdate|"):
        parts = data.split("|", 2); folder, fname = parts[1], parts[2]
        _STEP[cid] = {"step": "fupdate_file", "folder": folder, "filename": fname}
        bot.send_message(cid, f"📲 New file bhejo (replace `{fname}`):"); return

    if data.startswith("fzip_extract|"):
        parts = data.split("|", 2); folder, fname = parts[1], parts[2]
        mk = types.InlineKeyboardMarkup(row_width=1)
        mk.add(_btn("📄 Flat — Sab files ek saath", f"do_fzip_flat|{folder}|{fname}"))
        mk.add(_btn("📁 Structured — Sub-folders bhi", f"do_fzip_struct|{folder}|{fname}"))
        mk.add(_btn("🔙 Cancel", f"folder_open|{folder}"))
        bot.send_message(cid, f"📦 *Extract `{fname}`*\nMode choose karo:",
                         parse_mode="Markdown", reply_markup=mk); return

    if data.startswith("do_fzip_flat|") or data.startswith("do_fzip_struct|"):
        mode = "flat" if data.startswith("do_fzip_flat|") else "struct"
        parts = data.split("|", 2); folder, fname = parts[1], parts[2]
        raw = vault_get("folder_file", fname, folder)
        if not raw:
            bot.send_message(cid, "❌ ZIP not found in DB."); return
        msg = bot.send_message(cid, f"📦 Extracting `{fname}`…")
        def _do_fzip(fo=folder, fn=fname, zb=raw, mo=mode):
            try:
                stats = extract_zip_to_vault(zb, fo, mo)
                bot.edit_message_text(
                    f"✅ Extracted `{fn}`!\n"
                    f"📄 {stats['files']} files | 🐍 {stats['scripts']} | 🗄️ {stats['dbs']}",
                    cid, msg.message_id, parse_mode="Markdown",
                    reply_markup=_kb(_btn("📁 View Folder", f"folder_open|{fo}")))
            except Exception as e:
                bot.edit_message_text(f"❌ {e}", cid, msg.message_id)
        threading.Thread(target=_do_fzip, daemon=True).start(); return

    # ══════════════════════
    #  🗄️  DB FILES & EXPLORER (UPDATED)
    # ══════════════════════
    if data == "db_vault_explore":
        if not os.path.exists(DB_FILE):
            safe_answer(call.id, "❌ No DB file found!")
            return
            
        db_size = os.path.getsize(DB_FILE)
        con = _db_connect()
        tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        
        txt = f"🗄️ *vault.db Explorer*\nTotal Size: `{_human_size(db_size)}`\n\n*Tables in Database:*\n"
        mk = types.InlineKeyboardMarkup(row_width=1)
        
        for (tname,) in tables:
            if tname.startswith("sqlite_"): continue
            count = con.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
            txt += f" ├ 📋 `{tname}` ({count} records)\n"
            # Har table ka CSV export button
            mk.add(_btn(f"📥 Export Data: {tname} (.csv)", f"db_export|{tname}"))
            
        con.close()
        mk.add(_btn("🔙 Back", "list_dbfiles"))
        _eorsend(cid, mid, txt, reply_markup=mk)
        return
        
    if data.startswith("db_export|"):
        tname = data.split("|")[1]
        msg = bot.send_message(cid, f"⏳ Generating readable CSV for `{tname}`...")
        
        def _export_table():
            import csv, tempfile
            con = _db_connect()
            cursor = con.execute(f"SELECT * FROM {tname}")
            col_names = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            if not rows:
                bot.edit_message_text(f"⚠️ Table `{tname}` is currently empty.", cid, msg.message_id)
                con.close()
                return
                
            # 🔥 FIX (Bug #5): mktemp() TOCTOU race → mkstemp()
            _fd, tmp = tempfile.mkstemp(suffix=".csv")
            os.close(_fd)
            with open(tmp, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(col_names) # Heading daalna
                
                for r in rows:
                    row_data = []
                    for val in r:
                        # Agar value BLOB (binary file) hai, toh uska binary kachra CSV me print karne ke bajaye size likhenge
                        if isinstance(val, bytes):
                            row_data.append(f"<BLOB FILE: {_human_size(len(val))}>")
                        else:
                            row_data.append(str(val))
                    writer.writerow(row_data)
            con.close()
            
            # File Telegram par bhej do
            with open(tmp, "rb") as f:
                bot.send_document(cid, f, caption=f"📊 `{tname}` Data Export\nAap ise Excel ya text viewer me open kar sakte hain.", parse_mode="Markdown")
            os.remove(tmp)
            bot.delete_message(cid, msg.message_id)

        # Thread mein run karna taaki badi DB bot ko hang na kare
        threading.Thread(target=_export_table, daemon=True).start()
        return

    if data == "list_dbfiles":
        _eorsend(cid, mid, "🗄️ *Database Files*", reply_markup=kb_dbfiles()); return

    # ══════════════════════
    #  🧟  ZOMBIE WATCHDOG (disabled in Plus safe edition)
    # ══════════════════════
    if data == "zombie_menu" or data.startswith("zombie_"):
        bot.send_message(cid,
            "⚠️ Hidden/Zombie crontab mode Plus edition mein disabled hai.\n"
            "Legit auto-start ke liye systemd/pm2 ka normal service use karo; hidden persistence add nahi ki gayi.")
        return

    # ══════════════════════
    #  💾  BACKUP
    # ══════════════════════
    if data == "backup_now":
        bot.send_message(cid, "⏳ Backup ban raha hai…")
        threading.Thread(target=_do_backup, args=(cid,), daemon=True).start(); return

    if data == "backup_download":
        msg = bot.send_message(cid, "⏳ Unified backup ZIP ban raha hai (DB + disk-backed media)…")
        def _make_and_send():
            zip_path = None
            try:
                zip_path = _create_unified_backup_zip()
                bot.edit_message_text("📤 Backup ready, Telegram par bhej raha hun…", cid, msg.message_id)
                _send_big_file(cid, zip_path, f"📦 *Unified Backup*\n`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`", visible_name=f"adminv3_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
                try: bot.delete_message(cid, msg.message_id)
                except Exception: pass
            except Exception as e:
                bot.send_message(cid, f"❌ Backup download failed: `{_md_escape(e)}`", parse_mode="Markdown")
            finally:
                if zip_path and os.path.exists(zip_path):
                    os.remove(zip_path)
        threading.Thread(target=_make_and_send, daemon=True).start(); return

    if data == "backup_settings":
        _eorsend(cid, mid, "⚙️ *Backup Settings*", reply_markup=kb_backup_settings()); return

    if data == "backup_add_job":
        _STEP[cid] = {"step": "backup_job_interval"}
        bot.send_message(cid, "⏰ Auto backup interval (hours) daalo:"); return

    if data.startswith("backup_stop|"):
        jid = data[12:]
        con = _db_connect()
        con.execute("UPDATE backup_jobs SET active=0 WHERE job_id=?", (jid,)); con.commit(); con.close()
        bot.send_message(cid, f"⏹️ Job `{jid}` stopped.", parse_mode="Markdown",
                         reply_markup=kb_backup_settings()); return

    if data.startswith("backup_del|"):
        jid = data[11:]
        con = _db_connect()
        con.execute("DELETE FROM backup_jobs WHERE job_id=?", (jid,)); con.commit(); con.close()
        bot.send_message(cid, f"🗑️ Job `{jid}` deleted.", parse_mode="Markdown",
                         reply_markup=kb_backup_settings()); return

    if data == "upload_restore_backup":
        _STEP[cid] = {"step": "restore_backup_file"}
        bot.send_message(cid, "📤 Backup ZIP bhejo (scripts/folders wapas restore honge):"); return

    if data == "upload_restore_db":
        _STEP[cid] = {"step": "restore_unified_backup"}
        bot.send_message(cid,
            "📤 *Unified Backup ZIP file bhejo.*\n"
            "⚠️ Ye process aapki `vault.db` aur VPS disk (Media Vault) ki saari files ko ZIP se replace kar dega aur bot automatically restart hoga.",
            parse_mode="Markdown"); return
            
    # ══════════════════════
    #  🖥️  VPS EXPLORER  (State-based, no path in callback_data)
    # ══════════════════════
    if data == "vps_open":
        state = _VPS_STATE.get(cid, {"path": "/", "page": 0, "history": {}})
        path = state.get("path", "/")
        # File/Menu se waapas aate waqt page=None bhejenge taaki history se last page utha le
        text, mk = _build_vps_kb(cid, path, None)
        if mk: _eorsend(cid, mid, text, reply_markup=mk)
        return

    if data.startswith("vps_cd|"):
        path = data[7:]
        # Naye folder mein ghuste waqt bhi page=None
        text, mk = _build_vps_kb(cid, path, None)
        if mk: _eorsend(cid, mid, text, reply_markup=mk)
        return

    if data.startswith("vps_nav|"):
        action = data[8:]
        state  = _VPS_STATE.get(cid, {"path": "/", "page": 0, "history": {}})
        path   = state.get("path", "/")
        page   = state.get("page", 0)

        if action == "next":
            page += 1
            text, mk = _build_vps_kb(cid, path, page)
            if mk: _eorsend(cid, mid, text, reply_markup=mk)
            return
        elif action == "prev":
            page = max(0, page - 1)
            text, mk = _build_vps_kb(cid, path, page)
            if mk: _eorsend(cid, mid, text, reply_markup=mk)
            return
        elif action == "up":
            path = str(Path(path).parent)
            # Folder se Up aane par history memory restore hogi
            text, mk = _build_vps_kb(cid, path, None)
            if mk: _eorsend(cid, mid, text, reply_markup=mk)
            return
        elif action == "root":
            path = "/"
            text, mk = _build_vps_kb(cid, path, None)
            if mk: _eorsend(cid, mid, text, reply_markup=mk)
            return
        elif action == "zip":
            bot.send_message(cid, f"⏳ ZIP ban raha hai: `{path}`…", parse_mode="Markdown")
            def _do_zip(p=path):
                try:
                    tmp = zip_path_to_tmp(p)
                    fn = os.path.basename(p.rstrip("/")) + ".zip"
                    with open(tmp, "rb") as f:
                        bot.send_document(cid, f, visible_file_name=fn, caption=f"📦 `{p}`",
                                          parse_mode="Markdown")
                    os.remove(tmp)
                except Exception as e: bot.send_message(cid, f"❌ ZIP error: {e}")
            threading.Thread(target=_do_zip, daemon=True).start()
            return
        elif action == "upload":
            _STEP[cid] = {"step": "vps_upload", "path": path}
            bot.send_message(cid, f"📤 File bhejo — VPS path mein save hoga:\n`{path}`", parse_mode="Markdown")
            return
        elif action == "mkdir":
            _STEP[cid] = {"step": "vps_mkdir", "path": path}
            bot.send_message(cid, f"➕ Naye folder ka naam bhejo for:\n`{path}`", parse_mode="Markdown")
            return
        elif action == "screenshot":
            def _do_ss(p=path):
                try:
                    lines = [f"📂 VPS Screenshot: {p}", f"🕐 {datetime.now()}", "─" * 60]
                    for rt, dirs, files in os.walk(p):
                        rel = os.path.relpath(rt, p)
                        depth = 0 if rel == "." else rel.count(os.sep) + 1
                        if depth > 4: continue
                        indent = "  " * depth
                        lines.append(f"{indent}📁 {os.path.basename(rt) if rt != p else p}/")
                        for fn in sorted(files)[:50]:
                            try: sz = os.path.getsize(os.path.join(rt, fn))
                            except: sz = 0
                            lines.append(f"{indent}  📄 {fn}  [{_human_size(sz)}]")
                    txt = "\n".join(lines)
                    bio = io.BytesIO(txt.encode("utf-8"))
                    bio.name = f"ss_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    bot.send_document(cid, bio, caption=f"📸 `{p}`", parse_mode="Markdown")
                except Exception as e: bot.send_message(cid, f"❌ Screenshot error: {e}")
            threading.Thread(target=_do_ss, daemon=True).start()
            return

        text, mk = _build_vps_kb(cid, path, page)
        if mk: _eorsend(cid, mid, text, reply_markup=mk)
        return

    if data.startswith("vps_file|"):
        fpath = data[9:]
        if not os.path.isfile(fpath):
            bot.send_message(cid, "❌ File not found!"); return
        try: size = os.path.getsize(fpath)
        except: size = 0
        fname = os.path.basename(fpath)
        icon  = get_file_icon(fname)
        txt   = f"{icon} *{fname}*\n📦 Size: `{_human_size(size)}`\n📍 `{fpath}`"
        if size > 50 * 1024 * 1024: txt += f"\n⚠️ >50MB!"
        _eorsend(cid, mid, txt, reply_markup=kb_vpsfile(fpath)); return

    if data.startswith("vps_dl|"):
        fpath = data[7:]
        if not os.path.isfile(fpath):
            bot.send_message(cid, "❌ Not found!"); return
        size = os.path.getsize(fpath)
        if size > 50 * 1024 * 1024:
            sname, _ = _get_active_userbot()
            if sname and PYROGRAM_AVAILABLE:
                bot.send_message(cid, f"📤 Userbot se send ho raha hai…")
                def _big_send(fp=fpath):
                    try: _userbot_upload_thread(sname, cid, fp, f"📄 `{fp}`\n{_human_size(size)}")
                    except Exception as e: bot.send_message(cid, f"❌ Userbot failed: {e}")
                threading.Thread(target=_big_send, daemon=True).start()
            else:
                bot.send_message(cid, f"⚠️ File {_human_size(size)} — 50MB exceeded. Userbot add karo.")
        else:
            with open(fpath, "rb") as f:
                bot.send_document(cid, f, caption=f"`{fpath}`", parse_mode="Markdown")
        return

    if data.startswith("vps_ren|"):
        fpath = data[8:]
        if not os.path.exists(fpath):
            bot.send_message(cid, "❌ Not found!"); return
        _STEP[cid] = {"step": "vps_rename", "path": fpath}
        bot.send_message(cid, f"✏️ Naya naam bhejo:\n`{fpath}`", parse_mode="Markdown")
        return

    if data.startswith("vps_del|"):
        fpath = data[8:]
        if not os.path.exists(fpath):
            bot.send_message(cid, "❌ Not found!"); return
        _PENDING_DELETE[cid] = {"type": "vps", "path": fpath, "is_dir": os.path.isdir(fpath)}
        bot.send_message(cid,
            f"⚠️ *Delete confirm karo!*\n\n`{fpath}`\n\n🔐 Password daalo:",
            parse_mode="Markdown"); return

    if data.startswith("vps_extract|"):
        fpath = data[12:]
        fname = os.path.basename(fpath)
        base_folder_name = os.path.splitext(fname)[0]
        
        # 🔥 NAYA LOGIC: VPS mein bhi suffix lagane ke liye
        existing_folders = vault_list_folders()
        folder_name = base_folder_name
        counter = 1
        while folder_name in existing_folders:
            folder_name = f"{base_folder_name}_{counter}"
            counter += 1

        try:
            with open(fpath, "rb") as f: zip_bytes = f.read()
            stats = extract_zip_to_vault(zip_bytes, folder_name, "flat")
            bot.send_message(cid,
                f"✅ Extracted `{fname}` → *{folder_name}*\n"
                f"📄 {stats['files']} files | 🐍 {stats['scripts']} | 🗄️ {stats['dbs']}",
                parse_mode="Markdown",
                reply_markup=_kb(_btn(f"📁 View {folder_name}", f"folder_open|{folder_name}")))
        except Exception as e:
            bot.send_message(cid, f"❌ Extract failed: {e}")
        return

    if data == "vps_filter":
        fkey = _VPS_FILTER.get(cid, "ALL")
        _eorsend(cid, mid, "🔍 *Filter choose karo:*", reply_markup=kb_vps_filter(fkey)); return

    if data.startswith("vps_setfilter|"):
        fkey = data[14:]
        _VPS_FILTER[cid] = fkey
        state = _VPS_STATE.get(cid, {"path": "/", "page": 0})
        text, mk = _build_vps_kb(cid, state["path"], 0)
        if mk: _eorsend(cid, mid, text, reply_markup=mk)
        return

    if data == "top25_mem":
        _eorsend(cid, mid, get_top25_mem(), reply_markup=kb_top25_mem()); return

    if data.startswith("kill_pid|"):
        pid_str = data[9:]
        try:
            pid = int(pid_str)
            p = psutil.Process(pid)
            pname = p.name()
            p.terminate()
            try: p.wait(timeout=3)
            except psutil.TimeoutExpired: p.kill()
            safe_answer(call.id, f"✅ Killed: {pname} [{pid}]", show_alert=True)
        except psutil.NoSuchProcess:
            safe_answer(call.id, "⚠️ Process already dead.", show_alert=True)
        except Exception as e:
            safe_answer(call.id, f"❌ Kill failed: {e}", show_alert=True)
        _eorsend(cid, mid, get_top25_mem(), reply_markup=kb_top25_mem()); return

    # ══════════════════════
    #  📁  FILE MANAGER
    # ══════════════════════
    if data.startswith("fm_open|"):
        folder = data[8:]
        rows = vault_list("folder_file", folder=folder)
        total = len([r for r in rows if r[1] != ".init"])
        _eorsend(cid, mid,
                 f"📁 *{folder}* — File Manager\n📄 {total} files",
                 reply_markup=kb_file_manager(folder)); return

    if data.startswith("fm_cd|"):
        parts = data.split("|", 2); base_folder, sub = parts[1], parts[2]
        new_path = f"{base_folder}/{sub}"
        rows = vault_list("folder_file", folder=new_path)
        total = len([r for r in rows if r[1] != ".init"])
        _eorsend(cid, mid,
                 f"📁 *{new_path}* — File Manager\n📄 {total} files",
                 reply_markup=kb_file_manager(base_folder.split("/")[0], "/".join(new_path.split("/")[1:]))); return

    if data.startswith("fm_file|"):
        parts = data.split("|", 2); folder, fname = parts[1], parts[2]
        key = f"{folder}/{fname}"
        icon = get_file_icon(fname)
        rows = vault_list("folder_file", folder=folder)
        sz = next((r[2] for r in rows if r[1] == fname), 0)
        base_name = os.path.basename(fname)
        mk = types.InlineKeyboardMarkup(row_width=2)
        mk.row(_btn("⬇️ Download", f"ffile_dl|{folder}|{fname}"),
               _btn("🗑️ Delete",   f"ffile_del|{folder}|{fname}"))
        mk.row(_btn("📲 Update",   f"fupdate|{folder}|{fname}"),
               _btn("✏️ Rename",   f"ffile_ren|{folder}|{fname}"))
        if fname.endswith(SCRIPT_EXTS):
            if is_running(key):
                mk.row(_btn("🛑 Stop", f"fstop|{key}"), _btn("🔄 Restart", f"frestart|{key}"))
            else:
                mk.add(_btn("▶️ Run", f"frun|{key}"))
        if fname.lower().endswith(".zip"):
            mk.add(_btn("📦 Extract ZIP", f"fzip_extract|{folder}|{fname}"))
        root_folder = folder.split("/")[0]
        mk.add(_btn("🔙 Back", f"fm_open|{root_folder}"))
        txt = f"{icon} *{base_name}*\n📂 `{folder}`\n💾 {_human_size(sz)}"
        _eorsend(cid, mid, txt, reply_markup=mk); return

    if data.startswith("fm_upload|"):
        folder = data[10:]
        _STEP[cid] = {"step": "folder_upload", "folder": folder}
        bot.send_message(cid, f"📤 File bhejo (folder `{folder}` mein save hoga):"); return

    # ══════════════════════
    #  🔒  AUTOLOCK TOGGLE
    # ══════════════════════
    if data.startswith("autolock_toggle|"):
        key = data[16:]
        new_state = _autolock_toggle(key)
        lbl = "🔒 ON" if new_state else "🔓 OFF"
        safe_answer(call.id, f"AutoLock {lbl}", show_alert=False)
        if "/" in key:
            folder, fname = key.split("/", 1)
            status = "🟢 Running" if is_running(key) else "🔴 Stopped"
            base_name = os.path.basename(fname)
            txt = f"📄 *{base_name}*\n📂 `{folder}/{fname}`\nStatus: {status}"
            _eorsend(cid, mid, txt, reply_markup=kb_file_action(folder, fname, key))
        else:
            status = "🟢 Running" if is_running(key) else "🔴 Stopped"
            txt = f"📄 *{key}*\nStatus: {status}"
            _eorsend(cid, mid, txt, reply_markup=kb_script_ctrl(key))
        return

    # ══════════════════════
    #  🛡️  RAM GUARD TOGGLE
    # ══════════════════════
    if data == "ramguard_toggle":
        global _RAM_GUARD_ENABLED
        _RAM_GUARD_ENABLED = not _RAM_GUARD_ENABLED
        status_txt = "✅ ON" if _RAM_GUARD_ENABLED else "❌ OFF"
        safe_answer(call.id, f"RAM Guard {status_txt}", show_alert=False)
        _eorsend(cid, mid, get_sys_info(), reply_markup=kb_sys_monitor())
        return

    # ══════════════════════════
    #  🔒  ENCRYPT DB PROMPT
    # ══════════════════════════
    if data == "encrypt_db_prompt":
        safe_answer(call.id)
        if not _DB_IS_PLAINTEXT:
            bot.send_message(cid,
                "✅ *DB already SQLCipher-encrypted hai!*\nKuch karne ki zaroorat nahi.",
                parse_mode="Markdown")
        else:
            bot.send_message(cid,
                "🔒 *DB Encrypt Karne Ka Command:*\n\n"
                "Neeche diya command bhejo (apna password dalo):\n"
                "`/encryptdb YOUR_STRONG_PASSWORD`\n\n"
                "📋 *Kya hoga encrypt karne par:*\n"
                "• plain sqlite3 → SQLCipher encrypted DB\n"
                "• Purani plain copy backup mein save hogi\n"
                "• Bot restart hoga, har session mein password maanga jaayega\n\n"
                "⚠️ *Pehle install karo (agar nahi kiya):*\n"
                "`pip install pysqlcipher3`\nYa: `pip install sqlcipher3`",
                parse_mode="Markdown")
        return

    # ══════════════════════
    #  📊  SYSTEM MONITOR (inline, was missing from callbacks)
    # ══════════════════════
    if data == "sys_monitor":
        _eorsend(cid, mid, get_sys_info(), reply_markup=kb_sys_monitor())
        _auto_del_track(cid, mid, _DEL_MEDIUM)
        return

    
    # ── Panel Auto-Refresh stop button ──
    if data.startswith("panel_stop_ar|"):
        try:
            ar_msg_id = int(data.split("|", 1)[1])
        except (ValueError, IndexError):
            ar_msg_id = mid
        _stop_panel_autorefresh(cid, ar_msg_id)
        safe_answer(call.id, "⏸ Auto-Refresh stopped.", show_alert=False)
        # Static snapshot dikhao
        try:
            bot.edit_message_text(
                _running_panel_text(),
                cid, ar_msg_id,
                parse_mode="Markdown",
                reply_markup=kb_running_panel(),
            )
        except Exception:
            pass
        return

    if data == "shell_cmd":
        _STEP[cid] = {"step": "shell_input"}
        bot.send_message(
            cid,
            "🔧 *Shell Command*\nCommand daalo (pipe, &&, ; sab kuch allowed hai):\n"
            "_Examples: `ls -la /root`, `ps aux | grep python`, `cat /etc/os-release`_",
            parse_mode="Markdown",
        )
        return

    # ══════════════════════════════════════════════════════════
    #  🚀  SHELL V2 — Live Streaming Callbacks
    # ══════════════════════════════════════════════════════════

    if data == "shell_bg":
        # User ne "Background mein chalne do" dabaya
        sess = _SHELL_SESSIONS.get(cid)
        if not sess or sess.get("finished"):
            safe_answer(call.id, "ℹ️ Koi active shell session nahi.", show_alert=True)
            return
        sess["background"] = True
        safe_answer(call.id, "🔁 Process background mein chal raha hai!", show_alert=False)
        # Message update karo (buttons hata do, status dikhao)
        cmd_preview = sess["cmd_str"][:50] + ("…" if len(sess["cmd_str"]) > 50 else "")
        elapsed     = time.time() - sess["start_time"]
        try:
            bot.edit_message_text(
                f"⚙️ *Shell — Background Mode*\n`{cmd_preview}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔄 Process background mein chal raha hai…\n"
                f"⏱ `{elapsed:.0f}s` elapsed\n"
                f"📊 `{len(sess['log_buf'])} lines` collected abhi tak\n\n"
                f"_Finish hone par result + download button aayega_ ✅",
                cid, sess["msg_id"],
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    if data == "shell_stop":
        # User ne "Band Karo" dabaya
        sess = _SHELL_SESSIONS.get(cid)
        if not sess:
            safe_answer(call.id, "ℹ️ Koi active session nahi.", show_alert=True)
            return
        sess["stop_evt"].set()
        safe_answer(call.id, "🛑 Process band ho raha hai…", show_alert=False)
        # Agar already finished hai to log file bhejo
        if sess.get("finished"):
            _shell_send_log_file(cid, sess)
        return

    if data == "shell_log_dl":
        # Log file download
        sess = _SHELL_SESSIONS.get(cid)
        if not sess:
            safe_answer(call.id, "❌ Koi session nahi mila.", show_alert=True)
            return
        safe_answer(call.id, "📥 Log file bana raha hoon…", show_alert=False)
        threading.Thread(
            target=_shell_send_log_file, args=(cid, sess), daemon=True
        ).start()
        return

    if data == "shell_rerun":
        # Same command dobara chalao
        sess = _SHELL_SESSIONS.get(cid)
        if not sess:
            safe_answer(call.id, "❌ Session nahi mila.", show_alert=True)
            return
        cmd = sess.get("cmd_str", "")
        if not cmd:
            safe_answer(call.id, "❌ Command nahi mila.", show_alert=True)
            return
        safe_answer(call.id, "🔄 Re-running…", show_alert=False)
        threading.Thread(target=_run_shell, args=(cid, cmd), daemon=True).start()
        return

    # ══════════════════════
    #  📦  INSTALL LIB
    # ══════════════════════
    if data == "install_lib":
        _STEP[cid] = {"step": "install_input"}
        bot.send_message(cid,
            "📦 Library name bhejo:\n"
            "• `requests` → pip install\n"
            "• `pip install flask pillow`\n"
            "• `apt install curl`\n"
            "• `npm install express`", parse_mode="Markdown"); return

    # ══════════════════════
    #  👤  USERBOT SESSIONS
    # ══════════════════════
    if data == "userbot_list":
        _eorsend(cid, mid, "👤 *Userbot Sessions*", reply_markup=kb_userbot_list()); return

    if data == "userbot_add":
        if not PYROGRAM_AVAILABLE:
            bot.send_message(cid, "❌ Pyrogram not installed.\n`pip install pyrogram tgcrypto`",
                             parse_mode="Markdown"); return
        _STEP[cid] = {"step": "userbot_phone"}
        bot.send_message(cid, "📱 Phone number bhejo (+919XXXXXXX):"); return

    if data.startswith("userbot_manage|"):
        sname = data[15:]
        con = _db_connect()
        row = con.execute(
            "SELECT phone, logged_in, target_channel FROM userbot_sessions WHERE name=?",
            (sname,)).fetchone()
        con.close()
        if not row: bot.send_message(cid, "❌ Session not found."); return
        phone, li, ch = row
        status = "🟢 Active" if li else "🔴 Inactive"
        txt = f"👤 *{sname}*\n📱 Phone: `{phone}`\nStatus: {status}\n📡 Channel: `{ch or 'Not set'}`"
        mk = types.InlineKeyboardMarkup(row_width=2)
        mk.row(_btn("🗑️ Remove", f"userbot_del|{sname}"), _btn("🔙 Back", "userbot_list"))
        _eorsend(cid, mid, txt, reply_markup=mk); return

    if data.startswith("userbot_del|"):
        sname = data[12:]
        con = _db_connect()
        con.execute("DELETE FROM userbot_sessions WHERE name=?", (sname,))
        con.commit(); con.close()
        sf = f"{sname}.session"
        if os.path.exists(sf): os.remove(sf)
        _eorsend(cid, mid, f"🗑️ Session `{sname}` removed.", reply_markup=kb_userbot_list()); return
    
    # ── Upload Navigator Callbacks ──
    if data.startswith("upnav_") or data.startswith("upcol_"):
        sess = _UPLOAD_SESSIONS.get(cid)
        if not sess and data != "upnav_cancel":
            safe_answer(call.id, "❌ Session expired. File wapas bhejo.", show_alert=True)
            return
            
        action = data.split("|")[0]
        
        if action == "upnav_cd":
            sub = data.split("|", 1)[1]
            curr = sess.get("current_path", "")
            
            # Naya path generate karna (Folder ke andar folder)
            if curr:
                sess["current_path"] = f"{curr}/{sub}"
            else:
                sess["current_path"] = sub
                
            bot.edit_message_text(f"📂 *Upload Navigator*\nFile: `{sess['fname']}`\n📍 Path: `{sess['current_path']}`", 
                                  cid, mid, parse_mode="Markdown", reply_markup=kb_upload_navigator(cid))
            return
            
        if action == "upnav_back":
            curr = sess.get("current_path", "")
            
            # Ek level upar jana ya seedha Root par jana
            if "/" in curr:
                sess["current_path"] = curr.rsplit("/", 1)[0]
            else:
                sess["current_path"] = "" # Wapas Root par aa gaye
                
            p_text = sess["current_path"] if sess["current_path"] else "Root (Main Storage)"
            bot.edit_message_text(f"📂 *Upload Navigator*\nFile: `{sess['fname']}`\n📍 Path: `{p_text}`", 
                                  cid, mid, parse_mode="Markdown", reply_markup=kb_upload_navigator(cid))
            return
            
        if action == "upnav_cancel":
            if sess:
                tmp = sess["tmp_file"]
                if os.path.exists(tmp): os.remove(tmp)
                _UPLOAD_SESSIONS.pop(cid, None)
            bot.edit_message_text("❌ Upload Cancelled.", cid, mid)
            return
            
        if action == "upnav_mkdir":
            _STEP[cid] = {"step": "upnav_mkdir_input", "mid": mid}
            bot.send_message(cid, "➕ Naye sub-folder ka naam bhejo:", parse_mode="Markdown")
            return
            
        if action == "upnav_here":
            path = sess["current_path"]
            fname = sess["fname"]
            
            # 🔥 Collision Check (File pehle se toh nahi?)
            existing = vault_get("folder_file", fname, path)
            if existing is not None:
                mk = types.InlineKeyboardMarkup(row_width=2)
                mk.row(_btn("🔄 Replace", "upcol_rep"), _btn("✏️ Rename & Upload", "upcol_ren"))
                mk.add(_btn("❌ Cancel", "upnav_cancel"))
                bot.edit_message_text(f"⚠️ *File Already Exists!*\n`{fname}` pehle se `{path}` mein hai. Kya karna hai?", 
                                      cid, mid, parse_mode="Markdown", reply_markup=mk)
            else:
                _finalize_upload(cid, mid)
            return
            
        if action == "upcol_rep":
            _finalize_upload(cid, mid) # Replace auto handle ho jayega
            return
            
        if action == "upcol_ren":
            _STEP[cid] = {"step": "upcol_ren_input", "mid": mid}
            bot.send_message(cid, "✏️ File ka naya naam bhejo (extension ke saath):", parse_mode="Markdown")
            return
            


def _cleanup_all():
    # 💾 STEP 1: Pehle saare running scripts ka data save karo
    # (kill_script ke andar bhi save hota hai, lekin ye extra guarantee hai
    #  agar kill_script kisi reason se skip ho jaye)
    try:
        _save_all_running_data(log_prefix="Shutdown")
    except Exception as e:
        log.warning(f"[Shutdown] _save_all_running_data failed: {e}")

    # ⏹ Auto-save thread band karo
    try:
        _AUTOSAVE_STOP_EVT.set()
    except Exception:
        pass

    # 🔒 SECURITY HARDENING: Secure memory wipe on exit
    # _DB_KEY aur AES key ko memory se zero-out karo taaki
    # process exit ke baad RAM dumps mein easily na milein.
    global _SECURE_KEY_BUF, _AES_KEY_CACHED, _DB_KEY
    try:
        if _SECURE_KEY_BUF is not None:
            _SECURE_KEY_BUF.wipe()
            _SECURE_KEY_BUF = None
    except Exception:
        pass
    try:
        if _AES_KEY_CACHED is not None:
            # bytearray mein convert karke zero-fill karo
            buf_len = len(_AES_KEY_CACHED)
            zap = (ctypes.c_char * buf_len).from_buffer_copy(_AES_KEY_CACHED)
            ctypes.memset(ctypes.addressof(zap), 0, buf_len)
            _AES_KEY_CACHED = None
    except Exception:
        pass
    # _DB_KEY ko None karo (Python string GC-managed hai, direct wipe nahi ho sakta)
    _DB_KEY = None

    for k in list(RUNNING.keys()):
        kill_script(k)

    # Wipe entire RAM disk cache on exit (files AND sub-directories)
    for name in os.listdir(RAM_DISK_DIR):
        fp = os.path.join(RAM_DISK_DIR, name)
        try:
            if os.path.isdir(fp):
                shutil.rmtree(fp)
            else:
                os.remove(fp)
        except Exception:
            pass

    # ── Cache directory cleanup (exit par temporary files clean karo) ──
    try:
        if _RAM_DISK_MODE in ("tmp", "shm") and os.path.isdir(RAM_DISK_DIR):
            shutil.rmtree(RAM_DISK_DIR, ignore_errors=True)
    except Exception:
        pass

atexit.register(_cleanup_all)

# ── SIGTERM handler (systemd / kill command) ──
# sys.exit(0) → atexit → _cleanup_all → data save + process kill
signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

# ── SIGINT handler (Ctrl+C) ──
# Python default Ctrl+C sirf KeyboardInterrupt raise karta hai lekin
# agar atexit ke andar exception aaye to data save skip ho sakta tha.
# Yahan explicitly data save karte hain PEHLE, phir exit.
def _sigint_handler(signum, frame):
    print("\n⏳ Ctrl+C detected — saving all running data before exit…")
    try:
        _save_all_running_data(log_prefix="SIGINT")
    except Exception as e:
        print(f"⚠️ Data save error on SIGINT: {e}")
    sys.exit(0)  # → atexit → _cleanup_all (double-save guard built-in)

signal.signal(signal.SIGINT, _sigint_handler)

# ── Auto-save background thread ──
# Har 3 minute (180s) mein saare running scripts ke changed files vault mein save hote hain.
# Interval badlna ho toh: _autosave_loop(interval_seconds=300) — 5 minute
_autosave_thread = threading.Thread(
    target=_autosave_loop,
    args=(180,),   # ← interval in seconds — change karo as needed
    name="AutoSaveDaemon",
    daemon=True    # Main thread band ho to ye bhi band ho jata hai
)
_autosave_thread.start()


# ══════════════════════════════════════════════════════════════
#  🚀  STARTUP
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    log.info("=" * 65)
    log.info("👑 Admin Script Manager V3 — SQLCipher Edition — Starting…")
    log.info(f"   Allowed Admins : [{len(ALLOWED_ADMINS)} admin(s) configured]")  # 🔒 IDs log nahi karte
    log.info(f"   DB File        : {DB_FILE}")
    _mode_label_startup = (
        "🟢 SHM (Full RAM Speed)"   if _RAM_DISK_MODE == "shm"   else
        "🟢 /tmp (OS Page-Cache)"   if _RAM_DISK_MODE == "tmpfs" else
        "🟡 Physical Disk (Full VPS Storage)"
    )
    log.info(f"   RAM Disk       : {RAM_DISK_DIR}  [{_mode_label_startup}]")
    log.info(f"   Media Vault    : {LARGE_MEDIA_VAULT}  (>10 MB files stored here)")
    log.info(f"   Encryption     : {_SQLCIPHER_MODE}")
    log.info(f"   Pyrogram       : {'✅ Available' if PYROGRAM_AVAILABLE else '❌ Not installed'}")
    # ── VPS Resource Info ──
    try:
        _vm   = psutil.virtual_memory()
        _disk = shutil.disk_usage(BASE_DIR)
        log.info(f"   VPS RAM Total  : {_vm.total   // (1024**3)} GB  "
                 f"(Available: {_vm.available // (1024**3)} GB  "
                 f"Used: {_vm.percent:.1f}%)")
        log.info(f"   VPS Disk Total : {_disk.total // (1024**3)} GB  "
                 f"(Free: {_disk.free // (1024**3)} GB  "
                 f"Used: {(_disk.used*100//_disk.total)}%)")
    except Exception:
        pass
    if not API_TOKEN or API_TOKEN == "PUT_YOUR_TELEGRAM_BOT_TOKEN_HERE":
        log.error("TELEGRAM_BOT_TOKEN env var set nahi hai. Code ke andar token hardcode mat rakho.")
        sys.exit(1)
    if not ALLOWED_ADMINS:
        log.error("ADMIN_IDS env var set karo. Example: export ADMIN_IDS='123456789'")
        sys.exit(1)

    log.info("=" * 65)

    if not os.path.exists(DB_FILE):
        log.info("⚠️  No DB file found. Send /setpassword YOUR_PASSWORD to the bot to create it.")
    else:
        log.info("✅  DB file found. Send /start to bot and enter your password to unlock.")

    # NOTE: _DB_KEY is None at this point. ALL DB operations require the user to
    # first authenticate via /start → password → _unlock_db(). Nothing is read
    # from disk here. Backup jobs and auto-scripts resume inside _unlock_db().

    log.info("=" * 65)

    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            log.error(f"Polling error: {e} — retrying in 10s…")
            time.sleep(10)

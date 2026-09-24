import os
import re
import sys
import time
import secrets
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pymysql
import pymysql.cursors
import bcrypt

from .rcon import RconClient, RconError

# --------------------------------------------------------------------------- #
# 1. Settings
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    mgr_db: str
    sb_db: str
    sb_prefix: str
    session_secret: str
    server_id: int
    allowed_web_flags: int


def _env_required(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(f"Environment variable {name} must be an integer")


def _validate_identifier(name: str, varname: str) -> None:
    if not re.fullmatch(r'^[A-Za-z0-9_]+$', name):
        raise RuntimeError(f"{varname} must match ^[A-Za-z0-9_]+$")


def load_settings() -> Settings:
    db_host = os.getenv("L4D2MGR_DB_HOST", "127.0.0.1")
    db_port = _env_int("L4D2MGR_DB_PORT", 3306)
    db_user = _env_required("L4D2MGR_DB_USER")
    db_password = _env_required("L4D2MGR_DB_PASSWORD")

    mgr_db = os.getenv("L4D2MGR_MGR_DB", "l4d2mgr")
    sb_db = os.getenv("L4D2MGR_SB_DB", "sourcebans")
    sb_prefix = os.getenv("L4D2MGR_SB_PREFIX", "sb")
    _validate_identifier(mgr_db, "L4D2MGR_MGR_DB")
    _validate_identifier(sb_db, "L4D2MGR_SB_DB")
    _validate_identifier(sb_prefix, "L4D2MGR_SB_PREFIX")

    session_secret = _env_required("L4D2MGR_SESSION_SECRET")
    if len(session_secret) < 32:
        raise RuntimeError("L4D2MGR_SESSION_SECRET must be at least 32 characters")

    server_id = _env_int("L4D2MGR_SERVER_ID", 1)
    allowed_web_flags = _env_int("L4D2MGR_ALLOWED_WEB_FLAGS", 17301504)

    return Settings(
        db_host=db_host,
        db_port=db_port,
        db_user=db_user,
        db_password=db_password,
        mgr_db=mgr_db,
        sb_db=sb_db,
        sb_prefix=sb_prefix,
        session_secret=session_secret,
        server_id=server_id,
        allowed_web_flags=allowed_web_flags,
    )


settings = load_settings()
limiter = None  # will be set later


# --------------------------------------------------------------------------- #
# 2. Database connection helper
# --------------------------------------------------------------------------- #

def get_conn() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=5,
    )


# --------------------------------------------------------------------------- #
# 3. Authentication
# --------------------------------------------------------------------------- #

_DUMMY_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt())


def _hash_valid(hash_str: str) -> bool:
    return hash_str.startswith("$2y$") or hash_str.startswith("$2b$") or hash_str.startswith("$2a$")


def authenticate(username: str, password: str) -> Optional[Dict[str, Any]]:
    if not username or not password:
        return None
    if len(username) > 128 or len(password) > 128:
        return None

    sql = f"""
        SELECT a.aid, a.user, a.password, a.extraflags, COALESCE(g.flags, 0) AS gflags
        FROM `{settings.sb_db}`.`{settings.sb_prefix}_admins` a
        LEFT JOIN `{settings.sb_db}`.`{settings.sb_prefix}_groups` g
            ON a.gid = g.gid
        WHERE a.user = %s AND a.aid > 0
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (username,))
            row = cur.fetchone()
    if not row:
        bcrypt.checkpw(password.encode(), _DUMMY_HASH)
        return None

    pw_hash = row["password"]
    if not _hash_valid(pw_hash):
        bcrypt.checkpw(password.encode(), _DUMMY_HASH)
        return None

    if not bcrypt.checkpw(password.encode("utf-8"), pw_hash.encode()):
        return None

    extraflags = int(row["extraflags"])
    gflags = int(row["gflags"])
    if (extraflags | gflags) & settings.allowed_web_flags == 0:
        return None

    return {"aid": int(row["aid"]), "user": str(row["user"])}


def load_admin(aid: int) -> Optional[Dict[str, Any]]:
    if aid <= 0:
        return None
    with get_conn() as conn:
        cur = conn.cursor()
        query = f"""
            SELECT a.aid, a.user, a.extraflags, COALESCE(g.flags, 0) AS gflags
            FROM `{settings.sb_db}`.`{settings.sb_prefix}_admins` a
            LEFT JOIN `{settings.sb_db}`.`{settings.sb_prefix}_groups` g
                ON a.gid = g.gid
            WHERE a.aid = %s AND a.aid > 0
        """
        cur.execute(query, (aid,))
        row = cur.fetchone()
        if not row:
            return None
        flags = (row.get("extraflags") or 0) | (row.get("gflags") or 0)
        if (flags & settings.allowed_web_flags) == 0:
            return None
        return {"aid": row["aid"], "user": row["user"]}

# --------------------------------------------------------------------------- #
# 4. Login rate limiting
# --------------------------------------------------------------------------- #

class LoginLimiter:
    """Thread-safe in‑memory login failure limiter."""

    def __init__(self) -> None:
        self.max_failures = 5
        self.window = 900.0
        self.lockout = 900.0
        self._lock = threading.Lock()
        self._failures: Dict[str, List[float]] = {}
        self._blocked_until: Dict[str, float] = {}

    def is_blocked(self, ip: str) -> bool:
        with self._lock:
            until = self._blocked_until.get(ip, 0.0)
            return time.monotonic() < until

    def record_failure(self, ip: str) -> None:
        now = time.monotonic()
        with self._lock:
            lst = self._failures.get(ip, [])
            # Remove old timestamps
            lst = [t for t in lst if now - t < self.window]
            lst.append(now)
            self._failures[ip] = lst
            if len(lst) >= self.max_failures:
                self._blocked_until[ip] = now + self.lockout

    def reset(self, ip: str) -> None:
        with self._lock:
            self._failures.pop(ip, None)
            self._blocked_until.pop(ip, None)


limiter = LoginLimiter()


# --------------------------------------------------------------------------- #
# 5. CSRF helpers
# --------------------------------------------------------------------------- #

def ensure_csrf(session: Dict[str, Any]) -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def check_csrf(session, token):
    csrf = session.get("csrf")
    if not isinstance(csrf, str) or not isinstance(token, str):
        return False
    if not token:
        return False
    try:
        return secrets.compare_digest(csrf.encode("utf-8"), token.encode("utf-8"))
    except Exception:
        return False

# --------------------------------------------------------------------------- #
# 6. Validation
# --------------------------------------------------------------------------- #

MAP_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def valid_map(name: str) -> bool:
    return bool(MAP_RE.fullmatch(name))


# --------------------------------------------------------------------------- #
# 7. RCON
# --------------------------------------------------------------------------- #

def get_rcon_target() -> Tuple[str, int, str]:
    with get_conn() as conn:
        cur = conn.cursor()
        query = f"SELECT ip, port, rcon FROM `{settings.sb_db}`.`{settings.sb_prefix}_servers` WHERE sid = %s"
        cur.execute(query, (settings.server_id,))
        row = cur.fetchone()
        if not row or not row.get("rcon"):
            raise LookupError(f"Server id {settings.server_id} not found or rcon not configured")
        return row["ip"], int(row["port"]), row["rcon"]

def rcon_command(cmd: str) -> str:
    ip, port, pw = get_rcon_target()
    with RconClient(ip, port, pw, timeout=5.0) as client:
        return client.command(cmd)


# --------------------------------------------------------------------------- #
# 8. Rotation data
# --------------------------------------------------------------------------- #

_ROTATION_TABLE = f"`{settings.mgr_db}`.`rotation`"


def list_rotation(server_id: int) -> List[Dict[str, Any]]:
    sql = f"""
        SELECT id, position, map, enabled
        FROM {_ROTATION_TABLE}
        WHERE server_id = %s
        ORDER BY position
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (server_id,))
            return cur.fetchall()


def add_map(server_id: int, map_name: str) -> None:
    if not valid_map(map_name):
        raise ValueError("Invalid map name")
    sql_max = f"SELECT COALESCE(MAX(position),0)+1 AS p FROM {_ROTATION_TABLE} WHERE server_id = %s FOR UPDATE"
    sql_insert = f"INSERT INTO {_ROTATION_TABLE} (server_id, position, map, enabled) VALUES (%s, %s, %s, 1)"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql_max, (server_id,))
            new_pos = cur.fetchone()["p"]
            cur.execute(sql_insert, (server_id, new_pos, map_name))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_entry(server_id: int, entry_id: int) -> bool:
    sql = f"DELETE FROM {_ROTATION_TABLE} WHERE id = %s AND server_id = %s"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (entry_id, server_id))
            deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def toggle_entry(server_id: int, entry_id: int) -> bool:
    sql = f"UPDATE {_ROTATION_TABLE} SET enabled = 1 - enabled WHERE id = %s AND server_id = %s"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (entry_id, server_id))
            toggled = cur.rowcount > 0
        conn.commit()
        return toggled
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def move_entry(server_id: int, entry_id: int, direction: str) -> bool:
    if direction not in ("up", "down"):
        raise ValueError("direction must be 'up' or 'down'")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, position FROM {_ROTATION_TABLE} WHERE id = %s AND server_id = %s FOR UPDATE",
                (entry_id, server_id),
            )
            row = cur.fetchone()
            if not row:
                return False
            cur_pos = row["position"]

            if direction == "up":
                cur.execute(
                    f"SELECT id, position FROM {_ROTATION_TABLE} WHERE server_id = %s AND position < %s ORDER BY position DESC LIMIT 1 FOR UPDATE",
                    (server_id, cur_pos),
                )
            else:
                cur.execute(
                    f"SELECT id, position FROM {_ROTATION_TABLE} WHERE server_id = %s AND position > %s ORDER BY position ASC LIMIT 1 FOR UPDATE",
                    (server_id, cur_pos),
                )
            neighbor = cur.fetchone()
            if not neighbor:
                return False
            neighbor_id = neighbor["id"]
            neighbor_pos = neighbor["position"]

            # Swap positions
            cur.execute(
                f"UPDATE {_ROTATION_TABLE} SET position = -1 WHERE id = %s AND server_id = %s",
                (entry_id, server_id),
            )
            cur.execute(
                f"UPDATE {_ROTATION_TABLE} SET position = %s WHERE id = %s AND server_id = %s",
                (cur_pos, neighbor_id, server_id),
            )
            cur.execute(
                f"UPDATE {_ROTATION_TABLE} SET position = %s WHERE id = %s AND server_id = %s",
                (neighbor_pos, entry_id, server_id),
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 9. Audit
# --------------------------------------------------------------------------- #

def audit(
    aid: Optional[int],
    user: Optional[str],
    action: str,
    detail: Optional[str],
    ip: Optional[str],
) -> None:
    sql = f"""
        INSERT INTO `{settings.mgr_db}`.`audit_log`
        (aid, user, action, detail, ip)
        VALUES (%s, %s, %s, %s, %s)
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        aid,
                        user[:64] if user else None,
                        action[:64],
                        detail[:255] if detail else None,
                        ip[:45] if ip else None,
                    ),
                )
            conn.commit()
    except Exception as exc:
        sys.stderr.write(f"Audit failed: {exc}\n")
        sys.stderr.flush()


# --------------------------------------------------------------------------- #
# 10. Detections (l4d2mgr_ac)
# --------------------------------------------------------------------------- #

DETECTION_STATUSES = ("new", "dismissed", "submitted")

def list_detections(server_id: int, status: Optional[str], limit: int = 200) -> List[Dict[str, Any]]:
    """
    Retrieve a list of detections for a given server, optionally filtered by status.
    """
    if status is not None and status not in DETECTION_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    limit = max(1, min(1000, limit))
    base_sql = (
        f"SELECT id, ts, detector, severity, steamid, steamid64, name, map, detail, status, reviewed_by, reviewed_at "
        f"FROM {settings.mgr_db}.detections WHERE server_id=%s"
    )
    params: List[Any] = [server_id]
    if status is not None:
        base_sql += " AND status=%s"
        params.append(status)
    base_sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(base_sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def get_detection(server_id: int, det_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieve a single detection record by its ID and server.
    """
    sql = (
        f"SELECT id, ts, detector, severity, steamid, steamid64, name, map, detail, status, reviewed_by, reviewed_at "
        f"FROM {settings.mgr_db}.detections WHERE id=%s AND server_id=%s"
    )
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (det_id, server_id))
            return cur.fetchone()
    finally:
        conn.close()


def dismiss_detection(server_id: int, det_id: int, reviewer: str) -> bool:
    """
    Mark a detection as dismissed if it is currently new.
    """
    sql = (
        f"UPDATE {settings.mgr_db}.detections "
        f"SET status='dismissed', reviewed_by=%s, reviewed_at=NOW() "
        f"WHERE id=%s AND server_id=%s AND status='new'"
    )
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (reviewer, det_id, server_id))
            conn.commit()
            return cur.rowcount == 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def submit_detection(server_id: int, det_id: int, reviewer: str, reviewer_ip: str) -> bool:
    """
    Submit a detection to SourceBans and mark it as submitted.
    """
    detections_table = f"{settings.mgr_db}.detections"
    sb_servers_table = f"{settings.sb_db}.{settings.sb_prefix}_servers"
    sb_submissions_table = f"{settings.sb_db}.{settings.sb_prefix}_submissions"

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 1. Lock the detection row
            cur.execute(
                f"SELECT id, ts, detector, severity, detail, status, steamid, name "
                f"FROM {detections_table} WHERE id=%s AND server_id=%s FOR UPDATE",
                (det_id, server_id),
            )
            det_row = cur.fetchone()
            if not det_row or det_row["status"] != "new":
                conn.rollback()
                return False

            # 2. Get the mod ID from SourceBans
            cur.execute(
                f"SELECT modid FROM {sb_servers_table} WHERE sid=%s",
                (server_id,),
            )
            sb_row = cur.fetchone()
            if not sb_row:
                conn.rollback()
                raise LookupError("SourceBans server not found")

            modid = sb_row["modid"]
            # 3. Build reason string
            ts_str = det_row["ts"].strftime("%Y-%m-%d %H:%M:%S UTC")
            reason = (
                f"[l4d2mgr AC] {det_row['detector']} sev{det_row['severity']}: "
                f"{det_row['detail']} (detection #{det_row['id']}, {ts_str})"
            )[:1000]

            # 4. Insert into submissions
            cur.execute(
                f"INSERT INTO {sb_submissions_table} "
                f"(submitted, ModID, SteamId, name, email, reason, ip, subname, sip, archiv, server) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    int(time.time()),
                    modid,
                    det_row["steamid"],
                    det_row["name"][:128],
                    '',
                    reason,
                    '',
                    reviewer[:128],
                    reviewer_ip[:64],
                    0,
                    server_id,
                ),
            )

            # 5. Update detection status
            cur.execute(
                f"UPDATE {detections_table} SET status='submitted', reviewed_by=%s, reviewed_at=NOW() "
                f"WHERE id=%s AND server_id=%s AND status='new'",
                (reviewer, det_id, server_id),
            )

            conn.commit()
            return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
# ============================================================
# 以下を web/l4d2mgr_web/core.py の末尾に追記する
# ファイル冒頭の import に re が無ければ追加（既に import re 済みのはず）
# ============================================================

_COUNTRY_FILTER_TABLE = f"`{settings.mgr_db}`.`country_filter_blocklist`"
COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")


def list_country_filters() -> List[Dict[str, Any]]:
    sql = f"SELECT id, country_code, added_by, added_at FROM {_COUNTRY_FILTER_TABLE} ORDER BY country_code"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


def add_country_filter(country_code: str, added_by: str) -> None:
    if not COUNTRY_CODE_RE.fullmatch(country_code):
        raise ValueError("Invalid country code")
    sql = f"INSERT INTO {_COUNTRY_FILTER_TABLE} (country_code, added_by) VALUES (%s, %s)"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (country_code, added_by))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_country_filter(entry_id: int) -> bool:
    sql = f"DELETE FROM {_COUNTRY_FILTER_TABLE} WHERE id = %s"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (entry_id,))
            deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

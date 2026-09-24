from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    FastAPI,
    Request,
    Form,
    HTTPException,
    status,
    Depends,
)
from fastapi.responses import (
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from . import core

# ----------------------------------------------
# App setup
# ----------------------------------------------
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    SessionMiddleware,
    secret_key=core.settings.session_secret,
    session_cookie="l4d2mgr_session",
    max_age=8 * 3600,
    same_site="strict",
    https_only=False,
)

# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers[
        "Content-Security-Policy"
    ] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return response

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# ----------------------------------------------
# Helpers
# ----------------------------------------------
def client_ip(request: Request) -> str:
    host = request.client.host if request.client else ""
    if host in ("127.0.0.1", "::1") and (real_ip := request.headers.get("X-Real-IP")):
        return real_ip
    return host

def flash(request: Request, level: str, msg: str) -> None:
    request.session.setdefault("flash", []).append([level, msg])

def pop_flashes(request: Request) -> List[List[str]]:
    return request.session.pop("flash", [])

def current_admin(request: Request) -> Optional[Dict[str, Any]]:
    aid = request.session.get("aid")
    if not isinstance(aid, int):
        return None
    admin = core.load_admin(aid)
    if admin is None:
        request.session.clear()
        return None
    return admin

def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)

def require_csrf(request: Request, token: str) -> None:
    if not core.check_csrf(request.session, token):
        raise HTTPException(status_code=403, detail="CSRF token invalid")

def reload_rotation_plugin(request: Request) -> None:
    try:
        core.rcon_command("sm_rotation_reload")
    except (core.RconError, LookupError, OSError) as exc:
        flash(request, "error", f"Saved, but RCON reload failed: {exc}")

# ----------------------------------------------
# Routes
# ----------------------------------------------
@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"

@app.get("/login")
def get_login(request: Request):
    if current_admin(request):
        return redirect("/")
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "csrf": core.ensure_csrf(request.session),
            "flashes": pop_flashes(request),
        },
    )

@app.post("/login")
def post_login(request: Request, username: str = Form(""), password: str = Form(""), csrf: str = Form("")):
    # Validate CSRF first
    require_csrf(request, csrf)
    ip = client_ip(request)
    if core.limiter.is_blocked(ip):
        flash(request, "error", "Too many failed attempts. Try again later.")
        core.audit(None, username[:64], "login_blocked", None, ip)
        return redirect("/login")
    try:
        admin = core.authenticate(username, password)
    except Exception as e:
        flash(request, "error", f"Database error: {type(e).__name__}")
        return redirect("/login")
    if admin is None:
        core.limiter.record_failure(ip)
        core.audit(None, username[:64], "login_failed", None, ip)
        flash(request, "error", "Invalid credentials or insufficient permissions.")
        return redirect("/login")
    core.limiter.reset(ip)
    request.session.clear()
    request.session["aid"] = admin["aid"]
    request.session["user"] = admin["user"]
    core.ensure_csrf(request.session)
    core.audit(admin["aid"], admin["user"], "login", None, ip)
    return redirect("/")

@app.post("/logout")
def post_logout(request: Request, csrf: str = Form("")):
    admin = current_admin(request)
    aid = admin["aid"] if admin else None
    user = admin["user"] if admin else None
    require_csrf(request, csrf)
    if aid is not None:
        core.audit(aid, user, "logout", None, client_ip(request))
    request.session.clear()
    return redirect("/login")

@app.get("/")
def index(request: Request):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    try:
        rotation = core.list_rotation(core.settings.server_id)
    except Exception as e:
        rotation = []
        flash(request, "error", f"Database error: {type(e).__name__}")
    status_text = None
    status_error = None
    try:
        status_text = core.rcon_command("status")
    except (core.RconError, LookupError, OSError) as exc:
        status_error = str(exc)
    try:
        new_detections = core.list_detections(core.settings.server_id, "new", 10)
    except Exception as e:
        new_detections = []
        flash(request, "error", f"Database error: {type(e).__name__}")
    try:
        country_filters = core.list_country_filters()
    except Exception as e:
        country_filters = []
        flash(request, "error", f"Database error: {type(e).__name__}")
    csrf = core.ensure_csrf(request.session)
    flashes = pop_flashes(request)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "admin": admin,
            "csrf": csrf,
            "flashes": flashes,
            "status_text": status_text,
            "status_error": status_error,
            "rotation": rotation,
            "server_id": core.settings.server_id,
            "new_detections": new_detections,
            "country_filters": country_filters,
        },
    )

@app.get("/rotation")
def rotation_page(request: Request):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    try:
        rotation = core.list_rotation(core.settings.server_id)
    except Exception as e:
        rotation = []
        flash(request, "error", f"Database error: {type(e).__name__}")
    csrf = core.ensure_csrf(request.session)
    flashes = pop_flashes(request)
    return templates.TemplateResponse(
        request,
        "rotation.html",
        {
            "admin": admin,
            "csrf": csrf,
            "flashes": flashes,
            "rotation": rotation,
        },
    )

# --------------------
# Rotation management
# --------------------
@app.post("/rotation/add")
def rotation_add(
    request: Request,
    map_name: str = Form(""),
    csrf: str = Form(""),
):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    require_csrf(request, csrf)
    ip = client_ip(request)
    core.audit(admin["aid"], admin["user"], "rotation_add", map_name, ip)
    map_name = map_name.strip()
    if not core.valid_map(map_name):
        flash(request, "error", "Invalid map name.")
        return redirect("/rotation")
    try:
        core.add_map(core.settings.server_id, map_name)
        flash(request, "ok", f"Added {map_name}")
        reload_rotation_plugin(request)
    except ValueError:
        flash(request, "error", "Invalid map name.")
    except Exception as e:
        flash(request, "error", f"Database error: {type(e).__name__}")
    return redirect("/rotation")

@app.post("/rotation/{entry_id}/delete")
def rotation_delete(
    request: Request,
    entry_id: int,
    csrf: str = Form(""),
):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    require_csrf(request, csrf)
    ip = client_ip(request)
    core.audit(admin["aid"], admin["user"], "rotation_delete", str(entry_id), ip)
    try:
        if core.delete_entry(core.settings.server_id, entry_id):
            flash(request, "ok", "Deleted entry")
            reload_rotation_plugin(request)
        else:
            flash(request, "error", "Entry not found.")
    except Exception as e:
        flash(request, "error", f"Database error: {type(e).__name__}")
    return redirect("/rotation")

@app.post("/rotation/{entry_id}/toggle")
def rotation_toggle(
    request: Request,
    entry_id: int,
    csrf: str = Form(""),
):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    require_csrf(request, csrf)
    ip = client_ip(request)
    core.audit(admin["aid"], admin["user"], "rotation_toggle", str(entry_id), ip)
    try:
        if core.toggle_entry(core.settings.server_id, entry_id):
            flash(request, "ok", "Toggled entry")
            reload_rotation_plugin(request)
        else:
            flash(request, "error", "Entry not found.")
    except Exception as e:
        flash(request, "error", f"Database error: {type(e).__name__}")
    return redirect("/rotation")

@app.post("/rotation/{entry_id}/move")
def rotation_move(
    request: Request,
    entry_id: int,
    direction: str = Form(""),
    csrf: str = Form(""),
):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    require_csrf(request, csrf)
    ip = client_ip(request)
    core.audit(admin["aid"], admin["user"], "rotation_move", f"{entry_id} {direction}", ip)
    if direction not in ("up", "down"):
        flash(request, "error", "Invalid direction.")
        return redirect("/rotation")
    try:
        moved = core.move_entry(core.settings.server_id, entry_id, direction)
        if moved:
            flash(request, "ok", "Moved entry")
            reload_rotation_plugin(request)
        else:
            flash(request, "error", "Cannot move.")
    except ValueError:
        flash(request, "error", "Invalid direction.")
    except Exception as e:
        flash(request, "error", f"Database error: {type(e).__name__}")
    return redirect("/rotation")

# --------------------
# Server actions
# --------------------
@app.post("/server/changelevel")
def server_changelevel(
    request: Request,
    map_name: str = Form(""),
    csrf: str = Form(""),
):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    require_csrf(request, csrf)
    ip = client_ip(request)
    core.audit(admin["aid"], admin["user"], "changelevel", map_name, ip)
    if not core.valid_map(map_name):
        flash(request, "error", "Invalid map name.")
        return redirect("/")
    try:
        core.rcon_command(f"changelevel {map_name}")
        flash(request, "ok", f"changelevel {map_name} sent")
    except (core.RconError, LookupError, OSError) as exc:
        flash(request, "error", str(exc))
    return redirect("/")

@app.post("/server/next")
def server_next(request: Request, csrf: str = Form("")):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    require_csrf(request, csrf)
    ip = client_ip(request)
    core.audit(admin["aid"], admin["user"], "rotation_next", None, ip)
    try:
        out = core.rcon_command("sm_rotation_next")
        flash(request, "ok", out.strip()[:200])
    except (core.RconError, LookupError, OSError) as exc:
        flash(request, "error", str(exc))
    return redirect("/")


# --------------------
# Detections (l4d2mgr_ac)
# --------------------
@app.get("/detections")
def detections_page(request: Request, status: str = "new"):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    if status == "all":
        filt = None
    elif status in core.DETECTION_STATUSES:
        filt = status
    else:
        status = "new"
        filt = status
    try:
        rows = core.list_detections(core.settings.server_id, filt, 200)
    except Exception as e:
        rows = []
        flash(request, "error", f"Database error: {type(e).__name__}")
    ctx = {
        "admin": admin,
        "csrf": core.ensure_csrf(request.session),
        "flashes": pop_flashes(request),
        "rows": rows,
        "status": status
    }
    return templates.TemplateResponse(request, "detections.html", ctx)

@app.post("/detections/{det_id}/dismiss")
def dismiss_detection(request: Request, det_id: int, csrf: str = Form("")):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    require_csrf(request, csrf)
    try:
        ok = core.dismiss_detection(core.settings.server_id, det_id, admin["user"])
        if ok:
            flash(request, "ok", f"Detection #{det_id} dismissed")
        else:
            flash(request, "error", "Already reviewed or not found.")
    except Exception as e:
        flash(request, "error", f"Database error: {type(e).__name__}")
    core.audit(admin["aid"], admin["user"], "detection_dismiss", str(det_id), client_ip(request))
    return redirect("/detections")

@app.post("/detections/{det_id}/submit")
def submit_detection(request: Request, det_id: int, csrf: str = Form("")):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    require_csrf(request, csrf)
    try:
        ok = core.submit_detection(core.settings.server_id, det_id, admin["user"], client_ip(request))
        if ok:
            flash(request, "ok", f"Detection #{det_id} sent to SourceBans++ as a ban report")
        else:
            flash(request, "error", "Already reviewed or not found.")
    except LookupError as e:
        flash(request, "error", str(e))
    except Exception as e:
        flash(request, "error", f"Database error: {type(e).__name__}")
    core.audit(admin["aid"], admin["user"], "detection_submit", str(det_id), client_ip(request))
    return redirect("/detections")
# ============================================================
# 以下を web/l4d2mgr_web/app.py に追記する
# ファイル冒頭に import re が無ければ追加すること
# reload_rotation_plugin() の近くに reload_country_filter_plugin() を追加、
# ルート定義群の末尾に3ルートを追加する想定
# ============================================================

def reload_country_filter_plugin(request: Request) -> None:
    try:
        core.rcon_command("sm_l4d2cf_reload")
    except (core.RconError, LookupError, OSError) as exc:
        flash(request, "error", f"Saved, but RCON reload failed: {exc}")


# --------------------
# Country filter management
# --------------------
@app.get("/country-filter")
def country_filter_page(request: Request):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    try:
        filters = core.list_country_filters()
    except Exception as e:
        filters = []
        flash(request, "error", f"Database error: {type(e).__name__}")
    csrf = core.ensure_csrf(request.session)
    flashes = pop_flashes(request)
    return templates.TemplateResponse(
        request,
        "country_filter.html",
        {
            "admin": admin,
            "csrf": csrf,
            "flashes": flashes,
            "filters": filters,
        },
    )


@app.post("/country-filter/add")
def country_filter_add(
    request: Request,
    code: str = Form(""),
    csrf: str = Form(""),
):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    require_csrf(request, csrf)
    ip = client_ip(request)
    core.audit(admin["aid"], admin["user"], "country_filter_add", code, ip)
    code = code.strip().upper()
    if not core.COUNTRY_CODE_RE.fullmatch(code):
        flash(request, "error", "Invalid country code (2-letter ISO 3166-1 alpha-2).")
        return redirect("/country-filter")
    try:
        core.add_country_filter(code, admin["user"])
        flash(request, "ok", f"Blocked country: {code}")
        reload_country_filter_plugin(request)
    except ValueError:
        flash(request, "error", "Invalid country code.")
    except Exception as e:
        flash(request, "error", f"Database error: {type(e).__name__}")
    return redirect("/country-filter")


@app.post("/country-filter/{entry_id}/delete")
def country_filter_delete(
    request: Request,
    entry_id: int,
    csrf: str = Form(""),
):
    admin = current_admin(request)
    if not admin:
        return redirect("/login")
    require_csrf(request, csrf)
    ip = client_ip(request)
    core.audit(admin["aid"], admin["user"], "country_filter_delete", str(entry_id), ip)
    try:
        if core.delete_country_filter(entry_id):
            flash(request, "ok", "Deleted entry")
            reload_country_filter_plugin(request)
        else:
            flash(request, "error", "Entry not found.")
    except Exception as e:
        flash(request, "error", f"Database error: {type(e).__name__}")
    return redirect("/country-filter")

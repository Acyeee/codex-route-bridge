"""Restricted local desktop IPC. Credentials never appear in returned JSON."""
from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("CODEX_ROUTE_HOME", str(Path.home() / ".codex/route-switch")))


def plain_path(path):
    # Tauri hands over verbatim paths (backslash-backslash-?-backslash prefix); PowerShell cannot resolve a drive from them.
    verbatim, unc = chr(92) * 2 + "?" + chr(92), chr(92) * 2 + "?" + chr(92) + "UNC" + chr(92)
    text = str(path)
    if text.startswith(unc):
        return Path(chr(92) * 2 + text[len(unc):])
    return Path(text[len(verbatim):]) if text.startswith(verbatim) else Path(text)


BUNDLE = plain_path(Path(__file__).resolve().parent)


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def backup(path):
    if path.exists():
        path.with_suffix(path.suffix + ".bak").write_bytes(path.read_bytes())


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value):
        raise ValueError("线路标识只能使用字母、数字、下划线和短横线。")
    return value


def valid_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("请填写完整 API 地址；不要在地址中放入密钥或查询参数。")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("远程站点须使用 HTTPS；本机端口可以使用 HTTP。")
    _ = parsed.port
    return value.rstrip("/")


class Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, decrypt=False):
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypto = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypto.CryptUnprotectData if decrypt else crypto.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    fn.restype = ctypes.c_int
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError("Windows 凭据加密失败，请使用原 Windows 账户重试。")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.memset(target.data, 0, target.size)
        kernel.LocalFree(target.data)
        ctypes.memset(buffer, 0, len(data))


def key_for(profile):
    path = ROOT / "credentials" / (valid_id(profile["id"]) + ".dpapi")
    if path.exists():
        return protect(path.read_bytes(), True).decode("utf-8")
    key = os.environ.get(profile.get("credentialEnv") or "", "")
    if key:
        return key
    return ""


def state():
    value = read(ROOT / "profiles.json", {"version": 1, "activeProfile": "official", "profiles": [
        {"id": "official", "name": "官方 Plus", "kind": "official", "enabled": True}
    ]})
    active = read(ROOT / "active-profile.json", {})
    value["activeProfile"] = active.get("profileId", value.get("activeProfile"))
    return value


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def snapshot():
    value = state()
    rows = []
    for p in value["profiles"]:
        # Whitelist metadata; no secret-bearing field can be serialized accidentally.
        row = {k: p.get(k) for k in ("id", "name", "kind", "baseUrl", "model", "enabled")}
        if p.get("kind") == "relay":
            row["models"] = models_for(p)
        row["hasCredential"] = p.get("kind") == "official" or bool(key_for(p))
        rows.append(row)
    launched = read(ROOT / "desktop-launch.json")
    confirmed = read(ROOT / "desktop-confirmation.json")
    running = bool(launched and process_alive(launched.get("pid")))
    verified = bool(running and confirmed and confirmed.get("launchId") == launched.get("launchId") and confirmed.get("profileId") == launched.get("profileId"))
    return {"activeProfile": value.get("activeProfile"), "providers": rows,
            "launchedProfile": launched.get("profileId") if running else None,
            "launchedUnpatched": bool(running and launched.get("unpatched")),
            "confirmedProfile": confirmed.get("profileId") if verified else None,
            "confirmedAt": confirmed.get("utc") if verified else None}


def models_for(profile):
    """Every model the relay offers, default first; older profiles only stored the default."""
    models = [m for m in profile.get("models") or [] if isinstance(m, str)]
    default = profile.get("model")
    if default and default not in models:
        models.insert(0, default)
    return models


def clean_models(values, default):
    if values is None:
        values = []
    if not isinstance(values, list) or len(values) > 500:
        raise ValueError("模型列表格式不正确，或超过 500 个。")
    seen, models = set(), []
    for item in values:
        item = str(item).strip()
        if not item or len(item) > 128 or any(ord(c) < 32 for c in item):
            raise ValueError("模型名不能为空、超过 128 个字符或含控制字符。")
        if item not in seen:
            seen.add(item)
            models.append(item)
    if default not in seen:
        models.insert(0, default)
    return models


def profile_for(profile_id):
    profile_id = valid_id(profile_id)
    found = next((p for p in state()["profiles"] if p["id"] == profile_id and p.get("enabled", True)), None)
    if found is None:
        raise ValueError("找不到这条线路，可能已被删除，请刷新后重试。")
    return found


def save(args):
    profile_id = valid_id(args.get("id"))
    if profile_id == "official":
        raise ValueError("官方登录由 Codex 管理，无需编辑。")
    name, model = str(args.get("name", "")).strip(), str(args.get("model", "")).strip()
    key = str(args.get("key") or "").strip()
    if not name or len(name) > 100 or not model or len(model) > 128 or any(ord(c) < 32 for c in name + model + key):
        raise ValueError("请填写线路名称和模型；字段不能含控制字符。")
    base = valid_url(str(args.get("baseUrl") or "").strip())
    models = clean_models(args.get("models"), model)
    value = state()
    old = next((p for p in value["profiles"] if p["id"] == profile_id), {})
    if not key and not (old and key_for(old)):
        raise ValueError("新线路需要 API Key。")
    new = dict(old, id=profile_id, name=name, kind="relay", baseUrl=base, model=model, models=models,
               wireApi="responses", enabled=True, requiresOpenAIAuth=False)
    backup(ROOT / "profiles.json")
    if key:
        folder = ROOT / "credentials"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (profile_id + ".dpapi")
        backup(path)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(protect(key.encode("utf-8")))
        os.replace(temporary, path)
    value["profiles"] = [new if p["id"] == profile_id else p for p in value["profiles"]]
    if not old:
        value["profiles"].append(new)
    write(ROOT / "profiles.json", value)
    return snapshot()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


USER_AGENT = "codex-route-switch/1.0"


def http_error_detail(code):
    if code in (401, 403):
        return f"上游返回 HTTP {code}：密钥无效、已过期，或该站点拒绝此类请求。"
    if code == 404:
        return "上游返回 HTTP 404：API 地址通常需要以 /v1 结尾，请核对。"
    if code == 429:
        return "上游返回 HTTP 429：请求过于频繁，请稍后再试。"
    return f"上游返回 HTTP {code}，请检查地址、凭据及权限。"


def request_models(base, key):
    """Read the model catalog. Returns (ids, elapsed_ms, error_detail); the key never leaves this function."""
    request = urllib.request.Request(valid_url(base) + "/models", headers={
        "Authorization": "Bearer " + key, "Accept": "application/json", "User-Agent": USER_AGENT})
    started = time.monotonic()
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
            data = json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as exc:
        return None, 0, http_error_detail(exc.code)
    except Exception:
        return None, 0, "连接未完成，请检查网络、证书和 API 地址。"
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None, 0, "返回内容不是模型目录，请检查 API 地址。"
    ids = sorted({m["id"] for m in rows if isinstance(m, dict) and isinstance(m.get("id"), str) and 0 < len(m["id"]) <= 128})
    return ids, round((time.monotonic() - started) * 1000), None


def check(profile):
    if profile["kind"] == "official":
        return {"ok": True, "detail": "官方登录由 Codex 管理，未发送网络请求。"}
    key = key_for(profile)
    if not key:
        raise ValueError("请先保存 API Key。")
    ids, elapsed, error = request_models(profile["baseUrl"], key)
    if error:
        return {"ok": False, "detail": error}
    found = profile["model"] in ids
    return {"ok": True, "detail": f"连接成功 · {elapsed} ms · " + ("已找到所选模型" if found else "目录未列出所选模型，请核对模型名") + "；尚未发起模型调用。"}


def fetch_models(args):
    """List models for a saved route, or for an unsaved draft (address + key come from the form)."""
    saved = next((p for p in state()["profiles"] if p["id"] == args.get("id")), None) if args.get("id") else None
    base = str(args.get("baseUrl") or (saved or {}).get("baseUrl") or "").strip()
    key = str(args.get("key") or "").strip() or (key_for(saved) if saved and saved.get("kind") == "relay" else "")
    if not base:
        raise ValueError("请先填写 API 地址。")
    if not key:
        raise ValueError("请先填写 API Key。")
    ids, elapsed, error = request_models(base, key)
    if error:
        return {"ok": False, "models": [], "detail": error}
    return {"ok": True, "models": ids[:500], "detail": f"共 {len(ids)} 个模型 · {elapsed} ms"}


def remove(profile):
    if profile["kind"] == "official":
        raise ValueError("官方登录不能删除。")
    value = state()
    backup(ROOT / "profiles.json")
    value["profiles"] = [p for p in value["profiles"] if p["id"] != profile["id"]]
    if value.get("activeProfile") == profile["id"]:
        value["activeProfile"] = "official"
    write(ROOT / "profiles.json", value)
    active_path = ROOT / "active-profile.json"
    active = read(active_path, {})
    if active.get("profileId") == profile["id"]:
        backup(active_path)
        write(active_path, {"profileId": "official", "selectedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    secret = ROOT / "credentials" / (profile["id"] + ".dpapi")
    if secret.exists():
        os.replace(secret, secret.with_suffix(".dpapi.removed"))
    return snapshot()


def launch(profile, restart=False, allow_force=False):
    import msvcrt
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "desktop-launch.lock").open("a+b") as lock:
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise ValueError("已有 Codex 启动或重启操作正在执行。") from None
        return start_desktop(profile, restart, allow_force)


def start_desktop(profile, restart, allow_force):
    relay = profile["kind"] == "relay"
    key = key_for(profile) if relay else ""
    if relay and not key:
        raise ValueError("当前线路缺少 API Key。")
    launch_id = uuid.uuid4().hex
    env = os.environ.copy()
    env.update(CODEX_ROUTE_KIND=profile["kind"], CODEX_ROUTE_ID=profile["id"],
               CODEX_ROUTE_BASE=profile.get("baseUrl") or "", CODEX_ROUTE_MODEL=profile.get("model") or "",
               CODEX_ROUTE_MODELS=json.dumps(models_for(profile) if relay else []),
               CODEX_ROUTE_KEY=key, CODEX_ROUTE_LAUNCH_ID=launch_id, CODEX_ROUTE_HOME=str(ROOT))
    powershell = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    command = [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(BUNDLE / "Start-ManagedCodex.ps1")]
    if restart:
        command.append("-Restart")
    if restart and allow_force:
        command.append("-AllowForce")
    result = subprocess.run(command,
                            env=env, capture_output=True, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        # Only the script's own one-line reason is surfaced, with the route key scrubbed.
        lines = [x.strip() for x in result.stderr.decode("utf-8", "replace").splitlines() if x.strip()]
        reason = lines[-1][:240] if lines else ""
        if key:
            reason = reason.replace(key, "***")
        hint = "启动或重启未完成。未记录成功启动。" + (f"原因：{reason}" if reason else "（脚本未返回原因）")
        raise ValueError(hint + " 若旧实例仍在托盘，请完全退出后重试。")
    lines = [x.strip() for x in result.stdout.decode("utf-8-sig", "replace").splitlines() if x.strip().startswith("{")]
    if not lines:
        raise ValueError("启动脚本没有返回进程信息，请重试。")
    payload = json.loads(lines[-1])
    write(ROOT / "desktop-launch.json", {"pid": payload["pid"], "profileId": profile["id"], "launchId": launch_id, "unpatched": bool(payload.get("unpatched"))})
    return snapshot()


def dispatch(request):
    op, args = request.get("operation"), request.get("args") or {}
    if op == "list":
        return snapshot()
    if op == "save":
        return save(args)
    if op == "models":
        return fetch_models(args)
    profile = profile_for(args.get("id"))
    if op == "remove":
        return remove(profile)
    if op == "select":
        if profile["kind"] != "official" and not key_for(profile):
            raise ValueError("请先配置此线路的 API Key。")
        path = ROOT / "active-profile.json"
        backup(path)
        write(path, {"profileId": profile["id"], "selectedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return snapshot()
    if op == "check":
        return check(profile)
    if op == "launch":
        return launch(profile, restart=args.get("restart") is True, allow_force=args.get("allowForce") is True)
    raise ValueError("不支持的操作。")


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        result = dispatch(json.load(sys.stdin))
        print(json.dumps({"result": result}, ensure_ascii=False))
    except ValueError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
    except Exception:
        print(json.dumps({"error": "线路操作失败，请检查本机配置后重试。"}, ensure_ascii=False))

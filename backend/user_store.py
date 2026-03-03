import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

try:
    from .user_access import (
        DEFAULT_PLAN_KEY,
        DEFAULT_ROLE_KEY,
        build_access_profile,
        resolve_plan_key,
        resolve_role_key,
    )
except ImportError:
    from user_access import (
        DEFAULT_PLAN_KEY,
        DEFAULT_ROLE_KEY,
        build_access_profile,
        resolve_plan_key,
        resolve_role_key,
    )


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_USERS_PATH = PROJECT_ROOT / "data" / "users.json"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def build_workspace_key(user_id, provider="google"):
    raw_key = f"{provider}_{user_id}".strip().lower()
    sanitized = re.sub(r"[^a-z0-9._-]+", "_", raw_key).strip("._-")
    return sanitized or f"{provider}_user"


def build_workspace_metadata(user_id, provider="google"):
    workspace_key = build_workspace_key(user_id, provider=provider)
    workspace_root = Path("data") / "users" / workspace_key
    return {
        "key": workspace_key,
        "scope": "user",
        "root": workspace_root.as_posix(),
        "documents_dir": (workspace_root / "documentos").as_posix(),
        "vectorstore_dir": (workspace_root / "chroma_db").as_posix(),
    }


class UserStore:
    def __init__(self, data_path=None):
        self.data_path = Path(data_path or DEFAULT_USERS_PATH).resolve()
        self._lock = Lock()
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.data_path.exists():
            self._write_data({"users": {}})

    def _read_data(self):
        if not self.data_path.exists():
            return {"users": {}}

        try:
            with self.data_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            return {"users": {}}

        if not isinstance(data, dict):
            return {"users": {}}

        users = data.get("users")
        if not isinstance(users, dict):
            data["users"] = {}

        return data

    def _write_data(self, data):
        with self.data_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)

    def _normalize_user_record(self, user):
        if not isinstance(user, dict):
            return None, False

        user_id = str(user.get("id", "")).strip()
        if not user_id:
            return user, False

        provider = str(user.get("provider", "google")).strip().lower() or "google"
        expected_workspace = build_workspace_metadata(user_id, provider=provider)
        current_workspace = user.get("workspace")
        role_key = resolve_role_key(user.get("role_key"))
        plan_key = resolve_plan_key(user.get("plan_key"))
        expected_access = build_access_profile(role_key=role_key, plan_key=plan_key)
        updated = False

        if not isinstance(current_workspace, dict):
            user["workspace"] = expected_workspace
            updated = True
        else:
            normalized_workspace = {
                "key": current_workspace.get("key") or expected_workspace["key"],
                "scope": current_workspace.get("scope") or expected_workspace["scope"],
                "root": current_workspace.get("root") or expected_workspace["root"],
                "documents_dir": (
                    current_workspace.get("documents_dir") or expected_workspace["documents_dir"]
                ),
                "vectorstore_dir": (
                    current_workspace.get("vectorstore_dir") or expected_workspace["vectorstore_dir"]
                ),
            }
            if normalized_workspace != current_workspace:
                user["workspace"] = normalized_workspace
                updated = True

        workspace_key = user["workspace"]["key"]
        if user.get("workspace_key") != workspace_key:
            user["workspace_key"] = workspace_key
            updated = True

        if user.get("role_key") != expected_access["role_key"]:
            user["role_key"] = expected_access["role_key"]
            updated = True

        if user.get("plan_key") != expected_access["plan_key"]:
            user["plan_key"] = expected_access["plan_key"]
            updated = True

        if user.get("access") != expected_access:
            user["access"] = expected_access
            updated = True

        return user, updated

    def get_user(self, user_id):
        with self._lock:
            data = self._read_data()
            user = data.get("users", {}).get(user_id)
            if not isinstance(user, dict):
                return None

            normalized_user, updated = self._normalize_user_record(user)
            if updated:
                data["users"][user_id] = normalized_user
                self._write_data(data)

            return normalized_user

    def get_user_workspace(self, user_id):
        user = self.get_user(user_id)
        if not user:
            return None

        return user.get("workspace")

    def get_user_access(self, user_id):
        user = self.get_user(user_id)
        if not user:
            return None

        return user.get("access")

    def update_user_access(self, user_id, role_key=None, plan_key=None):
        with self._lock:
            data = self._read_data()
            users = data.setdefault("users", {})
            user = users.get(user_id)
            if not isinstance(user, dict):
                return None

            resolved_role_key = resolve_role_key(role_key or user.get("role_key") or DEFAULT_ROLE_KEY)
            resolved_plan_key = resolve_plan_key(plan_key or user.get("plan_key") or DEFAULT_PLAN_KEY)
            user["role_key"] = resolved_role_key
            user["plan_key"] = resolved_plan_key
            user["access"] = build_access_profile(
                role_key=resolved_role_key,
                plan_key=resolved_plan_key,
            )
            users[user_id] = user
            self._write_data(data)

        return user

    def upsert_google_user(self, token_info):
        user_id = token_info["sub"]
        now = utc_now_iso()
        workspace = build_workspace_metadata(user_id, provider="google")

        with self._lock:
            data = self._read_data()
            users = data.setdefault("users", {})
            existing = users.get(user_id, {})

            login_count = int(existing.get("login_count", 0)) + 1
            created_at = existing.get("created_at", now)
            role_key = resolve_role_key(existing.get("role_key") or DEFAULT_ROLE_KEY)
            plan_key = resolve_plan_key(existing.get("plan_key") or DEFAULT_PLAN_KEY)
            access = build_access_profile(role_key=role_key, plan_key=plan_key)

            user = {
                "id": user_id,
                "provider": "google",
                "email": token_info.get("email", "").lower(),
                "email_verified": bool(token_info.get("email_verified", False)),
                "name": token_info.get("name", ""),
                "given_name": token_info.get("given_name", ""),
                "family_name": token_info.get("family_name", ""),
                "picture": token_info.get("picture", ""),
                "locale": token_info.get("locale", ""),
                "hosted_domain": token_info.get("hd", ""),
                "created_at": created_at,
                "last_login_at": now,
                "login_count": login_count,
                "workspace_key": workspace["key"],
                "workspace": workspace,
                "role_key": access["role_key"],
                "plan_key": access["plan_key"],
                "access": access,
            }

            users[user_id] = user
            self._write_data(data)

        return user

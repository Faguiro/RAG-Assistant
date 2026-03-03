import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_USERS_PATH = PROJECT_ROOT / "data" / "users.json"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


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

    def get_user(self, user_id):
        with self._lock:
            data = self._read_data()
            user = data.get("users", {}).get(user_id)
            return user if isinstance(user, dict) else None

    def upsert_google_user(self, token_info):
        user_id = token_info["sub"]
        now = utc_now_iso()

        with self._lock:
            data = self._read_data()
            users = data.setdefault("users", {})
            existing = users.get(user_id, {})

            login_count = int(existing.get("login_count", 0)) + 1
            created_at = existing.get("created_at", now)

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
            }

            users[user_id] = user
            self._write_data(data)

        return user

"""Minimal Kitsu (Zou) REST client built on urllib, so no extra packages are needed."""

import json
import mimetypes
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

TIMEOUT = 30


class KitsuError(Exception):
    pass


def normalize_host(url: str) -> str:
    """Turn '127.0.0.1:8012', 'http://host/' or 'http://host/api' into 'http://host'."""
    url = url.strip().rstrip("/")
    if not url:
        raise KitsuError("Server address is empty.")
    if not re.match(r"^https?://", url):
        url = "http://" + url
    if url.endswith("/api"):
        url = url[:-4]
    return url


def is_local_host(url: str) -> bool:
    host = urllib.parse.urlparse(normalize_host(url)).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


class KitsuClient:
    def __init__(self):
        self.host = ""
        self.access_token = None
        self.user = None
        self.organisation = None
        self._email = None
        self._password = None  # kept in memory only, used to log in again if the token expires

    # ------------------------------------------------------------------ auth
    @property
    def logged_in(self) -> bool:
        return bool(self.access_token)

    def login(self, host: str, email: str, password: str) -> dict:
        self.host = normalize_host(host)
        self._email, self._password = email.strip(), password
        self._do_login()
        return self.user

    def _do_login(self):
        res = self._request("POST", "/auth/login",
                            {"email": self._email, "password": self._password},
                            auth=False)
        if not res or not res.get("login"):
            raise KitsuError("Login refused by server.")
        self.access_token = res["access_token"]
        self.user = res.get("user") or {}
        self.organisation = res.get("organisation") or {}

    def logout(self):
        if self.access_token:
            try:
                self._request("GET", "/auth/logout", retry=False)
            except KitsuError:
                pass
        self.access_token = None
        self.user = None
        self.organisation = None
        self._password = None

    # --------------------------------------------------------------- requests
    def _request(self, method, path, data=None, auth=True, retry=True, upload=None):
        """`upload` is (field_name, filename, bytes, content_type) for a multipart file upload."""
        if not self.host:
            raise KitsuError("Not connected to a server.")
        url = self.host + "/api" + path
        headers = {"Accept": "application/json"}
        if auth:
            if not self.access_token:
                raise KitsuError("Not logged in.")
            headers["Authorization"] = "Bearer " + self.access_token
        if upload:
            field, filename, content, ctype = upload
            boundary = uuid.uuid4().hex
            body = (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
                    f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n').encode("utf-8")
            body += content + f"\r\n--{boundary}--\r\n".encode("utf-8")
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        else:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code == 401 and auth and retry and self._password:
                # Token expired: log in again once and repeat the call.
                self._do_login()
                return self._request(method, path, data, auth, retry=False, upload=upload)
            raise KitsuError(self._error_message(e)) from None
        except urllib.error.URLError as e:
            raise KitsuError(f"Cannot reach {self.host}: {e.reason}") from None
        except (TimeoutError, OSError) as e:
            raise KitsuError(f"Connection to {self.host} failed: {e}") from None

    @staticmethod
    def _error_message(e):
        try:
            payload = json.loads(e.read().decode("utf-8"))
            msg = payload.get("message") or payload.get("error") or str(payload)
        except Exception:
            msg = e.reason
        return f"HTTP {e.code}: {msg}"

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, data):
        return self._request("POST", path, data)

    # ------------------------------------------------------------------ data
    def server_info(self):
        return self._request("GET", "/", auth=False)

    def open_projects(self):
        return self.get("/data/projects/open")

    def task_types(self):
        return self.get("/data/task-types")

    def task_statuses(self):
        return self.get("/data/task-status")

    def asset_types(self):
        return self.get("/data/asset-types")

    def entity_types(self):
        return self.get("/data/entity-types")

    def episodes(self, project_id):
        return self.get(f"/data/projects/{project_id}/episodes")

    def sequences(self, project_id):
        return self.get(f"/data/projects/{project_id}/sequences")

    def shots(self, project_id):
        return self.get(f"/data/projects/{project_id}/shots")

    def assets(self, project_id):
        return self.get(f"/data/projects/{project_id}/assets")

    def project_tasks(self, project_id):
        return self.get(f"/data/projects/{project_id}/tasks")

    def entity(self, entity_id):
        return self.get(f"/data/entities/{entity_id}")

    def task(self, task_id):
        return self.get(f"/data/tasks/{task_id}")

    def download(self, path, dest, timeout=5):
        """Save a binary file (e.g. a thumbnail) from the API to `dest`."""
        if not self.logged_in:
            raise KitsuError("Not logged in.")
        req = urllib.request.Request(self.host + "/api" + path,
                                     headers={"Authorization": "Bearer " + self.access_token})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise KitsuError(f"Download failed: {e}") from None
        with open(dest, "wb") as f:
            f.write(content)
        return dest

    def thumbnail(self, preview_file_id, dest):
        return self.download(f"/pictures/thumbnails/preview-files/{preview_file_id}.png", dest)

    # ------------------------------------------------------------ versions
    def create_working_file(self, task_id, entity_id, revision, path, comment=""):
        return self.post("/data/working-files", {
            "name": "main", "task_id": task_id, "entity_id": entity_id,
            "revision": revision, "path": path, "comment": comment,
            "person_id": (self.user or {}).get("id"),
        })

    def comment_task(self, task_id, task_status_id, text):
        return self.post(f"/actions/tasks/{task_id}/comment",
                         {"task_status_id": task_status_id, "comment": text})

    def add_preview(self, task_id, comment_id, revision=None):
        data = {"revision": revision} if revision else {}
        return self.post(f"/actions/tasks/{task_id}/comments/{comment_id}/add-preview", data)

    def upload_preview(self, preview_id, filepath):
        with open(filepath, "rb") as f:
            content = f.read()
        name = os.path.basename(filepath)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return self._request("POST", f"/pictures/preview-files/{preview_id}",
                             upload=("file", name, content, ctype))


# Single shared client for the Blender session.
client = KitsuClient()

import cgi
import io
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import dropbox
from dropbox.files import WriteMode, FolderMetadata, FileMetadata
from dropbox.exceptions import ApiError
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DROPBOX_TOKEN")
if not TOKEN:
    sys.exit("DROPBOX_TOKEN не найден в .env")

dbx = dropbox.Dropbox(TOKEN)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")


def human_size(n):
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} ПБ"


class Handler(BaseHTTPRequestHandler):

    # ---------- служебные ----------
    def log_message(self, fmt, *args):
        sys.stderr.write("[server] " + fmt % args + "\n")

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code, text):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        if not os.path.isfile(path):
            self.send_error(404)
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body, ctype, filename=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    # ---------- GET ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path, qs = parsed.path, parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._serve_index()
            elif path == "/static/style.css":
                self._send_file(os.path.join(STATIC_DIR, "style.css"), "text/css; charset=utf-8")
            elif path == "/static/app.js":
                self._send_file(os.path.join(STATIC_DIR, "app.js"), "application/javascript; charset=utf-8")
            elif path == "/api/user":
                self._api_user()
            elif path == "/api/space":
                self._api_space()
            elif path == "/api/list":
                self._api_list(qs.get("path", [""])[0])
            elif path == "/api/metadata":
                self._api_metadata(qs.get("path", [""])[0])
            elif path == "/api/download":
                self._api_download(qs.get("path", [""])[0])
            elif path == "/api/shared-links":
                self._api_shared_links()
            elif path == "/api/search":
                self._api_search(qs.get("q", [""])[0], qs.get("filename_only", ["true"])[0])
            else:
                self.send_error(404)
        except ApiError as e:
            self._json(400, {"error": str(e)})
        except Exception as e:
            self._json(500, {"error": str(e)})

    # ---------- POST ----------
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/folder/create":
                d = self._read_json()
                self._api_folder_create(d.get("path", "").strip())
            elif path == "/api/delete":
                d = self._read_json()
                self._api_delete(d.get("path", "").strip())
            elif path == "/api/move":
                d = self._read_json()
                self._api_move(d.get("src", "").strip(), d.get("dst", "").strip())
            elif path == "/api/copy":
                d = self._read_json()
                self._api_copy(d.get("src", "").strip(), d.get("dst", "").strip())
            elif path == "/api/share":
                d = self._read_json()
                self._api_share(d.get("path", "").strip())
            elif path == "/api/upload":
                self._api_upload()
            else:
                self.send_error(404)
        except ApiError as e:
            self._json(400, {"error": str(e)})
        except Exception as e:
            self._json(500, {"error": str(e)})

    # ---------- страница ----------
    def _serve_index(self):
        index_path = os.path.join(TEMPLATES_DIR, "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
        html = html.replace("{{ url_for('static', filename='style.css') }}", "/static/style.css")
        html = html.replace("{{ url_for('static', filename='app.js') }}", "/static/app.js")
        self._html(200, html)

    # ---------- API ----------
    def _api_user(self):
        acc = dbx.users_get_current_account()
        self._json(200, {
            "name": acc.name.display_name,
            "email": acc.email,
            "account_id": acc.account_id,
            "account_type": acc.account_type._tag,
            "country": acc.country,
        })

    def _api_space(self):
        usage = dbx.users_get_space_usage()
        if usage.allocation.is_individual():
            allocated = usage.allocation.get_individual().allocated
        else:
            allocated = usage.allocation.get_team().allocated
        used = usage.used
        self._json(200, {
            "allocated_h": human_size(allocated),
            "used_h": human_size(used),
            "free_h": human_size(allocated - used),
            "percent": round(used / allocated * 100, 1) if allocated else 0,
        })

    def _api_list(self, path):
        result = dbx.files_list_folder(path)
        entries = list(result.entries)
        while result.has_more:
            result = dbx.files_list_folder_continue(result.cursor)
            entries.extend(result.entries)
        items = []
        for e in entries:
            if isinstance(e, FolderMetadata):
                items.append({"type": "folder", "name": e.name, "path": e.path_display})
            elif isinstance(e, FileMetadata):
                items.append({
                    "type": "file", "name": e.name, "path": e.path_display,
                    "size_h": human_size(e.size),
                    "modified": e.server_modified.isoformat(),
                })
        self._json(200, {"path": path or "/", "items": items})

    def _api_folder_create(self, path):
        if not path:
            return self._json(400, {"error": "path required"})
        res = dbx.files_create_folder_v2(path)
        self._json(200, {"ok": True, "path": res.metadata.path_display})

    def _api_delete(self, path):
        if not path:
            return self._json(400, {"error": "path required"})
        res = dbx.files_delete_v2(path)
        self._json(200, {"ok": True, "path": res.metadata.path_display})

    def _api_move(self, src, dst):
        if not src or not dst:
            return self._json(400, {"error": "src and dst required"})
        dbx.files_move_v2(src, dst)
        self._json(200, {"ok": True, "src": src, "dst": dst})

    def _api_copy(self, src, dst):
        if not src or not dst:
            return self._json(400, {"error": "src and dst required"})
        dbx.files_copy_v2(src, dst)
        self._json(200, {"ok": True, "src": src, "dst": dst})

    def _api_metadata(self, path):
        if not path:
            return self._json(400, {"error": "path required"})
        m = dbx.files_get_metadata(path)
        if isinstance(m, FileMetadata):
            return self._json(200, {
                "type": "file", "name": m.name, "path": m.path_display,
                "size_h": human_size(m.size),
                "modified": m.server_modified.isoformat(),
                "id": m.id, "rev": m.rev,
            })
        self._json(200, {
            "type": "folder", "name": m.name,
            "path": m.path_display, "id": m.id,
        })

    def _api_download(self, path):
        if not path:
            return self._json(400, {"error": "path required"})
        metadata, response = dbx.files_download(path)
        self._send_bytes(response.content, "application/octet-stream", metadata.name)

    def _api_share(self, path):
        if not path:
            return self._json(400, {"error": "path required"})
        settings = dropbox.sharing.SharedLinkSettings(
            requested_visibility=dropbox.sharing.RequestedVisibility.public
        )
        try:
            res = dbx.sharing_create_shared_link_with_settings(path, settings)
            return self._json(200, {"ok": True, "url": res.url, "name": res.name})
        except ApiError as e:
            if getattr(e.error, "_tag", "") == "shared_link_already_exists":
                existing = dbx.sharing_list_shared_links(path=path)
                if existing.links:
                    link = existing.links[0]
                    return self._json(200, {
                        "ok": True, "url": link.url, "name": link.name, "existing": True,
                    })
            raise

    def _api_shared_links(self):
        res = dbx.sharing_list_shared_links()
        items = []
        for link in res.links:
            is_file = isinstance(link, dropbox.sharing.FileLinkMetadata)
            items.append({"type": "file" if is_file else "folder",
                          "name": link.name, "url": link.url})
        self._json(200, {"items": items})

    def _api_search(self, q, filename_only):
        if not q:
            return self._json(400, {"error": "q required"})
        fn_only = str(filename_only).lower() == "true"
        options = dropbox.files.SearchOptions(path="", max_results=30, filename_only=fn_only)
        res = dbx.files_search_v2(q, options)
        items = []
        for m in res.matches:
            meta = m.metadata.get_metadata()
            items.append({
                "type": "folder" if isinstance(meta, FolderMetadata) else "file",
                "name": meta.name, "path": meta.path_display,
            })
        self._json(200, {"items": items})

    def _api_upload(self):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return self._json(400, {"error": "multipart expected"})
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        env = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": ctype,
            "CONTENT_LENGTH": str(length),
        }
        fs = cgi.FieldStorage(fp=io.BytesIO(body), headers=self.headers, environ=env)

        remote = fs.getvalue("path", "").strip()
        overwrite = str(fs.getvalue("overwrite", "false")).lower() == "true"
        if "file" not in fs:
            return self._json(400, {"error": "file required"})
        data = fs["file"].file.read()
        if not remote:
            return self._json(400, {"error": "path required"})

        mode = WriteMode.overwrite if overwrite else WriteMode.add
        res = dbx.files_upload(data, remote, mode=mode)
        self._json(200, {"ok": True, "path": res.path_display,
                         "size_h": human_size(res.size)})


def run(port=8080):
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Сервер запущен")
    print("Ctrl+C — остановить.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.")


if __name__ == "__main__":
    run()

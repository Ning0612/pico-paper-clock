import concurrent.futures
import http.client
import ipaddress
import json
import socket
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import quote, urlencode, urlsplit


API_VERSION = 1


class DeviceError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class DeviceInfo:
    host: str
    api_version: int
    heap_free: int
    fs_free: int


def _base_host(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "http://" + value
    parsed = urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("Device must be an HTTP host or IPv4 address.")
    return parsed.netloc


class DeviceClient:
    def __init__(self, host: str, username: str = "admin", password: str = "", timeout: float = 15.0):
        self.host = _base_host(host)
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session_cookie = None
        self.csrf_token = None

    def _connection(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection(self.host, timeout=self.timeout)

    @staticmethod
    def _json_response(response):
        raw = response.read()
        try:
            value = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeError, json.JSONDecodeError):
            value = {}
        return value

    def _login(self):
        connection = self._connection()
        try:
            connection.request("GET", "/api/v1/auth/status")
            status_response = connection.getresponse()
            status = self._json_response(status_response)
            if status_response.status >= 400:
                raise DeviceError(status.get("message", "Unable to read device auth status."), status_response.status)
            if status.get("setup_required"):
                raise DeviceError("Complete first-time WebUI password setup before using the image tool.", 409, "setup_required")
            csrf = status.get("csrf_token")
            if not csrf:
                raise DeviceError("Device did not provide a pre-auth CSRF token.")
        finally:
            connection.close()

        body = urlencode({
            "username": self.username,
            "password": self.password,
            "password_confirm": self.password,
            "csrf_token": csrf,
        }).encode("utf-8")
        connection = self._connection()
        try:
            connection.request(
                "POST",
                "/api/v1/auth/login",
                body=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Content-Length": str(len(body)),
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            value = self._json_response(response)
            if response.status >= 400:
                raise DeviceError(value.get("message", f"Login failed with HTTP {response.status}."), response.status, value.get("error"))
            cookie = response.getheader("Set-Cookie", "")
            self.session_cookie = cookie.split(";", 1)[0] if cookie else None
            self.csrf_token = value.get("csrf_token")
            if not self.session_cookie or not self.csrf_token:
                raise DeviceError("Device login did not return a session cookie and CSRF token.")
        finally:
            connection.close()

    def _ensure_session(self):
        if not self.session_cookie or not self.csrf_token:
            self._login()

    def _request(self, method: str, path: str, body: bytes | None = None, mutate: bool = False):
        self._ensure_session()
        headers = {
            "Cookie": self.session_cookie,
            "X-CSRF-Token": self.csrf_token,
            "Accept": "application/json",
        }
        if mutate:
            headers["X-Pico-Clock-API"] = "1"
        if body is not None:
            headers["Content-Type"] = "application/octet-stream"
            headers["Content-Length"] = str(len(body))
        connection = self._connection()
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            value = self._json_response(response)
            if response.status >= 400:
                raise DeviceError(value.get("message", f"Device returned HTTP {response.status}."), response.status, value.get("error"))
            return value
        finally:
            connection.close()

    def info(self) -> DeviceInfo:
        connection = self._connection()
        try:
            connection.request("GET", "/api/v1/device")
            response = connection.getresponse()
            value = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
        if value.get("device") != "pi-paper-clock":
            raise DeviceError("Host is not a Pi Paper Clock.")
        version = int(value.get("api_version", 0))
        if version != API_VERSION:
            raise DeviceError(f"Unsupported device API version: {version}")
        return DeviceInfo(self.host, version, int(value.get("heap_free", -1)), int(value.get("fs_free", -1)))

    @staticmethod
    def _resource(collection: str, filename: str, event: str | None = None) -> str:
        name = quote(filename, safe="")
        if collection == "events":
            if not event:
                raise ValueError("Event target requires MMDD or birthday.")
            return f"/api/v1/images/events/{quote(event, safe='')}/{name}"
        if collection not in ("custom", "login"):
            raise ValueError("Unsupported image collection.")
        return f"/api/v1/images/{collection}/{name}"

    def list_images(self, collection: str, event: str | None = None):
        query = {"collection": collection}
        if collection == "events":
            query["event"] = event or "0101"
        return self._request("GET", "/api/v1/images?" + urlencode(query))

    def upload(self, data: bytes, collection: str, filename: str, event: str | None = None,
               overwrite: bool = False, preview: bool = False,
               progress: Callable[[int, int], None] | None = None):
        resource = self._resource(collection, filename, event)
        resource += "?" + urlencode({"overwrite": int(overwrite), "preview": int(preview)})
        self._ensure_session()
        connection = self._connection()
        headers = {
            "Cookie": self.session_cookie,
            "X-CSRF-Token": self.csrf_token,
            "X-Pico-Clock-API": "1",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(data)),
            "Accept": "application/json",
        }
        try:
            connection.putrequest("PUT", resource)
            for name, value in headers.items():
                connection.putheader(name, value)
            connection.endheaders()
            sent = 0
            for offset in range(0, len(data), 512):
                chunk = data[offset:offset + 512]
                connection.send(chunk)
                sent += len(chunk)
                if progress:
                    progress(sent, len(data))
            response = connection.getresponse()
            value = self._json_response(response)
            if response.status >= 400:
                raise DeviceError(value.get("message", f"Upload failed with HTTP {response.status}."), response.status, value.get("error"))
            return value
        finally:
            connection.close()

    def delete(self, collection: str, filename: str, event: str | None = None):
        return self._request("DELETE", self._resource(collection, filename, event), mutate=True)

    def preview(self, collection: str, filename: str, event: str | None = None):
        return self._request("POST", self._resource(collection, filename, event) + "/preview", mutate=True)


def local_24_subnets() -> list[ipaddress.IPv4Network]:
    networks = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if not address.startswith("127."):
                networks.add(ipaddress.ip_network(address + "/24", strict=False))
    except OSError:
        pass
    return sorted(networks, key=str)


def discover(subnets: Iterable[str | ipaddress.IPv4Network] | None = None, timeout: float = 0.35,
             workers: int = 32) -> list[DeviceInfo]:
    requested = list(subnets or local_24_subnets())
    if not requested:
        requested = [ipaddress.ip_network("192.168.4.0/24")]
    networks = [item if isinstance(item, ipaddress.IPv4Network) else ipaddress.ip_network(item, strict=False) for item in requested]
    hosts = []
    for network in networks:
        if network.num_addresses > 256:
            raise ValueError(f"Discovery subnet is too large: {network}; use /24 or smaller.")
        hosts.extend(str(host) for host in network.hosts())
    hosts.append("192.168.4.1")
    hosts = list(dict.fromkeys(hosts))

    def probe(host: str):
        try:
            return DeviceClient(host, timeout=timeout).info()
        except Exception:
            return None

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 32))) as executor:
        for result in executor.map(probe, hosts):
            if result:
                results.append(result)
    return sorted(results, key=lambda item: item.host)

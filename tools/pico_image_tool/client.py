import concurrent.futures
import http.client
import ipaddress
import json
import os
import re
import socket
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import quote, urlencode, urlsplit


API_VERSION = 1
PICO_MAC_PREFIXES = ("28-cd-c1", "2c-cf-67", "b8-27-eb", "dc-a6-32", "e4-5f-01")


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


def _hidden_subprocess_kwargs() -> dict:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


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
            parsed = ipaddress.ip_address(address)
            if not parsed.is_loopback and not parsed.is_link_local:
                networks.add(ipaddress.ip_network(address + "/24", strict=False))
    except OSError:
        pass
    return sorted(networks, key=str)


def _arp_hosts() -> list[ipaddress.IPv4Address]:
    try:
        result = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            encoding="ascii",
            errors="ignore",
            timeout=2,
            check=False,
            **_hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return []

    addresses = []
    for line in result.stdout.splitlines():
        match = re.match(
            r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F-]{17})\s+",
            line,
        )
        if not match:
            continue
        try:
            address = ipaddress.ip_address(match.group(1))
        except ValueError:
            continue
        if (
            isinstance(address, ipaddress.IPv4Address)
            and address.is_private
            and not address.is_link_local
            and not address.is_multicast
            and not address.is_unspecified
        ):
            mac = match.group(2).lower()
            addresses.append((address, mac))
    return [
        address
        for address, _mac in sorted(
            set(addresses),
            key=lambda item: (
                not item[1].startswith(PICO_MAC_PREFIXES),
                str(item[0]),
            ),
        )
    ]


def _ping_host(host: str, timeout: float) -> str | None:
    try:
        if os.name == "nt":
            command = ["ping", "-n", "1", "-w", str(max(100, int(timeout * 1000))), host]
        else:
            command = ["ping", "-c", "1", "-W", str(max(1, int(timeout))), host]
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=max(1.0, timeout + 0.5),
            check=False,
            **_hidden_subprocess_kwargs(),
        )
        if result.returncode == 0:
            return host
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def discover(subnets: Iterable[str | ipaddress.IPv4Network] | None = None, timeout: float = 5.0,
             workers: int = 32, first_only: bool = False) -> list[DeviceInfo]:
    requested = list(subnets or local_24_subnets())
    if not requested:
        requested = [ipaddress.ip_network("192.168.4.0/24")]
    networks = [item if isinstance(item, ipaddress.IPv4Network) else ipaddress.ip_network(item, strict=False) for item in requested]
    cached_hosts = _arp_hosts()
    cached_hosts_by_network = []
    network_hosts = []
    for network in networks:
        if network.num_addresses > 256:
            raise ValueError(f"Discovery subnet is too large: {network}; use /24 or smaller.")
        hosts = [str(host) for host in network.hosts()]
        network_hosts.extend(hosts)
        cached_hosts_by_network.extend(
            str(host)
            for host in cached_hosts
            if host in network
            and (
                network.num_addresses <= 2
                or host not in (network.network_address, network.broadcast_address)
            )
        )

    cached_hosts_by_network = list(dict.fromkeys(cached_hosts_by_network))
    network_hosts = list(dict.fromkeys(network_hosts))
    cached_set = set(cached_hosts_by_network)
    fallback_hosts = [host for host in network_hosts if host not in cached_set]
    fallback_hosts.append("192.168.4.1")
    fallback_hosts = list(dict.fromkeys(fallback_hosts))

    def probe(host: str):
        try:
            return DeviceClient(host, timeout=timeout).info()
        except Exception:
            return None

    def probe_batches(hosts_to_probe: list[str], stop_after_first: bool) -> list[DeviceInfo]:
        results = []
        batch_size = max(1, min(workers, 32))
        for start in range(0, len(hosts_to_probe), batch_size):
            batch = hosts_to_probe[start:start + batch_size]
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(batch_size, len(batch))) as executor:
                futures = [executor.submit(probe, host) for host in batch]
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    if not result:
                        continue
                    if stop_after_first:
                        return [result]
                    results.append(result)
        return sorted({result.host: result for result in results}.values(), key=lambda item: item.host)

    def find_ping_hosts(hosts_to_probe: list[str]) -> list[str]:
        ping_timeout = min(timeout, 0.5)
        ping_workers = 32
        pinged_hosts = []
        for start in range(0, len(hosts_to_probe), ping_workers):
            batch = hosts_to_probe[start:start + ping_workers]
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(ping_workers, len(batch))) as executor:
                futures = [executor.submit(_ping_host, host, ping_timeout) for host in batch]
                for future in concurrent.futures.as_completed(futures):
                    host = future.result()
                    if host is not None:
                        pinged_hosts.append(host)
        return sorted(set(pinged_hosts), key=lambda host: ipaddress.ip_address(host))

    # ARP is a useful fast path, but it is only a cache: a sleeping/rebooting
    # Pico may not be present there yet. Always continue with the local subnet
    # when cached candidates do not identify a device.
    if cached_hosts_by_network:
        cached_results = probe_batches(cached_hosts_by_network, stop_after_first=True)
        if cached_results:
            return cached_results

    open_hosts = find_ping_hosts(fallback_hosts)
    if not open_hosts:
        # Keep a protocol-only fallback for platforms without a usable ping
        # command or networks where ICMP is filtered.
        open_hosts = fallback_hosts
    return probe_batches(open_hosts, stop_after_first=first_only)

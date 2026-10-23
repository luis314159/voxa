"""Cliente HTTP mínimo (urllib en un hilo) para no depender de librerías extra."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class HttpError(Exception):
    """No hubo respuesta: sin red, DNS o timeout."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    data: Any = None


class Http(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        form: Mapping[str, str] | None = None,
        timeout: float = 8.0,
    ) -> HttpResponse: ...


class UrllibHttp:
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        form: Mapping[str, str] | None = None,
        timeout: float = 8.0,
    ) -> HttpResponse:
        return await asyncio.to_thread(self._request, method, url, params, headers, json_body, form, timeout)

    @staticmethod
    def _request(method, url, params, headers, json_body, form, timeout) -> HttpResponse:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        all_headers = dict(headers or {})
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode()
            all_headers["Content-Type"] = "application/json"
        elif form is not None:
            body = urllib.parse.urlencode(form).encode()
            all_headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif method in ("PUT", "POST"):
            body = b""
        req = urllib.request.Request(url, data=body, headers=all_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return HttpResponse(resp.status, _decode(resp.read()))
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, _decode(exc.read()))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HttpError(str(exc)) from exc


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode(errors="replace")

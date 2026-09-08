"""요청 속도 제한 + 재시도를 담당하는 HTTP 클라이언트."""

from __future__ import annotations

import ssl
import threading
import time
from urllib.parse import urlparse

import httpx

from utils.crawler_logger import get_logger


class AccessDeniedError(RuntimeError):
    """403 또는 접근 통제(웹방화벽/CAPTCHA)로 판단된 경우. 우회하지 않는다."""


#: OpenSSL SSL_OP_LEGACY_SERVER_CONNECT
_OP_LEGACY_SERVER_CONNECT = 0x4


def legacy_ssl_context() -> ssl.SSLContext:
    """구형 TLS 스택(재협상 허용/약한 서명 알고리즘)을 쓰는 사이트용 SSL 컨텍스트.

    DB생명·한화생명·AIG손해보험은 기본 컨텍스트로 접속하면
    ``UNSAFE_LEGACY_RENEGOTIATION_DISABLED`` / ``WRONG_SIGNATURE_TYPE`` /
    ``TLS/SSL connection has been closed`` 로 연결 자체가 실패합니다(실측).
    인증·접근통제를 우회하는 것이 아니라 **연결 호환성만** 낮춥니다.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.options |= _OP_LEGACY_SERVER_CONNECT
    for ciphers in ("DEFAULT@SECLEVEL=0", "DEFAULT@SECLEVEL=1"):
        try:
            ctx.set_ciphers(ciphers)
            break
        except ssl.SSLError:
            continue
    ctx.minimum_version = ssl.TLSVersion.TLSv1
    return ctx


class RateLimiter:
    """도메인당 동시요청 1 + 요청 간 최소 간격."""

    def __init__(self, interval: float, max_concurrent: int = 1):
        self.interval = max(0.0, float(interval))
        self._locks: dict[str, threading.Semaphore] = {}
        self._last: dict[str, float] = {}
        self._guard = threading.Lock()
        self._max_concurrent = max(1, int(max_concurrent))

    def _sem(self, host: str) -> threading.Semaphore:
        with self._guard:
            if host not in self._locks:
                self._locks[host] = threading.Semaphore(self._max_concurrent)
            return self._locks[host]

    def wait(self, url: str) -> None:
        host = urlparse(url).netloc or url
        sem = self._sem(host)
        sem.acquire()
        try:
            with self._guard:
                last = self._last.get(host, 0.0)
                delta = time.monotonic() - last
                sleep_for = self.interval - delta
            if sleep_for > 0:
                time.sleep(sleep_for)
            with self._guard:
                self._last[host] = time.monotonic()
        finally:
            sem.release()


class HttpClient:
    """httpx.Client 래퍼. 재시도/백오프/속도제한/접근거부 판정을 담당."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        interval: float = 2.0,
        max_concurrent: int = 1,
        max_retries: int = 3,
        backoff: list[float] | None = None,
        retry_status_codes: set[int] | None = None,
        user_agent: str = "Mozilla/5.0",
        headers: dict | None = None,
        legacy_ssl: bool = False,
    ):
        self.max_retries = max_retries
        self.backoff = backoff or [3, 10, 30]
        self.retry_status_codes = retry_status_codes or {408, 429, 500, 502, 503, 504}
        self.limiter = RateLimiter(interval, max_concurrent)
        self.log = get_logger()
        default_headers = {
            "User-Agent": user_agent,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        }
        default_headers.update(headers or {})
        self._client = httpx.Client(
            headers=default_headers,
            timeout=timeout,
            follow_redirects=True,
            # 일부 보험사 사이트의 중간 인증서 체인 누락 대응.
            # legacy_ssl=True 인 사이트는 구형 TLS 호환 컨텍스트를 쓴다(기본값은 종전과 동일).
            verify=legacy_ssl_context() if legacy_ssl else False,
        )

    # ------------------------------------------------------------------
    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """속도 제한과 재시도를 적용해 요청한다."""
        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self.max_retries:
            self.limiter.wait(url)
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    raise
                delay = self._delay(attempt)
                self.log.warning("요청 실패(%s) 재시도 %d/%d, %.0f초 후: %s",
                                 type(exc).__name__, attempt + 1, self.max_retries, delay, url)
                time.sleep(delay)
                attempt += 1
                continue

            if response.status_code == 403:
                raise AccessDeniedError(f"HTTP 403 - {url}")

            if response.status_code in self.retry_status_codes and attempt < self.max_retries:
                delay = self._delay(attempt)
                self.log.warning("HTTP %d 재시도 %d/%d, %.0f초 후: %s",
                                 response.status_code, attempt + 1, self.max_retries, delay, url)
                time.sleep(delay)
                attempt += 1
                continue

            return response

        raise last_exc if last_exc else RuntimeError(f"요청 실패: {url}")

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def _delay(self, attempt: int) -> float:
        if not self.backoff:
            return 3.0
        return float(self.backoff[min(attempt, len(self.backoff) - 1)])

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

"""訂單送出時的輕量防濫用保護。

這是單一服務執行個體的記憶體保護：不保存原始 IP、聯絡資料或姓名，
只保存不可逆雜湊與短時間戳。服務重新啟動時紀錄會自然清除。
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Sequence


RATE_LIMIT_MAX_ORDERS = 5
RATE_LIMIT_WINDOW_SECONDS = 10 * 60
DUPLICATE_WINDOW_SECONDS = 30


class DuplicateOrderSubmissionError(Exception):
    """同一來源在短時間內送出內容相同的訂單。"""


class OrderRateLimitExceededError(Exception):
    """同一來源在單一菜單的短時間送單次數過多。"""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("order rate limit exceeded")
        self.retry_after_seconds = max(1, retry_after_seconds)


@dataclass(frozen=True)
class _Reservation:
    rate_key: str
    duplicate_key: str
    timestamp: float


def _digest(*parts: object) -> str:
    serialized = json.dumps(
        parts,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class OrderAbuseGuard:
    """以短時間速率與訂單內容指紋攔截重複或大量送單。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rate_events: dict[str, deque[float]] = {}
        self._duplicate_events: dict[str, float] = {}

    def reset(self) -> None:
        """清除記憶體狀態；供服務啟動與隔離測試使用。"""
        with self._lock:
            self._rate_events.clear()
            self._duplicate_events.clear()

    def _cleanup(self, now: float) -> None:
        rate_cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        empty_rate_keys: list[str] = []
        for key, timestamps in self._rate_events.items():
            while timestamps and timestamps[0] <= rate_cutoff:
                timestamps.popleft()
            if not timestamps:
                empty_rate_keys.append(key)
        for key in empty_rate_keys:
            self._rate_events.pop(key, None)

        duplicate_cutoff = now - DUPLICATE_WINDOW_SECONDS
        expired_duplicates = [
            key
            for key, timestamp in self._duplicate_events.items()
            if timestamp <= duplicate_cutoff
        ]
        for key in expired_duplicates:
            self._duplicate_events.pop(key, None)

    def reserve(
        self,
        *,
        scope: str,
        source_ip: str,
        identity: str,
        customer_name: str,
        items: Sequence[dict],
    ) -> _Reservation:
        """原子檢查並保留一次送單；成功寫入後保留短期指紋。"""
        now = time.monotonic()
        source_key = _digest(scope, source_ip, identity)
        duplicate_key = _digest(scope, source_ip, identity, customer_name, items)

        with self._lock:
            self._cleanup(now)
            if duplicate_key in self._duplicate_events:
                raise DuplicateOrderSubmissionError

            timestamps = self._rate_events.setdefault(source_key, deque())
            if len(timestamps) >= RATE_LIMIT_MAX_ORDERS:
                retry_after = math.ceil(
                    RATE_LIMIT_WINDOW_SECONDS - (now - timestamps[0])
                )
                raise OrderRateLimitExceededError(retry_after)

            timestamps.append(now)
            self._duplicate_events[duplicate_key] = now
            return _Reservation(source_key, duplicate_key, now)

    def release(self, reservation: _Reservation) -> None:
        """下游建立失敗時撤銷保留，避免一般系統錯誤消耗限制。"""
        with self._lock:
            timestamps = self._rate_events.get(reservation.rate_key)
            if timestamps is not None:
                try:
                    timestamps.remove(reservation.timestamp)
                except ValueError:
                    pass
                if not timestamps:
                    self._rate_events.pop(reservation.rate_key, None)
            if self._duplicate_events.get(reservation.duplicate_key) == reservation.timestamp:
                self._duplicate_events.pop(reservation.duplicate_key, None)


ORDER_ABUSE_GUARD = OrderAbuseGuard()


@contextmanager
def protect_order_submission(
    *,
    scope: str,
    source_ip: str,
    identity: str,
    customer_name: str,
    items: Sequence[dict],
) -> Iterator[None]:
    """建立失敗會自動撤銷保留；成功時保留防重複與速率紀錄。"""
    reservation = ORDER_ABUSE_GUARD.reserve(
        scope=scope,
        source_ip=source_ip,
        identity=identity,
        customer_name=customer_name,
        items=items,
    )
    try:
        yield
    except Exception:
        ORDER_ABUSE_GUARD.release(reservation)
        raise


def reset_order_abuse_guard() -> None:
    ORDER_ABUSE_GUARD.reset()

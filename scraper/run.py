"""GitHub Actions から定期実行: 取得 → 前回との差分 → ntfy 通知 → 暗号化して docs/data.enc.json へ。

環境変数:
  DATA_PASSPHRASE  必須。docs/data.enc.json の暗号化パスフレーズ（アプリで入力するもの）
  NTFY_TOPIC       通知先 ntfy トピック（推測されにくい文字列に）
  NTFY_SERVER      省略時 https://ntfy.sh
  WELLNESS_USER    CNS ログイン名（省略するとログインせず公開情報のみ）
  WELLNESS_PASS    CNS パスワード
  FAVORITES        空き通知したい種目キーワード（カンマ区切り、例: "テニス,ヨガ"）
  APP_URL          通知タップで開く URL
"""
import base64
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from wellness import Wellness

JST = timezone(timedelta(hours=9))
OUT = Path(__file__).resolve().parent.parent / "docs" / "data.enc.json"
ITER = 310_000


# ---- 暗号化（ブラウザ側は WebCrypto で同じ方式を復号） ----

def _key(passphrase, salt, it):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=it)
    return kdf.derive(passphrase.encode())


def encrypt(obj, passphrase):
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    ct = AESGCM(_key(passphrase, salt, ITER)).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode(), None)
    b = lambda x: base64.b64encode(x).decode()
    return {"v": 1, "iter": ITER, "salt": b(salt), "iv": b(iv), "ct": b(ct)}


def decrypt(env, passphrase):
    d = lambda k: base64.b64decode(env[k])
    pt = AESGCM(_key(passphrase, d("salt"), env["iter"])).decrypt(d("iv"), d("ct"), None)
    return json.loads(pt)


# ---- 差分 ----

def slot_key(s):
    return f'{s["iso"]}|{s["period"]}|{s["name"]}|{s["teacher"]}'


def diff(prev, cur, favorites):
    """通知メッセージのリストを返す。"""
    msgs = []
    if not prev:
        return msgs
    prev_slots = {slot_key(s): s for s in prev.get("open", {}).get("slots", [])}
    prev_days = {s["iso"] for s in prev_slots.values()}
    cur_slots = cur["open"]["slots"]

    # 新しく予約受付が始まった日（毎朝6時に14日後の分が開く）
    new_days = sorted({s["iso"] for s in cur_slots} - prev_days)
    new_days = [d for d in new_days if not prev_days or d > max(prev_days)]
    for day in new_days:
        items = [s for s in cur_slots if s["iso"] == day]
        lines = [f'{s["period"]} {s["name"]}（空{s["vacancy"]}）' for s in items]
        msgs.append({
            "title": f'予約受付開始: {items[0]["date"]}',
            "body": "\n".join(lines[:12]) + (f"\n…ほか{len(lines) - 12}件" if len(lines) > 12 else ""),
            "tags": "date",
        })

    # お気に入り種目に空きが出た（既存日のみ。新規日は上で通知済み）
    if favorites:
        appeared = [s for s in cur_slots
                    if s["iso"] not in new_days
                    and slot_key(s) not in prev_slots
                    and any(f in s["name"] for f in favorites)]
        if appeared:
            msgs.append({
                "title": "お気に入りに空きあり",
                "body": "\n".join(f'{s["date"]} {s["period"]} {s["name"]}（空{s["vacancy"]}）' for s in appeared[:12]),
                "tags": "star",
                "priority": "high",
            })

    # 自分の予約: 抽選結果・休講
    pm, cm = prev.get("mine"), cur.get("mine")
    if isinstance(pm, dict) and isinstance(cm, dict):
        today = datetime.now(JST).date().isoformat()
        before = {r["id"]: r for r in pm["reservations"]}
        after = {r["id"]: r for r in cm["reservations"]}
        label = lambda r: f'{r["date"]} {r["period"]} {r["name"]}'
        moved = [r for i, r in after.items() if i in before and before[i]["status"] != r["status"]]
        won = [r for r in moved if "確定" in r["status"]]
        other = [r for r in moved if r not in won]
        lost = [r for i, r in before.items() if i not in after and "抽選" in r["status"] and (r["iso"] or "") >= today]
        if won:
            msgs.append({"title": "抽選に当選しました", "body": "\n".join(map(label, won)), "tags": "tada", "priority": "high"})
        if lost:
            msgs.append({"title": "抽選待ちの授業が予約一覧から消えました",
                         "body": "\n".join(map(label, lost)) + "\n（落選の可能性。空き枠を確認してください）", "tags": "warning"})
        if other:
            msgs.append({"title": "予約状況が変わりました",
                         "body": "\n".join(f'{label(r)}: {r["status"]}' for r in other), "tags": "memo"})
        off = [r for i, r in after.items() if r["cancelled"] and not before.get(i, {}).get("cancelled")]
        if off:
            msgs.append({"title": "休講のお知らせ", "body": "\n".join(f'{label(r)}: {r["cancelled"]}' for r in off),
                         "tags": "no_entry", "priority": "high"})
    return msgs


def notify(msgs):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        for m in msgs:
            print("[notify:dry]", m["title"], "\n", m["body"])
        return
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    url = os.environ.get("APP_URL")
    for m in msgs:
        headers = {"Title": m["title"].encode(), "Tags": m.get("tags", "")}
        if m.get("priority"):
            headers["Priority"] = m["priority"]
        if url:
            headers["Click"] = url
        requests.post(f"{server}/{topic}", data=m["body"].encode(), headers=headers, timeout=30)


def main():
    passphrase = os.environ.get("DATA_PASSPHRASE")
    if not passphrase:
        sys.exit("DATA_PASSPHRASE が未設定です")
    favorites = [f.strip() for f in os.environ.get("FAVORITES", "").split(",") if f.strip()]

    prev = None
    if OUT.exists():
        try:
            prev = decrypt(json.loads(OUT.read_text()), passphrase)
        except Exception as e:  # パスフレーズ変更時など
            print("前回データを復号できませんでした:", e)

    w = Wellness()
    cur = {
        "updated": datetime.now(JST).isoformat(timespec="minutes"),
        "open": w.open_slots(),
        "timetable": w.timetable(),
        "mine": None,
        "error": None,
        "ntfy": {
            "server": os.environ.get("NTFY_SERVER", "https://ntfy.sh"),
            "topic": os.environ.get("NTFY_TOPIC", ""),
            "favorites": favorites,
        },
    }

    user, pw = os.environ.get("WELLNESS_USER"), os.environ.get("WELLNESS_PASS")
    if user and pw:
        try:
            w.login(user, pw)
            cur["mine"] = w.mine()
        except Exception as e:
            cur["error"] = str(e)
            cur["mine"] = prev.get("mine") if prev else None

    msgs = diff(prev, cur, favorites)
    notify(msgs)
    OUT.write_text(json.dumps(encrypt(cur, passphrase)))
    n = "-" if cur["mine"] is None else len(cur["mine"].get("reservations", []))
    print(f'ok: {len(cur["open"]["slots"])} slots, reservations={n}, notified={len(msgs)}')


if __name__ == "__main__":
    main()

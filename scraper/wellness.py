"""SFC 体育システム V4 の取得・解析。

予約は一切しない（規則で自動スクリプトによる予約は禁止）。閲覧のみ。
"""
import re

import requests
from bs4 import BeautifulSoup

BASE = "https://wellness.sfc.keio.ac.jp/v4/index.php"
UA = "Mozilla/5.0 (personal reservation viewer; read-only)"
TIMEOUT = 30


def _text(el):
    return el.get_text(" ", strip=True) if el else ""


def _lines(el):
    """<br> 区切りのセルを行リストにする。"""
    for br in el.find_all("br"):
        br.replace_with("\n")
    return [s.strip() for s in el.get_text().split("\n") if s.strip()]


class Wellness:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.semester = None

    def get(self, **params):
        params.setdefault("lang", "ja")
        if self.semester:
            params.setdefault("semester", self.semester)
        r = self.s.get(BASE, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
        return BeautifulSoup(r.text, "html.parser")

    def top(self, limit=None):
        params = {"page": "top"}
        if limit:
            params["limit"] = limit
        soup = self.get(**params)
        m = re.search(r"semester=(\d+)", str(soup))
        if m:
            self.semester = m.group(1)
        return soup

    # ---- 公開ページ ----

    def timetable(self):
        """時間割: [{day, period, name, teacher, lang, tags}] と スポット授業。"""
        soup = self.get(page="timetable")
        classes = []
        tables = soup.select("table.timetable2")
        if not tables:
            return {"title": "", "regular": [], "spot": []}
        main = tables[0]
        days = [_text(th) for th in main.select("thead th")][1:]
        period = None
        for tr in main.select("tbody tr"):
            th = tr.find("th")
            if th:
                period = _text(th)
            for i, td in enumerate(tr.find_all("td")):
                c = _parse_tt_cell(td)
                if c and i < len(days):
                    c.update(day=days[i], period=period)
                    classes.append(c)
        spot = []
        for t in tables[1:]:
            for td in t.select("tbody td"):
                c = _parse_tt_cell(td)
                if c:
                    spot.append(c)
        h = soup.select_one("#maincontents h2")
        return {"title": _text(h), "regular": classes, "spot": spot}

    def open_slots(self, soup=None):
        """トップページの「予約空き授業」(公開)。limit=9999 で予約受付中の2週間分すべて。"""
        soup = soup or self.top(limit=9999)
        out = []
        h = next((h for h in soup.select("#maincontents h2") if "予約空き授業" in _text(h)), None)
        if not h:
            return {"range": "", "slots": out}
        table = h.find_next("table")
        years = re.findall(r"(\d{4})年(\d+)月", _text(h))
        date = period = None
        for tr in table.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 8:
                continue
            date = _text(tds[0]) or date
            period = _text(tds[1]) or period
            out.append({
                "iso": _iso(date, years),
                "date": date,
                "period": period,
                "name": _text(tds[2]),
                "teacher": _text(tds[3]),
                "place": _text(tds[4]),
                "intensity": _text(tds[5]),
                "vacancy": _int(_text(tds[7])),
            })
        return {"range": _text(h).split(":", 1)[-1].strip(), "slots": out}

    # ---- ログイン後 ----

    def login(self, user, password):
        soup = self.top()
        form = soup.find("form")
        data = {i["name"]: i.get("value", "") for i in form.find_all("input") if i.get("name")}
        data.update(login=user, password=password)
        r = self.s.post(BASE, data=data, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        if soup.find("input", {"type": "password"}):
            raise RuntimeError("ログインに失敗しました（ID/パスワードを確認）")
        return soup

    def mine(self):
        """ログイン後: 授業予定(予約一覧) と 取得状況。"""
        out = parse_status(self.get(page="status"))
        out.update(parse_history(self.get(page="history")))
        return out


def _parse_tt_cell(td):
    b = td.find("b")
    if not b:
        return None
    name = _text(b)
    tags = re.findall(r"\*(向|座|限)", name)
    name = re.sub(r"\*(向|座|限)", "", name)
    teacher = td.select_one(".teacher")
    lang = next((_text(s) for s in td.find_all("small") if "開講言語" in _text(s) and not s.find("b")), "")
    return {
        "name": name,
        "teacher": " / ".join(_lines(teacher)) if teacher else "",
        "lang": lang.replace("開講言語:", "").strip(),
        "tags": tags,
    }


def _int(s):
    m = re.search(r"-?\d+", s or "")
    return int(m.group()) if m else None


def _iso(date, years):
    """'10月27日(火)' → '2026-10-27'。見出しの年(年跨ぎ対応)を使う。"""
    m = re.search(r"(\d+)月(\d+)日", date or "")
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    y = int(years[0][0]) if years else 2000
    if years and mo < int(years[0][1]):
        y += 1
    return f"{y:04d}-{mo:02d}-{d:02d}"



def _fields(td):
    """<strong>ラベル:</strong> 値 の並びを dict にする。"""
    out = {}
    for div in td.find_all("div", recursive=False):
        st = div.find("strong")
        if not st:
            continue
        key = _text(st).rstrip(":：")
        st.extract()
        for a in div.find_all("a"):
            if _text(a) in ("シラバス", "iCalendar"):
                a.extract()
        out[key] = "\n".join(_lines(div))
    return out


def parse_status(soup):
    """授業予定ページ → {summary, reservations:[...]}。"""
    main = soup.select_one("#maincontents") or soup
    summary = _text(main.select_one(".w3-panel"))
    rows = []
    table = main.select_one("table.cool")
    for tr in table.select("tbody tr") if table else []:
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue
        when = _lines(tds[0])
        a = _fields(tds[1])
        b = _fields(tds[2])
        state = _lines(tds[5])
        lec = tr.find("input", {"name": "lectures[]"}) or tr.find("a", href=re.compile(r"lecture=\d+"))
        lid = lec.get("value") if lec and lec.name == "input" else (re.search(r"lecture=(\d+)", lec["href"]).group(1) if lec else None)
        rows.append({
            "id": lid,
            "date": when[0] if when else "",
            "iso": _iso(when[0] if when else "", _years_near(when[0] if when else "")),
            "period": when[1] if len(when) > 1 else "",
            "name": a.get("種目", ""),
            "teacher": a.get("教員", ""),
            "intensity": a.get("運動強度", ""),
            "mode": b.get("実施形態", ""),
            "place": b.get("場所", ""),
            "lang": b.get("開講言語", ""),
            "theme": b.get("テーマ", ""),
            "content": b.get("内容", ""),
            "cancelled": _text(tds[4]),
            "status": state[0] if state else "",
        })
    return {"summary": summary, "reservations": rows}


def parse_history(soup):
    """出欠履歴ページ上部の取得状況 → {credits:[[k,v]], priority:[[種目,値]]}。個人情報の行は捨てる。"""
    keep = re.compile(r"^体育\d")
    credits, priority = [], []
    t = soup.select_one("table.itemize")
    last = None
    for tr in t.find_all("tr") if t else []:
        k = _text(tr.find("th")).rstrip(":：") or last
        v = _text(tr.find("td"))
        last = k
        if k and keep.match(k):
            credits.append([k, v])
        elif k == "抽選優先度" and ":" in v:
            name, val = v.rsplit(":", 1)
            priority.append([name.strip(), val.strip().replace("−", "-")])
    return {"credits": credits, "priority": priority}


def _years_near(date):
    """予約一覧には年が無いので、今日に近い年を推定（12月に1月の授業を見るケース等）。"""
    import datetime
    today = datetime.date.today()
    m = re.search(r"(\d+)月", date or "")
    y = today.year
    if m:
        mo = int(m.group(1))
        if mo - today.month > 6:
            y -= 1
        elif today.month - mo > 6:
            y += 1
    return [(str(y), "1")]

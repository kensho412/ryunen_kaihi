# SFC体育ビューア

SFC 体育システム V4 の「自分の予約状況」「時間割」「2週間分の空き授業」をスマホで見る PWA と、
毎朝 6:00 の予約受付開始を ntfy でスマホに通知する GitHub Actions。

- **予約はしません**（規則で自動スクリプトによる予約は禁止・予約停止の対象）。表示と通知だけ。予約は公式サイトで手動で。
- アクセスは 1 日 3 回（JST 6:07 / 12:07 / 21:07）。ログインも 1 日 3 回だけ。
- 取得データは AES-GCM で暗号化して `docs/data.enc.json` に置くので、公開リポジトリ + GitHub Pages でも中身は見えません。

## 構成

```
scraper/wellness.py   サイト取得・解析（公開ページ + ログイン後ページ）
scraper/run.py        前回との差分 → ntfy 通知 → 暗号化して保存
docs/                 スマホ用 PWA（GitHub Pages で配信）
.github/workflows/check.yml  定期実行
```

## セットアップ

1. GitHub に新しいリポジトリを作り、このフォルダを push
2. **Settings → Secrets and variables → Actions → Secrets** に登録

   | 名前 | 内容 |
   | --- | --- |
   | `DATA_PASSPHRASE` | アプリを開くときのパスフレーズ（長めに） |
   | `NTFY_TOPIC` | 通知トピック名。推測されない文字列に（例: `sfcw-` + ランダム20文字） |
   | `WELLNESS_USER` | CNS ログイン名（または学籍番号）※予約状況を見る場合のみ |
   | `WELLNESS_PASS` | CNS パスワード ※同上 |

3. 同じ画面の **Variables** に `FAVORITES`（例: `テニス,ヨガ,空手`）を入れると、その種目に空きが出たときも通知
4. **Settings → Pages** → Source: `Deploy from a branch`、Branch: `main` / `/docs`
5. **Actions → check → Run workflow** で一度手動実行
6. スマホで `https://<ユーザー名>.github.io/<リポジトリ名>/` を開き、共有メニュー →「ホーム画面に追加」
7. ntfy アプリを入れて `NTFY_TOPIC` のトピックを購読（アプリの「通知」タブにも手順あり）

## 通知の種類

- 🗓 **予約受付開始** — 14日後の授業が予約可能になった（毎朝）
- ⭐ **お気に入りに空き** — `FAVORITES` の種目に新しく空きが出た
- 🎉 **抽選当選** — 抽選待ちが予約確定になった
- ⚠️ **抽選待ちが消えた** — 落選の可能性
- ⛔ **休講** — 予約中の授業が休講になった

## ローカルで試す

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
DATA_PASSPHRASE=test .venv/bin/python scraper/run.py
python3 -m http.server 8787 -d docs   # → http://localhost:8787 でパスフレーズ test
```

CNS パスワードは GitHub Secrets にのみ置き、リポジトリや `.env` をコミットしないこと。

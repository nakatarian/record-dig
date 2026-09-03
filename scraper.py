import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, parse_qs, urlparse
from supabase import create_client, Client
import time
import sys
import re
from datetime import datetime, timezone

# ==========================================
# 1. 設定情報（環境変数より取得）
# ==========================================
SUPABASE_URL = "https://slnraznxgatrefbuawqy.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SECRET_KEY")

# ★ Discord Webhook URL
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not SUPABASE_KEY:
    print("❌ エラー: SUPABASE_SECRET_KEY が環境変数に設定されていません。")
    sys.exit(1)

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"❌ [Supabase初期化エラー] {e}")
    sys.exit(1)

# スクレイピング対象カテゴリ
CATEGORIES = [
    {"name": "Deep House", "url": "https://www.newtone-records.com/store/deephouse/"},
    {"name": "Tech House", "url": "https://www.newtone-records.com/store/techhouse/"}
]

# ジャンルタグの正規化マップ
GENRE_MAP = {
    "deep house": "Deep House",
    "deep tech house": "Deep House",
    "deep tech": "Deep House",
    "tech house": "Tech House",
    "minimal house": "Minimal",
    "minimal": "Minimal",
    "minimal techno": "Minimal"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.newtone-records.com/"
}

# ==========================================
# 2. 通知・補助関数
# ==========================================

def send_discord_notification(count):
    """ Discord Webhook で新着件数を通知 """
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ DISCORD_WEBHOOK_URL が設定されていないため通知をスキップします。")
        return

    payload = {
        "content": f"NEWTONEに新着レコード{count}件追加"
    }
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if res.status_code in [200, 204]:
            print(f"📲 Discord通知を送信しました: NEWTONEに新着レコード{count}件追加")
        else:
            print(f"❌ Discord通知送信失敗: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ Discord通知エラー: {e}")

def clean_audio_url(file_src, base_url):
    """ 音源URLのドメイン・パス補正 """
    if not file_src: return ""
    full_url = urljoin(base_url, file_src.strip())
    full_url = full_url.replace("www.newtone-records.com", "dept.newtone-records.com")
    if "dept.newtone-records.com" in full_url and "/sound/" not in full_url:
        full_url = full_url.replace("dept.newtone-records.com/", "dept.newtone-records.com/sound/")
    full_url = full_url.replace("/sound/product/", "/sound/")
    return full_url

def extract_track_list_tracks(detail_soup, item_url):
    """ トラックリストおよび各曲試聴URLの抽出 """
    tracks = []
    heading = detail_soup.find(lambda tag: tag.name in ['h3', 'h4', 'div', 'p', 'span', 'dt'] and 'Track List' in tag.text)
    if heading:
        container = heading.find_next(['ul', 'ol', 'div', 'dl']) or heading.parent
        if container:
            links = container.select("a[file-src], a[data-src], a[href*='.mp3'], a[onclick*='sound']") or container.find_all(['a', 'li'])
            for node in links:
                text = node.text.strip()
                file_src = node.get("file-src") or node.get("data-src") or node.get("href")
                class_str = " ".join(node.get("class", []))
                if "sample" in class_str.lower() or "btn" in class_str.lower(): continue
                if not text or "Track List" in text or re.match(r'^Sample\s*\d+', text, re.IGNORECASE): continue
                if file_src:
                    full_audio = clean_audio_url(file_src, item_url)
                    if full_audio and not any(t["audio_url"] == full_audio or t["title"] == text for t in tracks):
                        tracks.append({"title": text, "audio_url": full_audio})
    return tracks

def cleanup_old_records(limit=30):
    """ DB内の件数が上限を超えた場合、古いデータを削除する """
    try:
        res = supabase.table("records").select("id, scraped_at").order("scraped_at", desc=True).execute()
        all_records = res.data or []
        
        if len(all_records) > limit:
            ids_to_delete = [r["id"] for r in all_records[limit:]]
            supabase.table("records").delete().in_("id", ids_to_delete).execute()
            print(f"🧹 古いデータ {len(ids_to_delete)} 件を削除し、最新{limit}件に整理しました。")
    except Exception as e:
        print(f"⚠️ データ自動クリーニングエラー: {e}")

# ==========================================
# 3. メイン処理（スクレイピング & DB更新）
# ==========================================

def scrape_and_update():
    session = requests.Session()
    session.headers.update(HEADERS)
    records_map = {}
    current_time_iso = datetime.now(timezone.utc).isoformat()

    # ★ 既存データの item_url と created_at を読み込み
    existing_records = {}
    is_first_run = False
    try:
        res = supabase.table("records").select("item_url, created_at").execute()
        if res.data:
            existing_records = {r["item_url"].strip(): r.get("created_at") for r in res.data if r.get("item_url")}
        else:
            is_first_run = True  # DBが空の場合は初回実行と判定
    except Exception as e:
        print(f"⚠️ 既存データの読み込み時にスキップ: {e}")

    for cat in CATEGORIES:
        # ★ 全体で既に30件取得済みの場合はカテゴリ巡回を打ち切り
        if len(records_map) >= 30:
            break

        try:
            res = session.get(cat["url"], timeout=15)
            if res.status_code != 200: continue
        except Exception as e:
            print(f"❌ カテゴリページの取得エラー ({cat['name']}): {e}")
            continue

        soup = BeautifulSoup(res.text, "html.parser")
        item_links = []
        seen_ids = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(k in href for k in ["/product/", "/item/", "item.php", "/physical/"]):
                if "category" in href or "cart" in href or "wishlist" in href: continue
                full_url = urljoin(cat["url"], href).strip()
                parsed = urlparse(full_url)
                item_id = parse_qs(parsed.query).get("id", [None])[0] or parsed.path.rstrip("/").split("/")[-1]
                if item_id and item_id not in seen_ids:
                    seen_ids.add(item_id)
                    item_links.append((item_id, full_url))

        # ★ 1カテゴリあたり必要な件数分（残枠）だけ切り出し
        remaining_slots = 30 - len(records_map)
        item_links = item_links[:remaining_slots]

        for local_rank, (item_id, item_url) in enumerate(item_links, 1):
            if item_id in records_map: continue
            
            # ★ 累計30件に達した時点で詳細ページの取得を停止
            if len(records_map) >= 30:
                break

            time.sleep(0.15)
            try:
                detail_res = session.get(item_url, timeout=10)
                if detail_res.status_code != 200: continue
                detail_soup = BeautifulSoup(detail_res.text, "html.parser")

                # ハッシュタグから対応ジャンルを検出
                detected_genres = []
                for elem in detail_soup.find_all(string=True):
                    txt = elem.strip()
                    if txt.startswith("#"):
                        clean_tag = re.sub(r'\s+', ' ', txt.lstrip("#").strip().lower())
                        if clean_tag in GENRE_MAP and GENRE_MAP[clean_tag] not in detected_genres:
                            detected_genres.append(GENRE_MAP[clean_tag])

                if not detected_genres: continue

                # タイトル抽出
                title = ""
                title_el = detail_soup.select_one("h1, .item-title, .item_title, .title, #title")
                if title_el: title = title_el.text.strip()
                if not title and detail_soup.title: title = detail_soup.title.text.strip()
                if title: title = re.sub(r'\s*\|\s*NEWTONE\s*RECORDS.*$', '', title, flags=re.IGNORECASE).strip()

                # 画像URL抽出
                image_url = ""
                og_img = detail_soup.select_one("meta[property='og:image']")
                if og_img and og_img.get("content"): image_url = og_img.get("content", "").strip()
                if not image_url or not image_url.startswith("http"):
                    img_el = detail_soup.select_one(".item_img img, #item_img img, .item-image img, .main-img img, img[src*='/pic/'], img[src*='/product/']")
                    if img_el and img_el.get("src"): image_url = urljoin(item_url, img_el["src"])

                # 型番・発売日
                cat_no = ""
                release_date = None
                page_text = detail_soup.text
                cat_el = detail_soup.select_one("li.catno, .catno, .cat-no, .catalog, .code, .cat_no")
                if cat_el: cat_no = cat_el.text.strip()
                else:
                    cat_match = re.search(r'(?:Cat\s*No\.?:?\s*|型番\s*:\s*)([A-Z0-9_\-\s\/]+)', page_text, re.IGNORECASE)
                    if cat_match: cat_no = cat_match.group(1).strip()
                cat_no = re.sub(r'^(?:Cat\s*No\.?:?\s*|型番\s*:\s*)', '', cat_no, flags=re.IGNORECASE).strip()

                date_match = re.search(r'20\d{2}[-/.]\d{2}[-/.]\d{2}', page_text)
                if date_match: release_date = date_match.group(0).replace('/', '-').replace('.', '-')

                # 在庫ステータス
                page_text_upper = page_text.upper()
                is_sold_out = ("OUT OF STOCK" in page_text_upper or "SOLD OUT" in page_text_upper or "売り切れ" in page_text_upper or bool(detail_soup.select_one(".soldout, .sold-out, .out-of-stock")))

                # トラック情報・音声URL
                tracks = extract_track_list_tracks(detail_soup, item_url)
                audio_url = tracks[0]["audio_url"] if tracks else ""

                record_data = {
                    "item_url": item_url,
                    "title": title,
                    "cat_no": cat_no,
                    "image_url": image_url,
                    "audio_url": audio_url,
                    "tracks": tracks,
                    "genre": detected_genres[0],
                    "genres": detected_genres,
                    "is_sold_out": is_sold_out,
                    "release_date": release_date,
                    "scraped_at": current_time_iso
                }

                # ★ 既存データがあれば過去の created_at を維持
                if item_url in existing_records:
                    record_data["created_at"] = existing_records[item_url]
                else:
                    record_data["created_at"] = current_time_iso

                records_map[item_id] = record_data
                print(f"  ✓ [{detected_genres[0]}] {title} (Tracks: {len(tracks)})")
            except Exception as e:
                print(f"  ❌ エラー {item_url}: {e}")

    records_to_insert = list(records_map.values())
    if records_to_insert:
        try:
            # ★ DBに存在しない新規件数を正確にカウント
            new_items_count = sum(1 for r in records_to_insert if r["item_url"] not in existing_records)
            
            # データベースへUpsert（更新・挿入）
            supabase.table("records").upsert(records_to_insert, on_conflict="item_url").execute()
            print(f"\n🎉 データベース書き込み完了！（新規件数: {new_items_count}件）")
            
            # 古いレコードを整理（最新30件を保持）
            cleanup_old_records(limit=30)

            # ★ 初回実行時ではなく、本当に新着が1件以上増えた時のみ Discord 通知を送信
            if not is_first_run and new_items_count > 0:
                send_discord_notification(new_items_count)
            else:
                print("ℹ️ 新着レコードがないため、Discord通知をスキップしました。")

        except Exception as e:
            print(f"  ❌ Supabaseエラー: {e}")

if __name__ == "__main__":
    scrape_and_update()
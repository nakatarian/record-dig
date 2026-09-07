import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, parse_qs, urlparse
import time
import re
from datetime import datetime, timezone, timedelta, date

CATEGORIES = [
    {"name": "Deep House", "url": "https://www.freestyle-online.net/products/list.php?category_id=11"},
    {"name": "Tech House", "url": "https://www.freestyle-online.net/products/list.php?category_id=12"},
    {"name": "Minimal", "url": "https://www.freestyle-online.net/products/list.php?category_id=13"}
]

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
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

def fetch_url(session, url, retries=3, timeout=30):
    for i in range(retries):
        try:
            res = session.get(url, timeout=timeout)
            if res.status_code == 200:
                return res
        except Exception as e:
            if i == retries - 1:
                raise e
            time.sleep(2)
    return None

def extract_track_list_tracks(detail_soup, item_url):
    tracks = []
    # トラックリストの親要素（.track_list, .tracklist, テーブル等）を探す
    track_container = detail_soup.select_one(".track_list, .tracklist, #tracklist, .track_info")
    
    if track_container:
        nodes = track_container.select("li, tr, p, div")
        for node in nodes:
            text = node.text.strip()
            if not text or "Track" in text:
                continue
            
            # プレイヤー要素やリンクから音声URLを探す
            audio_node = node.select_one("a[href*='.mp3'], audio source, [data-src*='.mp3']")
            audio_url = ""
            if audio_node:
                src = audio_node.get("href") or audio_node.get("src") or audio_node.get("data-src")
                if src:
                    audio_url = urljoin(item_url, src.strip())
            
            if text and not any(t["title"] == text for t in tracks):
                tracks.append({"title": text, "audio_url": audio_url})
    
    return tracks

def scrape_freestyle(existing_records_map):
    session = requests.Session()
    session.headers.update(HEADERS)
    records_map = {}
    current_time_iso = datetime.now(timezone.utc).isoformat()
    cutoff_date = date.today() - timedelta(days=7)

    for cat in CATEGORIES:
        print(f"\n🔍 [FREESTYLE] カテゴリ巡回開始: {cat['name']}")
        
        page = 1
        stop_cat = False
        sort_order_counter = 1  # サイト上の掲載順（1, 2, 3...）

        while True:
            if stop_cat:
                break

            page_url = f"{cat['url']}&pageno={page}" if page > 1 else cat['url']
            print(f"  📄 ページ取得中 ({page}ページ目): {page_url}")

            try:
                res = fetch_url(session, page_url, retries=3, timeout=30)
                if not res or res.status_code != 200:
                    print("  ⚠️ アクセス失敗のためカテゴリ移動")
                    break
            except Exception as e:
                print(f"❌ [FREESTYLE] ページ取得エラー: {e}")
                break

            soup = BeautifulSoup(res.text, "html.parser")
            
            # 商品リンクを抽出
            item_links = []
            seen_ids = set()

            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "products/detail.php" in href:
                    full_url = urljoin(cat["url"], href).strip()
                    parsed = urlparse(full_url)
                    item_id = parse_qs(parsed.query).get("product_id", [None])[0]
                    
                    if item_id and item_id not in seen_ids:
                        seen_ids.add(item_id)
                        item_links.append((item_id, full_url, sort_order_counter))
                        sort_order_counter += 1

            if not item_links:
                print("  ℹ️ 商品が見つからなくなったため次のカテゴリへ")
                break

            # 詳細ページの解析
            for item_id, item_url, sort_order in item_links:
                if item_id in records_map:
                    continue

                time.sleep(0.3)
                try:
                    detail_res = fetch_url(session, item_url, retries=2, timeout=20)
                    if not detail_res or detail_res.status_code != 200:
                        continue

                    detail_soup = BeautifulSoup(detail_res.text, "html.parser")
                    page_text = detail_soup.text

                    # タイトル
                    title = ""
                    title_el = detail_soup.select_one("h2.title, .product_name, h1")
                    if title_el:
                        title = title_el.text.strip()
                    if not title and detail_soup.title:
                        title = detail_soup.title.text.strip()

                    # 日付（入荷日・発売日）
                    date_match = re.search(r'20\d{2}[-/.]\d{2}[-/.]\d{2}', page_text)
                    release_date_str = None
                    if date_match:
                        raw_date_str = date_match.group(0).replace('/', '-').replace('.', '-')
                        try:
                            item_date = datetime.strptime(raw_date_str, "%Y-%m-%d").date()
                            release_date_str = raw_date_str
                            if item_date < cutoff_date:
                                print(f"  ⏹️ {item_date} のデータ（1週間以上前）に達したため {cat['name']} の取得を終了します。")
                                stop_cat = True
                                break
                        except ValueError:
                            pass

                    # ジャンル判定
                    detected_genres = []
                    for elem in detail_soup.find_all(string=True):
                        txt = elem.strip().lower()
                        if txt in GENRE_MAP and GENRE_MAP[txt] not in detected_genres:
                            detected_genres.append(GENRE_MAP[txt])

                    # 該当ジャンルがない場合はデフォルトでカテゴリ名を使用
                    if not detected_genres and cat['name'] in GENRE_MAP.values():
                        detected_genres.append(cat['name'])

                    if not detected_genres:
                        continue

                    # 画像URL
                    image_url = ""
                    img_el = detail_soup.select_one(".product_image img, .main_image img, img[src*='/upload/']")
                    if img_el and img_el.get("src"):
                        image_url = urljoin(item_url, img_el["src"])

                    # 型番 (Catalog No)
                    cat_no = ""
                    cat_match = re.search(r'(?:Cat\s*No\.?:?\s*|型番\s*:\s*)([A-Z0-9_\-\s\/]+)', page_text, re.IGNORECASE)
                    if cat_match:
                        cat_no = cat_match.group(1).strip()

                    # 在庫状況
                    page_text_upper = page_text.upper()
                    is_sold_out = ("SOLDOUT" in page_text_upper or "売り切れ" in page_text_upper or "在庫なし" in page_text_upper)

                    # トラックリスト・試聴音源
                    tracks = extract_track_list_tracks(detail_soup, item_url)
                    audio_url = tracks[0]["audio_url"] if tracks else ""

                    # 代表音源が取れていない場合、全体からmp3リンクを探索
                    if not audio_url:
                        mp3_match = re.search(r'https?://[^\s\'"]+?\.mp3', detail_res.text, re.IGNORECASE)
                        if mp3_match:
                            audio_url = mp3_match.group(0)

                    record_data = {
                        "site": "freestyle",
                        "item_url": item_url,
                        "title": title,
                        "cat_no": cat_no,
                        "image_url": image_url,
                        "audio_url": audio_url,
                        "tracks": tracks,
                        "genre": detected_genres[0],
                        "genres": detected_genres,
                        "is_sold_out": is_sold_out,
                        "release_date": release_date_str,
                        "sort_order": sort_order,
                        "scraped_at": current_time_iso
                    }

                    if isinstance(existing_records_map, dict) and item_url in existing_records_map:
                        record_data["created_at"] = existing_records_map[item_url]
                    else:
                        record_data["created_at"] = current_time_iso

                    records_map[item_id] = record_data
                    print(f"  ✓ [順位:{sort_order}] [{detected_genres[0]}] ({release_date_str}) {title}")

                except Exception as e:
                    print(f"  ❌ エラー {item_url}: {e}")

            # ページの移動判定
            next_page_link = soup.select_one("a:-soup-contains('次へ'), a:-soup-contains('NEXT')")
            if not next_page_link or stop_cat:
                break

            page += 1

    return list(records_map.values())
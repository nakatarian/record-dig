import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import re
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

FREESTYLE_ALL_URL = "https://freestyleonline.net/list.php?GENRE=ALL"

# 指定タグの変換マッピング
TAG_MAP = {
    "techhouse": "Tech House",
    "minimal": "Minimal",
    "deep": "Deep House"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

def fetch_and_parse_item(item_url, session, today, cutoff_past_date, now_jst, existing_records_map):
    """1つの商品詳細ページをスクレイピングする関数"""
    JST = timezone(timedelta(hours=9))
    try:
        detail_res = session.get(item_url, timeout=15)
        detail_res.encoding = detail_res.apparent_encoding or 'utf-8'
        if detail_res.status_code != 200:
            return None

        detail_soup = BeautifulSoup(detail_res.text, "html.parser")
        page_text = detail_soup.text

        # --------------------------------------------------
        # タグの抽出
        # --------------------------------------------------
        detected_genres = []
        tags_matched = re.findall(r'#([a-zA-Z0-9]+)', page_text, re.IGNORECASE)
        for t in tags_matched:
            tag_lower = t.lower()
            if tag_lower in TAG_MAP and TAG_MAP[tag_lower] not in detected_genres:
                detected_genres.append(TAG_MAP[tag_lower])

        if not detected_genres:
            return None

        # --------------------------------------------------
        # 日付の分離処理
        # --------------------------------------------------
        update_datetime = None
        upcoming_arrival_date = None

        for tr in detail_soup.find_all("tr"):
            tr_text = tr.text.strip()
            date_match = re.search(r'20\d{2}[./-]\d{2}[./-]\d{2}', tr_text)
            
            if date_match:
                found_date_str = date_match.group(0).replace('.', '-').replace('/', '-')
                try:
                    d_obj = datetime.strptime(found_date_str, "%Y-%m-%d").date()
                    
                    time_match = re.search(r'(\d{1,2}):(\d{2})', tr_text)
                    if time_match:
                        hh, mm = map(int, time_match.groups())
                        dt_obj = datetime(d_obj.year, d_obj.month, d_obj.day, hh, mm, tzinfo=JST)
                    else:
                        dt_obj = datetime(d_obj.year, d_obj.month, d_obj.day, 0, 0, tzinfo=JST)

                    if "入荷予定" in tr_text:
                        if d_obj > today:
                            upcoming_arrival_date = d_obj.strftime("%Y-%m-%d")
                    
                    if "更新日" in tr_text or "更新" in tr_text:
                        update_datetime = dt_obj

                except ValueError:
                    pass

        if not update_datetime:
            update_datetime = now_jst

        # 7日以上前の過去データはスキップ
        if update_datetime.date() < cutoff_past_date:
            return None

        # --------------------------------------------------
        # タイトル・キャットナンバー
        # --------------------------------------------------
        title = ""
        title_el = detail_soup.select_one("h1, h2, .item_title, font[size='+1']")
        if title_el:
            title = title_el.text.strip()
        if not title and detail_soup.title:
            title = detail_soup.title.text.strip()

        cat_no = ""
        cat_match = re.search(r'cat\.?no\s*:?\s*([A-Za-z0-9_\-\s\/]+)', page_text, re.IGNORECASE)
        if cat_match:
            cat_no = cat_match.group(1).split('\n')[0].strip()

        # --------------------------------------------------
        # 画像URL
        # --------------------------------------------------
        image_url = ""
        for img in detail_soup.find_all("img"):
            src = img.get("src", "")
            if not src: continue
            src_lower = src.lower()
            if any(x in src_lower for x in ["header", "logo", "cart", "icon", "banner", "button", "panda", "twitter", "facebook", "listen_b.gif"]):
                continue
            if any(x in src_lower for x in ["/listen/img/", "/photo/", "/item/", "disco", ".jpg", ".jpeg", ".png"]):
                image_url = urljoin(item_url, src)
                break

        # --------------------------------------------------
        # 在庫状態
        # --------------------------------------------------
        page_text_upper = page_text.upper()
        is_sold_out = any(k in page_text_upper for k in ["OUT OF STOCK", "SOLD OUT", "在庫なし", "売り切れ"])

        # --------------------------------------------------
        # 音声 & トラックリスト
        # --------------------------------------------------
        audio_url = ""
        listen_a_tag = detail_soup.find("a", href=re.compile(r"OPENLISTEN", re.IGNORECASE))
        if listen_a_tag:
            href_attr = listen_a_tag.get("href", "")
            m = re.search(r"OPENLISTEN\('([^']+)'\)", href_attr, re.IGNORECASE)
            if m:
                audio_url = urljoin(item_url, m.group(1))

        if not audio_url:
            audio_match = re.search(r"([a-zA-Z0-9_\-]+\.mp3)", page_text)
            if audio_match:
                filename = audio_match.group(1)
                audio_url = f"https://freestyleonline.net/audio/mp3/{filename}"

        tracks = []
        parsed_track_lines = []
        track_td = detail_soup.find("td", attrs={"colspan": "2"})
        if track_td:
            lines = track_td.get_text(separator="\n").splitlines()
            for line in lines:
                clean_line = line.strip()
                if re.match(r'^[A-D][1-9]\s*:', clean_line):
                    parsed_track_lines.append(clean_line)

        if parsed_track_lines:
            for line in parsed_track_lines:
                tracks.append({"title": line, "audio_url": audio_url})
        else:
            tracks.append({"title": title, "audio_url": audio_url})

        # --------------------------------------------------
        # データの組み立て
        # --------------------------------------------------
        updated_at_iso = update_datetime.isoformat()
        updated_display_str = f"{update_datetime.strftime('%Y-%m-%d')} ({update_datetime.strftime('%H:%M')}更新)"

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
            "upcoming_arrival_date": upcoming_arrival_date,
            "updated_at": updated_at_iso,
            "updated_display": updated_display_str,
            "scraped_at": now_jst.isoformat()
        }

        # existing_records_map の型安全チェック
        created_at_val = now_jst.isoformat()
        if isinstance(existing_records_map, dict) and item_url in existing_records_map:
            exist_item = existing_records_map[item_url]
            if isinstance(exist_item, dict):
                created_at_val = exist_item.get("created_at", created_at_val)
            elif isinstance(exist_item, str):
                created_at_val = exist_item

        record_data["created_at"] = created_at_val

        item_id = item_url.split("=")[-1] if "=" in item_url else item_url
        
        genres_label = ", ".join(detected_genres)
        print(f"  ✓ [FREESTYLE] [{genres_label}] ({updated_display_str}) {title}")
        return item_id, record_data

    except Exception as e:
        print(f"  ❌ エラー {item_url}: {e}")
        return None


def scrape_freestyle(existing_records_map):
    session = requests.Session()
    session.headers.update(HEADERS)
    records_map = {}
    
    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)
    today = now_jst.date()
    cutoff_past_date = today - timedelta(days=7)

    print(f"\n🔍 [FREESTYLE] 1ページ目取得開始: {FREESTYLE_ALL_URL}")
    try:
        res = session.get(FREESTYLE_ALL_URL, timeout=30)
        res.encoding = res.apparent_encoding or 'utf-8'
        if res.status_code != 200:
            print("  ⚠️ FREESTYLEへのアクセスに失敗しました。")
            return []
    except Exception as e:
        print(f"❌ [FREESTYLE] 通信エラー: {e}")
        return []

    soup = BeautifulSoup(res.text, "html.parser")
    
    target_links = []
    seen_urls = set()

    # ★ 修正箇所: item.php ではなく detail.php や code= を含む商品URLを取得
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "detail.php" in href or "code=" in href:
            full_url = urljoin(FREESTYLE_ALL_URL, href).strip()
            if full_url not in seen_urls:
                seen_urls.add(full_url)
                target_links.append(full_url)

    print(f"  📦 1ページ目から抽出された商品リンク: {len(target_links)} 件")

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(
                fetch_and_parse_item, 
                url, session, today, cutoff_past_date, now_jst, existing_records_map
            ) 
            for url in target_links
        ]
        
        for future in as_completed(futures):
            res = future.result()
            if res:
                item_id, record_data = res
                records_map[item_id] = record_data

    results = list(records_map.values())
    results.sort(key=lambda x: x["updated_at"], reverse=True)

    return results
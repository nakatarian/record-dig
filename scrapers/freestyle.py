import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import re
from datetime import datetime, timezone, timedelta, date

FREESTYLE_ALL_URL = "https://freestyleonline.net/list.php?GENRE=ALL"

# ② 指定タグの変換マッピング
TAG_MAP = {
    "techhouse": "Tech House",
    "minimal": "Minimal",
    "deep": "Deep House"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

def scrape_freestyle(existing_records_map):
    session = requests.Session()
    session.headers.update(HEADERS)
    records_map = {}
    current_time_iso = datetime.now(timezone.utc).isoformat()
    
    today = date.today()
    cutoff_past_date = today - timedelta(days=7)

    print(f"\n🔍 [FREESTYLE] 一覧ページ取得開始: {FREESTYLE_ALL_URL}")
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
    
    detail_links = []
    seen_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "item.php" in href or "detail" in href:
            full_url = urljoin(FREESTYLE_ALL_URL, href).strip()
            if full_url not in seen_urls:
                seen_urls.add(full_url)
                detail_links.append(full_url)

    print(f"  📦 検出された商品リンク: {len(detail_links)} 件")

    for item_url in detail_links:
        time.sleep(0.3)
        try:
            detail_res = session.get(item_url, timeout=20)
            detail_res.encoding = detail_res.apparent_encoding or 'utf-8'
            if detail_res.status_code != 200: continue
            
            detail_soup = BeautifulSoup(detail_res.text, "html.parser")
            page_text = detail_soup.text

            # --------------------------------------------------
            # ② 該当タグ（複数対応・大文字小文字無視）の抽出
            # --------------------------------------------------
            detected_genres = []
            tags_matched = re.findall(r'#([a-zA-Z0-9]+)', page_text, re.IGNORECASE)
            for t in tags_matched:
                tag_lower = t.lower()
                if tag_lower in TAG_MAP and TAG_MAP[tag_lower] not in detected_genres:
                    detected_genres.append(TAG_MAP[tag_lower])

            if not detected_genres:
                continue

            # --------------------------------------------------
            # ① 日付の精緻な抽出
            # --------------------------------------------------
            release_date_str = None
            update_date = None
            arrival_date = None
            is_rearrival = False

            for tr in detail_soup.find_all("tr"):
                tr_text = tr.text.strip()
                date_match = re.search(r'20\d{2}[./-]\d{2}[./-]\d{2}', tr_text)
                
                if date_match:
                    found_date_str = date_match.group(0).replace('.', '-').replace('/', '-')
                    try:
                        d_obj = datetime.strptime(found_date_str, "%Y-%m-%d").date()
                        
                        if "入荷予定" in tr_text:
                            arrival_date = d_obj
                        elif "更新日" in tr_text:
                            update_date = d_obj
                            if "[再入荷]" in tr_text:
                                is_rearrival = True
                    except ValueError:
                        pass

            chosen_date = None
            if arrival_date and arrival_date >= today:
                chosen_date = arrival_date
            elif is_rearrival and update_date:
                chosen_date = update_date
            else:
                valid_dates = [d for d in [update_date, arrival_date] if d is not None]
                if valid_dates:
                    chosen_date = max(valid_dates)

            if chosen_date:
                release_date_str = chosen_date.strftime("%Y-%m-%d")
                if chosen_date < cutoff_past_date:
                    print(f"  ⏹️ {release_date_str} のためスキップ（7日以上前の過去データ）")
                    continue

            # --------------------------------------------------
            # タイトル・キャットナンバーの取得
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
            # 画像URLの取得
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
            # 在庫状態の判定
            # --------------------------------------------------
            page_text_upper = page_text.upper()
            is_sold_out = any(k in page_text_upper for k in ["OUT OF STOCK", "SOLD OUT", "在庫なし", "売り切れ"])

            # --------------------------------------------------
            # 音声ファイル (.mp3) の抽出
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

            # --------------------------------------------------
            # トラックリストの取得（1曲ずつ改行するよう変更）
            # --------------------------------------------------
            tracks = []
            parsed_track_lines = []

            track_td = detail_soup.find("td", attrs={"colspan": "2"})
            if track_td:
                lines = track_td.get_text(separator="\n").splitlines()
                for line in lines:
                    clean_line = line.strip()
                    if re.match(r'^[A-D][1-9]\s*:', clean_line):
                        parsed_track_lines.append(clean_line)

            # 1曲ずつ改行 (\n) で結合
            if parsed_track_lines:
                combined_track_title = "\n".join(parsed_track_lines)
            else:
                combined_track_title = title

            if audio_url:
                tracks.append({"title": combined_track_title, "audio_url": audio_url})

            # --------------------------------------------------
            # データの組み立て
            # --------------------------------------------------
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
                "scraped_at": current_time_iso
            }

            if item_url in existing_records_map:
                record_data["created_at"] = existing_records_map[item_url]
            else:
                record_data["created_at"] = current_time_iso

            item_id = item_url.split("=")[-1] if "=" in item_url else item_url
            records_map[item_id] = record_data
            
            genres_label = ", ".join(detected_genres)
            print(f"  ✓ [FREESTYLE] [{genres_label}] ({release_date_str}) {title}")

        except Exception as e:
            print(f"  ❌ エラー {item_url}: {e}")

    return list(records_map.values())

if __name__ == "__main__":
    print("🚀 Freestyle 単体テスト実行開始...")
    test_results = scrape_freestyle({})
    print(f"\n✅ 取得完了: 計 {len(test_results)} 件")
    for r in test_results:
        print(f"・ジャンル: {r['genres']} | タイトル: {r['title']} | 日付: {r['release_date']}")
        print(f"  画像: {r['image_url']}")
        print(f"  音源: {r['audio_url']}")
        print(f"  曲名:\n{r['tracks'][0]['title'] if r['tracks'] else 'なし'}\n")
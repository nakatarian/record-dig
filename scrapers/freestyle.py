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
    
    # 本日の日付
    today = date.today()
    cutoff_past_date = today - timedelta(days=7) # 過去1週間（7日前）

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
            # ② 該当タグ（複数対応）の抽出
            # --------------------------------------------------
            detected_genres = []
            tags_matched = re.findall(r'#([a-zA-Z0-9]+)', page_text)
            for t in tags_matched:
                tag_lower = t.lower()
                # 対象のタグ（techhouse, minimal, deep）に一致するものだけを配列に追加
                if tag_lower in TAG_MAP and TAG_MAP[tag_lower] not in detected_genres:
                    detected_genres.append(TAG_MAP[tag_lower])

            # 対象タグが1つも含まれていなければスキップ
            if not detected_genres:
                continue

            # --------------------------------------------------
            # ① 日付のチェック
            # 入荷予定（今日以降）：すべて取得
            # 入荷済み（今日より過去）：1週間以内（7日前まで）のみ取得
            # --------------------------------------------------
            dates = re.findall(r'20\d{2}[./-]\d{2}[./-]\d{2}', page_text)
            release_date_str = None
            if dates:
                raw_date_str = dates[0].replace('.', '-').replace('/', '-')
                try:
                    item_date = datetime.strptime(raw_date_str, "%Y-%m-%d").date()
                    release_date_str = raw_date_str
                    
                    # 過去データかつ7日より古い場合はスキップ
                    if item_date < today and item_date < cutoff_past_date:
                        print(f"  ⏹️ {item_date} のためスキップ（7日以上前の過去データ）")
                        continue
                except ValueError:
                    pass

            # --------------------------------------------------
            # タイトル・キャットナンバー・画像の取得
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

            image_url = ""
            img_el = detail_soup.select_one("img[src*='image/'], img[src*='photo/'], img[src*='item/']")
            if img_el and img_el.get("src"):
                image_url = urljoin(item_url, img_el["src"])

            # --------------------------------------------------
            # ④ 在庫状態の判定
            # --------------------------------------------------
            page_text_upper = page_text.upper()
            is_sold_out = any(k in page_text_upper for k in ["OUT OF STOCK", "SOLD OUT", "在庫なし", "売り切れ"])

            # --------------------------------------------------
            # ③ 音声ファイル (.mp3) の抽出
            # --------------------------------------------------
            tracks = []
            audio_url = ""

            audio_match = re.search(r"([a-zA-Z0-9_\-]+\.mp3)", page_text)
            if audio_match:
                filename = audio_match.group(1)
                audio_url = f"https://freestyleonline.net/audio/mp3/{filename}"

            track_matches = re.findall(r'([A-D][1-9]\s*:\s*[^:\n]+)', page_text)
            if track_matches:
                combined_track_title = " / ".join([t.strip() for t in track_matches])
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
                "genre": detected_genres[0], # 筆頭のメインジャンル
                "genres": detected_genres,  # ★ 該当するタグ全件の配列
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
            
            # ログ表示（複数ジャンルの確認用）
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
        print(f"・ジャンル全件: {r['genres']} | タイトル: {r['title']} | 日付: {r['release_date']} | 音源: {r['audio_url']}")
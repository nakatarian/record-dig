import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import re
from datetime import datetime, timezone, timedelta, date

BASE_URL = "https://teq-tokyo.com"
NEW_RELEASES_URL = "https://teq-tokyo.com/collections/new-releases?page={page}"

# 取得対象の3ジャンルと表記の揺れ（マッピング）
GENRE_TARGETS = {
    "deep house": "Deep House",
    "tech house": "Tech House",
    "minimal": "Minimal"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

def fetch_url(session, url, retries=3, timeout=20):
    for i in range(retries):
        try:
            res = session.get(url, timeout=timeout)
            if res.status_code == 200:
                return res
        except Exception as e:
            if i == retries - 1:
                raise e
            time.sleep(1)
    return None

def scrape_teq(existing_records_map):
    session = requests.Session()
    session.headers.update(HEADERS)
    records_map = {}

    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)
    today = now_jst.date()
    cutoff_date = today - timedelta(days=7)  # 1週間前

    target_links = []
    seen_urls = set()
    sort_order = 1

    print("\n🔍 [TEQ] /collections/new-releases より商品一覧を抽出中...")

    # 30件取得（通常1ページに24〜30件あるため1〜2ページ巡回）
    for page in [1, 2]:
        page_url = NEW_RELEASES_URL.format(page=page)
        res = fetch_url(session, page_url)
        if not res:
            continue

        soup = BeautifulSoup(res.text, "html.parser")
        
        # 商品カードリンクを収集
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/products/" in href and not href.endswith(".json"):
                full_url = urljoin(BASE_URL, href).split("?")[0].strip()
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    target_links.append((full_url, sort_order))
                    sort_order += 1
                    if len(target_links) >= 30:  # 最大30件に変更
                        break
        
        if len(target_links) >= 30:
            break

    print(f"  📦 抽出された商品リンク: 上から {len(target_links)} 件")

    # 各商品の詳細を取得・パース
    for item_url, order in target_links:
        time.sleep(0.3)  # アクセス負荷軽減
        try:
            # 1. Shopify の .json エンドポイントから基本データを取得
            json_url = f"{item_url}.json"
            res_json = fetch_url(session, json_url)
            if not res_json:
                continue
            
            product_data = res_json.json().get("product", {})
            if not product_data:
                continue

            # 日付（published_at）の判定
            published_at_str = product_data.get("published_at")
            release_date_str = None
            
            if published_at_str:
                pub_dt = datetime.fromisoformat(published_at_str)
                pub_date = pub_dt.date()
                release_date_str = pub_date.strftime("%Y-%m-%d")

                # 1週間以上前のデータに達した瞬間に処理（スクレイピング）を完全終了する
                if pub_date < cutoff_date:
                    print(f"  ⏹️ 1週間以上前のデータ ({release_date_str}: {product_data.get('title')}) に達したため、処理を終了します。")
                    break  # continue から break に変更

            # 2. HTML詳細ページを取得（ジャンル・トラック・SOLD OUTの確認）
            res_html = fetch_url(session, item_url)
            if not res_html:
                continue

            detail_soup = BeautifulSoup(res_html.text, "html.parser")
            
            # --- 【ジャンル判定】 ---
            detected_genres = []
            styles_div = detail_soup.select_one(".itemInfo.styles, .styles")
            if styles_div:
                style_links = styles_div.find_all("a")
                for a_tag in style_links:
                    style_txt = a_tag.text.strip().lower()
                    for target_key, target_name in GENRE_TARGETS.items():
                        if target_key in style_txt and target_name not in detected_genres:
                            detected_genres.append(target_name)

            # 3対象ジャンルのいずれにも該当しない場合はスキップ（次の商品の確認へ）
            if not detected_genres:
                continue

            # --- 【SOLD OUT 判定】 ---
            is_sold_out = False
            submit_btn = detail_soup.select_one("button.product-form__submit, button[name='add']")
            if submit_btn:
                if submit_btn.has_attr("disabled"):
                    is_sold_out = True
                elif "SOLD OUT" in submit_btn.text.upper() or "売り切れ" in submit_btn.text:
                    is_sold_out = True
            else:
                price_area = detail_soup.select_one(".product-form, .product__info-container")
                if price_area and ("SOLD OUT" in price_area.text.upper() or "売り切れ" in price_area.text):
                    is_sold_out = True

            # --- 【音声URL（MP3）の抽出（// 形式にも対応）】 ---
            mp3_matches = re.findall(r'(?:https?:)?//[^\s\'"]+?\.mp3(?:\?[^\s\'"]*)?', res_html.text, re.IGNORECASE)
            
            # 重複を除去しつつ、https: を補完してリスト化
            audio_urls = []
            for url in mp3_matches:
                full_audio_url = "https:" + url if url.startswith("//") else url
                if full_audio_url not in audio_urls:
                    audio_urls.append(full_audio_url)

            # 代表audio_url（最初のMP3）
            primary_audio_url = audio_urls[0] if audio_urls else ""

            # --- 【トラック名 & 各トラックへのaudio_urlの割り当て】 ---
            tracks = []
            track_elems = detail_soup.select(".itemTracks-name")
            
            for idx, elem in enumerate(track_elems):
                title_p = elem.select_one(".track-title")
                track_title = title_p.text.strip() if title_p else elem.text.strip()
                
                # トラックに対応するMP3があれば個別に設定、なければ空文字
                track_audio = audio_urls[idx] if idx < len(audio_urls) else ""
                tracks.append({"title": track_title, "audio_url": track_audio})

            # もしHTML上に .itemTracks-name がないが MP3 が見つかった場合のフォールバック
            if not tracks and audio_urls:
                for idx, a_url in enumerate(audio_urls):
                    tracks.append({"title": f"Track {idx + 1}", "audio_url": a_url})

            # --- 【基本データの整形】 ---
            title = product_data.get("title", "").strip()
            variants = product_data.get("variants", [])
            cat_no = variants[0].get("sku", "").strip() if variants else ""
            images = product_data.get("images", [])
            image_url = images[0].get("src", "") if images else ""

            item_id = str(product_data.get("id"))

            record_data = {
                "site": "teq",
                "item_url": item_url,
                "title": title,
                "cat_no": cat_no,
                "image_url": image_url,
                "audio_url": primary_audio_url,
                "tracks": tracks,
                "genre": detected_genres[0],
                "genres": detected_genres,
                "is_sold_out": is_sold_out,
                "release_date": release_date_str,
                "sort_order": order,
                "scraped_at": now_jst.isoformat()
            }

            # 既存レコードから created_at を引き継ぎ
            if isinstance(existing_records_map, dict) and item_url in existing_records_map:
                exist_item = existing_records_map[item_url]
                if isinstance(exist_item, dict):
                    record_data["created_at"] = exist_item.get("created_at", now_jst.isoformat())
                else:
                    record_data["created_at"] = exist_item
            else:
                record_data["created_at"] = now_jst.isoformat()

            records_map[item_id] = record_data
            genres_label = ", ".join(detected_genres)
            status_label = "[SOLD OUT]" if is_sold_out else "[IN STOCK]"
            audio_status = f"[Audio: {len(audio_urls)}件]" if audio_urls else "[Audio: なし]"
            print(f"  ✓ [順位:{order}] {status_label} {audio_status} [{genres_label}] ({release_date_str}) {title}")

        except Exception as e:
            print(f"  ❌ エラー {item_url}: {e}")

    return list(records_map.values())
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import json
import html
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

    # 最大30件取得のため、1〜2ページ目を巡回
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
                    if len(target_links) >= 30:
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

                # 1週間以上前のデータに達した瞬間に処理を完全終了する
                if pub_date < cutoff_date:
                    print(f"  ⏹️ 1週間以上前のデータ ({release_date_str}: {product_data.get('title')}) に達したため、処理を終了します。")
                    break

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

            # 3対象ジャンルのいずれにも該当しない場合はスキップ
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

            # --- 【class="itemTracksList" から data-files / data-names を抽出】 ---
            tracks = []
            audio_urls = []
            tracks_list_elem = detail_soup.select_one(".itemTracksList")

            if tracks_list_elem:
                raw_files = tracks_list_elem.get("data-files", "")
                raw_names = tracks_list_elem.get("data-names", "")

                try:
                    # HTMLエンティティのエスケープ解除（&quot; 等）
                    files_json_str = html.unescape(raw_files)
                    names_json_str = html.unescape(raw_names)

                    file_paths = json.loads(files_json_str) if files_json_str else []
                    track_names = json.loads(names_json_str) if names_json_str else []

                    # URLの補完処理 (\/\/teq-tokyo.com\... -> https://teq-tokyo.com/...)
                    for f_path in file_paths:
                        clean_path = f_path.replace("\\", "")  # エスケープ用バックスラッシュを除去
                        if clean_path.startswith("//"):
                            full_audio_url = "https:" + clean_path
                        elif clean_path.startswith("/"):
                            full_audio_url = urljoin(BASE_URL, clean_path)
                        else:
                            full_audio_url = clean_path

                        audio_urls.append(full_audio_url)

                    # トラックとURLのマッピング
                    for idx, url_val in enumerate(audio_urls):
                        t_name = track_names[idx] if idx < len(track_names) else f"Track {idx + 1}"
                        tracks.append({
                            "title": t_name,
                            "audio_url": url_val
                        })

                except Exception as parse_err:
                    print(f"  ⚠️ Tracks JSON解析エラー ({item_url}): {parse_err}")

            # 代表audio_url（A1などの最初のトラック音声）
            primary_audio_url = audio_urls[0] if audio_urls else ""

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
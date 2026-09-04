import os
import sys
import requests
from supabase import create_client, Client
from datetime import datetime, timezone, timedelta

# 各スクレイパーをモジュールとして読み込み
from scrapers.newtone import scrape_newtone
from scrapers.freestyle import scrape_freestyle

SUPABASE_URL = "https://slnraznxgatrefbuawqy.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SECRET_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not SUPABASE_KEY:
    print("❌ エラー: SUPABASE_SECRET_KEY が環境変数に設定されていません。")
    sys.exit(1)

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"❌ [Supabase初期化エラー] {e}")
    sys.exit(1)

def send_discord_notification(new_records):
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ DISCORD_WEBHOOK_URL が設定されていないため通知をスキップします。")
        return

    count = len(new_records)
    titles_str = "\n".join([f"・[{r.get('site', 'NEWTONE').upper()}] {r['title']}" for r in new_records])
    message = f"🎵 **新着レコードが {count} 件追加されました！（在庫あり）**\n\n{titles_str}"

    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        if res.status_code in [200, 204]:
            print(f"📲 Discord通知を送信しました: 新着レコード {count} 件")
    except Exception as e:
        print(f"❌ Discord通知エラー: {e}")

def cleanup_old_records(days=7):
    try:
        threshold_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        res = supabase.table("records").delete().lt("created_at", threshold_date).execute()
        deleted_count = len(res.data) if res.data else 0
        if deleted_count > 0:
            print(f"🧹 保持期間（{days}日間）を超えた古いデータ {deleted_count} 件を自動削除しました。")
    except Exception as e:
        print(f"⚠️ データ自動クリーニングエラー: {e}")

def main():
    existing_records = {}
    is_first_run = False
    try:
        res = supabase.table("records").select("item_url, created_at").execute()
        if res.data:
            existing_records = {r["item_url"].strip(): r.get("created_at") for r in res.data if r.get("item_url")}
        else:
            is_first_run = True
    except Exception as e:
        print(f"⚠️ 既存データの読み込みエラー: {e}")

    all_scraped_records = []

    # 1. NEWTONE 実行
    newtone_records = scrape_newtone(existing_records)
    all_scraped_records.extend(newtone_records)

    # 2. TEQ TOKYO (後でここに追加)

    # 3. FREESTYLE 実行
    freestyle_records = scrape_freestyle(existing_records)
    all_scraped_records.extend(freestyle_records)

    if all_scraped_records:
        try:
            # 新規かつ在庫ありのレコード（通知対象）の抽出
            notifiable_records = [
                r for r in all_scraped_records 
                if r["item_url"] not in existing_records and not r["is_sold_out"]
            ]
            
            # Supabase へ保存 (item_url をキーに更新/追加)
            supabase.table("records").upsert(all_scraped_records, on_conflict="item_url").execute()
            print(f"\n🎉 全サイトのデータベース書き込み完了！（取得総数: {len(all_scraped_records)}件）")
            
            # クリーニングの実行
            cleanup_old_records(days=7)

            # 通知処理
            if not is_first_run and len(notifiable_records) > 0:
                send_discord_notification(notifiable_records)
            else:
                print("ℹ️ 在庫ありの新規追加盤がないため、Discord通知をスキップしました。")

        except Exception as e:
            print(f"  ❌ Supabase保存エラー: {e}")

if __name__ == "__main__":
    main()
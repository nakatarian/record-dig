// ==========================================
// 1. Supabase 初期化設定
// ==========================================
const SUPABASE_URL = "https://slnraznxgatrefbuawqy.supabase.co";
// ★ anon public キーを設定してください
const SUPABASE_KEY = "sb_publishable_WpYhXPMuXpuCerFoAZtx7Q__8GcvJvS"; 

// ライブラリとの名前衝突を避けるため `supabaseClient` と命名
const supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY);

// グローバル変数
let allRecords = [];
let currentGenreFilter = 'ALL';
let currentSiteFilter = 'newtone'; // 初期表示は Newtone

// ==========================================
// 2. 日時・表示用フォーマット & ソート関数
// ==========================================

function sortRecordsByReleaseDate(records) {
  return records.sort((a, b) => {
    // 優先度①: release_date (日付 YYYY-MM-DD) の新しい順
    const dateA = a.release_date || "";
    const dateB = b.release_date || "";

    if (dateA !== dateB) {
      return dateB.localeCompare(dateA); // 降順
    }

    // 優先度②: created_at または scraped_at の「時間部分 (16:45等)」の新しい順
    const getTimeMinutes = (record) => {
      const targetStr = record.created_at || record.scraped_at || record.updated_at;
      if (!targetStr) return -1;
      const d = new Date(targetStr);
      if (isNaN(d.getTime())) return -1;
      return d.getHours() * 60 + d.getMinutes(); // 1日の経過分換算
    };

    const timeA = getTimeMinutes(a);
    const timeB = getTimeMinutes(b);

    if (timeA !== timeB) {
      return timeB - timeA; // 降順 (遅い時刻が上)
    }

    // 優先度③: サイト上の掲載順 (sort_order の昇順: 1, 2, 3...)
    // NULLや未定義の場合は一番後ろ（Infinity）にする
    const orderA = (a.sort_order !== null && a.sort_order !== undefined) ? Number(a.sort_order) : Infinity;
    const orderB = (b.sort_order !== null && b.sort_order !== undefined) ? Number(b.sort_order) : Infinity;

    return orderA - orderB; // 昇順
  });
}

function formatRecordDate(record) {
  // スクレイパー側で生成された updated_display があれば最優先で使用
  if (record.updated_display) {
    return record.updated_display;
  }

  // 従来通りのフォールバック処理
  let timeStr = "";
  if (record.created_at || record.scraped_at) {
    const dateObj = new Date(record.created_at || record.scraped_at);
    const hours = String(dateObj.getHours()).padStart(2, '0');
    const minutes = String(dateObj.getMinutes()).padStart(2, '0');
    timeStr = ` (${hours}:${minutes}更新)`;
  }
  
  const baseDate = record.release_date || "日付不明";
  return `${baseDate}${timeStr}`;
}

function getLatestScrapedTime(records) {
  if (!records || records.length === 0) return new Date().getTime();
  
  const latestIso = records.reduce((max, r) => {
    const scraped = r.scraped_at || r.created_at;
    return (scraped && scraped > max) ? scraped : max;
  }, records[0].scraped_at || records[0].created_at || new Date().toISOString());

  return new Date(latestIso).getTime();
}

function updateHeaderLastUpdated(records) {
  const updatedEl = document.getElementById('last-updated-text');
  if (!updatedEl || !records || records.length === 0) return;

  const latestScraped = records.reduce((max, r) => {
    const scraped = r.scraped_at || r.created_at;
    return (scraped && scraped > max) ? scraped : max;
  }, records[0].scraped_at || records[0].created_at || "");

  if (latestScraped) {
    const date = new Date(latestScraped);
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    const hh = String(date.getHours()).padStart(2, '0');
    const min = String(date.getMinutes()).padStart(2, '0');
    updatedEl.textContent = `更新日時: ${yyyy}/${mm}/${dd} ${hh}:${min}`;
  }
}

// ==========================================
// 3. データ取得 & レンダリング処理
// ==========================================

async function fetchRecords() {
  // Supabaseからデータ取得（全サイトのデータを十分カバーするため上限を500に拡張）
  let query = supabaseClient
    .from('records')
    .select('*')
    .order('release_date', { ascending: false, nullsFirst: false })
    .limit(500);

  const { data, error } = await query;
  
  if (error) {
    console.error('❌ データ取得エラー:', error);
    return;
  }

  // JS側で優先度①〜③を適用して確実にソート
  allRecords = sortRecordsByReleaseDate(data || []);
  applyFiltersAndRender();
  updateHeaderLastUpdated(allRecords);
}

function applyFiltersAndRender() {
  let filtered = [...allRecords];

  // 1. ジャンルフィルター
  if (currentGenreFilter !== 'ALL') {
    filtered = filtered.filter(r => {
      const genresList = r.genres && r.genres.length > 0 ? r.genres : [r.genre];
      return genresList.includes(currentGenreFilter);
    });
  }

  // 2. サイトフィルター (文字前後の余白を除去して比較)
  if (currentSiteFilter !== 'ALL') {
    const targetSiteFilter = currentSiteFilter.trim().toLowerCase();
    
    filtered = filtered.filter(r => {
      const recordSite = (r.site || '').trim().toLowerCase();
      // 'teq' や 'teq tokyo' や 't' などの表記揺れを吸収
      if (targetSiteFilter === 'teq' || targetSiteFilter === 't') {
        return recordSite === 'teq' || recordSite === 'teq tokyo' || recordSite === 't';
      }
      return recordSite === targetSiteFilter;
    });
  }

  renderRecords(filtered);
}

function renderRecords(records) {
  const container = document.getElementById('records-grid');
  if (!container) return;

  if (records.length === 0) {
    container.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-sub); padding: 40px 0;">該当するレコードはありません。</div>';
    return;
  }

  const latestScrapedTime = getLatestScrapedTime(allRecords);
  container.innerHTML = records.map(record => createRecordCard(record, latestScrapedTime)).join('');
}

function createRecordCard(record, latestScrapedTime) {
  const formattedMetaDate = formatRecordDate(record);
  const genresList = record.genres && record.genres.length > 0 ? record.genres : [record.genre];

  // ==========================================
  // NEWバッジ判定（created_at / scraped_at が現在時刻から24時間以内か）
  // ==========================================
  let isNew = false;
  const rawTimestamp = record.created_at || record.scraped_at;

  if (rawTimestamp) {
    const recordTime = new Date(rawTimestamp).getTime();
    const now = Date.now();

    if (!isNaN(recordTime)) {
      const diffInHours = (now - recordTime) / (1000 * 60 * 60);
      // DB格納日時が過去24時間以内（0 <= 時差 <= 24）であれば NEW
      isNew = diffInHours >= 0 && diffInHours <= 24;
    }
  }

  // ★ 入荷予定バッジ（存在する場合のみ表示）
  const upcomingBadgeHTML = (record.upcoming_arrival_date && !record.is_sold_out)
    ? `<span class="upcoming-badge">📅 ${record.upcoming_arrival_date} 入荷予定</span>`
    : '';

  return `
    <div class="card ${record.is_sold_out ? 'sold-out' : ''}" onclick="openModal('${record.id}')">
      <div class="image-wrapper">
        <img src="${record.image_url}" alt="${record.title}" loading="lazy" />
        ${isNew ? '<span class="new-badge">NEW</span>' : ''}
        ${record.is_sold_out ? '<span class="soldout-badge">SOLD OUT</span>' : ''}
        ${upcomingBadgeHTML}
      </div>
      <div class="card-content">
        <div class="genre-badges-container">
          ${genresList.map(g => `<span class="genre-badge">${g}</span>`).join('')}
        </div>
        <div class="record-title">${record.title}</div>
        <div class="record-meta">${formattedMetaDate}</div>
      </div>
    </div>
  `;
}

// ==========================================
// 4. フィルター切替処理
// ==========================================

function filterGenre(genre, btnElement) {
  currentGenreFilter = genre;
  
  const buttons = document.querySelectorAll('.category-filter .filter-btn');
  buttons.forEach(btn => btn.classList.remove('active'));
  if (btnElement) {
    btnElement.classList.add('active');
  }

  applyFiltersAndRender();
}

function filterSite(siteName, btnElement) {
  currentSiteFilter = siteName;

  const buttons = document.querySelectorAll('.site-filter .site-filter-btn');
  buttons.forEach(btn => btn.classList.remove('active'));
  if (btnElement) {
    btnElement.classList.add('active');
  }

  applyFiltersAndRender();
}

// ==========================================
// 5. モーダル（試聴・詳細表示）制御処理
// ==========================================
function openModal(recordId) {
  const record = allRecords.find(r => String(r.id) === String(recordId));
  if (!record) return;

  const modal = document.getElementById('player-modal');
  const coverImg = document.getElementById('modal-cover');
  const genreContainer = document.getElementById('modal-genre-container');
  const titleEl = document.getElementById('modal-title');
  const catEl = document.getElementById('modal-cat');
  const dateEl = document.getElementById('modal-date');
  const externalLink = document.getElementById('modal-external-link');
  const tracksContainer = document.getElementById('modal-tracks-container');

  if (coverImg) coverImg.src = record.image_url || '';
  if (titleEl) titleEl.textContent = record.title || '';
  if (catEl) catEl.textContent = record.cat_no ? `Cat No: ${record.cat_no}` : '';
  if (dateEl) dateEl.textContent = formatRecordDate(record);
  if (externalLink) externalLink.href = record.item_url || '#';

  if (genreContainer) {
    const genresList = record.genres && record.genres.length > 0 ? record.genres : [record.genre];
    genreContainer.innerHTML = genresList.map(g => `<span class="genre-badge">${g}</span>`).join('');
  }

  if (tracksContainer) {
    const tracks = record.tracks || [];
    const siteLower = (record.site || '').toLowerCase();
    let html = '';

    // 【パターンA】Freestyle のみ（1音声ファイル ＋ トラックリストテキスト）
    if (siteLower === 'freestyle') {
      if (record.audio_url) {
        html += `
          <div class="main-audio-player" style="margin-bottom: 16px; padding: 12px; background: rgba(255,255,255,0.05); border-radius: 8px;">
            <div style="font-size: 12px; color: var(--text-sub); margin-bottom: 6px; font-weight: bold;">🔊 Listen Sample (Full)</div>
            <audio controls src="${record.audio_url}" style="width: 100%;"></audio>
          </div>
        `;
      }

      if (tracks.length > 0) {
        html += `<div class="track-list-text" style="display: flex; flex-direction: column; gap: 6px;">`;
        tracks.forEach(track => {
          html += `
            <div class="track-title-only" style="font-size: 13px; color: var(--text-main, #e0e0e0); font-family: monospace; padding: 4px 8px; background: rgba(255,255,255,0.02); border-radius: 4px;">
              ${track.title}
            </div>
          `;
        });
        html += `</div>`;
      } else if (!record.audio_url) {
        html = '<div style="color: var(--text-sub); font-size: 12px;">試聴音源・トラック情報はありません。</div>';
      }
    } 
    // 【パターンB】Newtone & TEQ TOKYO（各トラックごとに個別音声プレイヤーを表示）
    else {
      if (tracks.length > 0) {
        html = tracks.map(track => {
          const currentAudioUrl = track.audio_url || record.audio_url || '';
          return `
            <div class="track-item" style="margin-bottom: 12px;">
              <div class="track-name" style="font-size: 13px; margin-bottom: 4px; font-weight: 500;">${track.title}</div>
              ${
                currentAudioUrl 
                  ? `<audio class="track-audio" controls src="${currentAudioUrl}" preload="none" style="width: 100%;"></audio>` 
                  : '<div style="font-size: 11px; color: var(--text-sub);">試聴音源なし</div>'
              }
            </div>
          `;
        }).join('');
      } else if (record.audio_url) {
        html = `
          <div class="track-item">
            <div class="track-name">Sample Track</div>
            <audio class="track-audio" controls src="${record.audio_url}" style="width: 100%;"></audio>
          </div>
        `;
      } else {
        html = '<div style="color: var(--text-sub); font-size: 12px;">試聴音源はありません。</div>';
      }
    }

    tracksContainer.innerHTML = html;
  }

  if (modal) modal.classList.add('active');
}

function closeModal(event) {
  const modal = document.getElementById('player-modal');
  if (modal) {
    modal.classList.remove('active');
    
    const audioElements = modal.querySelectorAll('audio');
    audioElements.forEach(audio => {
      audio.pause();
      audio.currentTime = 0;
    });
  }
}

// ==========================================
// 6. ページ読み込み時 初期実行
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
  fetchRecords();
});
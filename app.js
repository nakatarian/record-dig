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
    // 1優先: release_date (更新日付 YYYY-MM-DD) の新しい順
    const dateA = a.release_date || "";
    const dateB = b.release_date || "";

    if (dateA !== dateB) {
      return dateB.localeCompare(dateA); // 降順 (新しい日付が上)
    }

    // 2優先: scraped_at または created_at (取得・更新時刻) の新しい順
    const timeA = new Date(a.scraped_at || a.created_at || a.updated_at || 0).getTime();
    const timeB = new Date(b.scraped_at || b.created_at || b.updated_at || 0).getTime();

    return timeB - timeA; // 降順 (新しい時刻が上)
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
  // Supabaseから release_date(降順) -> scraped_at(降順) で取得
  let query = supabaseClient
    .from('records')
    .select('*')
    .order('release_date', { ascending: false, nullsFirst: false })
    .order('scraped_at', { ascending: false, nullsFirst: false })
    .limit(150);

  const { data, error } = await query;
  
  if (error) {
    console.error('❌ データ取得エラー:', error);
    return;
  }

  // JS側でも念のため二重ソートをかけて確実に整列
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

  // 2. サイトフィルター
  if (currentSiteFilter !== 'ALL') {
    filtered = filtered.filter(r => (r.site || '').toLowerCase() === currentSiteFilter.toLowerCase());
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
  // release_date(日付) + scraped_at(時刻) で24時間以内か判定
  // ==========================================
  let isNew = false;

  if (record.release_date) {
    // 時刻ソースを取得（scraped_at > created_at > updated_at の順）
    const timeSource = record.scraped_at || record.created_at || record.updated_at;
    
    let hours = '00';
    let minutes = '00';
    let seconds = '00';

    if (timeSource) {
      const timeObj = new Date(timeSource);
      if (!isNaN(timeObj.getTime())) {
        hours = String(timeObj.getHours()).padStart(2, '0');
        minutes = String(timeObj.getMinutes()).padStart(2, '0');
        seconds = String(timeObj.getSeconds()).padStart(2, '0');
      }
    }

    // release_date (YYYY-MM-DD) と scraped_at の時刻 (HH:mm:ss) を合成
    const cleanDateStr = record.release_date.replace(/\//g, '-');
    const combinedIsoStr = `${cleanDateStr}T${hours}:${minutes}:${seconds}`;
    const recordTime = new Date(combinedIsoStr).getTime();

    // 現在時刻（Date.now()）との差分を時間単位で計算
    if (!isNaN(recordTime)) {
      const now = Date.now();
      const diffInHours = (now - recordTime) / (1000 * 60 * 60);

      // 合成日時が過去24時間以内（0 <= diff <= 24）であれば NEW マークを表示
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
    const isFreestyle = (record.site || '').toLowerCase() === 'freestyle';
    let html = '';

    // 【パターンA】Freestyle（1音声ファイル ＋ トラックリストテキスト）
    if (isFreestyle) {
      // 1. 全曲共通の試聴プレイヤーを一番上に表示
      if (record.audio_url) {
        html += `
          <div class="main-audio-player" style="margin-bottom: 16px; padding: 12px; background: rgba(255,255,255,0.05); border-radius: 8px;">
            <div style="font-size: 12px; color: var(--text-sub); margin-bottom: 6px; font-weight: bold;">🔊 Listen Sample (Full)</div>
            <audio controls src="${record.audio_url}" style="width: 100%;"></audio>
          </div>
        `;
      }

      // 2. トラックリスト（A1, A2...などのテキスト）を一覧表示
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
    // 【パターンB】Newtone（各トラックごとに個別音声ファイル）
    else {
      if (tracks.length > 0) {
        html = tracks.map(track => `
          <div class="track-item" style="margin-bottom: 10px;">
            <div class="track-name" style="font-size: 13px; margin-bottom: 4px;">${track.title}</div>
            <audio class="track-audio" controls src="${track.audio_url}" preload="none" style="width: 100%;"></audio>
          </div>
        `).join('');
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
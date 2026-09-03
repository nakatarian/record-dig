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
let currentFilter = 'ALL';

// ==========================================
// 2. 日時・表示用フォーマット & ソート関数
// ==========================================

/**
 * リリース日付（2026-09-03等）を最優先にし、同じ日付内では追加・更新時間順に並び替える
 */
function sortRecordsByReleaseDate(records) {
  return records.sort((a, b) => {
    // 1. release_date (例: "2026-09-03") の比較 (降順: 新しい順)
    const dateA = a.release_date || "";
    const dateB = b.release_date || "";

    if (dateA !== dateB) {
      return dateB.localeCompare(dateA);
    }

    // 2. release_date が同じ場合は created_at または scraped_at の時間で比較 (降順)
    const timeA = new Date(a.created_at || a.scraped_at || 0).getTime();
    const timeB = new Date(b.created_at || b.scraped_at || 0).getTime();

    return timeB - timeA;
  });
}

/**
 * リリリース日付と初回取得時間から「YYYY-MM-DD (HH:mm更新)」の文字列を作る
 */
function formatRecordDate(releaseDate, createdAtIso) {
  let timeStr = "";
  if (createdAtIso) {
    const dateObj = new Date(createdAtIso);
    const hours = String(dateObj.getHours()).padStart(2, '0');
    const minutes = String(dateObj.getMinutes()).padStart(2, '0');
    timeStr = ` (${hours}:${minutes}更新)`;
  }
  
  const baseDate = releaseDate || "日付不明";
  return `${baseDate}${timeStr}`;
}

/**
 * レコードの最新 scraped_at（全体の最終更新日時）を取得する
 */
function getLatestScrapedTime(records) {
  if (!records || records.length === 0) return new Date().getTime();
  
  const latestIso = records.reduce((max, r) => {
    return (r.scraped_at > max) ? r.scraped_at : max;
  }, records[0].scraped_at);

  return new Date(latestIso).getTime();
}

/**
 * 画面右上の最終更新日時（最新の scraped_at）を更新表示する
 */
function updateHeaderLastUpdated(records) {
  const updatedEl = document.getElementById('last-updated-text');
  if (!updatedEl || !records || records.length === 0) return;

  const latestScraped = records.reduce((max, r) => {
    return (r.scraped_at > max) ? r.scraped_at : max;
  }, records[0].scraped_at);

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

async function fetchRecords(genre = 'ALL') {
  currentFilter = genre;
  
  // release_date と created_at の組み合わせで並び替えを指定して取得
  let query = supabaseClient
    .from('records')
    .select('*')
    .order('release_date', { ascending: false, nullsFirst: false })
    .order('created_at', { ascending: false })
    .limit(50);

  if (genre !== 'ALL') {
    query = query.contains('genres', [genre]);
  }

  const { data, error } = await query;
  
  if (error) {
    console.error('❌ データ取得エラー:', error);
    return;
  }

  allRecords = sortRecordsByReleaseDate(data || []);
  renderRecords(allRecords);
  updateHeaderLastUpdated(allRecords);
}

function renderRecords(records) {
  const container = document.getElementById('records-grid');
  if (!container) return;

  if (records.length === 0) {
    container.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-sub); padding: 40px 0;">該当するレコードはありません。</div>';
    return;
  }

  // Record Dig の最新更新時間を基準として取得
  const latestScrapedTime = getLatestScrapedTime(allRecords);

  container.innerHTML = records.map(record => createRecordCard(record, latestScrapedTime)).join('');
}

function createRecordCard(record, latestScrapedTime) {
  const formattedMetaDate = formatRecordDate(record.release_date, record.created_at);
  const genresList = record.genres && record.genres.length > 0 ? record.genres : [record.genre];

  // 【24時間以内判定】
  // Record Digの最新更新時間から、アイテムの追加時間(created_at)が24時間以内（86,400,000ミリ秒）か判定
  const createdAtTime = new Date(record.created_at || record.scraped_at).getTime();
  const isNew = (latestScrapedTime - createdAtTime) <= (24 * 60 * 60 * 1000);

  return `
    <div class="card ${record.is_sold_out ? 'sold-out' : ''}" onclick="openModal('${record.id}')">
      <div class="image-wrapper">
        <img src="${record.image_url}" alt="${record.title}" loading="lazy" />
        ${isNew ? '<span class="new-badge">NEW</span>' : ''}
        ${record.is_sold_out ? '<span class="soldout-badge">SOLD OUT</span>' : ''}
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
// 4. ジャンルフィルター切替処理
// ==========================================
function filterGenre(genre, btnElement) {
  const buttons = document.querySelectorAll('.filter-btn');
  buttons.forEach(btn => btn.classList.remove('active'));
  if (btnElement) {
    btnElement.classList.add('active');
  }

  fetchRecords(genre);
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
  if (dateEl) dateEl.textContent = formatRecordDate(record.release_date, record.created_at);
  if (externalLink) externalLink.href = record.item_url || '#';

  if (genreContainer) {
    const genresList = record.genres && record.genres.length > 0 ? record.genres : [record.genre];
    genreContainer.innerHTML = genresList.map(g => `<span class="genre-badge">${g}</span>`).join('');
  }

  if (tracksContainer) {
    const tracks = record.tracks || [];
    if (tracks.length === 0 && record.audio_url) {
      tracksContainer.innerHTML = `
        <div class="track-item">
          <div class="track-name">Sample Track</div>
          <audio class="track-audio" controls src="${record.audio_url}"></audio>
        </div>
      `;
    } else if (tracks.length > 0) {
      tracksContainer.innerHTML = tracks.map(track => `
        <div class="track-item">
          <div class="track-name">${track.title}</div>
          <audio class="track-audio" controls src="${track.audio_url}" preload="none"></audio>
        </div>
      `).join('');
    } else {
      tracksContainer.innerHTML = '<div style="color: var(--text-sub); font-size: 12px;">試聴音源はありません。</div>';
    }
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
  fetchRecords('ALL');
});
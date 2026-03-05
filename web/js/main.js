import { buildConfig } from './config.js';
import { MIDNIGHT_MS, parseTimestamp } from './utils.js';
import { buildConversationItem, buildConversationView } from './ui.js';
import { initAudioPlayers, stopAllAudioPlayers } from './audio-player.js';
import { buildMediaList, openLightbox, closeLightbox, navigateLightbox } from './lightbox.js';
import { initDatePicker, openDatePicker, closeDatePicker, updatePickerCurrentDay } from './date-picker.js';

let vjsPlayers = {};
let currentDay = '';

const NO_SELECTION_HTML = `<div id="no-selection" class="flex-1 flex items-center justify-center flex-col text-text-tertiary">
  <div class="text-6xl mb-4 opacity-50">💬</div>
  <div class="text-lg font-medium">Select a conversation to view</div>
</div>`;

function captureFirstFrame(player) {
  const video = player.el().querySelector('video');
  if (!video) return;
  const draw = () => {
    if (!video.videoWidth || !video.videoHeight) return;
    const c = document.createElement('canvas');
    c.width = video.videoWidth;
    c.height = video.videoHeight;
    c.getContext('2d').drawImage(video, 0, 0);
    try { player.poster(c.toDataURL('image/jpeg', 0.85)); } catch (_) {}
  };
  if (video.readyState >= 2) draw();
  else player.one('loadeddata', draw);
}

function initVideoPlayers() {
  document.querySelectorAll('video.video-js:not([data-vjs-init])').forEach(el => {
    if (!el.id) return;
    const p = videojs.getPlayer(el.id) || videojs(el.id, { controls: true, preload: 'auto' });
    if (!p) return;
    vjsPlayers[el.id] = p;
    el.setAttribute('data-vjs-init', '1');
    captureFirstFrame(p);
  });
}

function teardown() {
  Object.values(vjsPlayers).forEach(p => { try { p.dispose(); } catch (_) {} });
  vjsPlayers = {};
  stopAllAudioPlayers();
  closeLightbox();
  document.getElementById('conversation-list').innerHTML = '';
  document.getElementById('right-panel').innerHTML = NO_SELECTION_HTML;
}

function renderApp(headerConfig, conversationConfig, prevDay, nextDay) {
  // 1. Setup Header
  currentDay = headerConfig.date;
  updatePickerCurrentDay(currentDay);
  const dateObj = new Date(headerConfig.date + "T12:00:00");
  document.getElementById("header-date").textContent = dateObj.toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
  document.getElementById("header-conversations").textContent = `${headerConfig.conversations} conversations`;
  document.getElementById("header-messages").textContent      = `${headerConfig.messages} messages`;
  document.getElementById("header-media").textContent         = `${headerConfig.media} media`;

  // 2. Wire up day navigation
  const prevBtn = document.querySelector('[aria-label="Previous day"]');
  const nextBtn = document.querySelector('[aria-label="Next day"]');

  // Reset button state
  prevBtn.disabled = false; prevBtn.style.opacity = ''; prevBtn.style.cursor = '';
  nextBtn.disabled = false; nextBtn.style.opacity = ''; nextBtn.style.cursor = '';
  // Clone to remove old listeners
  const newPrev = prevBtn.cloneNode(true);
  const newNext = nextBtn.cloneNode(true);
  prevBtn.replaceWith(newPrev);
  nextBtn.replaceWith(newNext);

  if (prevDay) {
    newPrev.addEventListener('click', () => loadDay(prevDay));
  } else {
    newPrev.disabled = true;
    newPrev.style.opacity = '0.35';
    newPrev.style.cursor = 'default';
  }
  if (nextDay) {
    newNext.addEventListener('click', () => loadDay(nextDay));
  } else {
    newNext.disabled = true;
    newNext.style.opacity = '0.35';
    newNext.style.cursor = 'default';
  }

  // 3. Sort and Setup Conversations
  const list = document.getElementById("conversation-list");
  const sortedConfigs = [...conversationConfig].sort((a, b) =>
    (MIDNIGHT_MS - parseTimestamp(a.timestamp)) - (MIDNIGHT_MS - parseTimestamp(b.timestamp))
  );

  if (list) {
    list.innerHTML = sortedConfigs.map(buildConversationItem).join("\n");
  }

  // 4. Inject Conversation Views
  const rightPanel = document.getElementById("right-panel");
  sortedConfigs.forEach((cfg, i) => {
    rightPanel.insertAdjacentHTML("beforeend", buildConversationView(cfg, i));
  });

  // 5. Initialize Media
  initVideoPlayers();
  initAudioPlayers();

  // 6. Sidebar Navigation Listeners
  const noSelection  = document.getElementById("no-selection");
  const allViews     = rightPanel.querySelectorAll(".conversation-view");
  const sidebarItems = list ? list.querySelectorAll("[role='button']") : [];

  sidebarItems.forEach((item, i) => {
    item.addEventListener("click", () => {
      noSelection.style.display = "none";
      allViews.forEach(v => { v.style.display = "none"; });
      const target = rightPanel.querySelector(`.conversation-view[data-index="${i}"]`);
      if (target) target.style.display = "flex";
    });
  });

  // 7. Lightbox Triggers (re-bound each render via event delegation on document — already set up once)
  // Store sortedConfigs for lightbox trigger handler
  document._sortedConfigs = sortedConfigs;
}

async function loadDay(dateStr) {
  const loader = document.getElementById('day-loading');
  loader.style.display = 'flex';
  try {
    const mod = await import(`../days/${dateStr}.js`);
    const { headerConfig, conversationConfig, prevDay, nextDay } = buildConfig(mod.json);
    teardown();
    renderApp(headerConfig, conversationConfig, prevDay, nextDay);
    history.replaceState(null, '', '#' + dateStr);
  } catch (err) {
    console.error('Failed to load day:', err);
  } finally {
    loader.style.display = 'none';
  }
}

function setupStaticListeners() {
  // Dashboard button
  const dashBtn = document.querySelector('[aria-label="Return to Dashboard"]');
  if (dashBtn) {
    dashBtn.addEventListener('click', () => { window.location.href = 'dashboard.html'; });
  }

  // Date picker trigger
  const headerDate = document.getElementById('header-date');
  if (headerDate) {
    headerDate.addEventListener('click', () => openDatePicker(currentDay));
    headerDate.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') openDatePicker(currentDay); });
  }

  // Lightbox Triggers (delegated — fires for any day's content)
  document.addEventListener('click', e => {
    const trigger = e.target.closest('.media-trigger');
    if (!trigger) return;
    Object.values(vjsPlayers).forEach(p => { try { p.pause(); } catch (_) {} });
    const convIndex = parseInt(trigger.dataset.convIndex, 10);
    const mediaSeq  = parseInt(trigger.dataset.mediaSeq, 10);
    const list = buildMediaList(convIndex, document._sortedConfigs || []);
    openLightbox(list, mediaSeq);
  });

  // Lightbox UI Controls
  document.getElementById('lightbox-close').addEventListener('click', closeLightbox);
  document.getElementById('lightbox-prev').addEventListener('click', () => navigateLightbox(-1));
  document.getElementById('lightbox-next').addEventListener('click', () => navigateLightbox(1));
  document.getElementById('lightbox').addEventListener('click', e => {
    if (e.target === document.getElementById('lightbox')) closeLightbox();
  });

  // Keyboard Shortcuts
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      if (document.getElementById('date-picker').style.display !== 'none') { closeDatePicker(); return; }
      if (document.getElementById('lightbox').classList.contains('open')) closeLightbox();
    }
    if (!document.getElementById('lightbox').classList.contains('open')) return;
    if (e.key === 'ArrowLeft')   navigateLightbox(-1);
    if (e.key === 'ArrowRight')  navigateLightbox(1);
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  setupStaticListeners();

  // Load manifest — fetch resolves relative to document (output/index.html)
  let days = [];
  try {
    const { index } = await import('../days/index.js');
    days = index.days;
  } catch (err) {
    console.error('Failed to load day manifest:', err);
    return;
  }

  if (!days.length) {
    console.error('No days found in manifest.');
    return;
  }

  initDatePicker(days, dateStr => loadDay(dateStr));

  // Determine initial day from hash, fallback to latest
  const hash = location.hash.slice(1);
  const initial = (hash && days.includes(hash)) ? hash : days[days.length - 1];
  await loadDay(initial);

  // Hash-based navigation (browser back/forward)
  window.addEventListener('hashchange', () => {
    const day = location.hash.slice(1);
    if (day && days.includes(day)) loadDay(day);
  });
});

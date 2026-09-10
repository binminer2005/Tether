document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.waveform').forEach(function (wf) {
    const bars = 22;
    for (let i = 0; i < bars; i++) {
      const bar = document.createElement('span');
      const h = 6 + Math.round(Math.sin(i * 1.3) * 10 + Math.random() * 8 + 10);
      bar.style.height = h + 'px';
      wf.appendChild(bar);
    }
  });

  const toggle = document.querySelector('.menu-toggle');
  const nav = document.querySelector('.main-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      nav.classList.toggle('nav-open');
      toggle.setAttribute('aria-expanded', nav.classList.contains('nav-open') ? 'true' : 'false');
    });
  }

  const searchForm = document.querySelector('.nav-search');
  const searchInput = searchForm ? searchForm.querySelector('input') : null;
  const searchButton = searchForm ? searchForm.querySelector('button') : null;
  if (searchForm && searchInput && searchButton) {
    searchButton.addEventListener('click', function (event) {
      if (!searchForm.classList.contains('is-open')) {
        event.preventDefault();
        searchForm.classList.add('is-open');
        searchInput.focus();
      }
    });
    searchInput.addEventListener('blur', function () {
      if (!searchInput.value.trim()) searchForm.classList.remove('is-open');
    });
  }

  const player = document.querySelector('[data-audio-player]');
  const audio = document.querySelector('[data-audio-element]');
  if (!player || !audio) return;

  const playerTitle = player.querySelector('[data-player-title]');
  const playerKind = player.querySelector('[data-player-kind]');
  const playerProgress = player.querySelector('[data-player-progress]');
  const playerSeek = player.querySelector('[data-player-seek]');
  const playerCurrent = player.querySelector('[data-player-current]');
  const playerDuration = player.querySelector('[data-player-duration]');
  const togglePlayer = player.querySelector('[data-player-toggle]');
  const previousEpisode = player.querySelector('[data-player-prev]');
  const nextEpisode = player.querySelector('[data-player-next]');
  const episodeKindLabels = { radio: 'Radio', podcast: 'Podcast' };
  const playerStorageKey = 'tether_audio_player_state';
  let activeEpisode = null;

  function bindEpisodeControls() {
    document.querySelectorAll('[data-play-episode]').forEach(function (control) {
      if (control.dataset.playerBound) return;
      control.dataset.playerBound = 'true';
      control.addEventListener('click', function (event) {
        event.preventDefault();
        const row = control.closest('[data-episode]');
        if (row) selectEpisode(row);
      });
    });

    document.querySelectorAll('[data-episode][data-detail-url]').forEach(function (row) {
      if (row.dataset.playerBound) return;
      row.dataset.playerBound = 'true';
      row.addEventListener('click', function (event) {
        if (event.target.closest('[data-play-episode]')) return;
        navigateWithPlayer(row.dataset.detailUrl);
      });
    });
  }

  function navigateWithPlayer(url) {
    persistPlayerState();
    fetch(url, { headers: { 'X-Requested-With': 'Tether-Navigation' } })
      .then(function (response) {
        if (!response.ok) throw new Error('Navigation failed');
        return response.text();
      })
      .then(function (html) {
        const nextDocument = new DOMParser().parseFromString(html, 'text/html');
        const nextMain = nextDocument.querySelector('main');
        const currentMain = document.querySelector('main');
        if (!nextMain || !currentMain) throw new Error('Page content unavailable');
        currentMain.innerHTML = nextMain.innerHTML;
        document.title = nextDocument.title;
        window.history.pushState({}, '', url);
        nextMain.querySelectorAll('script').forEach(function (sourceScript) {
          const script = document.createElement('script');
          script.textContent = sourceScript.textContent;
          document.body.appendChild(script);
          script.remove();
        });
        bindEpisodeControls();
        document.querySelectorAll('.waveform').forEach(function (waveform) {
          if (waveform.children.length) return;
          for (let i = 0; i < 22; i++) {
            const bar = document.createElement('span');
            bar.style.height = (6 + Math.round(Math.sin(i * 1.3) * 10 + Math.random() * 8 + 10)) + 'px';
            waveform.appendChild(bar);
          }
        });
        window.scrollTo(0, 0);
      })
      .catch(function () { window.location.href = url; });
  }

  function formatTime(time) {
    if (!Number.isFinite(time) || time < 0) return '0:00';
    const totalSeconds = Math.floor(time);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) return hours + ':' + String(minutes).padStart(2, '0') + ':' + String(seconds).padStart(2, '0');
    return minutes + ':' + String(seconds).padStart(2, '0');
  }

  function updateProgress() {
    const duration = audio.duration;
    const currentTime = audio.currentTime;
    const percentage = Number.isFinite(duration) && duration > 0 ? currentTime / duration * 100 : 0;
    playerProgress.style.width = percentage + '%';
    playerCurrent.textContent = formatTime(currentTime);
    playerDuration.textContent = formatTime(duration);
    playerSeek.setAttribute('aria-valuemax', Number.isFinite(duration) ? String(Math.floor(duration)) : '0');
    playerSeek.setAttribute('aria-valuenow', Number.isFinite(currentTime) ? String(Math.floor(currentTime)) : '0');
    playerSeek.setAttribute('aria-valuetext', formatTime(currentTime) + ' / ' + formatTime(duration));
  }

  function showPlayer() {
    player.hidden = false;
    player.classList.add('is-visible');
  }

  function updatePlayerButton() {
    const isPlaying = !audio.paused;
    togglePlayer.textContent = isPlaying ? '||' : '▶';
    togglePlayer.setAttribute('aria-label', isPlaying ? 'Tạm dừng' : 'Phát');
    player.classList.toggle('is-playing', isPlaying);
  }

  function playAudio() {
    const playback = audio.play();
    if (playback && typeof playback.catch === 'function') {
      playback.catch(function (error) {
        updatePlayerButton();
        playerKind.textContent = 'Không thể phát bản thu';
        console.error('Không thể phát audio:', error);
      });
    }
  }

  function persistPlayerState() {
    const payload = {
      visible: !player.hidden,
      title: playerTitle.textContent,
      kind: activeEpisode ? activeEpisode.dataset.kind : null,
      audio: activeEpisode && activeEpisode.dataset.audio ? activeEpisode.dataset.audio : (audio.currentSrc || audio.src || ''),
      isPlaying: !audio.paused,
    };
    localStorage.setItem(playerStorageKey, JSON.stringify(payload));
  }

  function restorePlayerState() {
    try {
      const rawState = localStorage.getItem(playerStorageKey);
      if (!rawState) return;
      const state = JSON.parse(rawState);
      if (!state || !state.audio) return;
      showPlayer();
      playerTitle.textContent = state.title || 'Đang nghe';
      playerKind.textContent = episodeKindLabels[state.kind] || 'Đang nghe';
      audio.src = state.audio;
      if (state.isPlaying) {
        playAudio();
      }
      updatePlayerButton();
    } catch (error) {
      localStorage.removeItem(playerStorageKey);
    }
  }

  function selectEpisode(row) {
    activeEpisode = row;
    showPlayer();
    playerTitle.textContent = row.dataset.title;
    playerKind.textContent = episodeKindLabels[row.dataset.kind] || 'Đang nghe';
    updateProgress();
    audio.pause();
    audio.removeAttribute('src');
    if (row.dataset.audio) {
      audio.src = row.dataset.audio;
      audio.volume = 1;
      playAudio();
    } else {
      playerKind.textContent += ' · Bản thu đang được chuẩn bị';
    }
    updatePlayerButton();
    persistPlayerState();
  }

  bindEpisodeControls();

  document.addEventListener('click', function (event) {
    const link = event.target.closest('a[href]');
    if (!link || !audio.src || link.target || link.hasAttribute('download') || link.href.startsWith('javascript:')) return;
    const linkUrl = new URL(link.href, window.location.href);
    if (linkUrl.origin !== window.location.origin || linkUrl.pathname === '/dang-xuat' || (linkUrl.hash && linkUrl.pathname === window.location.pathname)) return;
    event.preventDefault();
    navigateWithPlayer(linkUrl.href);
  });

  window.addEventListener('popstate', function () {
    if (audio.src) navigateWithPlayer(window.location.href);
    else window.location.reload();
  });

  togglePlayer.addEventListener('click', function () {
    if (!activeEpisode || !activeEpisode.dataset.audio) return;
    if (audio.paused) playAudio();
    else audio.pause();
  });

  function selectAdjacentEpisode(direction) {
    if (!activeEpisode) return;
    const episodes = Array.from(document.querySelectorAll('[data-episode][data-kind="' + activeEpisode.dataset.kind + '"]'));
    const currentIndex = episodes.indexOf(activeEpisode);
    const nextIndex = currentIndex + direction;
    if (episodes[nextIndex]) selectEpisode(episodes[nextIndex]);
  }

  previousEpisode.addEventListener('click', function () {
    selectAdjacentEpisode(-1);
  });
  nextEpisode.addEventListener('click', function () {
    selectAdjacentEpisode(1);
  });

  function seekToPosition(position) {
    if (!Number.isFinite(audio.duration) || audio.duration <= 0) return;
    const bounds = playerSeek.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (position - bounds.left) / bounds.width));
    audio.currentTime = ratio * audio.duration;
    updateProgress();
  }

  playerSeek.addEventListener('pointerdown', function (event) {
    event.preventDefault();
    seekToPosition(event.clientX);
  });
  playerSeek.addEventListener('keydown', function (event) {
    if (!Number.isFinite(audio.duration) || audio.duration <= 0) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      audio.currentTime = Math.min(audio.duration, Math.max(0, audio.currentTime + (event.key === 'ArrowRight' ? 5 : -5)));
      updateProgress();
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      audio.currentTime = event.key === 'Home' ? 0 : audio.duration;
      updateProgress();
    }
  });

  player.querySelector('[data-player-close]').addEventListener('click', function () {
    audio.pause();
    player.hidden = true;
    player.classList.remove('is-playing');
    playerTitle.textContent = 'Chưa chọn tập';
    playerKind.textContent = 'Đang nghe';
    updateProgress();
    activeEpisode = null;
    localStorage.removeItem(playerStorageKey);
  });

  audio.addEventListener('timeupdate', function () {
    updateProgress();
  });
  audio.addEventListener('loadedmetadata', updateProgress);
  audio.addEventListener('durationchange', updateProgress);
  audio.addEventListener('play', function () {
    updatePlayerButton();
    persistPlayerState();
  });
  audio.addEventListener('pause', function () {
    updatePlayerButton();
    persistPlayerState();
  });
  audio.addEventListener('error', function () {
    updatePlayerButton();
    playerKind.textContent = 'Không thể tải bản thu';
    console.error('Không thể tải audio:', audio.error);
  });

  playerTitle.textContent = 'Chưa chọn tập';
  playerKind.textContent = 'Đang nghe';
  updateProgress();
});

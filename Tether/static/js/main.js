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
    });
  }

  const player = document.querySelector('[data-audio-player]');
  const audio = document.querySelector('[data-audio-element]');
  if (!player || !audio) return;

  const playerTitle = player.querySelector('[data-player-title]');
  const playerKind = player.querySelector('[data-player-kind]');
  const playerProgress = player.querySelector('[data-player-progress]');
  const togglePlayer = player.querySelector('[data-player-toggle]');
  const previousEpisode = player.querySelector('[data-player-prev]');
  const nextEpisode = player.querySelector('[data-player-next]');
  const episodeKindLabels = { radio: 'Radio', podcast: 'Podcast' };
  let activeEpisode = null;

  function updatePlayerButton() {
    const isPlaying = !audio.paused;
    togglePlayer.textContent = isPlaying ? 'Ⅱ' : '▶';
    togglePlayer.setAttribute('aria-label', isPlaying ? 'Tạm dừng' : 'Phát');
    player.classList.toggle('is-playing', isPlaying);
  }

  function selectEpisode(row) {
    activeEpisode = row;
    player.hidden = false;
    playerTitle.textContent = row.dataset.title;
    playerKind.textContent = episodeKindLabels[row.dataset.kind] || 'Đang nghe';
    playerProgress.style.width = '0%';
    audio.pause();
    audio.removeAttribute('src');
    if (row.dataset.audio) {
      audio.src = row.dataset.audio;
      audio.play().catch(function () {});
    } else {
      playerKind.textContent += ' · Bản thu đang được chuẩn bị';
    }
    updatePlayerButton();
  }

  document.querySelectorAll('[data-play-episode]').forEach(function (control) {
    control.addEventListener('click', function (event) {
      event.preventDefault();
      const row = control.closest('[data-episode]');
      if (row) selectEpisode(row);
    });
  });

  document.querySelectorAll('[data-episode][data-detail-url]').forEach(function (row) {
    row.addEventListener('click', function (event) {
      if (event.target.closest('[data-play-episode]')) return;
      window.location.href = row.dataset.detailUrl;
    });
  });

  togglePlayer.addEventListener('click', function () {
    if (!activeEpisode || !activeEpisode.dataset.audio) return;
    if (audio.paused) audio.play().catch(function () {});
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

  player.querySelector('[data-player-close]').addEventListener('click', function () {
    audio.pause();
    player.hidden = true;
    activeEpisode = null;
  });

  audio.addEventListener('timeupdate', function () {
    if (audio.duration) playerProgress.style.width = (audio.currentTime / audio.duration * 100) + '%';
  });
  audio.addEventListener('play', updatePlayerButton);
  audio.addEventListener('pause', updatePlayerButton);
});

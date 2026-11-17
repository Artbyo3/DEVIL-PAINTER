---
hide:
  - navigation
  - toc
---

<div class="dp-landing-container">
  <div class="dp-video-slot">
    <img src="assets/logo-hero.svg" alt="Devil Painter animated logo" class="dp-overview-img" />
  </div>

  <main class="dp-landing-content">
    <h1 class="dp-landing-title">Devil Painter</h1>
    <p class="dp-landing-tagline">A layer-based texture painting add-on for Blender.</p>

    <div class="dp-install-card" id="dp-install-card">
      <button type="button"
              class="dp-install-btn-primary"
              id="dp-install-btn"
              aria-label="Get Add-on">
        Get Add-on
      </button>
      <div class="dp-install-drag-group" id="dp-install-drag-group">
        <a href="https://github.com/Artbyo3/DEVIL-PAINTER/releases"
           class="dp-install-drag-zone"
           id="dp-install-drag"
           target="_blank"
           rel="noopener"
           aria-label="Download Devil Painter from GitHub Releases">
          <svg class="dp-install-drag-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          <span>Download from GitHub Releases</span>
        </a>
        <div class="dp-install-fallback">
          ...or follow the <a href="install/" class="dp-install-fallback-link">Install guide</a> to <a href="install/#build-and-install-from-source" class="dp-install-fallback-link">Install from Disk</a>
        </div>
      </div>
    </div>

    <nav class="dp-landing-nav" aria-label="Documentation entry points">
      <a href="quickstart/" class="dp-landing-btn dp-landing-btn--primary">Quickstart</a>
      <a href="guide/" class="dp-landing-btn">Documentation</a>
      <a href="https://github.com/Artbyo3/DEVIL-PAINTER" class="dp-landing-btn" target="_blank" rel="noopener">GitHub</a>
    </nav>
  </main>

  <div class="dp-contributors-container" id="dp-contributors-container" style="display: none;">
    <div class="dp-contributors-label">Contributors</div>
    <div class="dp-contributors-stripe" id="dp-contributors-stripe">
      <div class="dp-contributors-track" id="dp-contributors-track"></div>
    </div>
  </div>
</div>

<script>
(function() {
  const card = document.getElementById('dp-install-card');
  const btn = document.getElementById('dp-install-btn');
  if (!card || !btn) return;

  btn.addEventListener('click', function() {
    card.classList.add('is-active');
  });
})();

(async function() {
  try {
    const res = await fetch('https://api.github.com/repos/Artbyo3/DEVIL-PAINTER/contributors');
    if (!res.ok) return;
    const contributors = await res.json();
    if (!Array.isArray(contributors) || contributors.length === 0) return;

    const stripe = document.getElementById('dp-contributors-stripe');
    const track = document.getElementById('dp-contributors-track');
    const container = document.getElementById('dp-contributors-container');
    if (!stripe || !track || !container) return;

    function renderItem(c) {
      return `
        <span class="dp-contributor-item">
          <img src="${c.avatar_url}" alt="" class="dp-contributor-avatar" loading="lazy" width="28" height="28" />
          <span class="dp-contributor-name">${c.login}</span>
        </span>
      `;
    }

    const baseHtml = contributors.map(renderItem).join('');
    track.innerHTML = `<div class="dp-marquee-set">${baseHtml}</div>`;
    container.style.display = 'flex';

    if (track.scrollWidth <= stripe.clientWidth) {
      stripe.classList.add('is-static');
      track.classList.add('is-static');
    } else {
      track.innerHTML = `
        <div class="dp-marquee-set">${baseHtml}</div>
        <div class="dp-marquee-set" aria-hidden="true">${baseHtml}</div>
      `;
    }
  } catch (e) {
  }
})();
</script>

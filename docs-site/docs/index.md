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
    <p class="dp-landing-tagline">Documentation shell — project overview coming soon.</p>

    <!-- Install action shell -->
    <div class="dp-install-card" id="dp-install-card">
      <button type="button"
              class="dp-install-btn-primary"
              id="dp-install-btn"
              aria-label="Get Add-on">
        Get Add-on
      </button>
      <div class="dp-install-drag-group" id="dp-install-drag-group">
        <div class="dp-install-drag-zone"
             id="dp-install-drag"
             role="note"
             aria-label="Add-on install placeholder">
          <span>Install link coming soon</span>
        </div>
        <div class="dp-install-fallback">
          See <a href="install/" class="dp-install-fallback-link">Install</a> or <a href="https://github.com/Artbyo3/DEVIL-PAINTER/releases" class="dp-install-fallback-link" target="_blank" rel="noopener">GitHub Releases</a>
        </div>
      </div>
    </div>

    <!-- Minimal entry options (Quickstart, Documentation, GitHub) -->
    <nav class="dp-landing-nav" aria-label="Documentation entry points">
      <a href="quickstart/" class="dp-landing-btn dp-landing-btn--primary">Quickstart</a>
      <a href="guide/" class="dp-landing-btn">Documentation</a>
      <a href="https://github.com/Artbyo3/DEVIL-PAINTER" class="dp-landing-btn" target="_blank" rel="noopener">GitHub</a>
    </nav>
  </main>

  <!-- Live contributors space -->
  <div class="dp-contributors-container" id="dp-contributors-container" style="display: none;">
    <div class="dp-contributors-label">Contributors</div>
    <div class="dp-contributors-stripe">
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

    const track = document.getElementById('dp-contributors-track');
    const container = document.getElementById('dp-contributors-container');
    if (!track || !container) return;

    function renderItem(c) {
      return `
        <span class="dp-contributor-item">
          <img src="${c.avatar_url}" alt="" class="dp-contributor-avatar" loading="lazy" width="28" height="28" />
          <span class="dp-contributor-name">${c.login}</span>
        </span>
      `;
    }

    const baseHtml = contributors.map(renderItem).join('');

    let count = contributors.length;
    let setHtml = baseHtml;
    while (count < 24) {
      setHtml += baseHtml;
      count += contributors.length;
    }

    track.innerHTML = `
      <div class="dp-marquee-set">${setHtml}</div>
      <div class="dp-marquee-set" aria-hidden="true">${setHtml}</div>
    `;
    container.style.display = 'flex';
  } catch (e) {
  }
})();
</script>

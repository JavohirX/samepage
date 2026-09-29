/**
 * Samepage Embeddable Gallery Widget (S10).
 *
 * Lightweight script-tag widget that fetches the public gallery JSON without cookies
 * and renders responsive project cards into a host container.
 *
 * Usage:
 *   <div id="samepage-gallery" data-event="evt_01"></div>
 *   <script src="/static/widget.js" data-target="#samepage-gallery"></script>
 */

(function () {
  "use strict";

  function initWidget() {
    const currentScript = document.currentScript;
    let targetSelector = currentScript ? currentScript.getAttribute("data-target") : "#samepage-gallery";
    let targetEl = targetSelector ? document.querySelector(targetSelector) : null;

    if (!targetEl) {
      targetEl = document.querySelector("#samepage-gallery") || document.querySelector(".samepage-gallery");
    }
    if (!targetEl) return;

    const eventId = targetEl.getAttribute("data-event") || (currentScript ? currentScript.getAttribute("data-event") : "");
    if (!eventId) {
      targetEl.innerHTML = "<p><em>Missing data-event attribute for Samepage gallery widget.</em></p>";
      return;
    }

    const host = targetEl.getAttribute("data-host") || (currentScript ? currentScript.getAttribute("data-host") : "") || window.location.origin;
    const galleryUrl = `${host.replace(/\/$/, "")}/e/${encodeURIComponent(eventId)}/projects`;
    const jsonUrl = `${galleryUrl}.json`;

    // Render loading state with accessible fallback link
    targetEl.innerHTML = `
      <div class="sp-widget-container" style="font-family: system-ui, -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 1rem;">
        <div class="sp-widget-header" style="display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; margin-bottom: 1rem;">
          <h3 style="margin: 0; font-size: 1.25rem; color: #1a202c;">Projects Gallery</h3>
          <a href="${galleryUrl}" target="_blank" rel="noopener" style="font-size: 0.875rem; color: #3182ce; text-decoration: none;">View full gallery &rarr;</a>
        </div>
        <div class="sp-widget-loading" style="padding: 2rem; text-align: center; color: #718096;">
          Loading projects...
        </div>
        <div class="sp-widget-cards" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 1rem;"></div>
      </div>
    `;

    fetch(jsonUrl, { credentials: "omit", mode: "cors" })
      .then((resp) => {
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return resp.json();
      })
      .then((data) => {
        const loading = targetEl.querySelector(".sp-widget-loading");
        if (loading) loading.remove();

        const cardsContainer = targetEl.querySelector(".sp-widget-cards");
        const items = data.items || [];

        if (items.length === 0) {
          cardsContainer.innerHTML = "<p style='color: #718096;'>No submitted projects yet.</p>";
          return;
        }

        cardsContainer.innerHTML = items
          .map((item) => {
            const title = escapeHtml(item.title || "Untitled Project");
            const tagline = escapeHtml(item.tagline || "");
            const track = escapeHtml(item.track || "");
            const prjId = encodeURIComponent(item.id);
            const projUrl = `${host.replace(/\/$/, "")}/e/${encodeURIComponent(eventId)}/projects/${prjId}`;

            return `
              <div class="sp-project-card" style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 1rem; background: #ffffff; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                  <h4 style="margin: 0 0 0.5rem 0; font-size: 1.1rem; color: #2d3748;">
                    <a href="${projUrl}" target="_blank" rel="noopener" style="color: inherit; text-decoration: none;">${title}</a>
                  </h4>
                  ${tagline ? `<p style="margin: 0 0 0.75rem 0; font-size: 0.875rem; color: #4a5568; line-height: 1.4;">${tagline}</p>` : ""}
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 0.5rem; font-size: 0.75rem;">
                  ${track ? `<span style="background: #edf2f7; color: #4a5568; padding: 0.2rem 0.5rem; border-radius: 4px;">${track}</span>` : "<span></span>"}
                  <a href="${projUrl}" target="_blank" rel="noopener" style="color: #3182ce; font-weight: 500; text-decoration: none;">View &rarr;</a>
                </div>
              </div>
            `;
          })
          .join("");
      })
      .catch((err) => {
        const container = targetEl.querySelector(".sp-widget-container");
        if (container) {
          container.innerHTML = `
            <p style="color: #718096;">Could not load gallery preview. <a href="${galleryUrl}" target="_blank" rel="noopener">Open project gallery &rarr;</a></p>
          `;
        }
      });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initWidget);
  } else {
    initWidget();
  }
})();

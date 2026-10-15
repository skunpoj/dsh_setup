    const mermaidPanZoomInstances = new Map();

    function initMermaidPanZoom() {
        if (typeof svgPanZoom === 'undefined') return;
        document.querySelectorAll('.mermaid-wrapper').forEach((wrapper) => {
            const container = wrapper.querySelector('.mermaid-container');
            if (!container) return;
            const svg = container.querySelector('svg');
            if (!svg) return;

            if (!svg.hasAttribute('data-original-viewbox')) svg.setAttribute('data-original-viewbox', svg.getAttribute('viewBox') || '0 0 1200 800');
            svg.removeAttribute('width');
            svg.removeAttribute('height');
            svg.style.setProperty('width', '100%', 'important');
            svg.style.setProperty('height', '100%', 'important');
            svg.style.setProperty('max-width', 'none', 'important');
            svg.style.setProperty('max-height', 'none', 'important');
            svg.style.setProperty('min-width', '100%', 'important');
            svg.style.setProperty('min-height', '100%', 'important');
            svg.style.display = 'block';

            const parentDiv = svg.parentElement;
            if (parentDiv && parentDiv !== container) {
                parentDiv.style.setProperty('width', '100%', 'important');
                parentDiv.style.setProperty('height', '100%', 'important');
                parentDiv.style.setProperty('min-width', '100%', 'important');
                parentDiv.style.setProperty('min-height', '100%', 'important');
                parentDiv.style.setProperty('display', 'flex', 'important');
            }

            if (mermaidPanZoomInstances.has(container)) {
                try { mermaidPanZoomInstances.get(container).destroy(); } catch(e) {}
                mermaidPanZoomInstances.delete(container);
            }

            try {
                const pz = svgPanZoom(svg, {
                    zoomEnabled: true,
                    controlIconsEnabled: false,
                    fit: true,
                    center: true,
                    minZoom: 0.1,
                    maxZoom: 10,
                    zoomScaleSensitivity: 0.25,
                    contain: false,
                    dblClickZoomEnabled: true,
                    mouseWheelZoomEnabled: true,
                    preventMouseEventsDefault: true
                });
                mermaidPanZoomInstances.set(container, pz);
                pz.resize();
                pz.fit();
                pz.center();
            } catch (e) {
                console.error('Error initializing pan-zoom:', e);
            }
        });
    }

    function panZoomMermaid(buttonEl, action) {
        const wrapper = buttonEl.closest('.mermaid-wrapper');
        if (!wrapper) return;
        const container = wrapper.querySelector('.mermaid-container');
        if (!container) return;

        if (action === 'fullscreen') {
            if (!document.fullscreenElement) {
                const req = wrapper.requestFullscreen || wrapper.webkitRequestFullscreen || wrapper.msRequestFullscreen;
                if (req) {
                    req.call(wrapper).then(() => {
                        setTimeout(() => {
                            const pz = mermaidPanZoomInstances.get(container);
                            if (pz) { pz.resize(); pz.fit(); pz.center(); }
                        }, 200);
                    }).catch(err => console.warn('Fullscreen error:', err));
                }
            } else {
                const exit = document.exitFullscreen || document.webkitExitFullscreen || document.msExitFullscreen;
                if (exit) {
                    exit.call(document).then(() => {
                        setTimeout(() => {
                            const pz = mermaidPanZoomInstances.get(container);
                            if (pz) { pz.resize(); pz.fit(); pz.center(); }
                        }, 200);
                    }).catch(err => console.warn('Exit fullscreen error:', err));
                }
            }
            return;
        }

        const pz = mermaidPanZoomInstances.get(container);
        if (!pz) return;

        if (action === 'zoomIn') {
            pz.zoomIn();
        } else if (action === 'zoomOut') {
            pz.zoomOut();
        } else if (action === 'reset') {
            pz.resetZoom();
            pz.resetPan();
            pz.fit();
            pz.center();
        }
    }

    function exportMermaid(buttonEl, format) {
        const wrapper = buttonEl.closest('.mermaid-wrapper') || buttonEl.closest('.mermaid-card') || buttonEl.closest('.card-body') || buttonEl.closest('.card-custom');
        if (!wrapper) return;
        const container = wrapper.querySelector('.mermaid-container') || wrapper.querySelector('.mermaid-card') || wrapper;
        const svgEl = container.querySelector('svg');
        const mermaidDiv = wrapper.querySelector('.mermaid');
        
        let title = "diagram";
        const titleEl = wrapper.querySelector('.diagram-title, .mermaid-header span, .card-header-custom span, h3, h4, h5');
        if (titleEl) {
            title = titleEl.innerText.trim()
                .replace(/[^a-zA-Z0-9_\u0E00-\u0E7F]+/g, '_')
                .replace(/^_+|_+$/g, '')
                .toLowerCase();
        }
        if (!title || title === "_") title = "diagram";

        if (format === 'copy') {
            let rawCode = "";
            if (mermaidDiv) {
                rawCode = mermaidDiv.getAttribute('data-raw-code') || mermaidDiv.innerText.trim();
            }
            if (!rawCode && svgEl) {
                rawCode = svgEl.getAttribute('data-raw-code') || "";
            }
            if (rawCode) {
                navigator.clipboard.writeText(rawCode).then(() => {
                    const origHtml = buttonEl.innerHTML;
                    buttonEl.innerHTML = '<i class="fa-solid fa-check text-success"></i> Copied!';
                    buttonEl.style.borderColor = '#10b981';
                    buttonEl.style.color = '#10b981';
                    setTimeout(() => {
                        buttonEl.innerHTML = origHtml;
                        buttonEl.style.borderColor = '';
                        buttonEl.style.color = '';
                    }, 2000);
                }).catch(err => {
                    console.warn("Clipboard copy failed, using prompt:", err);
                    prompt("Copy Mermaid Code:", rawCode);
                });
            } else {
                alert("Mermaid code snippet not found for copying.");
            }
            return;
        }

        if (!svgEl) {
            alert("Diagram SVG is still rendering. Please try again in a moment.");
            return;
        }

        const clonedSvg = svgEl.cloneNode(true);
        clonedSvg.removeAttribute('style');
        if (!clonedSvg.getAttribute('xmlns')) {
            clonedSvg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        }
        if (!clonedSvg.getAttribute('xmlns:xlink')) {
            clonedSvg.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
        }

        const bbox = svgEl.getBoundingClientRect();
        const viewBox = svgEl.getAttribute('data-original-viewbox') || svgEl.getAttribute('viewBox');
        const viewport = clonedSvg.querySelector('.svg-pan-zoom_viewport');
        if (viewport) viewport.removeAttribute('transform');
        if (viewBox) clonedSvg.setAttribute('viewBox', viewBox);
        let width = bbox.width || 1200;
        let height = bbox.height || 800;
        if (viewBox) {
            const parts = viewBox.split(/[\s,]+/).filter(Boolean).map(Number);
            if (parts.length === 4 && parts[2] > 0 && parts[3] > 0) {
                width = parts[2];
                height = parts[3];
            }
        } else {
            clonedSvg.setAttribute('viewBox', `0 0 ${width} ${height}`);
        }
        clonedSvg.setAttribute('width', width);
        clonedSvg.setAttribute('height', height);

        const styleEl = document.createElement('style');
        styleEl.textContent = "text { font-family: 'Sarabun', 'IBM Plex Sans Thai', -apple-system, sans-serif; }";
        clonedSvg.insertBefore(styleEl, clonedSvg.firstChild);

        const svgData = new XMLSerializer().serializeToString(clonedSvg);

        if (format === 'svg') {
            const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${title}.svg`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(() => URL.revokeObjectURL(url), 5000);
        } else if (format === 'png') {
            const scale = 2.5;
            const canvas = document.createElement('canvas');
            canvas.width = width * scale;
            canvas.height = height * scale;
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#0f172a';
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            const img = new Image();
            const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
            const url = URL.createObjectURL(svgBlob);

            img.onload = function() {
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                URL.revokeObjectURL(url);
                try {
                    const pngUrl = canvas.toDataURL('image/png');
                    const a = document.createElement('a');
                    a.href = pngUrl;
                    a.download = `${title}.png`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                } catch (e) {
                    console.error("Canvas export error:", e);
                    alert("PNG export failed: " + e.message);
                }
            };
            img.onerror = function(e) {
                console.error("SVG image load failed:", e);
                URL.revokeObjectURL(url);
                alert("Could not convert SVG to Canvas for PNG download.");
            };
            img.src = url;
        }
    }

    window.addEventListener('load', () => setTimeout(initMermaidPanZoom, 800));
    document.addEventListener('DOMContentLoaded', () => setTimeout(initMermaidPanZoom, 600));

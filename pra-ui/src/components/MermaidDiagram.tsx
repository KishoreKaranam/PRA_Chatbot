import { useEffect, useRef, useState } from "react";
import { Download, AlertTriangle, ZoomIn, ZoomOut, RotateCcw } from "lucide-react";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: false,
  theme: "default",
  securityLevel: "loose", // allow <br/> labels in node text
  fontFamily: "inherit",
  themeVariables: {
    fontSize: "12px",
  },
  flowchart: {
    useMaxWidth: false,  // render at natural size so labels stay readable; container scrolls
    htmlLabels: true,
    nodeSpacing: 25,     // tighter horizontal gaps
    rankSpacing: 35,     // tighter vertical gaps → less scrolling
    padding: 6,
    curve: "basis",
  },
  sequence: {
    useMaxWidth: false,
  },
});

interface MermaidDiagramProps {
  code: string;
  /** True while the answer is still streaming — a parse failure is treated as
   *  "not finished yet" rather than a hard error. */
  streaming?: boolean;
}

let diagramSeq = 0;

/**
 * Normalizes common LLM mistakes that make otherwise-correct Mermaid fail to
 * parse (which shows up as the diagram "sometimes" rendering and sometimes
 * staying as raw text):
 *   - curly/smart quotes → straight quotes
 *   - a stray leading "mermaid" token before the diagram type
 *   - fully-quoted code fences accidentally left in the source
 *   - non-breaking spaces → normal spaces
 */
function sanitizeMermaid(raw: string): string {
  let s = raw;
  // Smart quotes and other unicode punctuation that Mermaid can't tokenize.
  s = s
    .replace(/[\u201C\u201D\u201E\u201F\u2033]/g, '"') // “ ” „ ‟ ″ → "
    .replace(/[\u2018\u2019\u201A\u201B\u2032]/g, "'") // ‘ ’ ‚ ‛ ′ → '
    .replace(/[\u2013\u2014]/g, "-") // – — → -
    .replace(/\u00A0/g, " "); // non-breaking space → space
  // Drop stray fenced-code markers or a leading bare "mermaid" line.
  s = s.replace(/^\s*```(?:mermaid)?\s*/i, "").replace(/```$/i, "");
  s = s.replace(/^\s*mermaid\s*\n/i, "");
  return s.trim();
}


/**
 * Renders a Mermaid code block as an SVG picture with PNG/SVG download buttons.
 *
 * Rendering is driven purely by whether the Mermaid source is currently
 * parseable — NOT by the global streaming flag. This means a complete diagram
 * renders as soon as its source is valid, even if the surrounding stream has
 * not fully closed. While the source is still incomplete (mid-stream) parsing
 * fails and we show the raw source as a lightweight placeholder.
 */
export function MermaidDiagram({ code, streaming }: MermaidDiagramProps) {
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [zoom, setZoom] = useState<number>(1);
  const svgRef = useRef<string>("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const ZOOM_MIN = 0.4;
  const ZOOM_MAX = 3;
  const clampZoom = (z: number) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));
  const zoomIn = () => setZoom((z) => clampZoom(Math.round((z + 0.2) * 100) / 100));
  const zoomOut = () => setZoom((z) => clampZoom(Math.round((z - 0.2) * 100) / 100));
  const zoomReset = () => setZoom(1);

  // Ctrl/Cmd + wheel to zoom; plain wheel keeps native scrolling.
  const onWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    setZoom((z) => clampZoom(Math.round((z - Math.sign(e.deltaY) * 0.1) * 100) / 100));
  };

  // Drag anywhere on the canvas to pan the scroll container.
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = scrollRef.current;
    if (!el || e.button !== 0) return;
    const startX = e.clientX;
    const startY = e.clientY;
    const startLeft = el.scrollLeft;
    const startTop = el.scrollTop;
    el.setPointerCapture(e.pointerId);
    el.classList.add("mermaid-grabbing");
    const onMove = (ev: PointerEvent) => {
      el.scrollLeft = startLeft - (ev.clientX - startX);
      el.scrollTop = startTop - (ev.clientY - startY);
    };
    const onUp = (ev: PointerEvent) => {
      el.releasePointerCapture(ev.pointerId);
      el.classList.remove("mermaid-grabbing");
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
  };

  useEffect(() => {
    let cancelled = false;
    const source = sanitizeMermaid(code);
    if (!source) {
      setSvg("");
      setError("");
      svgRef.current = "";
      return;
    }

    (async () => {
      try {
        // parse() throws on invalid/incomplete syntax without touching the DOM.
        await mermaid.parse(source);
        // Unique id per attempt — avoids DOM id collisions under React
        // StrictMode's double-invoked effects.
        const id = `mermaid-${++diagramSeq}`;
        const { svg: rendered } = await mermaid.render(id, source);
        if (!cancelled) {
          svgRef.current = rendered;
          setSvg(rendered);
          setError("");
        }
      } catch (err) {
        if (!cancelled) {
          // Mid-stream the source is legitimately incomplete — don't flash an
          // error. Only surface a hard error once streaming has stopped.
          setSvg("");
          svgRef.current = "";
          setError(streaming ? "" : err instanceof Error ? err.message : "Failed to render diagram");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code, streaming]);

  const downloadSvg = () => {
    const blob = new Blob([svgRef.current], { type: "image/svg+xml;charset=utf-8" });
    triggerDownload(URL.createObjectURL(blob), "diagram.svg");
  };

  const downloadPng = () => {
    const img = new Image();
    const svgBlob = new Blob([svgRef.current], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);
    img.onload = () => {
      const scale = 2; // higher-resolution export
      const canvas = document.createElement("canvas");
      canvas.width = (img.width || 800) * scale;
      canvas.height = (img.height || 600) * scale;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => {
        if (blob) triggerDownload(URL.createObjectURL(blob), "diagram.png");
      }, "image/png");
    };
    img.onerror = () => URL.revokeObjectURL(url);
    img.src = url;
  };

  // Rendered diagram — the primary, expected output.
  if (svg) {
    return (
      <div className="mermaid-block">
        <div className="mermaid-toolbar">
          <button className="mermaid-download-btn" onClick={zoomOut} title="Zoom out">
            <ZoomOut size={12} />
          </button>
          <button className="mermaid-download-btn" onClick={zoomReset} title="Reset zoom">
            <RotateCcw size={12} /> {Math.round(zoom * 100)}%
          </button>
          <button className="mermaid-download-btn" onClick={zoomIn} title="Zoom in">
            <ZoomIn size={12} />
          </button>
          <button className="mermaid-download-btn" onClick={downloadPng} title="Download as PNG">
            <Download size={12} /> PNG
          </button>
          <button className="mermaid-download-btn" onClick={downloadSvg} title="Download as SVG">
            <Download size={12} /> SVG
          </button>
        </div>
        <div
          className="mermaid-viewport"
          ref={scrollRef}
          onWheel={onWheel}
          onPointerDown={onPointerDown}
          title="Drag to pan · Ctrl+scroll to zoom"
        >
          <div
            className="mermaid-canvas"
            style={{ zoom }}
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      </div>
    );
  }

  // Hard error — only shown once streaming has stopped and the source is invalid.
  if (error) {
    return (
      <div className="mermaid-error">
        <div className="mermaid-error-title">
          <AlertTriangle size={14} /> Could not render diagram
        </div>
        <pre>
          <code>{code}</code>
        </pre>
      </div>
    );
  }

  // Mid-stream / not yet parseable — show a lightweight loader instead of the
  // raw diagram source so the user isn't staring at code while it generates.
  return (
    <div className="mermaid-loading" role="status" aria-live="polite">
      <span className="mermaid-spinner" aria-hidden="true" />
      <span>Rendering diagram…</span>
    </div>
  );
}

function triggerDownload(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

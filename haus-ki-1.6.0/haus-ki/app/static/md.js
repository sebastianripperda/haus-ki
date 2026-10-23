// Kleiner, sicherer Markdown-Renderer für Antworten: Erst wird alles HTML maskiert,
// dann werden nur bekannte Muster in Auszeichnung umgewandelt.
(function () {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  function inline(s) {
    const codes = [];
    s = s.replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return "\u0000" + (codes.length - 1) + "\u0000"; });
    s = esc(s);
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,:;!?]|$)/g, "$1<em>$2</em>");
    s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    s = s.replace(/\[(\d{1,2})\]/g, '<a class="ref" href="#cite-$1" data-ref="$1">[$1]</a>');
    s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => "<code>" + esc(codes[+i]) + "</code>");
    return s;
  }

  function table(lines) {
    const cells = (l) => l.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());
    const head = cells(lines[0]);
    const align = cells(lines[1]).map((c) => (/^:?-+:$/.test(c) && c.endsWith(":") ? "num" : ""));
    const body = lines.slice(2).map(cells);
    const isNum = (v) => /^[-−+]?[\d.,\s]+(\s?(€|%|°C|kWh|Min|h|GB|MB))?$/.test(v);
    const numCol = head.map((_, i) => align[i] === "num" || (body.length && body.every((r) => !r[i] || isNum(r[i]))));
    let h = '<div class="tbl"><table><thead><tr>' + head.map((c, i) => `<th class="${numCol[i] ? "num" : ""}">${inline(c)}</th>`).join("") + "</tr></thead><tbody>";
    for (const r of body) h += "<tr>" + head.map((_, i) => `<td class="${numCol[i] ? "num" : ""}">${inline(r[i] || "")}</td>`).join("") + "</tr>";
    return h + "</tbody></table></div>";
  }

  function render(src) {
    const lines = (src || "").replace(/\r\n/g, "\n").split("\n");
    let out = "", i = 0, para = [];
    const flush = () => { if (para.length) { out += "<p>" + inline(para.join("\n")).replace(/\n/g, "<br>") + "</p>"; para = []; } };
    while (i < lines.length) {
      const l = lines[i];
      const fence = l.match(/^\s*```(\w*)/);
      if (fence) {
        flush();
        const code = [];
        i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
        i++;
        out += `<pre><code${fence[1] ? ` data-lang="${esc(fence[1])}"` : ""}>${esc(code.join("\n"))}</code></pre>`;
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        flush();
        const t = [];
        while (i < lines.length && /^\s*\|.*\|?\s*$/.test(lines[i]) && lines[i].trim()) t.push(lines[i++]);
        out += table(t);
        continue;
      }
      const hd = l.match(/^(#{1,3})\s+(.*)/);
      if (hd) { flush(); out += `<h${hd[1].length + 1}>${inline(hd[2])}</h${hd[1].length + 1}>`; i++; continue; }
      if (/^\s*([-*•]|\d+[.)])\s+/.test(l)) {
        flush();
        const ordered = /^\s*\d+[.)]/.test(l);
        const items = [];
        while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
          let item = lines[i++].replace(/^\s*([-*•]|\d+[.)])\s+/, "");
          while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) item += " " + lines[i++].trim();
          items.push("<li>" + inline(item) + "</li>");
        }
        out += (ordered ? "<ol>" : "<ul>") + items.join("") + (ordered ? "</ol>" : "</ul>");
        continue;
      }
      if (/^>\s?/.test(l)) {
        flush();
        const q = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) q.push(lines[i++].replace(/^>\s?/, ""));
        out += "<blockquote>" + inline(q.join(" ")) + "</blockquote>";
        continue;
      }
      if (!l.trim()) { flush(); i++; continue; }
      para.push(l);
      i++;
    }
    flush();
    return out;
  }
  window.MD = { render, esc };
})();

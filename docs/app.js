// learn_upload public docs site — hash router + client-side markdown
// rendering. Pushing an updated .md file (via docs-sync.yml) is enough to
// update the site; no rebuild step.

const DOC_TITLES = {
  "GUI_Walkthrough.md": "GUI walkthrough",
  "GC_Elekta_Patient_Upload_Process.md": "GC Elekta patient upload process",
  "LEARN_Upload_Automation_Plan.md": "LEARN upload automation plan",
  "Elekta_XVI_Reconstruction_Directory_Analysis.md": "XVI reconstruction directory analysis",
  "elekta_rps_format_documentation.md": "Elekta RPS format documentation",
  "elekta_xvi_sro_experimental_validation.md": "SRO experimental validation notes",
};

const homePage = document.getElementById("home-page");
const docPage = document.getElementById("doc-page");
const docContent = document.getElementById("doc-content");

function currentDoc() {
  const m = /doc=([^&]+)/.exec(location.hash || "");
  return m ? decodeURIComponent(m[1]) : null;
}

function setActiveNav(doc) {
  document.querySelectorAll("a[data-doc]").forEach((a) => {
    a.classList.toggle("active", a.getAttribute("data-doc") === (doc || "home"));
  });
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function postProcessDoc(host) {
  host.querySelectorAll("table").forEach((t) => {
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    t.parentNode.insertBefore(wrap, t);
    wrap.appendChild(t);
  });
  host.querySelectorAll("a").forEach((a) => {
    const href = a.getAttribute("href") || "";
    if (/\.md(#.*)?$/i.test(href) && !/^https?:/i.test(href)) {
      const file = href.replace(/^.*\//, "").replace(/#.*$/, "");
      a.setAttribute("href", "#doc=" + file);
    } else if (/^https?:/i.test(href)) {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener");
    }
  });
  host.querySelectorAll("img").forEach((img) => {
    const src = img.getAttribute("src") || "";
    if (!/^https?:/i.test(src)) img.setAttribute("src", src.replace(/^\.\//, ""));
  });
}

async function loadDoc(name) {
  if (!DOC_TITLES[name]) {
    docContent.innerHTML = "<p>Unknown document: " + escapeHtml(name) + "</p>";
    return;
  }
  docContent.innerHTML = '<p class="doc-loading">Loading ' + escapeHtml(name) + "&hellip;</p>";
  let md;
  try {
    const res = await fetch(name);
    if (!res.ok) throw new Error(String(res.status));
    md = await res.text();
  } catch (e) {
    docContent.innerHTML = '<p class="doc-error">Could not load ' + escapeHtml(name) + ".</p>";
    return;
  }
  if (currentDoc() !== name) return; // hash changed while fetching
  const crumb =
    '<div class="doc-crumb"><a href="#" class="eyebrow">learn_upload</a>' +
    '<span class="doc-crumb-sep">/</span>' +
    '<span class="eyebrow doc-crumb-current">' + escapeHtml(DOC_TITLES[name]) + "</span></div>" +
    '<div class="doc-source">Source: Docs/' + escapeHtml(name) + "</div>";
  docContent.innerHTML = crumb + window.marked.parse(md, { gfm: true, breaks: false });
  postProcessDoc(docContent);
}

function render() {
  const doc = currentDoc();
  setActiveNav(doc);
  if (doc) {
    homePage.hidden = true;
    docPage.hidden = false;
    loadDoc(doc);
  } else {
    homePage.hidden = false;
    docPage.hidden = true;
  }
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", render);
render();

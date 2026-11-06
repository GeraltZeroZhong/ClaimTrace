"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const list = (value) => (Array.isArray(value) ? value : []);
const known = (value) =>
  value && !["unknown", "none", "null"].includes(String(value).toLowerCase());
const pretty = (value) => JSON.stringify(value, null, 2);
const icons = {
  plus: '<path d="M8 3v10M3 8h10"/>',
  close: '<path d="m4 4 8 8M12 4l-8 8"/>',
  arrow: '<path d="M3 8h10M9 4l4 4-4 4"/>',
  check: '<path d="m3 8 3 3 7-7"/>',
  search: '<circle cx="7" cy="7" r="4"/><path d="m10 10 3 3"/>',
  file: '<path d="M9 2H4v12h8V5zM9 2v3h3M6 8h4M6 11h4"/>',
  folder: '<path d="M2 4h5l2 2h5v7H2zM2 4V3h5l2 2h5v1"/>',
  upload: '<path d="M8 11V2M4 6l4-4 4 4M2 10v4h12v-4"/>',
  download: '<path d="M8 2v9M4 7l4 4 4-4M2 11v3h12v-3"/>',
  info: '<circle cx="8" cy="8" r="6"/><path d="M8 7v4M8 4.5v.5"/>',
  warn: '<path d="M8 2 1 14h14zM8 6v4M8 12v.3"/>',
  edit: '<path d="m10 3 3 3-7 7H3v-3zM9 4l3 3"/>',
  focus:
    '<path d="M6 2H2v4M10 2h4v4M2 10v4h4M10 14h4v-4"/><circle cx="8" cy="8" r="2"/>',
  layers: '<path d="m8 2 6 3-6 3-6-3zM2 8l6 3 6-3M2 11l6 3 6-3"/>',
  refresh: '<path d="M13 6A5 5 0 1 0 13 10M13 2v4H9"/>',
  image:
    '<rect x="2" y="2" width="12" height="12" rx="1"/><circle cx="6" cy="6" r="1"/><path d="m2 12 4-4 3 3 2-2 3 3"/>',
  minus: '<path d="M4 8h8"/>',
  link: '<path d="m6 6 2-2a3 3 0 0 1 4 4l-2 2M10 10l-2 2a3 3 0 0 1-4-4l2-2M6 10l4-4"/>',
};
const icon = (name, size = 16) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.file}</svg>`;
const state = {
  data: null,
  mode: "simple",
  claimId: null,
  sceneId: null,
  renderId: null,
  tab: "visual",
  view: "prepare",
  query: "",
  filter: "all",
  issues: false,
  sourceId: null,
  sourceLine: null,
  sourcePointer: null,
  busy: false,
  reviewer: "",
};
try {
  state.mode =
    localStorage.getItem("claimtrace-mode") === "expert" ? "expert" : "simple";
} catch {
  /* Private browsers may disable storage. */
}
let toastTimer,
  sourceRequest = 0;
const types = {
  simple_structure_view: "Structure view",
  selection_highlight: "Highlighted region",
  ligand_binding_pose: "Ligand binding pose",
  cryo_em_map_fit: "Cryo-EM map fit",
  xray_density_support: "X-ray density support",
  trajectory_mechanism: "Trajectory or mechanism",
  model_comparison: "Model comparison",
  computed_model_claim: "Computed model",
  unknown: "Other",
};
const stageNames = {
  claim: "Claim",
  visual: "Visual evidence",
  provenance: "Provenance",
  uncertainty: "Uncertainty",
  reproducibility: "Reproducibility",
};
const statusNames = {
  incomplete: "Needs details",
  review: "Review needed",
  recorded: "Recorded",
  missing: "Add details",
  not_applicable: "Optional",
  pass: "Ready",
  pass_with_warnings: "Review notes",
  fail: "Needs attention",
  needs_review: "Review needed",
};
const evidenceKinds = {
  manual_rationale: "Figure or structure inspection",
  contact_table: "Contact table",
  measurement: "Distance measurements",
  external_validation: "Comparison or validation report",
  density_support: "Electron-density inspection",
  map_fit_metric: "Map-fit measurements",
  trajectory_analysis: "Trajectory analysis",
  negative_control: "Negative control",
  native_observation: "Scene observation",
  waiver: "Recorded exception",
};
const limitationCategories = {
  general: "General limitation",
  alternative_pose: "Alternative poses",
  selection_bias: "Selection or cutoff",
  model_confidence: "Model confidence",
  method_limit: "Method limitation",
};
const packageURL = (path) =>
  `${path}${path.includes("?") ? "&" : "?"}package_root=${encodeURIComponent(state.data?.root || "")}`;
const artifactURL = (id, download = false) =>
  packageURL(`/api/artifact?id=${encodeURIComponent(id)}${download ? "&download=1" : ""}`);
const claim = () =>
  list(state.data?.semantic?.claims).find((c) => c.id === state.claimId);
const audit = () =>
  list(state.data?.audit?.claims).find((c) => c.id === state.claimId);
const semantic = () => state.data?.semantic || {};
const byIds = (items, ids) =>
  list(items).filter((x) => list(ids).includes(x.id));
const artifact = (id) => list(semantic().artifacts).find((a) => a.id === id);
const linkedEvidence = () =>
  list(semantic().evidence).filter(
    (e) =>
      list(claim()?.evidence_ids).includes(e.id) ||
      list(e.claim_ids).includes(state.claimId),
  );
const linkedUncertainty = () =>
  list(semantic().uncertainty).filter(
    (u) =>
      list(claim()?.uncertainty_ids).includes(u.id) ||
      list(u.claim_ids).includes(state.claimId),
  );
const linkedScenes = () =>
  claim()
    ? byIds(semantic().scenes, claim().scene_ids)
    : list(semantic().scenes);
const activeScene = () =>
  linkedScenes().find((s) => s.id === state.sceneId) || linkedScenes()[0];
const isStaticScene = (scene) =>
  ["plot", "figure_assembly"].includes(scene?.extensions?.view_kind);
const untypedImage = (scene) =>
  !!list(scene?.render_artifact_ids).length && !list(scene?.native_artifact_ids).length && !scene?.extensions?.view_kind;
const staticClaim = () =>
  audit()?.replay_status === "not_applicable" ||
  (linkedScenes().length > 0 && linkedScenes().every(isStaticScene));
const staticPackage = () =>
  list(semantic().scenes).length > 0 &&
  list(semantic().scenes).every(isStaticScene);
const authorContextText = (scene) =>
  scene?.camera?.author_context !== null &&
  typeof scene?.camera?.author_context === "object"
    ? pretty(scene.camera.author_context)
    : String(scene?.camera?.author_context || "");
const sourceFileIds = () => [
  ...new Set(linkedEvidence().flatMap((e) => list(e.source_artifact_ids))),
];
const hasViewContext = (scene) =>
  isStaticScene(scene)
    ? hasCamera({ camera: { author_context: scene?.camera?.author_context } })
    : hasCamera(scene);
const badge = (status, label) =>
  `<span class="badge ${esc(status)}">${esc(label || statusNames[status] || status)}</span>`;
function toast(message, error = false) {
  clearTimeout(toastTimer);
  const node = $("#live-status");
  node.textContent = message;
  node.className = `toast${error ? " error" : ""}`;
  node.hidden = false;
  toastTimer = setTimeout(
    () => {
      node.hidden = true;
    },
    error ? 9000 : 4000,
  );
}
function busy(on) {
  state.busy = on;
  document.body.setAttribute("aria-busy", String(on));
  $(".busy-strip")?.remove();
  if (on) {
    const strip = document.createElement("div");
    strip.className = "busy-strip";
    document.body.append(strip);
  }
  $$("dialog button[type=submit]").forEach((b) => (b.disabled = on));
}
async function api(path, body) {
  const response = await fetch(
    body === undefined && path.startsWith("/api/answers") ? packageURL(path) : path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...body, package_root: state.data?.root || null }),
        },
  );
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(
      `Check that the local server is running. Response (${response.status}).`,
    );
  }
  if (!response.ok)
    throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function rememberView() {
  if (!state.data?.root) return;
  try {
    sessionStorage.setItem(
      "claimtrace-workspace-view",
      JSON.stringify({
        root: state.data.root, view: state.view,
        claimId: state.claimId, sceneId: state.sceneId, tab: state.tab,
      }),
    );
  } catch {
    /* Workspace navigation also works when browser storage is unavailable. */
  }
}
function acceptData(data, preserve = true) {
  const oldRoot = state.data?.root;
  let restoredBrowsing = false;
  const continuingCopy = Boolean(data.working_copy_from) && data.working_copy_from === oldRoot;
  const newPackage = oldRoot !== data.root && !continuingCopy;
  state.data = data;
  if (!preserve || newPackage) {
    state.claimId = null;
    state.sceneId = null;
    state.query = "";
    state.filter = "all";
    state.tab = "visual";
    state.view = list(data.semantic?.claims).length ? "review" : "prepare";
    state.issues = false;
  }
  if (!oldRoot) {
    try {
      const saved = JSON.parse(sessionStorage.getItem("claimtrace-workspace-view"));
      if (saved?.root === data.root) {
        if (["prepare", "review", "export"].includes(saved.view)) state.view = saved.view;
        const savedClaim = list(data.semantic?.claims).find((c) => c.id === saved.claimId);
        if (savedClaim) {
          state.claimId = savedClaim.id;
          if (list(savedClaim.scene_ids).includes(saved.sceneId)) state.sceneId = saved.sceneId;
          if (["claim", "visual", "evidence", "uncertainty", "reproducibility", "expert"].includes(saved.tab))
            state.tab = saved.tab;
        } else if (saved.claimId === null &&
          (!saved.sceneId || list(data.semantic?.scenes).some((s) => s.id === saved.sceneId))) {
          state.claimId = null;
          state.sceneId = saved.sceneId || null;
          restoredBrowsing = true;
        }
      }
    } catch {
      /* Use the package's starting view when browser storage is unavailable. */
    }
  }
  const launchView = new URLSearchParams(location.search).get("view");
  if (!oldRoot && ["prepare", "review", "export"].includes(launchView))
    state.view = launchView;
  if (state.claimId && !claim()) state.claimId = null;
  if (!state.claimId && !restoredBrowsing && (!oldRoot || !preserve || newPackage))
    state.claimId = list(data.semantic?.claims)[0]?.id || null;
  state.sourceId = null;
  state.sourceLine = null;
  state.sourcePointer = null;
  state.renderId = null;
  render();
}
async function mutate(path, body, message, preserve = true) {
  if (state.busy) return;
  busy(true);
  try {
    const data = await api(path, body);
    acceptData(data, preserve);
    if (data.working_copy_from) toast("Changes saved in a working copy.");
    else if (message) toast(message);
    return data;
  } finally {
    busy(false);
  }
}
function render() {
  rememberView();
  state.sourceId = null;
  ++sourceRequest;
  $$("[data-mode]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode)),
  );
  $("#main").innerHTML = state.data?.semantic ? workspace() : welcome();
  bindDropzone();
}
function welcome() {
  return `<section class="welcome"><div class="welcome-grid"><div><div class="eyebrow">Evidence behind molecular figures</div><h1>Show what supports<br>your figure.</h1><p class="welcome-intro">Record a figure statement, link its source files, and share a short review of the evidence and limitations.</p><div class="sample-link"><button class="button" data-action="examples">Try an example ${icon("arrow")}</button><span>Files and suggested answers included</span></div><section class="outcome-preview" aria-label="Example review"><h2>What you will make</h2><dl><dt>Claim</dt><dd>Two residues are highlighted.</dd><dt>Visual evidence</dt><dd>Chain A · residues 42 and 85</dd><dt>Provenance</dt><dd>Saved scene and structure file</dd><dt>Uncertainty</dt><dd>One conformation shown</dd><dt>Reproducibility</dt><dd>View and selection recorded</dd></dl><p>A concise record to share with your figure.</p></section></div><div class="import-card"><div class="import-icon">${icon("layers", 24)}</div><h2>Use your own files</h2><p>Start with a figure image, saved molecular scene, structure, or results table.</p><div class="dropzone" id="dropzone"><button class="button secondary" data-action="pick-import">${icon("upload")} Choose files</button><p>or drop files here</p><div class="formats">PML · CXC · MVSJ · IMAGES · TABLES</div></div><div class="card-separator">Continue or review a shared package</div><button class="button secondary full-width" data-action="open-path">${icon("folder")} Open package</button><p class="welcome-footnote">A package keeps the figure, sources, and review together. Files stay on your computer.</p></div></div><div class="preview-flow"><ol><li>Prepare<small>Write a statement and link its support</small></li><li>Review<small>Follow the statement to its evidence</small></li><li>Export<small>Download the review and its files</small></li></ol></div></section>`;
}
function workspace() {
  const pkg = semantic().package || {},
    count = list(semantic().claims).length;
  return `<div class="workspace-bar"><div class="package-info">${icon("folder", 20)}<div><div class="package-title">${esc(pkg.title)}</div><button class="text-button package-location" data-action="package-location">${state.data.is_exported ? "Shared package" : "Saved locally"} · ${list(semantic().artifacts).length} ${list(semantic().artifacts).length === 1 ? "file" : "files"}</button></div></div><nav class="workflow-nav" aria-label="Workspace"><button data-view="prepare" aria-current="${state.view === "prepare" ? "page" : "false"}">Prepare</button><button data-view="review" aria-current="${state.view === "review" ? "page" : "false"}">Review</button><button data-view="export" aria-current="${state.view === "export" ? "page" : "false"}">Export</button></nav><button class="text-button" data-action="attach">${icon("plus")} Add files</button></div>${state.data.is_exported ? '<p class="micro-note">Saving changes creates a working copy in your local workspace.</p>' : ""}<div class="workspace"><aside class="sidebar" aria-label="Claims"><div class="sidebar-heading"><span>Claims <span class="count">${count}</span></span></div>${count > 3 ? `<div class="search-box">${icon("search", 14)}<input id="claim-search" type="search" value="${esc(state.query)}" placeholder="Search claims" aria-label="Search claims"></div>` : ""}<select class="mobile-claim-select" id="mobile-claim-select" aria-label="Current claim" ${count ? "" : "hidden"}><option value="" ${!state.claimId ? "selected" : ""}>Browse scenes</option>${list(
    semantic().claims,
  )
    .map(
      (c) =>
        `<option value="${esc(c.id)}" ${c.id === state.claimId ? "selected" : ""}>${esc(known(c.figure_ref) ? c.figure_ref : "Draft figure")} · ${esc(c.claim_text.value)}</option>`,
    )
    .join(
      "",
    )}</select><div class="claim-list" id="claim-list">${claimCards()}</div><button class="button secondary small full-width add-claim-button" data-action="new-claim">${icon("plus", 13)} Add claim</button><details class="source-inventory"><summary>Scenes &amp; files</summary><div class="scene-list">${list(
    semantic().scenes,
  )
    .map(
      (scene) =>
        `<button class="scene-link" data-browse-scene="${esc(scene.id)}" aria-current="${!claim() && activeScene()?.id === scene.id}">${icon("layers", 14)}<span>${esc(sceneLabel(scene))}</span></button>`,
    )
    .join(
      "",
    )}</div><button class="text-button" data-action="files">Browse ${list(semantic().artifacts).length} files ${icon("arrow", 12)}</button></details><p class="sidebar-note">${esc(lifecycleLabel())}<br>Save each form to update this package.</p></aside><article class="detail" id="claim-detail">${detail()}</article></div>`;
}
function lifecycleLabel() {
  const lifecycle = state.data?.workflow?.lifecycle;
  return !lifecycle || lifecycle.mode === "draft"
    ? "Working draft"
    : `Preparing for ${lifecycle.label.toLowerCase()}`;
}
function claimCards() {
  const claims = list(semantic().claims)
    .filter((c) =>
      `${c.claim_text.value} ${c.figure_ref}`
        .toLowerCase()
        .includes(state.query.toLowerCase()),
    )
    .filter(
      (c) =>
        state.filter === "all" ||
        list(state.data.audit?.claims).find((a) => a.id === c.id)?.status !==
          "recorded",
    );
  return (
    claims
      .map((c) => {
        const a = list(state.data.audit?.claims).find((a) => a.id === c.id);
        const questions = list(state.data?.workflow?.tasks).filter(
          (t) => t.claim_id === c.id,
        ).length;
        return `<button class="claim-card" data-claim="${esc(c.id)}" aria-current="${c.id === state.claimId}"><div class="claim-card-meta"><span>${esc(known(c.figure_ref) ? c.figure_ref : "Draft figure")}</span></div><p>${esc(c.claim_text.value)}</p><div class="claim-card-bottom"><i class="status-dot ${esc(questions ? "review" : a?.status)}"></i>${questions ? `${questions} ${questions === 1 ? "detail" : "details"} to review` : esc(statusNames[a?.status] || "Review needed")}</div></button>`;
      })
      .join("") ||
    `<p class="empty-list">${list(semantic().claims).length ? (state.query ? "Try another search." : "All claims are shown.") : "Your figure claims will appear here."}</p>`
  );
}
function detail() {
  if (state.view === "export") return exportView();
  const c = claim();
  const heading = `<div class="claim-heading-meta"><span class="claim-ref">${c ? esc(known(c.figure_ref) ? c.figure_ref : "Draft figure") : "Figure workspace"}${c ? ` <span class="muted">/ ${esc(types[c.claim_type] || c.claim_type)}</span>` : ""}</span><span class="small muted">${esc(lifecycleLabel())}</span></div><div class="claim-heading"><h1>${c ? esc(c.claim_text.value) : "What does this figure show?"}</h1>${c ? '<button class="text-button edit-claim" data-action="edit-claim">Edit claim</button>' : ""}</div>`;
  return `${practiceGuide()}${heading}<div class="figure-workbench"><aside class="figure-context">${figureContext()}</aside><div class="reasoning-workspace">${proposalSection()}${state.view === "prepare" ? prepareView() : reviewView()}</div></div>${state.mode === "expert" ? `<details class="technical-section"><summary>Technical details &amp; source records</summary><div class="section-heading"><h2>Source inspection</h2><button class="button secondary small" data-action="answers">Edit answers.yml</button></div>${expertPanel()}</details>` : ""}`;
}
function figureContext() {
  const scenes = linkedScenes(),
    scene = activeScene();
  const renders = byIds(semantic().artifacts, scene?.render_artifact_ids);
  const figure = renders.find((r) => r.id === state.renderId) || renders[0];
  const native = list(scene?.native_artifact_ids);
  const staticView = isStaticScene(scene);
  const needsFigureType = untypedImage(scene);
  const selections = byIds(semantic().selections, scene?.selection_ids);
  const structureIds = [
    ...new Set([
      ...byIds(semantic().entities, scene?.entity_ids).flatMap((e) =>
        list(e.source_artifact_ids),
      ),
      ...selections.flatMap((sel) =>
        byIds(semantic().entities, sel.entity_ids).flatMap((e) =>
          list(e.source_artifact_ids),
        ),
      ),
    ]),
  ].filter((id) => artifact(id)?.role === "structure");
  return `<section class="panel context-panel"><div class="panel-header"><h2>${staticView || needsFigureType ? "Figure" : "Figure &amp; scene"}</h2>${scenes.length > 1 ? `<select id="scene-select" aria-label="${staticClaim() ? "Choose figure" : "Choose scene"}">${scenes.map((s) => `<option value="${esc(s.id)}" ${s.id === scene?.id ? "selected" : ""}>${esc(sceneLabel(s))}</option>`).join("")}</select>` : ""}</div><div class="figure-area">${figure ? `<img src="${artifactURL(figure.id)}" alt="${esc(known(claim()?.figure_ref) ? claim().figure_ref : fileName(figure.id))}" data-render-image>` : `<div class="figure-placeholder">${icon("image", 30)}<h3>Add a figure image</h3><p>Add a PNG, JPEG, or SVG of the figure.</p><button class="button secondary small" data-action="add-figure">Add figure</button></div>`}</div>${figure ? `<div class="figure-caption"><span>${esc(fileName(figure.id))}</span><button class="text-button" data-file="${esc(figure.id)}">Enlarge</button></div>` : ""}${renders.length > 1 ? `<div class="render-picker">${renders.map((r) => `<button data-render="${esc(r.id)}" aria-pressed="${r.id === figure?.id}">${esc(fileName(r.id))}</button>`).join("")}</div>` : ""}<div class="context-facts"><p>${esc(scene ? sceneLabel(scene) : "Scene to add")}</p><span class="small muted">${needsFigureType ? "Choose a molecular view, analysis plot, or figure assembly" : staticView ? `Saved figure · ${hasViewContext(scene) ? "Settings recorded" : "Settings to add"}` : native.length ? `${selections.length} ${selections.length === 1 ? "selection" : "selections"} · ${hasCamera(scene) ? "View recorded" : "View details needed"}` : "Figure image · Add a saved scene for replay in its original viewer"}</span>${needsFigureType ? `<button class="text-button" data-action="context">Set figure type</button>` : staticView ? `<button class="text-button" data-action="context">Edit figure settings</button>` : native.length ? `<button class="text-button" data-action="view-source">View scene source ${icon("arrow", 12)}</button>` : '<button class="text-button" data-action="attach">Add saved scene</button>'}</div>${!staticView && selections.length ? `<details class="context-selection"><summary>Selected regions <span class="count">${selections.length}</span></summary>${selections.map((sel) => `<button class="target-selection" data-selection="${esc(sel.id)}"><strong>${esc(sel.name)}</strong><span class="selection-action">View source ${icon("arrow", 12)}</span>${state.mode === "expert" ? `<span class="mono">${esc(sel.native_selector.value)}</span>` : ""}</button>`).join("")}${structureIds.map(fileChip).join("")}${claim() ? '<button class="text-button" data-action="identify-regions">Edit region identities</button>' : ""}</details>` : ""}</section>${needsFigureType ? "" : staticView ? `<details class="panel source-panel"><summary>${icon("file", 14)} Figure sources</summary><div class="panel-body">${sourceFileIds().map(fileChip).join("") || "Link the analysis files in Evidence &amp; sources."}</div></details>` : `<details class="panel source-panel" id="source-panel"><summary>${icon("file", 14)} Scene source</summary><div class="source-toolbar">${native.length ? `<select id="source-select" aria-label="Scene source file">${native.map((id) => `<option value="${esc(id)}">${esc(fileName(id))}</option>`).join("")}</select><a class="text-button" id="source-download" href="${artifactURL(native[0], true)}" download>Download</a>` : "Add a saved scene to inspect its source."}</div><div id="source-content" class="source-lines"><p class="micro-note">Open to load the scene.</p></div></details>`}`;
}
function scopedTasks(includePackage = false) {
  return list(state.data?.workflow?.tasks).filter(
    (t) =>
      t.claim_id === state.claimId || (includePackage && t.scope === "package"),
  );
}
function taskRows(tasks, limit = 4) {
  const rows = tasks.map(
    (task, index) =>
      `<li class="decision-row"><div class="decision-number">${String(index + 1).padStart(2, "0")}</div><div><h3>${esc(task.title)}</h3>${state.view === "export" && task.claim_id ? `<div class="task-scope">${esc(list(semantic().claims).find((c) => c.id === task.claim_id)?.figure_ref || "Draft figure")} · ${esc(list(semantic().claims).find((c) => c.id === task.claim_id)?.claim_text.value)}</div>` : ""}<p>${esc(task.detail)}</p><button class="text-button" data-task="${esc(task.id)}">${esc(taskButton(task))} ${icon("arrow", 12)}</button></div></li>`,
  );
  return `<ol class="decision-list">${rows.slice(0, limit).join("")}</ol>${rows.length > limit ? `<details class="remaining-decisions"><summary>${rows.length - limit} more ${rows.length - limit === 1 ? "detail" : "details"}</summary><ol class="decision-list">${rows.slice(limit).join("")}</ol></details>` : ""}`;
}
function taskButton(task) {
  return (
    {
      "new-claim": "Add claim",
      "edit-claim": "Edit claim",
      "new-evidence": "Add evidence",
      "edit-evidence": "Complete evidence",
      cutoff: "Record cutoff",
      "new-uncertainty": "Add limitation",
      "identify-regions": "Identify regions",
      "explain-colors": "Explain visual meaning",
      "add-figure": "Add figure",
      "add-structure": "Add structure",
      attach: "Add files",
      answers: "Review technical record",
      "review-scene": "Review scene",
      "view-source": "View scene source",
      context: task.scene_id
        ? isStaticScene(
            list(semantic().scenes).find((s) => s.id === task.scene_id),
          )
          ? "Edit figure settings"
          : "Edit view details"
        : "Edit package details",
      "edit-uncertainty": "Complete limitation",
      "review-proposal": "Review suggestion",
    }[task.action] || "Review detail"
  );
}
function claimExample() {
  if (practice()?.claim?.claim_text) return practice().claim.claim_text;
  const scene = activeScene();
  if (untypedImage(scene)) return "";
  if (scene?.extensions?.view_kind === "figure_assembly")
    return "Two molecular views show the ligand and its surrounding pocket.";
  if (scene?.extensions?.view_kind === "plot")
    return "The sampled structures form four groups in the plotted data.";
  return "The teal markers identify residues 42 and 85 in chain A.";
}
function prepareView() {
  const proposedClaim = !list(semantic().claims).length && list(state.data?.workflow?.tasks).find((task) => task.action === "review-proposal");
  if (proposedClaim)
    return `<section class="decision-card"><div class="eyebrow">Statement awaiting review</div><h2>Review the suggested statement.</h2><p>Compare the proposed changes with their source files.</p>${taskRows([proposedClaim])}</section><section class="materials-note"><h3>Explore your files</h3><p>Open the figure and its supporting files.</p><button class="text-button" data-action="files">Browse files ${icon("arrow", 12)}</button></section>`;
  if (!claim())
    return `<section class="decision-card"><div class="eyebrow">Start with one sentence</div><h2>Write the statement for this figure.</h2><p>Use one sentence from your figure legend.</p>${claimExample() ? `<div class="sentence-example">${esc(claimExample())}</div>` : ""}<button class="button" data-action="new-claim">Add claim ${icon("arrow", 13)}</button></section><section class="materials-note"><h3>Explore your files</h3><p>Open the figure and its supporting files.</p><button class="text-button" data-action="files">Browse files ${icon("arrow", 12)}</button></section>${
      list(state.data?.workflow?.tasks).some(
        (t) => t.scope === "package" && t.action !== "new-claim",
      )
        ? `<section class="decision-card"><h2>Files to complete</h2>${taskRows(
            list(state.data.workflow.tasks).filter(
              (t) => t.scope === "package" && t.action !== "new-claim",
            ),
            2,
          )}</section>`
        : ""
    }`;
  const tasks = scopedTasks(),
    packageTasks = list(state.data?.workflow?.tasks).filter(
      (t) => t.scope === "package",
    );
  return `<section class="decision-card"><div class="section-heading"><h2>${tasks.length ? "Details to complete" : "Claim details saved"}</h2><span class="small muted">${tasks.length ? `${tasks.length} ${tasks.length === 1 ? "question" : "questions"}` : "Saved locally"}</span></div>${tasks.length ? taskRows(tasks, 3) : '<p>Review the figure, its support, and the limits of the claim.</p><button class="button" data-view="review">Review record ' + icon("arrow", 13) + "</button>"}</section><section class="recorded-details"><div class="section-heading"><h2>Claim details</h2></div><details class="disclosure"><summary>Evidence &amp; sources <span class="count">${linkedEvidence().length}</span></summary><div class="panel-body">${evidencePanel()}</div></details>${!linkedUncertainty().length && ["simple_structure_view", "selection_highlight"].includes(claim().claim_type) ? `<div class="optional-record"><div><h3>Limitations <span class="small muted">Optional</span></h3><p>Add an assumption or alternative when it affects this claim.</p></div><button class="text-button" data-action="new-uncertainty">Add limitation</button></div>` : `<details class="disclosure"><summary>Limitations <span class="count">${linkedUncertainty().length}</span></summary><div class="panel-body">${uncertaintyPanel()}</div></details>`}<details class="disclosure"><summary>${staticClaim() ? "Figure settings &amp; sources" : "Scene meaning &amp; replay"}</summary><div class="panel-body"><div class="context-actions">${linkedScenes().some((s) => list(s.selection_ids).length) ? '<button class="text-button" data-action="identify-regions">Identify regions</button>' : ""}${linkedScenes().some((s) => list(s.native_artifact_ids).length) ? '<button class="text-button" data-action="explain-colors">Explain visual meaning</button>' : ""}<button class="text-button" data-action="context">${staticClaim() ? "Edit figure settings" : "Edit view details"}</button></div>${reproducibilityPanel()}</div></details></section>${packageTasks.length ? `<div class="package-task-note"><span>${packageTasks.length} package ${packageTasks.length === 1 ? "detail" : "details"} to review</span><button class="text-button" data-view="export">Prepare export ${icon("arrow", 12)}</button></div>` : ""}${tasks.length ? `<div class="view-footer"><button class="text-button" data-view="review">Review record ${icon("arrow", 13)}</button></div>` : ""}`;
}
function reviewView() {
  if (!list(semantic().claims).length && list(state.data?.workflow?.tasks).some((task) => task.action === "review-proposal"))
    return prepareView();
  if (!claim())
    return `<section class="decision-card"><h2>Create the first claim record</h2><p>Add the statement that connects this figure to its supporting files.</p><button class="button" data-action="new-claim">Add claim</button></section>`;
  const evidence = linkedEvidence(),
    limits = linkedUncertainty(),
    scene = activeScene();
  const values = {
    claim: claim().claim_text.value,
    visual: isStaticScene(scene)
      ? sceneLabel(scene)
      : `${scene ? sceneLabel(scene) : "Link a scene"} · ${
          byIds(semantic().selections, scene?.selection_ids)
            .map((s) => s.name)
            .join(", ") ||
          (list(scene?.native_artifact_ids).length
            ? "Selected regions to record"
            : "Figure image")
        }`,
    provenance:
      evidence
        .map((e) =>
          [
            known(e.result_summary) ? e.result_summary : "Finding to record",
            auditFileSummary(e.source_artifact_ids),
          ]
            .filter(Boolean)
            .join(" · "),
        )
        .join(" ") || "Add the supporting observation and its source.",
    uncertainty:
      limits.map((u) => u.statement).join(" ") ||
      (["simple_structure_view", "selection_highlight"].includes(
        claim().claim_type,
      )
        ? "Optional for a descriptive claim."
        : "Record the relevant limits and alternatives."),
    reproducibility: linkedScenes().some(isStaticScene)
      ? list(audit()?.stages).find((stage) => stage.key === "reproducibility")
          ?.summary.replace(". Molecular replay: not applicable. Package validation is reported separately.", ".") || "Record the figure sources and settings."
      : linkedScenes().length
        ? `${linkedScenes().filter(hasCamera).length}/${linkedScenes().length} views recorded · ${linkedScenes().every((s) => list(s.native_artifact_ids).length) ? "Scene files attached" : "Scene file to add"} · Replay pending`
        : "Link a saved scene to this claim.",
  };
  return `<section class="review-record"><div class="section-heading"><h2>Claim audit</h2><a class="text-button" href="${esc(packageURL("/api/audit?format=md"))}" download>Download summary</a></div><div class="audit-record">${list(
    audit()?.stages,
  )
    .map(
      (stage) =>
        `<button class="audit-row" data-tab="${stageTab(stage.key)}" aria-expanded="${state.tab === stageTab(stage.key)}"><span class="audit-label">${esc(stageNames[stage.key])}<span class="audit-state">${esc(statusNames[stage.status] || stage.status)}</span></span><span class="audit-value">${esc(values[stage.key])}</span><span aria-hidden="true">${icon("arrow", 13)}</span></button>`,
    )
    .join(
      "",
    )}</div><p class="audit-reading-hint">${staticClaim() ? "Open a row to inspect the figure, sources, and analysis settings." : "Recorded details are saved in this package. Open a row to inspect them. Scene replay is checked in the original molecular viewer."}</p><section class="audit-inspector" id="audit-panel" tabindex="-1">${auditRowQuestions()}${({ claim: claimPanel, visual: visualDetails, evidence: evidencePanel, uncertainty: uncertaintyPanel, reproducibility: reproducibilityPanel }[state.tab] || visualDetails)()}</section></section><div class="view-footer"><button class="text-button" data-view="prepare">Edit record</button><button class="button secondary small" data-view="export">Prepare export ${icon("arrow", 13)}</button></div>`;
}
function proposalClaimIds(proposal) {
  const candidates = [proposal.claim_id, ...list(proposal.changes).flatMap((change) => [change.claim_id, change.record_type === "claim" ? change.record_id : null])];
  return [...new Set(candidates.filter((id) => id && list(semantic().claims).some((item) => item.id === id)))];
}
function scopedProposals() {
  return list(state.data?.proposals).filter((proposal) => {
    const ids = proposalClaimIds(proposal);
    return !ids.length || ids.includes(state.claimId);
  });
}
function proposalActor(proposal) {
  const actor = proposal.actor || {};
  return [actor.name || "Agent", actor.model, actor.version].filter(Boolean).join(" · ");
}
function proposalSceneIds(proposal) {
  const ids = list(proposal.changes).flatMap((change) => [change.record_type === "scene" ? change.record_id : null, ...list(change.fields?.scene_ids)]);
  for (const id of proposalClaimIds(proposal)) ids.push(...list(list(semantic().claims).find((item) => item.id === id)?.scene_ids));
  return [...new Set(ids.filter((id) => list(semantic().scenes).some((scene) => scene.id === id)))];
}
function proposalStatus(proposal) {
  return ({ pending: "Awaiting review", accepted: "Accepted", rejected: "Rejected", reverted: "Reverted" })[proposal.status] || proposal.status;
}
function proposalSection() {
  const proposals = scopedProposals();
  if (!proposals.length) return "";
  const pending = proposals.filter((item) => item.status === "pending");
  const history = proposals.filter((item) => item.status !== "pending");
  const card = (proposal) => `<article class="proposal-card"><div class="record-header"><h3>${esc(proposal.title || "Suggested update")}</h3><span class="small muted">${esc(proposalStatus(proposal))}</span></div><p class="proposal-actor">${esc(proposalActor(proposal))}</p>${proposal.rationale ? `<p>${esc(proposal.rationale)}</p>` : ""}${list(proposal.source_artifact_ids).length ? `<div class="proposal-sources">${list(proposal.source_artifact_ids).map(fileChip).join("")}</div>` : ""}<div class="proposal-actions"><button class="button secondary small" data-proposal="${esc(proposal.id)}">${proposal.status === "pending" ? "Review suggestion" : "View decision"} ${icon("arrow", 12)}</button>${proposalClaimIds(proposal).length ? `<button class="text-button" data-proposal-locate="${esc(proposal.id)}">Open claim</button>` : '<span class="small muted">New record</span>'}${proposalSceneIds(proposal).map((id, index, ids) => `<button class="text-button" data-proposal-scene="${esc(id)}" data-proposal-owner="${esc(proposal.id)}" title="${esc(sceneLabel(list(semantic().scenes).find((scene) => scene.id === id)))}">Open scene${ids.length > 1 ? ` ${index + 1}` : ""}</button>`).join("")}</div></article>`;
  return `<section class="proposal-section" aria-labelledby="proposal-section-title"><div class="section-heading"><h2 id="proposal-section-title" tabindex="-1">Agent suggestions</h2>${pending.length ? `<span class="small muted">${pending.length} awaiting review</span>` : ""}</div>${pending.map(card).join("")}${history.length ? `<details class="proposal-history"><summary>Reviewed suggestions <span class="count">${history.length}</span></summary>${history.map(card).join("")}</details>` : ""}</section>`;
}
function proposalValue(value) {
  if (value === null || value === undefined || value === "") return '<span class="muted">Empty</span>';
  if (Array.isArray(value)) return value.length ? value.map(proposalValue).join("<br>") : '<span class="muted">Empty</span>';
  if (typeof value === "object") return state.mode === "expert" ? `<pre class="proposal-object">${esc(pretty(value))}</pre>` : `<dl class="proposal-values">${Object.entries(value).map(([key, item]) => `<dt>${esc(key.replace(/_/g, " "))}</dt><dd>${proposalValue(item)}</dd>`).join("")}</dl>`;
  const item = [...list(semantic().artifacts), ...list(semantic().scenes), ...list(semantic().selections), ...list(semantic().entities)].find((record) => record.id === value);
  if (item) return esc(item.path || item.name || item.label || item.description || value);
  return esc(value);
}
function proposalCurrentValue(item) {
  const collection = ({ claim: "claims", evidence: "evidence", uncertainty: "uncertainty", scene: "scenes", selection: "selections", entity: "entities" })[item.record_type];
  const record = list(semantic()[collection]).find((entry) => entry.id === item.record_id);
  if (!record) return null;
  if (["claim_text", "native_selector"].includes(item.field)) return record[item.field]?.value ?? null;
  if (item.field === "accessibility") return record.extensions?.accessibility || {};
  return record[item.field] ?? null;
}
function proposalFieldValue(item, value) {
  const labels = ({ claim_type: types, evidence_kind: evidenceKinds, category: limitationCategories })[item.field];
  return proposalValue(labels && typeof value === "string" ? labels[value] || value.replace(/_/g, " ") : value);
}
function proposalDiff(proposal, original = false) {
  const accepted = !original && list(proposal.accepted_diff).length > 0;
  const items = accepted ? proposal.accepted_diff : proposal.diff;
  return `<div class="proposal-diff">${list(items).map((item) => {
    const current = proposal.status === "pending" ? proposalCurrentValue(item) : item.before;
    const changed = proposal.status === "pending" && pretty(current) !== pretty(item.before);
    return `<section class="proposal-change"><h3>${esc(item.label || item.field)}</h3>${state.mode === "expert" ? `<p class="small muted">${esc(item.record_type)} · ${esc(item.record_id)}</p>` : ""}<div class="proposal-comparison"><div><span class="proposal-column-label">${proposal.status === "pending" ? "Current" : "Before"}</span><div>${proposalFieldValue(item, current)}</div>${changed ? `<details class="proposal-original"><summary>When suggested</summary>${proposalFieldValue(item, item.before)}</details>` : ""}</div><div><span class="proposal-column-label">${accepted ? proposal.status === "reverted" ? "Accepted, then reverted" : "Accepted" : "Proposed"}</span><div>${proposalFieldValue(item, item.after)}</div></div></section>`;
  }).join("")}</div>`;
}
function proposalEditableFields(proposal) {
  return list(proposal.changes).flatMap((change, index) => Object.entries(change.fields || {}).map(([key, value]) => {
    const diff = list(proposal.diff).find((item) => item.record_type === change.record_type && item.record_id === change.record_id && item.field === key);
    return { index, key, value, name: `proposal_${index}_${key}`, label: diff?.label || key.replace(/_/g, " "), complex: value !== null && typeof value === "object" };
  }));
}
function proposalEdits(proposal, form) {
  const changes = JSON.parse(JSON.stringify(proposal.changes));
  for (const field of proposalEditableFields(proposal)) {
    if (!form.has(field.name)) continue;
    const text = String(form.get(field.name));
    let value = text;
    if (field.complex) {
      try { value = JSON.parse(text); } catch { throw fieldError(`Enter valid JSON for ${field.label.toLowerCase()}.`, field.name); }
      if (Array.isArray(field.value) !== Array.isArray(value) || value === null || typeof value !== "object")
        throw fieldError(`Keep the same data format for ${field.label.toLowerCase()}.`, field.name);
    } else if (typeof field.value === "number") {
      value = Number(text);
      if (!text.trim() || !Number.isFinite(value)) throw fieldError(`Enter a number for ${field.label.toLowerCase()}.`, field.name);
    } else if (typeof field.value === "boolean") value = text === "true";
    else if (field.value === null && !text) value = null;
    changes[field.index].fields[field.key] = value;
  }
  return changes;
}
function proposalReviewForm(id, decision = "accept", edit = false) {
  const proposal = list(state.data?.proposals).find((item) => item.id === id);
  if (!proposal) { toast("Refresh the package to review this suggestion.", true); return; }
  const prior = $("#dialog-form")?.dataset.proposal === id ? new FormData($("#dialog-form")) : null;
  const sources = list(proposal.source_artifact_ids).map((source) => `<button type="button" class="file-chip" data-inline-file="${esc(source)}">${icon("file", 13)}${esc(fileName(source))}</button>`).join("");
  const context = `<div class="proposal-review-context"><p class="proposal-actor">${esc(proposalActor(proposal))}</p>${proposal.rationale ? `<p>${esc(proposal.rationale)}</p>` : ""}${sources ? `<div class="proposal-sources">${sources}</div><div id="inline-file-preview" class="inline-file-preview" hidden></div>` : ""}</div>`;
  if (proposal.status !== "pending" && decision !== "revert") {
    const review = proposal.review || {};
    const original = proposal.accepted_diff && pretty(proposal.accepted_diff) !== pretty(proposal.diff) ? `<details class="disclosure"><summary>Original suggestion</summary>${proposalDiff(proposal, true)}</details>` : "";
    const history = list(proposal.review_history).length > 1 ? `<details class="disclosure"><summary>Review history</summary><div class="panel-body">${proposal.review_history.map((item) => `<p><strong>${esc(({ accept: "Accepted", reject: "Rejected", revert: "Reverted" })[item.decision] || item.decision)}</strong> · ${esc(item.reviewer)} · ${esc(item.reviewed_at)}${item.note ? `<br>${esc(item.note)}` : ""}</p>`).join("")}</div></details>` : "";
    dialog(proposal.title || "Reviewed suggestion", proposalStatus(proposal), `<div class="dialog-body">${context}${proposalDiff(proposal)}${original}<dl class="key-value"><dt>Reviewed by</dt><dd>${esc(review.reviewer || "Recorded reviewer")}</dd><dt>Reviewed at</dt><dd>${esc(review.reviewed_at || "")}</dd>${review.note ? `<dt>Review note</dt><dd>${esc(review.note)}</dd>` : ""}</dl>${history}</div>`, `<div class="dialog-footer">${proposal.status === "accepted" ? `<button class="button secondary" data-proposal-review="${esc(id)}" data-decision="revert">Revert changes</button>` : ""}<button class="button" data-action="close-dialog">Close</button></div>`, true);
    $("#dialog-title").tabIndex = -1;
    $("#dialog-title").focus();
    return;
  }
  const fields = proposalEditableFields(proposal);
  const editable = fields.filter((item) => !item.complex || state.mode === "expert");
  const editFields = edit ? `<fieldset class="proposal-edit-fields"><legend>Your revision</legend>${editable.map((item) => {
    const value = prior?.has(item.name) ? prior.get(item.name) : item.complex ? pretty(item.value) : item.value;
    const choices = ({ claim_type: types, evidence_kind: evidenceKinds, category: limitationCategories })[item.key];
    if (choices) return `<div class="form-field"><label for="f-${esc(item.name)}">${esc(item.label)}</label><select id="f-${esc(item.name)}" name="${esc(item.name)}">${Object.entries(String(value) in choices ? choices : { ...choices, [value]: String(value).replace(/_/g, " ") }).map(([key, label]) => `<option value="${esc(key)}" ${String(value) === key ? "selected" : ""}>${esc(label)}</option>`).join("")}</select></div>`;
    if (typeof item.value === "boolean") return `<div class="form-field"><label for="f-${esc(item.name)}">${esc(item.label)}</label><select id="f-${esc(item.name)}" name="${esc(item.name)}"><option value="true" ${String(value) === "true" ? "selected" : ""}>Yes</option><option value="false" ${String(value) === "false" ? "selected" : ""}>No</option></select></div>`;
    return typeof item.value === "number" ? field(item.label, item.name, value, "number") : textfield(item.label, item.name, value, item.complex ? "JSON data" : "");
  }).join("")}${fields.length > editable.length ? '<p class="micro-note">Additional fields are available in Expert mode.</p>' : ""}</fieldset>` : "";
  const label = decision === "reject" ? "Reject suggestion" : decision === "revert" ? "Revert changes" : edit ? "Save & accept" : "Accept suggestion";
  formDialog(decision === "accept" && !edit ? "Review suggestion" : label, proposal.title || "Suggested update", `${context}${proposalDiff(proposal)}${editFields}${decision === "accept" && !edit ? `<div class="proposal-review-options"><button type="button" class="text-button" data-proposal-review="${esc(id)}" data-decision="edit">Edit suggested values</button><button type="button" class="text-button" data-proposal-review="${esc(id)}" data-decision="reject">Reject suggestion</button></div>` : ""}${field("Your name", "reviewer", prior?.get("reviewer") || state.reviewer, "text", "Name or initials for this review.")}${textfield("Review note (optional)", "review_note", prior?.get("review_note") || "")}`, async (form) => {
    const reviewer = String(form.get("reviewer") || "").trim();
    if (!reviewer) throw fieldError("Enter your name or initials.", "reviewer");
    const body = { id, decision, reviewer, note: String(form.get("review_note") || "").trim() };
    if (decision === "accept" && edit) body.changes = proposalEdits(proposal, form);
    const newClaim = decision === "accept" && list(proposal.changes).find((change) => change.record_type === "claim" && !list(semantic().claims).some((item) => item.id === change.record_id))?.record_id;
    const message = decision === "reject" ? "Suggestion rejected. Decision saved." : decision === "revert" ? "Accepted changes reverted." : edit ? "Revision accepted. Record updated." : "Suggestion accepted. Record updated.";
    await mutate("/api/proposal-review", body, message);
    state.reviewer = reviewer;
    const linked = proposalClaimIds(proposal);
    if (newClaim || (!state.claimId && linked.length)) { state.claimId = newClaim || linked[0]; state.sceneId = null; updateDetail(); }
    dialogOpener = $("#proposal-section-title") || $("#main");
  }, label, true);
  $("#dialog-form").dataset.proposal = id;
  $("#dialog-title").tabIndex = -1;
  $("#dialog-title").focus();
}
function auditFileSummary(ids) {
  const names = [...new Set(list(ids))].map(fileName);
  const remaining = names.length - 2;
  return names.slice(0, 2).join(", ") + (remaining > 0 ? ` · ${remaining} more ${remaining === 1 ? "file" : "files"}` : "");
}
function auditRowQuestions() {
  const section = list(audit()?.stages).find((stage) => stageTab(stage.key) === state.tab)?.key;
  const rules = new Set(list(audit()?.issues)
    .filter((item) => item.section === section && item.status === "FAIL")
    .map((item) => item.rule_id).filter(Boolean));
  const tasks = scopedTasks().filter((task) => list(task.rule_ids).some((rule) => rules.has(rule)));
  return tasks.length ? `<div class="audit-row-questions">${taskRows(tasks, 3)}</div>` : "";
}
function visualDetails() {
  if (isStaticScene(activeScene())) {
    const scene = activeScene();
    return `<div class="section-heading"><h2>Visual evidence</h2></div><dl class="key-value"><dt>Figure</dt><dd>${esc(sceneLabel(scene))}</dd><dt>Saved output</dt><dd>${list(scene.render_artifact_ids).map(fileChip).join("") || "Attach the saved figure."}</dd><dt>${scene.extensions.view_kind === "figure_assembly" ? "Assembly settings" : "Plot settings"}</dt><dd>${hasViewContext(scene) ? esc(authorContextText(scene)) : "Record the figure settings."} <button class="text-button" data-action="context">Edit settings</button></dd><dt>Source files</dt><dd>${sourceFileIds().map(fileChip).join("") || "Link supporting files in Evidence &amp; sources."}</dd></dl>`;
  }
  const scene = activeScene(),
    selections = byIds(semantic().selections, scene?.selection_ids);
  const entityIds = [
    ...new Set([
      ...list(scene?.entity_ids),
      ...selections.flatMap((s) => list(s.entity_ids)),
    ]),
  ];
  return `<div class="section-heading"><h2>Visual evidence</h2></div><dl class="key-value"><dt>Scene</dt><dd>${esc(sceneLabel(scene))}</dd><dt>Selected regions</dt><dd>${selections.map((sel) => `<button class="file-chip" data-selection="${esc(sel.id)}">${esc(sel.name)} ${icon("arrow", 12)}</button>`).join("") || (list(scene?.native_artifact_ids).length ? "Selections to record" : "See the figure and statement")}</dd><dt>Molecular identity</dt><dd>${
    byIds(semantic().entities, entityIds)
      .map(
        (e) =>
          `<div>${esc(e.label)} ${list(e.source_artifact_ids).map(fileChip).join("")}</div>`,
      )
      .join("") ||
    (selections.length
      ? '<button class="text-button" data-action="identify-regions">Identify regions</button>'
      : '<span>Link identities from scene and structure files.</span> <button class="text-button" data-action="attach">Add scene files</button>')
  }</dd><dt>Camera &amp; state</dt><dd>${viewDescription(scene)} <button class="text-button" data-action="view-source">View source</button></dd></dl>`;
}
function exportView() {
  const lifecycle = state.data?.workflow?.lifecycle || {
    mode: "draft",
    ready: false,
    blocking_count: 0,
  };
  const purposes = [
    ["draft", "Working draft", "Save a portable work in progress."],
    ["internal", "Lab handoff", "Share within your project."],
    ["share", "External review", "Prepare a collaborator or reviewer copy."],
    ["archive", "Archive", "Preserve a self-contained record."],
  ];
  const blockers = list(state.data?.workflow?.tasks).filter((t) => t.blocking);
  return `<div class="claim-heading-meta"><span class="claim-ref">Package handoff</span><span class="small muted">${list(semantic().claims).length} ${list(semantic().claims).length === 1 ? "claim" : "claims"} · ${list(semantic().artifacts).length} files</span></div><div class="claim-heading"><h1>Prepare your review package.</h1></div><p class="export-intro">Choose the purpose of this copy.</p><div class="purpose-options" role="group" aria-label="Export purpose">${purposes.map(([mode, label, hint]) => `<button data-lifecycle="${mode}" aria-pressed="${lifecycle.mode === mode}"><strong>${label}</strong><span>${hint}</span></button>`).join("")}</div><section class="export-readiness"><div><h2>${lifecycle.ready ? (lifecycle.mode === "draft" ? "Draft checks passed" : `${esc(purposes.find((p) => p[0] === lifecycle.mode)?.[1])} checks passed`) : `${lifecycle.blocking_count} ${lifecycle.blocking_count === 1 ? "requirement" : "requirements"} to complete`}</h2><p>${lifecycle.mode === "draft" ? "Open questions stay with the exported draft." : "Checks cover the files and linked records for this purpose."}</p></div><button class="text-button" data-action="refresh">${icon("refresh")} Check again</button></section>${blockers.length ? `<section class="export-tasks"><h2>Before exporting</h2>${taskRows(blockers, 4)}</section>` : ""}${
    list(state.data?.workflow?.tasks).some((t) => !t.blocking)
      ? `<details class="export-tasks open-record-questions"><summary>${list(state.data?.workflow?.tasks).filter((t) => !t.blocking).length} open record ${list(state.data?.workflow?.tasks).filter((t) => !t.blocking).length === 1 ? "question" : "questions"}</summary>${taskRows(
          list(state.data?.workflow?.tasks).filter((t) => !t.blocking),
          3,
        )}</details>`
      : ""
  }<div id="export-feedback" role="status" hidden></div><div class="export-deliverables"><section class="delivery-card"><span class="eyebrow">Complete handoff</span><h2>Review package</h2><p>${staticPackage() ? "Figures, analysis data, evidence, and the claim record." : "Native scenes, figures, data, evidence, and the claim record."} Includes checks and recipient instructions.</p><button class="button" data-action="download-package" ${lifecycle.ready ? "" : "disabled"}>${icon("download")} Download package · ZIP</button><small>Validated again after assembly.</small></section><section class="delivery-card"><span class="eyebrow">Quick inspection</span><h2>Audit summary</h2><p>The short claim → evidence → provenance → uncertainty → reproducibility record, including open questions.</p><a class="button secondary" href="${esc(packageURL("/api/audit?format=md"))}" download>${icon("download")} Download summary · Markdown</a>${state.mode === "expert" ? `<a class="text-button" href="${esc(packageURL("/api/audit?format=json"))}" download>Download audit JSON</a>` : ""}</section></div><div class="view-footer"><button class="text-button" data-action="context">Edit software &amp; reuse details</button></div><p class="replay-status">${staticPackage() ? "Package checks cover saved figures, source files, and records. Review analysis settings alongside the evidence." : "Package checks cover saved files and records. To verify scene replay, open the scene in its original molecular viewer."}</p>${state.mode === "expert" ? `<details class="disclosure"><summary>Validation findings · ${esc(lifecycle.mode)}</summary><div class="panel-body">${findingsHTML(list(state.data?.report?.findings).filter((f) => f.status === "FAIL"))}</div></details>` : ""}`;
}
function hasIssue(...rules) {
  return list(audit()?.issues).some(
    (i) => i.status === "FAIL" && rules.includes(i.rule_id),
  );
}
function claimPanel() {
  const c = claim();
  return `<div class="section-heading"><h2>Claim record</h2><button class="button secondary small" data-action="edit-claim">Edit claim</button></div><div class="evidence-card"><dl class="key-value"><dt>Figure label</dt><dd>${esc(c.figure_ref)}</dd><dt>Claim type</dt><dd>${esc(types[c.claim_type] || c.claim_type)}</dd><dt>${staticClaim() ? "Linked figures" : "Linked scenes"}</dt><dd>${
    linkedScenes()
      .map((scene) => esc(sceneLabel(scene)))
      .join("<br>") || "Choose a scene"
  }</dd><dt>Author review</dt><dd>${esc(reviewLabel(c.review_status))}</dd></dl></div>`;
}
function sceneLabel(scene) {
  const paths = list(scene?.native_artifact_ids)
    .map((id) => artifact(id)?.path?.split("/").pop())
    .filter(Boolean);
  const label = scene?.description;
  if (/^Static image scene/i.test(label || ""))
    return (
      list(scene?.render_artifact_ids).map(fileName).join(", ") ||
      "Figure image"
    );
  return label && !/^Draft scene|^Imported|^Scene from/i.test(label)
    ? label
    : paths.join(", ") || label || "Figure scene";
}
function reviewLabel(status) {
  return (
    {
      confirmed: "Author confirmed",
      human_accepted: "Author accepted",
      auto_extracted: "Extracted from scene",
      needs_review: "Author review pending",
      rejected: "Rejected",
      superseded: "Superseded",
    }[status] || status
  );
}
function categoryLabel(category) {
  const text = String(category || "general").replaceAll("_", " ");
  return (
    limitationCategories[category] ||
    text.charAt(0).toUpperCase() + text.slice(1)
  );
}
function displayValue(value) {
  return typeof value === "object"
    ? Object.entries(value || {})
        .map(
          ([key, val]) =>
            `${key}: ${Array.isArray(val) ? val.join(", ") : String(val)}`,
        )
        .join(" · ")
    : String(value ?? "");
}
function sharedRecord(record, kind) {
  return (
    record &&
    list(semantic().claims).filter(
      (c) =>
        list(c[`${kind}_ids`]).includes(record.id) ||
        list(record.claim_ids).includes(c.id),
    ).length > 1
  );
}
function stageTab(key) {
  return (
    {
      claim: "claim",
      visual: "visual",
      provenance: "evidence",
      evidence: "evidence",
      uncertainty: "uncertainty",
      reproducibility: "reproducibility",
    }[key] || key
  );
}
function fileName(id) {
  const a = artifact(id);
  return (a?.path || a?.url || id).split("/").pop();
}
function fileRole(file) {
  const labels = {
    native_script: "Scene script",
    chimerax_script: "ChimeraX script",
    molviewspec: "MolViewSpec scene",
    render_image: "Figure image",
    structure: "Structure",
    contact_table: "Contact table",
    validation_report: "Validation report",
    evidence_document: "Supporting document",
    map: "Density map",
    trajectory: "Trajectory",
    topology: "Topology",
    package_metadata: "Package details",
    session: "Viewer session",
    native_session: "Viewer session",
    directory: "Folder",
    generic: /\.csv$/i.test(file.path || "") ? "Table" : "File",
  };
  return labels[file.role] || file.role.replaceAll("_", " ");
}
function fileChip(id) {
  const a = artifact(id);
  return a
    ? `<button class="file-chip" data-file="${esc(id)}" title="Open ${esc(a.path || a.url || id)}">${icon("file", 13)}${esc(fileName(id))}</button>`
    : `<span class="inline-empty">Locate file: ${esc(id)}</span>`;
}
function sourceWithinScene(source, scene) {
  if (!list(scene?.native_artifact_ids).includes(source?.artifact_id))
    return false;
  const prefix = scene?.extensions?.molviewspec_root?.json_pointer;
  if (!prefix) return true;
  const pointer = source?.json_pointer || "";
  return (
    pointer === prefix || pointer.startsWith(prefix.replace(/\/$/, "") + "/")
  );
}
function hasCamera(s) {
  const metadata = new Set([
    "source_type",
    "review_status",
    "status",
    "confidence",
    "source_location",
    "json_pointer",
    "source_path",
    "artifact_id",
    "line",
    "column",
    "reviewer",
    "reviewed_at",
  ]);
  const placeholders = new Set([
    "",
    "unknown",
    "unspecified",
    "todo",
    "tbd",
    "none",
    "null",
    "n/a",
    "na",
    "not applicable",
    "not_applicable",
  ]);
  const recorded = (value) => {
    if (value === null || value === undefined) return false;
    if (Array.isArray(value)) return value.length > 0 && value.every(recorded);
    if (typeof value === "object")
      return Object.entries(value).some(
        ([key, item]) => !metadata.has(key) && recorded(item),
      );
    if (typeof value === "number") return Number.isFinite(value);
    const text = String(value).trim().toLowerCase();
    return (
      !placeholders.has(text) &&
      !text.startsWith("todo") &&
      !text.startsWith("tbd")
    );
  };
  return recorded(s?.camera);
}
function viewDescription(scene) {
  if (isStaticScene(scene))
    return hasViewContext(scene)
      ? "Figure settings recorded"
      : "Figure settings to add";
  const { author_context, author_context_provenance, ...nativeCamera } =
    scene?.camera || {};
  if (hasCamera({ camera: nativeCamera })) return "Saved in the scene file";
  return known(author_context)
    ? "View described by the author"
    : "View details needed";
}
function evidencePanel() {
  const records = linkedEvidence();
  return `<div class="section-heading"><h2>Evidence &amp; sources</h2>${records.length ? '<button class="button secondary small" data-action="new-evidence">Add evidence</button>' : ""}</div>${
    records
      .map(
        (e) =>
          `<article class="evidence-card"><div class="record-header"><h3>${esc(known(e.method_name) ? e.method_name : evidenceKinds[e.evidence_kind] || "Evidence")}</h3><button class="text-button" data-edit-evidence="${esc(e.id)}">Edit evidence</button></div><p>${esc(known(e.result_summary) ? e.result_summary : "Describe the observation and its relevance to this claim.")}</p><dl class="record-detail"><dt>Source files</dt><dd>${list(e.source_artifact_ids).map(fileChip).join("") || `<button class="text-button" data-edit-evidence="${esc(e.id)}">Link a source file</button>`}</dd>${
            e.evidence_kind === "contact_table" ||
            Object.keys(e.thresholds || {}).length
              ? `<dt>Cutoff</dt><dd>${
                  Object.entries(e.thresholds || {})
                    .map(
                      ([key, value]) =>
                        `${esc(displayValue(value))} ${esc(e.units?.[key] || "unit needed")}${key !== "distance" ? ` (${esc(key)})` : ""}`,
                    )
                    .join(" · ") ||
                  `<button class="text-button" data-edit-evidence="${esc(e.id)}">Add cutoff &amp; unit</button>`
                }</dd>`
              : ""
          } ${e.evidence_kind === "measurement" ? `<dt>Measured distance</dt><dd>${e.parameters?.measured_distance != null ? `${esc(e.parameters.measured_distance)} ${esc(e.units?.distance || "unit needed")}` : `<button class="text-button" data-edit-evidence="${esc(e.id)}">Add measured distance</button>`}</dd>` : ""} ${known(e.parameters?.analysis_settings) ? `<dt>Analysis settings</dt><dd>${esc(e.parameters.analysis_settings)}</dd>` : ""}<dt>Review</dt><dd>${esc(reviewLabel(e.review_status))}</dd>${state.mode === "expert" ? `<dt>Parameters</dt><dd><pre>${esc(pretty(e.parameters))}</pre></dd><dt>Provenance</dt><dd><code>${esc(e.provenance_id || "Record pending")}</code></dd>` : ""}</dl></article>`,
      )
      .join("") ||
    '<div class="empty-panel"><h3>Add the supporting result</h3><p>Describe how you checked the claim, what you found, and which file contains the result.</p><button class="button" data-action="new-evidence">Add evidence</button></div>'
  }`;
}
function uncertaintyPanel() {
  const records = linkedUncertainty();
  return `<div class="section-heading"><h2>Limitations</h2>${records.length ? '<button class="button secondary small" data-action="new-uncertainty">Add limitation</button>' : ""}</div>${records.map((u) => `<article class="evidence-card"><div class="record-header"><h3>${esc(categoryLabel(u.category))}</h3><button class="text-button" data-edit-uncertainty="${esc(u.id)}">Edit limitation</button></div><p>${esc(u.statement)}</p>${list(u.alternative_explanations).length ? `<p class="muted">${esc(u.alternative_explanations.join("; "))}</p>` : ""}<div class="claim-context">${esc(reviewLabel(u.review_status))}</div></article>`).join("") || `<div class="empty-panel"><h3>Describe the limits of the claim</h3><p>${["simple_structure_view", "selection_highlight"].includes(claim()?.claim_type) ? "Optional for descriptive views. Add a limitation when the interpretation depends on a model, selection, or method." : "Include relevant assumptions, alternative poses, or limits of the analysis."}</p><button class="button" data-action="new-uncertainty">Add limitation</button></div>`}`;
}
function reproducibilityPanel() {
  if (staticClaim()) {
    const scenes = linkedScenes(),
      env = list(semantic().software_environment);
    const stage = list(audit()?.stages).find(
      (item) => item.key === "reproducibility",
    );
    return `<div class="section-heading"><h2>Figure &amp; analysis</h2>${badge(stage?.status || "review")}</div><div class="evidence-card"><dl class="key-value"><dt>Saved figures</dt><dd>${[...new Set(scenes.flatMap((s) => list(s.render_artifact_ids)))].map(fileChip).join("") || "Attach the saved figure."}</dd><dt>Analysis or assembly settings</dt><dd>${scenes.map((scene) => `<div><strong>${esc(sceneLabel(scene))}</strong><p>${hasViewContext(scene) ? esc(authorContextText(scene)) : "Record the figure settings."}</p></div>`).join("")}</dd><dt>Source files</dt><dd>${sourceFileIds().map(fileChip).join("") || "Link the supporting analysis files."}</dd><dt>Recorded software</dt><dd>${env.map((e) => `${esc(e.name)} ${esc(e.version)}`).join("<br>") || "Software details pending"}</dd><dt>Package check · ${esc(lifecycleLabel())}</dt><dd>${badge(state.data?.report?.overall_status || "needs_review")}</dd></dl></div><div class="replay-note"><p>Review the saved figure, source files and settings.</p><button class="button secondary small" data-action="context">Edit figure settings</button></div>`;
  }
  const scenes = linkedScenes(),
    env = list(semantic().software_environment);
  const native = scenes.flatMap((s) => list(s.native_artifact_ids));
  return `<div class="section-heading"><h2>Scene &amp; replay</h2>${badge("review", "Replay pending")}</div><div class="evidence-card"><dl class="key-value"><dt>Scene files</dt><dd>${
    scenes
      .flatMap((s) => list(s.native_artifact_ids))
      .map(fileChip)
      .join("") || "Scene file needed"
  }</dd><dt>View details</dt><dd>${scenes.map((s) => `<div>${esc(sceneLabel(s))} <span class="muted">· ${hasViewContext(s) ? "Recorded" : isStaticScene(s) ? "Figure settings needed" : "View details needed"}</span>${state.mode === "expert" && hasViewContext(s) ? `<pre>${esc(pretty(s.camera))}</pre>` : ""}</div>`).join("") || "Link a scene"}</dd><dt>Recorded software</dt><dd>${env.map((e) => `${esc(e.name)} ${esc(e.version)}`).join("<br>") || "Software details pending"}</dd>${state.mode === "expert" ? `<dt>Package check</dt><dd>${badge(state.data.report?.overall_status || "needs_review")}</dd>` : ""}</dl></div><div class="replay-note"><p>${native.length ? "Open the scene in its original viewer to check the saved view. Export includes the current replay status." : "The image supports a draft review. Add the saved PyMOL, ChimeraX, or MolViewSpec scene to preserve the interactive view."}</p><button class="button secondary small" data-action="attach">Add scene files</button>${native.length ? "" : '<button class="text-button" data-action="export-draft">Export a working draft</button>'}</div>`;
}
function scopedOperations() {
  const ids = new Set(list(audit()?.operation_ids));
  return list(semantic().observed_scene_operations).filter((o) =>
    claim()
      ? ids.has(o.operation_id)
      : sourceWithinScene(o.source_location, activeScene()),
  );
}
function findingsHTML(findings) {
  return (
    findings
      .map(
        (f) =>
          `<div class="report-finding"><div>${badge(f.severity === "ERROR" ? "missing" : f.severity === "WARNING" ? "review" : "neutral", f.severity)} <code>${esc(f.rule_id)}</code></div><p>${esc(f.message)}</p>${f.suggested_fix ? `<p class="fix">${esc(f.suggested_fix)}</p>` : ""}<p class="micro-note">${esc(f.json_pointer || "/")} · ${esc(f.status)}${list(f.blocks_modes).length ? (f.status === "FAIL" && f.severity === "ERROR" ? " · Blocks " : " · Applies to ") + esc(f.blocks_modes.join(", ")) : ""}</p></div>`,
      )
      .join("") || '<p class="micro-note">All checks passed.</p>'
  );
}
function expertPanel() {
  const ops = scopedOperations(),
    a = audit();
  const raw = list(semantic().raw_native_observations).filter((o) =>
    claim()
      ? list(a?.raw_observation_ids).includes(o.raw_id)
      : sourceWithinScene(o.source_location, activeScene()),
  );
  const resources = list(semantic().resource_references).filter((r) =>
    claim()
      ? list(a?.resource_ref_ids).includes(r.resource_ref_id)
      : sourceWithinScene(r.source_location, activeScene()),
  );
  return `<div class="expert-metrics"><div class="expert-metric"><strong>${ops.length}</strong><span>Scene operations</span></div><div class="expert-metric"><strong>${resources.length}</strong><span>Resource references</span></div><div class="expert-metric"><strong>${raw.length}</strong><span>Raw observations</span></div></div><details class="disclosure"><summary>Scene operations &amp; source locations</summary><div class="panel-body">${ops.map((o, i) => `<div class="operation"><span class="mono">${String(i + 1).padStart(2, "0")}</span><div><code>${esc(o.native_command || `${o.operation} ${o.target}`)}</code><small>${esc(o.meaning_status)} · ${esc(o.target_resolution_status)}</small><small>${esc(o.operation_id)}</small></div><button class="text-button" data-operation="${esc(o.operation_id)}">${esc(o.source_location?.line ? `Line ${o.source_location.line}` : o.source_location?.json_pointer || "View source")} ${icon("arrow", 11)}</button></div>`).join("") || '<p class="micro-note">Operations appear here after scene import.</p>'}</div></details><details class="disclosure"><summary>Resources &amp; evidence bindings</summary><pre class="json-block">${esc(pretty({ resources, raw_observations: raw, evidence_bindings: list(semantic().evidence_bindings).filter((b) => list(a?.evidence_binding_ids).includes(b.binding_id)) }))}</pre></details><details class="disclosure"><summary>Package check · ${esc(statusNames[state.data?.report?.overall_status] || "Review needed")}</summary><div class="panel-body">${findingsHTML(list(state.data?.report?.findings).filter((f) => f.status === "FAIL"))}</div></details><details class="disclosure"><summary>Claim data &amp; provenance</summary><pre class="json-block">${esc(pretty({ claim: claim(), audit: a, evidence: linkedEvidence(), uncertainty: linkedUncertainty(), provenance: semantic().provenance }))}</pre></details>`;
}
function updateDetail() {
  rememberView();
  state.sourceId = null;
  ++sourceRequest;
  $("#claim-detail").innerHTML = detail();
  $("#claim-list").innerHTML = claimCards();
  if ($("#mobile-claim-select"))
    $("#mobile-claim-select").value = state.claimId || "";
  $$("[data-view]").forEach((b) => {
    if (b.closest(".workflow-nav"))
      b.setAttribute(
        "aria-current",
        b.dataset.view === state.view ? "page" : "false",
      );
  });
}
function setTab(tab) {
  state.tab = tab;
  state.view = "review";
  updateDetail();
  $("#audit-panel")?.focus({ preventScroll: true });
}
let dialogOpener = null;
let dialogInitialValues = null;
function dialogValues() {
  const form = $("#dialog-form");
  return form ? JSON.stringify([...new FormData(form)].map(([key, value]) => [
    key,
    value instanceof File ? (value.name ? [value.name, value.size, value.lastModified] : null) : value,
  ])) : null;
}
function hasUnsavedDialog() {
  return $("#dialog").open && dialogInitialValues !== null &&
    dialogValues() !== dialogInitialValues;
}
function dialog(title, subtitle, body, footer = "", wide = false) {
  const d = $("#dialog");
  dialogInitialValues = null;
  if (!d.open) dialogOpener = document.activeElement;
  d.classList.toggle("wide", wide);
  $("#dialog-content").innerHTML =
    `<div class="dialog-header"><div><h2 id="dialog-title">${esc(title)}</h2>${subtitle ? `<p>${esc(subtitle)}</p>` : ""}</div><button class="icon-button" data-action="close-dialog" aria-label="Close dialog">${icon("close", 18)}</button></div>${body}${footer}`;
  if (!d.open) d.showModal();
}
function closeDialog() {
  if (state.busy || $("#dialog").dataset.submitting === "true") return;
  if (hasUnsavedDialog() && !window.confirm("Discard your unsaved changes? Choose Cancel to keep editing.")) return;
  $("#dialog").close();
}
const field = (label, name, value = "", type = "text", help = "") =>
  `<div class="form-field"><label for="f-${name}">${esc(label)}</label><input id="f-${name}" name="${name}" type="${type}" value="${esc(value)}" ${type === "number" ? 'step="any"' : ""} ${help ? `aria-describedby="hint-${name}"` : ""}>${help ? `<small id="hint-${name}">${esc(help)}</small>` : ""}</div>`;
const textfield = (label, name, value = "", help = "") =>
  `<div class="form-field"><label for="f-${name}">${esc(label)}</label><textarea id="f-${name}" name="${name}" ${help ? `aria-describedby="hint-${name}"` : ""}>${esc(value)}</textarea>${help ? `<small id="hint-${name}">${esc(help)}</small>` : ""}</div>`;
function fieldError(message, field) {
  return Object.assign(new Error(message), { field });
}
function clearFieldError(input) {
  const form = input.closest("form");
  if (!form) return;
  const name = input.id === "f-evidence-files" ? "source_artifact_ids" : input.name;
  if (!name) return;
  for (const field of [...form.elements].filter((el) => el.name === name)) {
    field.removeAttribute("aria-invalid");
    const described = (field.getAttribute("aria-describedby") || "")
      .split(" ").filter((id) => id && id !== "error-" + name);
    if (described.length) field.setAttribute("aria-describedby", described.join(" "));
    else field.removeAttribute("aria-describedby");
  }
  document.getElementById("error-" + name)?.remove();
}
function restoreDialogFocus() {
  if (dialogOpener?.isConnected) {
    dialogOpener.focus({ preventScroll: true });
    return;
  }
  const key = dialogOpener?.dataset?.action;
  const replacement =
    key &&
    $$("[data-action]").find(
      (el) => el.dataset.action === key && el.getClientRects().length,
    );
  (
    replacement ||
    $("#claim-detail [data-task]") ||
    $("#audit-panel") ||
    $("#main")
  )?.focus({ preventScroll: true });
}
function formDialog(
  title,
  subtitle,
  fields,
  onSubmit,
  button = "Save record",
  wide = false,
  allowDraft = false,
) {
  dialog(
    title,
    subtitle,
    `<form id="dialog-form"><div class="dialog-body"><div id="form-error" class="form-error" role="alert" hidden></div>${fields}${allowDraft ? `<p class="save-meaning">${esc(button)} confirms these details. Save draft keeps them open for editing.</p>` : ""}</div><div class="dialog-footer"><button type="button" class="button secondary" data-action="close-dialog">Cancel</button>${allowDraft ? '<button type="button" class="button secondary" data-save-draft>Save draft</button>' : ""}<button type="submit" class="button">${esc(button)}</button></div></form>`,
    "",
    wide,
  );
  const form = $("#dialog-form");
  dialogInitialValues = dialogValues();
  form.querySelector("textarea, input:not([type=hidden]), select")?.focus();
  let submitting = false;
  const submitForm = async (submit, saveDraft) => {
    if (state.busy || submitting) return;
    submitting = true;
    $("#dialog").dataset.submitting = "true";
    $$("button", form).forEach((b) => (b.disabled = true));
    const submitLabel = submit.textContent;
    submit.textContent = "Saving…";
    const err = $("#form-error");
    err.hidden = true;
    $$("[aria-invalid]", form).forEach((el) =>
      el.removeAttribute("aria-invalid"),
    );
    $$(".field-error", form).forEach((el) => el.remove());
    try {
      await onSubmit(new FormData(form), saveDraft);
      $("#dialog").close();
    } catch (error) {
      const input =
        error.field && [...form.elements].find((el) => el.name === error.field);
      if (input) {
        const container =
          input.closest(".form-field,fieldset") || input.parentElement;
        const note = document.createElement("p");
        note.className = "field-error";
        note.id = "error-" + input.name;
        note.textContent = error.message;
        container.append(note);
        input.setAttribute("aria-invalid", "true");
        input.setAttribute(
          "aria-describedby",
          [
            ...(input.getAttribute("aria-describedby") || "")
              .split(" ")
              .filter((v) => v && !v.startsWith("error-")),
            note.id,
          ].join(" "),
        );
        let parent = input.parentElement;
        while (parent && parent !== form) {
          if (parent.tagName === "DETAILS") parent.open = true;
          parent = parent.parentElement;
        }
        input.disabled = false;
        input.focus();
        input.scrollIntoView({ block: "center" });
      } else {
        err.textContent = error.message;
        err.hidden = false;
        err.scrollIntoView({ block: "nearest" });
      }
    } finally {
      submitting = false;
      delete $("#dialog").dataset.submitting;
      $$("button", form).forEach((b) => (b.disabled = false));
      submit.textContent = submitLabel;
    }
  };
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submitForm(e.submitter || form.querySelector("[type=submit]"), false);
  });
  $("[data-save-draft]", form)?.addEventListener("click", (e) =>
    submitForm(e.currentTarget, true),
  );
}
function openImport() {
  openPath();
}
function openPath() {
  formDialog(
    "Open package",
    "Open a saved ClaimTrace folder. Extract a received ZIP first.",
    field(
      "Package folder path",
      "path",
      "",
      "text",
      "Use the folder containing semantic_layer.json, such as /mnt/d/project/scene-package.",
    ),
    async (f) => {
      const path = String(f.get("path")).trim();
      if (!path) throw fieldError("Enter the package folder path.", "path");
      await mutate("/api/open", { path }, "Package opened", false);
    },
    "Open package",
  );
}
const practice = () => semantic().extensions?.gui_example;
function showHelp() {
  dialog(
    "Trace the evidence behind a figure",
    "ClaimTrace connects a molecular figure's statement to the files, observations, and limits behind it.",
    `<div class="dialog-body quick-guide"><ol><li><strong>Prepare</strong><p>Write one statement from your figure legend. Add the files you used, what you checked, and what you found.</p></li><li><strong>Review</strong><p>Follow the statement to its evidence. Open each audit row to inspect sources or complete a detail.</p></li><li><strong>Export</strong><p>Download a short review or a package containing the record and its files. A working draft keeps open questions visible.</p></li></ol><dl><dt>Claim</dt><dd>The statement you want this figure to support.</dd><dt>Scene</dt><dd>A saved molecular view, including its selected regions and display settings.</dd><dt>Package</dt><dd>A folder containing your files and their review record.</dd></dl></div>`,
    `<div class="dialog-footer"><button class="button secondary" data-action="examples">Try an example</button><button class="button" data-action="close-dialog">Continue</button></div>`,
  );
}
async function examplePicker() {
  const data = await api("/api/examples");
  dialog(
    "Choose a practice case",
    "Start with the first case to learn the workflow. Each includes files and suggested answers.",
    `<div class="dialog-body example-catalog">${list(data.examples)
      .map(
        (example, i) =>
          `<article class="example-option"><span class="eyebrow">${i === 0 ? "Start here" : `Case 0${i + 1}`}</span><h3>${esc(example.title)}</h3><p>${esc(example.description)}</p><button class="button ${i === 0 ? "" : "secondary"} small" data-example="${esc(example.id)}">${i === 0 ? "Start first example" : "Start this case"} ${icon("arrow", 13)}</button></article>`,
      )
      .join(
        "",
      )}<p class="micro-note">Each case opens a new local practice package. Your current package stays saved.</p></div>`,
  );
}
function practiceGuide() {
  const example = practice();
  if (!example) return "";
  const tasks = scopedTasks();
  const task = tasks.find((t) =>
    ["edit-claim", "new-evidence", "edit-evidence", "cutoff"].includes(
      t.action,
    ),
  );
  let next;
  if (state.view === "review" && claim())
    next = [
      "Review the figure and its evidence",
      'data-view="export"',
      "Go to export",
    ];
  else if (!claim())
    next = [
      "Write the figure statement",
      'data-action="new-claim"',
      "Add claim",
    ];
  else if (task)
    next = [task.title, `data-task="${esc(task.id)}"`, taskButton(task)];
  else if (!linkedUncertainty().length)
    next = [
      "Record a limit of this interpretation",
      'data-action="new-uncertainty"',
      "Add limitation",
    ];
  else if (tasks.length)
    next = [
      tasks[0].title,
      `data-task="${esc(tasks[0].id)}"`,
      taskButton(tasks[0]),
    ];
  else
    next = [
      "Read the short evidence review",
      'data-view="review"',
      "Review record",
    ];
  const e = example.evidence || {};
  return `<section class="practice-guide"><div class="practice-next"><div><span class="eyebrow">Practice · ${esc(example.title)}</span><h2>${esc(next[0])}</h2><p>${state.view === "review" ? "Open an audit row to inspect its sources and remaining questions." : "Use the supplied answers in each form, then review and save."}</p></div><button class="button secondary small" ${next[1]}>${esc(next[2])} ${icon("arrow", 13)}</button></div><details><summary>Example instructions &amp; answers</summary><div class="practice-content"><p>${esc(list(example.instructions)[0] || "Use the supplied files to complete a claim, its evidence, and a limitation. Then export your audit.")}</p><dl class="practice-values"><dt>Claim</dt><dd>${esc(example.claim?.claim_text)}</dd><dt>Figure / type</dt><dd>${esc(example.claim?.figure_ref)} · ${esc(types[example.claim?.claim_type])}</dd><dt>Evidence type</dt><dd>${esc(evidenceKinds[e.evidence_kind])}</dd><dt>How it was checked</dt><dd>${esc(e.method_name)}</dd><dt>What was found</dt><dd>${esc(e.result_summary)}</dd>${e.thresholds?.distance ? `<dt>Contact cutoff</dt><dd>${esc(e.thresholds.distance)} ${esc(e.units?.distance)}</dd>` : ""}<dt>Source files</dt><dd>${list(e.source_artifact_ids).map(fileChip).join("")}</dd><dt>Limitation</dt><dd>${esc(example.uncertainty?.statement)}</dd></dl></div></details></section>`;
}
function practiceFillButton(section) {
  if (!practice()?.[section]) return "";
  return `<div class="practice-fill"><span>Synthetic practice · ${esc(practice().title)}</span><button type="button" class="button secondary small" data-practice-fill="${section}">Use practice values</button></div>`;
}
function fillPractice(section) {
  const data = practice()?.[section];
  if (!data) return;
  const fields =
    section === "claim"
      ? ["claim_text", "figure_ref", "claim_type"]
      : section === "evidence"
        ? ["evidence_kind", "method_name", "result_summary"]
        : ["statement", "category"];
  fields.forEach((key) => {
    const el = $(`[name="${key}"]`, $("#dialog-form"));
    if (el) el.value = data[key] || "";
  });
  if (section === "evidence") {
    $("#dialog-form").dataset.practiceEvidence = "true";
    $$('[name="target_selection_ids"]', $("#dialog-form")).forEach((el) => {
      el.checked = list(data.target_selection_ids).includes(el.value);
    });
    $("#f-cutoff").value = data.thresholds?.distance ?? "";
    $("#f-unit").value = data.units?.distance || "";
    $$('[name="source_artifact_ids"]', $("#dialog-form")).forEach((el) => {
      el.checked = list(data.source_artifact_ids).includes(el.value);
    });
    evidenceHints();
    updateSourceCount();
  }
  const input = $(`[name="${fields[0]}"]`, $("#dialog-form"));
  input?.focus();
  toast("Practice values added. Review the fields, then save.");
}
const evidenceExamples = {
  manual_rationale: {
    methods: [
      "Visual inspection of the structure and selection",
      "Comparison with the figure legend",
    ],
    result:
      "Chain A residues 42, 85 and 117 are highlighted in the saved view.",
    template:
      "[Residues or region] are [visible feature] in [figure or scene].",
    source:
      "Choose the scene, structure, figure, or inspection notes you used.",
  },
  contact_table: {
    methods: [
      "Atom-distance calculation from coordinates",
      "PyMOL contact analysis",
      "ChimeraX contact analysis",
    ],
    result:
      "Three listed ligand–residue distances are within the 4 Å cutoff: 2.5, 2.9 and 2.9 Å.",
    template:
      "[Number] contacts between [ligand] and [residues] are within [cutoff and unit]; the measured distances are [values and unit].",
    source:
      "Choose both the structure file and the contact table containing these distances.",
  },
  measurement: {
    methods: [
      "PyMOL distance measurement",
      "ChimeraX distance measurement",
      "Atom-distance calculation from coordinates",
    ],
    result:
      "The distance between ligand atom N2 and residue 110 atom OD2 is 3.2 Å.",
    template:
      "The distance between [atom or residue pair] is [value and unit].",
    source:
      "Choose the structure file and the saved measurements or analysis report.",
  },
  external_validation: {
    methods: [
      "Coordinate comparison in a shared reference frame",
      "Structural alignment and RMSD calculation",
      "Review of a structure-validation report",
    ],
    result:
      "The four matched atoms differ by 0.5 Å RMSD in the supplied coordinate comparison.",
    template:
      "[Metric] for [models or region] is [value and unit], calculated using [selection or alignment].",
    source:
      "Choose the compared structures and the comparison table or validation report.",
  },
  density_support: {
    methods: ["Inspection of an electron-density map"],
    result:
      "The ligand atoms follow the density at the recorded contour level of 1.0 σ.",
    template:
      "At [contour level], the density around [region] shows [observed fit or discrepancy].",
    source: "Choose the map, fit report, or saved inspection record.",
  },
  map_fit_metric: {
    methods: ["Local map–model correlation calculation"],
    result: "The selected domain has a local map–model correlation of 0.82.",
    template:
      "[Map-fit metric] for [region] is [value], using [map and analysis settings].",
    source: "Choose the map-fit report containing the metric and settings.",
  },
  trajectory_analysis: {
    methods: [
      "Distance analysis across trajectory frames",
      "Contact occupancy analysis",
    ],
    result: "The contact is present in 65% of the 200 analyzed frames.",
    template:
      "[Feature or metric] is observed in [frames or fraction], using [selection and analysis settings].",
    source: "Choose the trajectory-analysis table or report.",
  },
};
function evidenceHints() {
  const kind = $("#f-evidence_kind")?.value;
  const ex = evidenceExamples[kind] || evidenceExamples.manual_rationale;
  const practiceEvidence = practice()?.evidence;
  const matchedPractice = practiceEvidence?.evidence_kind === kind;
  const distance = ["contact_table", "measurement"].includes(kind);
  $("#distance-fields").hidden = !distance;
  $("#f-measured_distance").closest(".form-field").hidden = kind !== "measurement";
  $("#f-cutoff").closest(".form-field").hidden = kind === "measurement" && !$("#f-cutoff").value;
  $("#unit-hint").textContent = kind === "measurement" ? "Use the unit of the measured distance, such as angstrom or nm." : "Å = angstrom; 1 nm = 10 Å.";
  const trajectory = kind === "trajectory_analysis";
  $("#analysis-settings-purpose").textContent = trajectory ? "Frames and replicates" : "Optional";
  if (trajectory) $("#analysis-settings").open = true;
  $("#hint-analysis_settings").textContent = trajectory
    ? "Record the frames or time range, sampling interval, selected atoms, and replicate count used in this analysis."
    : "Example: Chain A; polar contacts within 3.5 Å; time range 0–499 ns; three repeats.";
  $("#f-method_name").placeholder =
    `e.g. ${matchedPractice ? practiceEvidence.method_name : ex.methods[0]}`;
  $("#method-options").innerHTML = ex.methods
    .map((m) => `<option value="${esc(m)}">`)
    .join("");
  $("#f-result_summary").placeholder = matchedPractice
    ? practiceEvidence.result_summary
    : ex.result;
  $("#evidence-source-hint").textContent = ex.source;
  $("#filled-evidence-example").innerHTML =
    `<dl class="practice-values"><dt>How</dt><dd>${esc(matchedPractice ? practiceEvidence.method_name : ex.methods[0])}</dd><dt>Finding</dt><dd>${esc(matchedPractice ? practiceEvidence.result_summary : ex.result)}</dd></dl><p class="micro-note">${matchedPractice ? "From this practice case. Compare these values with the supplied files." : "Illustrative wording. Use the observations from your own files."}</p>`;
}
function insertResultTemplate() {
  const ex =
    evidenceExamples[$("#f-evidence_kind").value] ||
    evidenceExamples.manual_rationale;
  const input = $("#f-result_summary");
  if (input.value.trim()) {
    $("#result-template-preview").hidden = false;
    $("#result-template-preview").textContent = ex.template;
    return;
  }
  input.value = ex.template;
  input.focus();
  const end = input.value.indexOf("]") + 1;
  input.setSelectionRange(0, end);
}
function checkTemplate(value, fieldName) {
  const prompts = Object.values(evidenceExamples).flatMap(
    (ex) => ex.template.match(/\[[^\]]+\]/g) || [],
  );
  if (prompts.some((prompt) => value.includes(prompt)))
    throw new Error(
      `Replace the bracketed prompts in ${fieldName} with your observations.`,
    );
}
const limitationOptions = {
  single_view: {
    label: "One structure or conformation",
    category: "general",
    statement:
      "This view represents one conformation; other conformations may show different geometry.",
  },
  distance: {
    label: "Distance-based contacts",
    category: "method_limit",
    statement:
      "The contact list describes geometric proximity. Interaction strength also depends on chemistry and conformation.",
  },
  cutoff: {
    label: "Choice of contact cutoff",
    category: "selection_bias",
    statement:
      "The contact list depends on the chosen distance cutoff; changing it may change the included residues.",
  },
  model: {
    label: "Model or alignment uncertainty",
    category: "model_confidence",
    statement:
      "The comparison depends on the selected atoms and their coordinate accuracy.",
  },
};
function limitationPresets() {
  return `<div class="form-field"><label for="f-limitation-preset">Start with a common limitation <span class="muted">Optional</span></label><select id="f-limitation-preset"><option value="">Write your own</option>${Object.entries(
    limitationOptions,
  )
    .map(([key, p]) => `<option value="${key}">${esc(p.label)}</option>`)
    .join(
      "",
    )}</select><small>Choose one that applies, then adapt the wording below.</small><p id="limitation-suggestion" class="template-preview" hidden></p></div>`;
}
function identityForm() {
  const c = claim();
  const selections = byIds(semantic().selections, audit()?.selection_ids);
  const structures = list(semantic().artifacts).filter(
    (a) => a.role === "structure" && list(audit()?.artifact_ids).includes(a.id),
  );
  if (!selections.length) {
    setTab("visual");
    toast(
      "Add the named selections to your scene, then import the scene files.",
    );
    return;
  }
  const kinds = {
    ligand: "Ligand",
    residue: "Residues or binding site",
    model: "Protein or model",
    other: "Other molecule or region",
  };
  formDialog(
    "Identify the selected regions",
    "Use the molecule, chain and residue names from your structure file.",
    selections
      .map((s, i) => {
        const entity =
          byIds(semantic().entities, s.entity_ids).find(
            (e) => e.extensions?.gui_identity,
          ) || byIds(semantic().entities, s.entity_ids)[0];
        return `<fieldset class="identity-fields"><legend>Selection: ${esc(s.name)}</legend><p class="form-info">Saved selection: <code>${esc(s.native_selector.value)}</code></p><div class="form-field"><label for="identity-kind-${i}">What does this selection identify?</label><select id="identity-kind-${i}" name="kind-${i}"><option value="">Choose a region type</option>${Object.entries(
          kinds,
        )
          .map(
            ([k, v]) =>
              `<option value="${k}" ${entity?.entity_type === k ? "selected" : ""}>${v}</option>`,
          )
          .join(
            "",
          )}</select></div>${field("Molecule or residues", `identity-${i}`, entity?.label || "", "text", "Example: Chain B, ligand LIG 1, atom C1; or chain A, residues ASP 42 and SER 85.")}<div class="form-field"><span class="field-label">${structures.length > 1 ? "Source structures" : "Source structure"}</span>${structures.length === 1 ? `<input type="hidden" name="identity-source-${i}" value="${esc(structures[0].id)}"><p>${esc(fileName(structures[0].id))}</p>` : `<p class="form-info">Select every coordinate file used by this selection.</p><div class="check-list">${structures.map((a,j) => `<label><input type="checkbox" id="identity-source-${i}-${j}" name="identity-source-${i}" value="${esc(a.id)}" ${list(entity?.source_artifact_ids).includes(a.id) ? "checked" : ""}>${esc(fileName(a.id))}</label>`).join("")}</div>`}</div></fieldset>`;
      })
      .join(""),
    async (f) => {
      const identities = selections.map((s, i) => {
        const label = String(f.get(`identity-${i}`) || "").trim();
        const type = f.get(`kind-${i}`),
          sources = f.getAll(`identity-source-${i}`);
        if (!type) throw fieldError(`Choose the region type for ${s.name}.`, `kind-${i}`);
        if (!label) throw fieldError(`Name the molecule or residues for ${s.name}.`, `identity-${i}`);
        if (!sources.length) throw fieldError(`Choose the source structures for ${s.name}.`, `identity-source-${i}`);
        return {
          selection_id: s.id,
          entity_type: type,
          label,
          source_artifact_ids: sources,
        };
      });
      await mutate(
        "/api/identities",
        { claim_id: c.id, identities },
        "Region identities saved",
      );
      state.tab = "visual";
      render();
    },
    "Save identities",
  );
}
function colorForm() {
  const c = claim();
  const issues = list(audit()?.issues).filter(
    (i) =>
      i.rule_id === "SCENE.VISUAL_ENCODING.MEANING_MISSING" &&
      i.status === "FAIL",
  );
  const requiredIds = new Set(
    issues.map(
      (i) =>
        list(semantic().observed_scene_operations)[
          Number(i.json_pointer?.split("/")[2])
        ]?.operation_id,
    ),
  );
  const reviewedCueIds = new Set(
    list(semantic().visual_encoding_semantics)
      .filter(
        (v) =>
          [
            "user_confirmed_meaning",
            "user_declared_no_scientific_meaning",
          ].includes(v.meaning_status) &&
          (known(v.meaning) || known(v.no_scientific_meaning_reason)),
      )
      .flatMap((v) => list(v.operation_ids)),
  );
  const pending = scopedOperations().filter(
    (o) =>
      !reviewedCueIds.has(o.operation_id) &&
      ["colored", "labeled", "represented", "displayed"].includes(
        o.operation,
      ) &&
      (o.needs_author_confirmation ||
        ["requires_user_completion", "tool_suggested_meaning"].includes(
          o.meaning_status,
        )),
  );
  const operations = requiredIds.size
    ? scopedOperations().filter((o) => requiredIds.has(o.operation_id))
    : pending.length
      ? pending
      : scopedOperations().filter((o) => o.operation === "colored");
  if (!operations.length) {
    toast("Visual meanings are recorded for this scene.");
    return;
  }
  const colorsOnly = operations.every((o) => o.operation === "colored");
  formDialog(
    operations.every((o) => o.operation === "colored")
      ? "Explain the highlighted color"
      : "Explain the visual cue",
    "Describe the visual key a reader needs for this figure.",
    operations
      .map((o, i) => {
        const cue =
          o.operation === "colored"
            ? "color"
            : o.operation === "labeled"
              ? "label"
              : "representation";
        const saved = list(semantic().visual_encoding_semantics).find((v) =>
          list(v.operation_ids).includes(o.operation_id),
        );
        return `<fieldset class="identity-fields"><legend>${esc(o.details?.color || (cue === "label" ? "Label" : "Representation"))} · ${esc(o.target)}</legend><p class="form-info">Saved scene instruction: <code>${esc(o.native_command || o.target)}</code></p><div class="form-field"><label for="color-purpose-${i}">What is this ${cue} used for?</label><select id="color-purpose-${i}" name="color-purpose-${i}" data-color-purpose="${i}" data-target="${esc(o.target)}" data-color="${esc(o.details?.color || `This ${cue}`)}"><option value="">Choose a purpose</option><option value="identify" ${saved?.meaning_status === "user_confirmed_meaning" ? "selected" : ""}>Identify this molecule or region</option><option value="styling" ${saved?.meaning_status === "user_declared_no_scientific_meaning" ? "selected" : ""}>Display styling</option><option value="custom">Other meaning</option></select></div>${textfield(cue === "color" ? "Color key" : "Meaning", `color-meaning-${i}`, saved?.meaning || saved?.no_scientific_meaning_reason || "", cue === "color" ? "Example: Orange identifies the ligand." : "Example: The label identifies the residue discussed in this claim.")}</fieldset>`;
      })
      .join(""),
    async (f) => {
      const visual_meanings = operations.map((o, i) => {
        const purpose = f.get(`color-purpose-${i}`),
          meaning = String(f.get(`color-meaning-${i}`) || "").trim();
        if (!purpose || !meaning)
          throw new Error(
            `Choose a purpose and describe the visual key for ${o.target}.`,
          );
        return {
          operation_id: o.operation_id,
          meaning,
          presentation_only: purpose === "styling",
        };
      });
      await mutate(
        "/api/identities",
        { claim_id: c.id, visual_meanings },
        colorsOnly ? "Color key saved" : "Visual meaning saved",
      );
      state.tab = "visual";
      render();
    },
    colorsOnly ? "Save color key" : "Save visual meaning",
  );
}
async function encodeFiles(files) {
  return Promise.all(
    [...files].map(
      (file) =>
        new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () =>
            resolve({
              name: file.name,
              content: String(reader.result).split(",")[1],
            });
          reader.onerror = () =>
            reject(new Error(`Select ${file.name} again to read it.`));
          reader.readAsDataURL(file);
        }),
    ),
  );
}
function importFiles(files) {
  if (!files.length) return;
  if ([...files].reduce((n, f) => n + f.size, 0) > 45 * 1024 * 1024) {
    toast(
      "Choose up to 45 MiB per upload. Use claimtrace add-artifact for larger files.",
      true,
    );
    return;
  }
  formDialog(
    "Import files",
    `${files.length} ${files.length === 1 ? "file" : "files"} selected`,
    field("Package name", "title", files[0].name.replace(/\.[^.]+$/, "")) +
      `<div class="import-file-list">${[...files].map((f) => `<span>${icon("file", 13)} ${esc(f.name)}</span>`).join("")}</div><details class="form-disclosure"><summary>Save location</summary>${field("Destination folder", "out", "", "text", "Leave empty to create a package in claimtrace-workspace.")}</details>`,
    async (f) => {
      const payload = {
        files: await encodeFiles(files),
        title: String(f.get("title")).trim() || "Figure review",
      };
      if (String(f.get("out")).trim())
        payload.out = String(f.get("out")).trim();
      await mutate(
        "/api/import",
        payload,
        "Files imported. Add your claim to begin.",
        false,
      );
    },
    "Create package",
  );
}
function editClaim(existing) {
  const c = existing ? claim() : null,
    scenes = list(semantic().scenes),
    selected = c?.scene_ids || (activeScene() ? [activeScene().id] : []);
  const sceneField = !scenes.length
    ? '<p class="form-info">Use Save draft to keep this statement while you add a figure or scene.</p>'
    : scenes.length === 1
      ? `<input type="hidden" name="scene_ids" value="${esc(scenes[0].id)}"><p class="form-info">${isStaticScene(scenes[0]) ? "Figure" : "Scene"}: ${esc(sceneLabel(scenes[0]))}</p>`
      : `<fieldset><legend>${scenes.every(isStaticScene) ? "Linked figures" : "Linked scenes"}</legend><div class="check-list">${scenes.map((s) => `<label><input type="checkbox" name="scene_ids" value="${esc(s.id)}" ${selected.includes(s.id) ? "checked" : ""}>${esc(sceneLabel(s))}</label>`).join("")}</div></fieldset>`;
  formDialog(
    c ? "Edit claim" : "Add claim",
    "A claim is one statement you want this figure to support.",
    practiceFillButton("claim") +
      textfield(
        "Figure statement",
        "claim_text",
        c?.claim_text.value || "",
        practice()?.claim
          ? `Example: ${practice().claim.claim_text}`
          : claimExample() ? `Example: ${claimExample()}` : "Write one observation from your figure legend.",
      ) +
      `<div class="form-row">${field("Figure label", "figure_ref", known(c?.figure_ref) ? c.figure_ref : "", "text", "Example: Figure 1A")}<div class="form-field"><label for="f-claim_type">Statement type</label><select id="f-claim_type" name="claim_type" aria-describedby="hint-claim-type">${Object.entries(
        types,
      )
        .map(
          ([k, v]) =>
            `<option value="${k}" ${k === (c?.claim_type || practice()?.claim?.claim_type || "simple_structure_view") ? "selected" : ""}>${v}</option>`,
        )
        .join(
          "",
        )}</select><small id="hint-claim-type">Choose what the statement describes: a view, region, binding pose, or comparison.</small></div></div>${sceneField}`,
    async (f, saveDraft = false) => {
      const text = String(f.get("claim_text")).trim(),
        ref = String(f.get("figure_ref")).trim();
      if (!text)
        throw fieldError(
          "Write the statement this figure supports.",
          "claim_text",
        );
      if (!saveDraft) checkTemplate(text, "the claim");
      if (!ref && !saveDraft)
        throw fieldError(
          "Add a figure label, such as Figure 1A.",
          "figure_ref",
        );
      if (!saveDraft && !f.getAll("scene_ids").length)
        throw fieldError(
          staticPackage()
            ? "Choose the figure that shows this claim."
            : "Choose the scene that shows this claim.",
          "scene_ids",
        );
      const result = await mutate(
        "/api/claim",
        {
          ...(c ? { id: c.id } : {}),
          claim_text: text,
          save_draft: saveDraft,
          figure_ref: ref,
          claim_type: f.get("claim_type"),
          scene_ids: f.getAll("scene_ids"),
        },
        saveDraft ? "Claim draft saved" : "Claim saved",
      );
      if (!c && result) {
        state.claimId = list(result.semantic.claims).at(-1)?.id;
        state.tab = "visual";
        state.view = "prepare";
        render();
      }
    },
    "Save claim",
    false,
    true,
  );
}
function evidenceForm(id, kind, focusDistance = false) {
  const e = linkedEvidence().find((e) => e.id === id),
    c = claim();
  if (!c) return;
  const thresholds = e?.thresholds || {},
    units = e?.units || {};
  const selectedKind =
    e?.evidence_kind ||
    kind ||
    ({ligand_binding_pose: "contact_table", model_comparison: "external_validation", computed_model_claim: "external_validation", trajectory_mechanism: "trajectory_analysis", cryo_em_map_fit: "map_fit_metric", xray_density_support: "density_support"}[c.claim_type] || "manual_rationale");
  const targetIds = new Set([
    ...linkedScenes().flatMap((s) => list(s.selection_ids)),
    ...list(e?.target_selection_ids),
  ]);
  const targetSelections = list(semantic().selections).filter((s) =>
    targetIds.has(s.id),
  );
  const selectedTargets = e ? list(e.target_selection_ids) : [...targetIds];
  const mappedEntities = new Set(
    list(semantic().selections)
      .filter((s) => list(e?.target_selection_ids).includes(s.id))
      .flatMap((s) => list(s.entity_ids)),
  );
  const directEntityIds = list(e?.target_entity_ids).filter(
    (id) => !mappedEntities.has(id),
  );
  const targetFields = targetSelections.length
    ? `<details class="form-disclosure"><summary>Applies to ${targetSelections.length === 1 ? "this selection" : "these selections"}</summary><p class="form-info">Choose the regions described by this observation.</p><div class="check-list">${targetSelections.map((s) => `<label><input type="checkbox" name="target_selection_ids" value="${esc(s.id)}" ${selectedTargets.includes(s.id) ? "checked" : ""}><span>${esc(s.name)}<small>${esc(s.native_selector.value)}</small></span></label>`).join("")}</div></details>`
    : "";
  const recommendedSources = new Set(
    list(practice()?.evidence?.source_artifact_ids),
  );
  const files = [...list(semantic().artifacts)].sort(
    (a, b) =>
      Number(recommendedSources.has(b.id)) -
      Number(recommendedSources.has(a.id)),
  );
  const fileChoices = files.length
    ? `<div class="check-list evidence-files">${files.map((a) => `<div class="source-choice"><label><input type="checkbox" name="source_artifact_ids" value="${esc(a.id)}" ${list(e?.source_artifact_ids).includes(a.id) ? "checked" : ""}><span>${esc(fileName(a.id))}<small class="muted">${esc(fileRole(a))}</small></span></label><button type="button" class="text-button" data-inline-file="${esc(a.id)}" aria-label="Preview ${esc(fileName(a.id))}">Preview</button></div>`).join("")}</div>`
    : "";
  formDialog(
    e ? "Edit evidence" : "Add evidence",
    sharedRecord(e, "evidence")
      ? "Shared evidence: changes apply to all linked claims."
      : `For ${known(c.figure_ref) ? c.figure_ref : "this figure"}: ${c.claim_text.value}`,
    practiceFillButton("evidence") +
      `<div class="form-field"><label for="f-evidence_kind">Evidence type</label><select id="f-evidence_kind" name="evidence_kind">${Object.entries(
        evidenceKinds,
      )
        .filter(
          ([k]) =>
            state.mode === "expert" ||
            !["native_observation", "waiver", "negative_control"].includes(k) ||
            k === selectedKind,
        )
        .map(
          ([k, v]) =>
            `<option value="${k}" ${k === selectedKind ? "selected" : ""}>${v}</option>`,
        )
        .join("")}</select></div>
      <fieldset class="form-field"><legend>Source files <span id="selected-source-count" class="source-count"></span></legend><p id="evidence-source-hint" class="form-info"></p>${files.length > 8 ? `<div class="source-tools"><label for="source-filter">Find source files</label><input type="search" id="source-filter" placeholder="Filter by filename or file type"><div class="source-selection-actions"><button class="text-button" type="button" data-action="select-visible-sources">Select shown</button><button class="text-button" type="button" data-action="clear-visible-sources">Clear shown</button><span class="small muted" id="source-filter-count" role="status"></span></div></div>` : ""}${fileChoices}<div id="inline-file-preview" hidden></div><details class="inline-upload"><summary>Attach a file</summary><label for="f-evidence-files" class="sr-only">Supporting files</label><input type="file" id="f-evidence-files" name="files" multiple></details></fieldset>
      <div class="form-field"><label for="f-method_name">How was it checked?</label><input id="f-method_name" name="method_name" list="method-options" value="${esc(known(e?.method_name) ? e.method_name : "")}" aria-describedby="method-hint"><datalist id="method-options"></datalist><small id="method-hint">Choose a method or enter the analysis used.</small></div>
      <div class="form-field"><div class="field-heading"><label for="f-result_summary">What did you find?</label><button class="text-button" type="button" data-action="result-template">Use a sentence template</button></div><textarea id="f-result_summary" name="result_summary" aria-describedby="result-hint">${esc(known(e?.result_summary) ? e.result_summary : "")}</textarea><small id="result-hint">Include the relevant values, residues, or states.</small><p class="template-preview" id="result-template-preview" hidden></p></div>
      <details class="form-disclosure filled-example"><summary>View example answer</summary><div id="filled-evidence-example"></div></details>
      <div id="distance-fields" class="form-row" ${["contact_table", "measurement"].includes(selectedKind) || Object.keys(thresholds).length ? "" : "hidden"}>${field("Measured distance", "measured_distance", e?.parameters?.measured_distance ?? "", "number", "Enter the atom-to-atom distance. Include the atom names in your finding.")}${field("Contact distance cutoff", "cutoff", thresholds.distance ?? "", "number", "The maximum distance counted as a contact; use the value from your analysis.")}<div class="form-field"><label for="f-unit">Distance unit</label><input id="f-unit" name="unit" list="distance-units" value="${esc(units.distance || "")}" placeholder="e.g. angstrom" aria-describedby="unit-hint"><datalist id="distance-units"><option value="angstrom"><option value="nm"></datalist><small id="unit-hint">Å = angstrom; 1 nm = 10 Å.</small></div></div>
      <details id="analysis-settings" class="form-disclosure" ${known(e?.parameters?.analysis_settings) ? "open" : ""}><summary>Analysis settings <span id="analysis-settings-purpose" class="muted">Optional</span></summary>${textfield("Selections, cutoffs and sampling", "analysis_settings", e?.parameters?.analysis_settings || "", "Example: Chain A; polar contacts within 3.5 Å; time range 0–499 ns; three repeats.")}</details>
      ${targetFields}`,
    async (f, saveDraft = false) => {
      const method = String(f.get("method_name")).trim(),
        result = String(f.get("result_summary")).trim();
      if (!method && !saveDraft)
        throw fieldError(
          "Name the inspection or analysis used.",
          "method_name",
        );
      if (!result && !saveDraft)
        throw fieldError(
          "Describe the observation, including relevant values or residues.",
          "result_summary",
        );
      if (!saveDraft) checkTemplate(result, "your finding");
      const practiceValues =
        $("#dialog-form").dataset.practiceEvidence === "true"
          ? practice().evidence
          : {};
      const nextThresholds = { ...thresholds, ...practiceValues.thresholds },
        nextUnits = { ...units, ...practiceValues.units };
      const value = String(f.get("cutoff")).trim(),
        unit = String(f.get("unit")).trim();
      if (
        f.get("evidence_kind") === "contact_table" &&
        !value &&
        !saveDraft
      )
        throw fieldError(
          "Enter the contact cutoff used in this analysis.",
          "cutoff",
        );
      const measured = String(f.get("measured_distance") || "").trim();
      const isMeasurement = f.get("evidence_kind") === "measurement";
      if (isMeasurement && !measured && !value && !saveDraft)
        throw fieldError("Enter the measured distance between the selected atoms.", "measured_distance");
      if ((value || (isMeasurement && measured)) && !unit && !saveDraft)
        throw fieldError("Add the distance unit, such as angstrom.", "unit");
      if (isMeasurement && measured && (!Number.isFinite(Number(measured)) || Number(measured) <= 0))
        throw fieldError("Enter a measured distance greater than zero.", "measured_distance");
      if (value) {
        const n = Number(value);
        if (!Number.isFinite(n) || n <= 0)
          throw fieldError("Enter a cutoff greater than zero.", "cutoff");
        nextThresholds.distance = n;
        nextUnits.distance = unit;
      } else {
        delete nextThresholds.distance;
        delete nextUnits.distance;
      }
      const payload = {
        ...(e ? { id: e.id } : {}),
        claim_id: c.id,
        save_draft: saveDraft,
        evidence_kind: f.get("evidence_kind"),
        method_name: method,
        result_summary: result,
        source_artifact_ids: f.getAll("source_artifact_ids"),
        thresholds: nextThresholds,
        units: nextUnits,
        parameters: { ...(e?.parameters || {}) },
        target_selection_ids: f.getAll("target_selection_ids"),
        target_entity_ids: [
          ...new Set([
            ...directEntityIds,
            ...targetSelections
              .filter((s) => f.getAll("target_selection_ids").includes(s.id))
              .flatMap((s) => list(s.entity_ids)),
          ]),
        ],
      };
      if ($("#dialog-form").dataset.practiceEvidence === "true") {
        payload.parameters = { ...(practice().evidence.parameters || {}) };
      }
      if (isMeasurement && measured) {
        payload.parameters.measured_distance = Number(measured);
        payload.units.distance = unit;
      } else delete payload.parameters.measured_distance;
      const settings = String(f.get("analysis_settings") || "").trim();
      if (settings) payload.parameters.analysis_settings = settings;
      else delete payload.parameters.analysis_settings;
      const uploads = f.getAll("files").filter((f) => f.name);
      if (!saveDraft && !payload.source_artifact_ids.length && !uploads.length)
        throw fieldError(
          "Select a source file or attach your result.",
          files.length ? "source_artifact_ids" : "files",
        );
      if (uploads.reduce((n, f) => n + f.size, 0) > 45 * 1024 * 1024)
        throw new Error("Choose up to 45 MiB per upload.");
      if (uploads.length) payload.files = await encodeFiles(uploads);
      const data = await mutate(
        "/api/evidence",
        payload,
        saveDraft ? "Evidence draft saved" : "Evidence saved",
      );
      if (data) {
        state.tab = "evidence";
        render();
      }
    },
    "Save evidence",
    false,
    true,
  );
  evidenceHints();
  updateSourceCount();
  filterSourceFiles();
  if (focusDistance) {
    const input =
      Number(thresholds.distance) > 0 && !known(units.distance)
        ? $("#f-unit")
        : $("#f-cutoff");
    input?.focus();
    input?.select();
    input?.scrollIntoView({ block: "center" });
  }
}
function uncertaintyForm(id) {
  const u = linkedUncertainty().find((u) => u.id === id),
    c = claim();
  const categories = { ...limitationCategories };
  const practiceCategory = practice()?.uncertainty?.category;
  if (practiceCategory && !categories[practiceCategory])
    categories[practiceCategory] = categoryLabel(practiceCategory);
  if (u?.category && !categories[u.category])
    categories[u.category] = categoryLabel(u.category);
  formDialog(
    u ? "Edit limitation" : "Add limitation",
    sharedRecord(u, "uncertainty")
      ? "Shared limitation: changes apply to all linked claims."
      : "What limits this interpretation?",
    practiceFillButton("uncertainty") +
      limitationPresets() +
      textfield(
        "What limits this conclusion?",
        "statement",
        known(u?.statement) ? u.statement : "",
        "For example: This view shows one conformation; other poses may produce different contacts.",
      ) +
      `<details class="form-disclosure"><summary>Category</summary><label for="f-category">Limitation type</label><select id="f-category" name="category">${Object.entries(
        categories,
      )
        .map(
          ([k, v]) =>
            `<option value="${esc(k)}" ${k === (u?.category || "general") ? "selected" : ""}>${esc(v)}</option>`,
        )
        .join("")}</select></details>`,
    async (f) => {
      const statement = String(f.get("statement")).trim();
      if (!statement)
        throw fieldError("Describe what limits this conclusion.", "statement");
      checkTemplate(statement, "the limitation");
      const data = await mutate(
        "/api/uncertainty",
        {
          ...(u ? { id: u.id } : {}),
          claim_id: c.id,
          category: f.get("category") || "general",
          statement,
        },
        "Limitation saved",
      );
      if (data) {
        state.tab = "uncertainty";
        render();
      }
    },
    "Save limitation",
  );
}
function attachForm(options = {}) {
  const role = options.role || "auto",
    figure = role === "render_image";
  const roles = {
    auto: "Detect from file",
    render_image: "Figure image",
    structure: "Structure",
    contact_table: "Contact table",
    validation_report: "Validation report",
    evidence_document: "Supporting document",
    map: "Density map",
    trajectory: "Trajectory",
    topology: "Topology",
    generic: "Other file",
  };
  const scene = options.scene_id || activeScene()?.id || "",
    scenes = list(semantic().scenes);
  const existingImages = figure ? list(semantic().artifacts).filter((a) => a.role === "render_image") : [];
  formDialog(
    figure ? "Add figure" : "Add files",
    figure
      ? "Choose an image from this package or upload a figure."
      : "Add files to this review package.",
    `${existingImages.length ? `<fieldset class="form-field"><legend>Images in this package</legend><div class="check-list">${existingImages.map((a) => `<label><input type="checkbox" name="artifact_ids" value="${esc(a.id)}">${esc(fileName(a.id))}</label>`).join("")}</div></fieldset>` : ""}<div class="form-field"><label for="f-files">${figure ? existingImages.length ? "Upload another image" : "Figure image" : "Files"}</label><input id="f-files" name="files" type="file" ${figure ? 'accept=".png,.jpg,.jpeg,.tif,.tiff,.webp,.gif,.svg"' : ""} multiple ${existingImages.length ? "" : "required"}></div>${
      figure
        ? '<input type="hidden" name="role" value="render_image">'
        : `<div class="form-field"><label for="f-role">File type</label><select id="f-role" name="role">${Object.entries(
            roles,
          )
            .map(
              ([k, v]) =>
                `<option value="${k}" ${k === role ? "selected" : ""}>${v}</option>`,
            )
            .join("")}</select></div>`
    }<div class="form-field" id="attachment-scene" ${figure ? "" : "hidden"}><label for="f-scene_id">Link to scene</label><select id="f-scene_id" name="scene_id"><option value="">New scene</option>${scenes.map((s) => `<option value="${esc(s.id)}" ${s.id === scene ? "selected" : ""}>${esc(sceneLabel(s))}</option>`).join("")}</select></div>`,
    async (f) => {
      const files = f.getAll("files").filter((file) => file.name);
      const imageIds = f.getAll("artifact_ids");
      if (!files.length && !imageIds.length)
        throw fieldError(figure ? "Select an image or choose a file to upload." : "Choose a file to add.", existingImages.length ? "artifact_ids" : "files");
      if (files.reduce((n, f) => n + f.size, 0) > 45 * 1024 * 1024)
        throw new Error(
          "Choose up to 45 MiB per upload. Use claimtrace add-artifact for larger files.",
        );
      const payload = { files: await encodeFiles(files) };
      if (figure && claim()) payload.claim_id = claim().id;
      if (imageIds.length) payload.artifact_ids = imageIds;
      if (f.get("role") !== "auto") payload.role = f.get("role");
      const native = files.some((file) =>
        /\.(pml|cxc|mvsj|mvsx)$/i.test(file.name),
      );
      const images = files.every((file) =>
        /\.(png|jpe?g|tiff?|webp|gif|svg)$/i.test(file.name),
      );
      if (!payload.role && images) payload.role = "render_image";
      if (payload.role === "render_image" && !f.get("scene_id"))
        payload.new_scene = true;
      if (
        f.get("scene_id") &&
        (payload.role === "render_image" || (!payload.role && images))
      ) {
        payload.role = "render_image";
        payload.scene_id = f.get("scene_id");
      }
      if (native && f.get("scene_id")) payload.scene_id = f.get("scene_id");
      await mutate(
        "/api/attach",
        payload,
        figure ? "Figure added" : "Files added",
      );
    },
    figure ? "Add figure" : "Add files",
  );
}
function updateContextType() {
  const kind = $("#f-view_kind")?.value;
  if (!kind) return;
  const staticView = kind !== "molecular",
    assembly = kind === "figure_assembly";
  $("#dialog-title").textContent = staticView
    ? "Figure settings"
    : "Scene details";
  const subtitle = $("#dialog-title")?.parentElement.querySelector("p");
  if (subtitle)
    subtitle.textContent = staticView
      ? "Save the analysis and display settings for this figure."
      : "Save the view and assumptions for this claim.";
  const legend = $("#context-settings-legend");
  legend.textContent = `${staticView ? "Figure context" : "Scene context"} · ${legend.dataset.figureLabel}`;
  $('label[for="f-camera_context"]').textContent = staticView
    ? assembly
      ? "Assembly settings"
      : "Plot settings"
    : "Region and orientation shown";
  $("#hint-camera_context").textContent = staticView
    ? assembly
      ? "Example: Panels A–C use the linked plots; labels follow the source figure order."
      : "Example: Time in ns on the x-axis; contact state on the y-axis; all 500 frames; 4.5 Å cutoff."
    : "Example: Chain A residues 42 and 85, viewed from the ligand-facing side.";
  $("#context-view-hint").textContent = staticView
    ? "Record the settings used to produce this figure."
    : "Describe what is visible in this image. Add a saved molecular scene when it becomes available.";
  $('label[for="f-software_name"]').textContent = staticView
    ? "Analysis or figure software"
    : "Viewer or analysis software";
  $("#hint-software_name").textContent = staticView
    ? "Example: Python"
    : "Example: PyMOL";
  $('label[for="f-software_command"]').textContent = staticView
    ? "Figure command or instructions"
    : "Replay command or instructions";
  $("#hint-software_command").textContent = staticView
    ? "Example: python make_figure.py"
    : "Example: pymol native/figure.pml";
}
function contextForm(task) {
  const scene =
    list(semantic().scenes).find((s) => s.id === task?.scene_id) ||
    activeScene();
  const packageOnly = state.view === "export" && !task?.claim_id;
  const reuse = semantic().reuse || {};
  const software = list(semantic().software_environment)[0];
  const raw = list(semantic().raw_native_observations).filter(
    (r) =>
      scene &&
      (r.may_affect_scene_id === scene.id ||
        sourceWithinScene(r.source_location, scene)) &&
      ![
        "reviewed_no_claim_impact",
        "no_scene_effect",
        "not_applicable",
        "converted_to_evidence",
      ].includes(r.resolution),
  );
  const visibility = list(scene?.visibility)
    .map((v, index) => ({ ...v, index }))
    .filter((v) => ["hidden", "excluded", "simplified"].includes(v.state));
  const staticView = isStaticScene(scene);
  const assembly = scene?.extensions?.view_kind === "figure_assembly";
  const staticContext = !packageOnly ? staticView : staticPackage();
  const imageOnly =
    scene &&
    !list(scene.native_artifact_ids).length &&
    list(scene.render_artifact_ids).length;
  const viewKind = staticView ? scene.extensions.view_kind : "molecular";
  const contextValue = authorContextText(scene);
  const viewTypeField = imageOnly
    ? `<div class="form-field"><label for="f-view_kind">View type</label><select id="f-view_kind" name="view_kind"><option value="molecular" ${viewKind === "molecular" ? "selected" : ""}>Molecular view</option><option value="plot" ${viewKind === "plot" ? "selected" : ""}>Analysis plot</option><option value="figure_assembly" ${viewKind === "figure_assembly" ? "selected" : ""}>Figure assembly</option></select></div>`
    : "";
  const contextLabel = staticView
    ? assembly
      ? "Assembly settings"
      : "Plot settings"
    : imageOnly
      ? "Region and orientation shown"
      : "Saved view or camera context";
  const contextExample = staticView
    ? assembly
      ? "Example: Panels A–C use the linked plots; labels follow the source figure order."
      : "Example: Time in ns on the x-axis; contact state on the y-axis; all 500 frames; 4.5 Å cutoff."
    : imageOnly
      ? "Example: Chain A residues 42 and 85, viewed from the ligand-facing side."
      : "Example: PyMOL scene pocket_view, state 1, focused on ligand B/LIG1.";
  const contextInput =
    staticView || imageOnly
      ? textfield(contextLabel, "camera_context", contextValue, contextExample)
      : field(
          contextLabel,
          "camera_context",
          contextValue,
          "text",
          contextExample,
        );
  const sceneFields =
    !packageOnly && scene
      ? `<fieldset><legend id="context-settings-legend" data-figure-label="${esc(sceneLabel(scene))}">${staticView ? "Figure context" : "Scene context"} · ${esc(sceneLabel(scene))}</legend>${viewTypeField}${contextInput}<p class="form-info" id="context-view-hint">${staticView ? "Record the settings used to produce this figure." : imageOnly ? "Describe what is visible in this image. Add a saved molecular scene when it becomes available." : "Describe the view another reader should reopen."}</p>${visibility.map((v, i) => textfield(`Why is ${v.native_target || v.entity_id || v.selection_id || "this region"} ${v.state || v.visibility || "hidden"}?`, `visibility_${v.index}`, known(v.reason) ? v.reason : "", "Example: Waters are hidden to show the ligand contacts. Water-mediated contacts remain outside this view.")).join("")}</fieldset>${raw.length ? `<fieldset><legend>Review additional scene commands</legend>${raw.map((r, i) => `<div class="raw-review"><pre>${esc(r.native_text || r.raw_text || r.native_command || displayValue(r.raw_value) || r.reason)}</pre><div class="form-field"><label for="f-raw_${i}">How does this command affect the claim?</label><select id="f-raw_${i}" name="raw_${i}"><option value="">Review later</option><option value="reviewed_no_claim_impact">Reviewed: outside this claim</option><option value="no_scene_effect">Reviewed: leaves the scene unchanged</option><option value="not_applicable">Reviewed: outside this scene</option></select></div>${field("Review reason", `raw_reason_${i}`, "", "text", "Describe what you checked and why you chose this answer.")}</div>`).join("")}</fieldset>` : ""}`
      : "";
  formDialog(
    packageOnly
      ? "Package details"
      : staticView
        ? "Figure settings"
        : "Scene details",
    task?.title ||
      (packageOnly
        ? "Software and reuse details for the recipient."
        : staticView
          ? "Save the analysis and display settings for this figure."
          : "Save the view and assumptions for this claim."),
    sceneFields +
      `<details class="form-disclosure" ${packageOnly ? "open" : ""}><summary>Software &amp; reuse</summary><div class="form-row">${field(staticContext ? "Analysis or figure software" : "Viewer or analysis software", "software_name", known(software?.name) ? software.name : "", "text", staticContext ? "Example: Python" : "Example: PyMOL")}${field("Software version", "software_version", known(software?.version) ? software.version : "", "text", "Example: 3.1")}</div>${field(staticContext ? "Figure command or instructions" : "Replay command or instructions", "software_command", software?.command || "", "text", staticContext ? "Example: python make_figure.py" : "Example: pymol native/figure.pml")}${field("Reuse license", "reuse_license", known(reuse.license) ? reuse.license : "", "text", "Example: CC BY 4.0")}${textfield("Citation", "reuse_citation", known(reuse.citation) ? reuse.citation : "", "Example: Author, figure title, year, DOI or source URL.")}${textfield("Reuse conditions", "reuse_restrictions", list(reuse.restrictions).join("\n"), "One condition per line. Leave empty for unrestricted reuse under the chosen license.")}</details>`,
    async (f) => {
      const payload = {};
      if (!packageOnly && scene) {
        payload.scene = { id: scene.id };
        if (imageOnly) payload.scene.view_kind = f.get("view_kind");
        const camera = String(f.get("camera_context") || "").trim();
        if (camera !== contextValue.trim())
          payload.scene.camera_context = camera;
        payload.scene.visibility = visibility
          .map((v, i) => ({
            index: v.index,
            reason: String(f.get(`visibility_${v.index}`) || "").trim(),
          }));
        payload.raw_reviews = raw
          .map((r, i) => ({
            raw_id: r.raw_id,
            resolution: f.get(`raw_${i}`),
            reason: String(f.get(`raw_reason_${i}`) || "").trim(),
          }))
          .filter((r) => r.resolution);
        if (payload.raw_reviews.some((r) => !r.reason))
          throw new Error("Add a reason for each reviewed command.");
      }
      const name = String(f.get("software_name") || "").trim(),
        version = String(f.get("software_version") || "").trim();
      if (name || version || known(software?.name)) {
        if (!name || !version)
          throw fieldError(
            name ? "Add the software version." : "Add the software name.",
            name ? "software_version" : "software_name",
          );
        payload.software = {
          ...(software ? { id: software.id } : {}),
          name,
          version,
          command: String(f.get("software_command") || "").trim(),
        };
      }
      payload.reuse = {
        license: String(f.get("reuse_license") || "").trim() || "unknown",
        citation: String(f.get("reuse_citation") || "").trim() || "unknown",
        restrictions: String(f.get("reuse_restrictions") || "")
          .split("\n")
          .map((v) => v.trim())
          .filter(Boolean),
      };
      await mutate("/api/context", payload, "Details saved");
    },
    "Save details",
    true,
  );
}
async function answersForm() {
  busy(true);
  try {
    const data = await api("/api/answers");
    formDialog(
      "Edit answers.yml",
      "Current claim and evidence records, with package-wide review fields.",
      `${data.saved_available ? '<button class="text-button saved-answers-link" type="button" data-action="saved-answers">View saved version</button>' : ""}<label for="f-answers">Answers</label><textarea class="answers-editor" id="f-answers" name="text" spellcheck="false">${esc(data.text)}</textarea><details id="saved-answers" class="disclosure" hidden><summary>Saved version · read-only</summary><pre id="saved-answers-text" class="json-block"></pre></details>`,
      async (f) => {
        await mutate(
          "/api/answers",
          { text: f.get("text") },
          "Answers checked and saved",
        );
      },
      "Check and apply",
      true,
    );
  } finally {
    busy(false);
  }
}
async function showSavedAnswers() {
  const data = await api("/api/answers?source=saved");
  const container = $("#saved-answers");
  if (container) {
    container.hidden = false;
    container.open = true;
    $("#saved-answers-text").textContent = data.text;
    container.scrollIntoView({ block: "nearest" });
  }
}

function filterSourceFiles() {
  const search = $("#source-filter");
  if (!search) return;
  const query = search.value.trim().toLowerCase();
  const rows = $$(".evidence-files .source-choice");
  let visible = 0;
  for (const row of rows) {
    const id = row.querySelector("input").value;
    row.hidden = !(row.textContent + " " + (artifact(id)?.path || "")).toLowerCase().includes(query);
    if (!row.hidden) visible++;
  }
  $("#source-filter-count").textContent = `${visible} of ${rows.length} shown`;
}
function updateSourceCount() {
  const count =
    $$('input[name="source_artifact_ids"]:checked').length +
    ($("#f-evidence-files")?.files.length || 0);
  if ($("#selected-source-count"))
    $("#selected-source-count").textContent = count
      ? `${count} selected`
      : "Select the files you used";
}
function csvPreviewData(text, rowLimit = 40, columnLimit = 30, partial = false) {
  const rows = [];
  let row = [], value = "", quoted = false, afterQuote = false;
  const source = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    if (quoted) {
      if (char === '"') {
        if (source[i + 1] === '"') { value += '"'; i++; }
        else { quoted = false; afterQuote = true; }
      } else value += char;
    } else if (char === ",") {
      row.push(value); value = ""; afterQuote = false;
    } else if (char === "\n" || char === "\r") {
      row.push(value); rows.push(row);
      row = []; value = ""; afterQuote = false;
      if (char === "\r" && source[i + 1] === "\n") i++;
      if (partial && rows.length > rowLimit) break;
    } else if (char === '"' && !value && !afterQuote) {
      quoted = true;
    } else {
      if (afterQuote || char === '"') return null;
      value += char;
    }
  }
  if (quoted && !partial) return null;
  if (!partial && (value || row.length || afterQuote)) { row.push(value); rows.push(row); }
  if (!rows.length || rows[0].length < 2) return null;
  const columnCount = rows.reduce((max, item) => Math.max(max, item.length), 0);
  return {
    headers: rows[0].slice(0, columnLimit),
    rows: rows.slice(1, rowLimit + 1).map((item) => item.slice(0, columnLimit)),
    rowCount: partial ? null : rows.length - 1, columnCount, partial,
    shownColumns: Math.min(columnCount, columnLimit),
  };
}
function renderFilePreview(element, text, path, partial = false) {
  const csv = /\.csv$/i.test(path || "") && csvPreviewData(text, 40, 30, partial);
  if (!csv) {
    element.textContent = partial ? "Preview of the first 512 KiB. Download the original for the complete file.\n\n" + text : text;
    return;
  }
  const preview = document.createElement("div");
  preview.id = element.id;
  preview.className = element.className + " table-preview";
  const label = partial
    ? `Preview · first ${csv.rows.length} rows · ${csv.shownColumns} columns shown · partial file`
    : `Preview · ${csv.rows.length} of ${csv.rowCount} rows · ${csv.shownColumns} of ${csv.columnCount} columns`;
  const headers = Array.from({ length: csv.shownColumns }, (_, i) => csv.headers[i] || `Column ${i + 1}`);
  preview.innerHTML = `<p class="small muted">${esc(label)}</p><div class="table-scroll" tabindex="0" role="region" aria-label="CSV table preview"><table><thead><tr>${headers.map((name) => `<th scope="col">${esc(name)}</th>`).join("")}</tr></thead><tbody>${csv.rows.map((row) => `<tr>${headers.map((_, i) => `<td>${esc(row[i] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  element.replaceWith(preview);
}
async function previewInlineFile(id) {
  const panel = $("#inline-file-preview");
  if (!panel) return;
  const source = artifact(id);
  panel.hidden = false;
  panel.dataset.file = id;
  const isImage = source?.role === "render_image";
  panel.innerHTML = `<div class="inline-preview-heading"><strong>${esc(fileName(id))}</strong><button class="text-button" type="button" data-action="close-inline-preview">Close preview</button></div>${isImage ? `<img class="preview-image" src="${artifactURL(id)}" alt="${esc(fileName(id))}">` : '<pre class="inline-preview-content" tabindex="0" aria-label="Source file content">Loading file…</pre>'}<a class="text-button" href="${artifactURL(id, true)}" download>Download original</a>`;
  panel.scrollIntoView({ block: "nearest" });
  if (isImage) return;
  try {
    const response = await fetch(artifactURL(id));
    if (!response.ok) {
      const error = await response.json();
      throw new Error(
        error.error || "Download the original file to inspect it.",
      );
    }
    const text = await response.text();
    if (panel.isConnected && panel.dataset.file === id)
      renderFilePreview($(".inline-preview-content", panel), text, source?.path, response.headers.get("X-ClaimTrace-Preview") === "partial");
  } catch (error) {
    if (panel.isConnected && panel.dataset.file === id)
      $(".inline-preview-content", panel).textContent = error.message;
  }
}
async function previewFile(id) {
  const a = artifact(id);
  if (!a) {
    toast("Open the package containing this file.", true);
    return;
  }
  const path = a.path || a.url || a.id;
  const image =
    a.role === "render_image" || /\.(png|jpe?g|tiff?|webp|gif)$/i.test(path);
  dialog(
    path,
    "Linked file",
    `<div class="dialog-body">${image ? `<img class="preview-image" src="${artifactURL(id)}" alt="${esc(path)}">` : '<pre id="file-preview" class="file-preview">Loading file…</pre>'}</div>`,
    `<div class="dialog-footer"><a class="button secondary" href="${artifactURL(id, true)}" download>${icon("download")} Download file</a><button class="button" data-action="close-dialog">Close</button></div>`,
    true,
  );
  if (!image) {
    const preview = $("#file-preview");
    try {
      const response = await fetch(artifactURL(id));
      if (!response.ok) {
        const error = await response.json();
        throw new Error(
          error.error || "Download the original file to inspect it.",
        );
      }
      const text = await response.text();
      if (preview.isConnected) renderFilePreview(preview, text, path, response.headers.get("X-ClaimTrace-Preview") === "partial");
    } catch (e) {
      if (preview.isConnected) preview.textContent = e.message;
    }
  }
}
async function loadSource(id, line, pointer, focus = false) {
  const request = ++sourceRequest;
  const content = $("#source-content");
  if (!content || !id) return;
  state.sourceId = id;
  state.sourceLine = line || null;
  state.sourcePointer = pointer || null;
  content.textContent = "Loading scene…";
  if ($("#source-select")) $("#source-select").value = id;
  if ($("#source-download")) $("#source-download").href = artifactURL(id, true);
  try {
    const response = await fetch(artifactURL(id));
    if (!response.ok) {
      const error = await response.json();
      throw new Error(
        error.error || "Refresh the package to load its scene source.",
      );
    }
    const text = await response.text();
    if (request !== sourceRequest || !$("#source-content")) return;
    content.innerHTML =
      (response.headers.get("X-ClaimTrace-Preview") === "partial"
        ? '<p class="micro-note">Preview of the first 512 KiB. Download the original for the complete file.</p>' : "") +
      (pointer
        ? `<div class="micro-note source-pointer">JSON Pointer: <code>${esc(pointer)}</code></div>`
        : "") +
      text
        .split("\n")
        .map(
          (t, i) =>
            `<div class="source-line ${i + 1 === line ? "highlight" : ""}" ${i + 1 === line ? 'aria-current="location"' : ""}><span class="line-no">${i + 1}</span><span>${esc(t)}</span></div>`,
        )
        .join("");
    content.querySelector(".highlight")?.scrollIntoView({ block: "nearest" });
    if (focus) {
      const target =
        content.querySelector(".highlight, .source-pointer") || content;
      target.tabIndex = -1;
      target.focus({ preventScroll: true });
    }
  } catch (e) {
    if (request === sourceRequest) content.textContent = e.message;
  }
}
function locate(location, fallbackId) {
  const target = linkedScenes().find((s) => sourceWithinScene(location, s));
  if (target) state.sceneId = target.id;
  state.tab = "visual";
  updateDetail();
  const d = $("#source-panel");
  if (!d) return;
  d.open = true;
  const id =
    location?.artifact_id ||
    fallbackId ||
    activeScene()?.native_artifact_ids?.[0];
  loadSource(id, location?.line, location?.json_pointer, true);
  d.scrollIntoView({ block: "nearest", behavior: "smooth" });
}
function bindDropzone() {
  const d = $("#dropzone");
  if (!d) return;
  d.addEventListener("dragover", (e) => {
    e.preventDefault();
    d.classList.add("dragover");
  });
  d.addEventListener("dragleave", () => d.classList.remove("dragover"));
  d.addEventListener("drop", (e) => {
    e.preventDefault();
    d.classList.remove("dragover");
    importFiles([...e.dataTransfer.files]);
  });
}
async function downloadPackage() {
  if (state.busy) return;
  busy(true);
  const button = $('[data-action="download-package"]');
  button.disabled = true;
  button.textContent = "Checking and building package…";
  const feedback = $("#export-feedback");
  feedback.hidden = true;
  try {
    const response = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: state.data.workflow.lifecycle.mode, package_root: state.data.root }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "Review the export requirements.");
    }
    const blob = await response.blob(),
      url = URL.createObjectURL(blob),
      link = document.createElement("a");
    link.href = url;
    link.download = decodeURIComponent(
      response.headers
        .get("Content-Disposition")
        ?.match(/filename\*=UTF-8''([^;]+)/i)?.[1] || "claimtrace-review.zip",
    );
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    feedback.textContent = "Export checks passed. Your browser will download the package.";
    feedback.className = "export-success";
    feedback.hidden = false;
  } catch (error) {
    feedback.textContent = error.message;
    feedback.className = "form-error";
    feedback.hidden = false;
  } finally {
    busy(false);
    button.disabled = false;
    button.innerHTML = `${icon("download")} Download package · ZIP`;
  }
}
async function action(name) {
  switch (name) {
    case "select-visible-sources":
    case "clear-visible-sources":
      for (const row of $$(".evidence-files .source-choice")) {
        if (row.hidden) continue;
        const input = row.querySelector('input[name="source_artifact_ids"]');
        input.checked = name === "select-visible-sources";
        clearFieldError(input);
      }
      updateSourceCount();
      break;
    case "close-inline-preview":
      $("#inline-file-preview").hidden = true;
      $$("[data-inline-file]")
        .find(
          (b) =>
            b.dataset.inlineFile === $("#inline-file-preview").dataset.file,
        )
        ?.focus();
      break;
    case "download-package":
      await downloadPackage();
      break;
    case "view-source":
      locate();
      break;
    case "review-scene":
      setTab("reproducibility");
      break;
    case "package-location":
      dialog(
        "Saved package",
        "Reopen this folder to continue your work.",
        `<div class="dialog-body"><code>${esc(state.data.root)}</code></div>`,
      );
      break;
    case "files":
      dialog(
        "Package files",
        `${list(semantic().artifacts).length} files saved locally`,
        `<div class="dialog-body file-browser">${list(semantic().artifacts)
          .map(
            (a) =>
              `<div>${fileChip(a.id)}<span class="small muted">${esc(fileRole(a))}</span></div>`,
          )
          .join("")}</div>`,
      );
      break;
    case "reload":
      location.reload();
      break;
    case "open":
      openImport();
      break;
    case "open-path":
      openPath();
      break;
    case "pick-import":
      $("#import-files").click();
      break;
    case "close-dialog":
      closeDialog();
      break;
    case "examples":
      await examplePicker();
      break;
    case "help":
      showHelp();
      break;
    case "result-template":
      insertResultTemplate();
      break;
    case "demo":
      await mutate("/api/demo", {}, "Example opened", false);
      break;
    case "new-claim":
      editClaim(false);
      break;
    case "edit-claim":
      editClaim(true);
      break;
    case "add-figure":
      attachForm({ role: "render_image", scene_id: activeScene()?.id });
      break;
    case "add-structure":
      attachForm({ role: "structure" });
      break;
    case "attach":
      attachForm();
      break;
    case "new-evidence":
      evidenceForm();
      break;
    case "identify-regions":
      identityForm();
      break;
    case "explain-colors":
      colorForm();
      break;
    case "new-uncertainty":
      uncertaintyForm();
      break;
    case "context":
      contextForm();
      break;
    case "answers":
      await answersForm();
      break;
    case "saved-answers":
      await showSavedAnswers();
      break;
    case "toggle-issues":
      state.issues = !state.issues;
      updateDetail();
      break;
    case "refresh":
      await mutate("/api/validate", {}, "Audit refreshed");
      break;
    case "export":
      state.view = "export";
      updateDetail();
      break;
    case "export-draft":
      await mutate(
        "/api/lifecycle",
        { mode: "draft" },
        "Working draft selected",
      );
      state.view = "export";
      updateDetail();
      break;
  }
}
document.addEventListener("click", async (event) => {
  const button = event.target.closest("button,a");
  if (!button) return;
  try {
    if (button.dataset.proposal) {
      proposalReviewForm(button.dataset.proposal);
      return;
    }
    if (button.dataset.proposalReview) {
      const decision = button.dataset.decision;
      proposalReviewForm(button.dataset.proposalReview, decision === "edit" ? "accept" : decision, decision === "edit");
      return;
    }
    if (button.dataset.proposalLocate) {
      const proposal = list(state.data?.proposals).find((item) => item.id === button.dataset.proposalLocate);
      const id = proposal && proposalClaimIds(proposal)[0];
      if (id) {
        state.claimId = id;
        state.sceneId = null;
        state.renderId = null;
        setTab("claim");
      }
      return;
    }
    if (button.dataset.proposalScene) {
      const proposal = list(state.data?.proposals).find((item) => item.id === button.dataset.proposalOwner);
      const scene = button.dataset.proposalScene;
      state.claimId = proposalClaimIds(proposal).find((id) => list(list(semantic().claims).find((item) => item.id === id)?.scene_ids).includes(scene)) || null;
      state.sceneId = scene;
      state.renderId = null;
      state.view = state.claimId ? "review" : "prepare";
      state.tab = "visual";
      updateDetail();
      const panel = $(".context-panel");
      if (panel) { panel.tabIndex = -1; panel.focus(); }
      return;
    }
    if (button.dataset.view) {
      state.view = button.dataset.view;
      updateDetail();
      return;
    }
    if (button.dataset.lifecycle) {
      await mutate(
        "/api/lifecycle",
        { mode: button.dataset.lifecycle },
        "Export purpose updated",
      );
      return;
    }
    if (button.dataset.task) {
      const task = list(state.data?.workflow?.tasks).find(
        (t) => t.id === button.dataset.task,
      );
      if (!task) return;
      if (task.claim_id && task.claim_id !== state.claimId) {
        state.claimId = task.claim_id;
        state.sceneId = null;
      }
      if (task.scene_id) state.sceneId = task.scene_id;
      updateDetail();
      if (task.action === "cutoff")
        evidenceForm(task.record_id, "measurement", true);
      else if (task.action === "edit-evidence") evidenceForm(task.record_id);
      else if (task.action === "context") contextForm(task);
      else if (task.action === "answers") await answersForm();
      else if (task.action === "review-proposal") proposalReviewForm(task.record_id);
      else if (task.action === "edit-uncertainty")
        uncertaintyForm(task.record_id);
      else await action(task.action);
      return;
    }
    if (button.dataset.browseScene) {
      state.claimId = null;
      state.sceneId = button.dataset.browseScene;
      state.renderId = null;
      state.view = "prepare";
      render();
      return;
    }
    if (button.dataset.example) {
      if (state.busy) return;
      const result = await mutate(
        "/api/example",
        { id: button.dataset.example },
        "Practice files ready. Add the claim to begin.",
        false,
      );
      if (result) {
        closeDialog();
        $("#main").focus();
      }
      return;
    }
    if (button.dataset.practiceFill) {
      fillPractice(button.dataset.practiceFill);
      return;
    }
    if (button.dataset.action) {
      await action(button.dataset.action);
      return;
    }
    if (button.dataset.mode) {
      state.mode = button.dataset.mode;
      if (state.mode === "simple" && state.tab === "expert")
        state.tab = "visual";
      try {
        localStorage.setItem("claimtrace-mode", state.mode);
      } catch {}
      render();
      return;
    }
    if (button.dataset.claim) {
      state.claimId = button.dataset.claim;
      if (state.view === "export") state.view = "review";
      state.sceneId = null;
      state.renderId = null;
      state.sourceId = null;
      state.issues = false;
      updateDetail();
      $('[data-claim][aria-current="true"]')?.focus({ preventScroll: true });
      return;
    }
    if (button.dataset.filter) {
      state.filter = button.dataset.filter;
      $$("[data-filter]").forEach((b) =>
        b.setAttribute(
          "aria-pressed",
          String(b.dataset.filter === state.filter),
        ),
      );
      $("#claim-list").innerHTML = claimCards();
      return;
    }
    if (button.dataset.stage) {
      setTab(stageTab(button.dataset.stage));
      return;
    }
    if (button.dataset.tab) {
      setTab(button.dataset.tab);
      return;
    }
    if (button.dataset.inlineFile) {
      await previewInlineFile(button.dataset.inlineFile);
      return;
    }
    if (button.dataset.file) {
      await previewFile(button.dataset.file);
      return;
    }
    if (button.dataset.render) {
      state.renderId = button.dataset.render;
      updateDetail();
      return;
    }
    if (button.dataset.selection) {
      const sel = list(semantic().selections).find(
        (s) => s.id === button.dataset.selection,
      );
      locate(sel?.native_selector.source_location, sel?.source_artifact_id);
      return;
    }
    if (button.dataset.operation) {
      const op = list(semantic().observed_scene_operations).find(
        (o) => o.operation_id === button.dataset.operation,
      );
      locate(op?.source_location);
      return;
    }
    if (button.dataset.editEvidence) {
      evidenceForm(button.dataset.editEvidence);
      return;
    }
    if (button.dataset.cutoff) {
      evidenceForm(
        button.dataset.cutoff === "new" ? undefined : button.dataset.cutoff,
        "measurement",
        true,
      );
      return;
    }
    if (button.dataset.editUncertainty) {
      uncertaintyForm(button.dataset.editUncertainty);
    }
  } catch (error) {
    toast(error.message, true);
  }
});
document.addEventListener("input", (event) => {
  clearFieldError(event.target);
  if (event.target.id === "source-filter") filterSourceFiles();
  if (event.target.id === "claim-search") {
    state.query = event.target.value;
    $("#claim-list").innerHTML = claimCards();
  }
});
document.addEventListener("change", (event) => {
  clearFieldError(event.target);
  if (event.target.id === "f-view_kind") updateContextType();
  if (
    event.target.name === "source_artifact_ids" ||
    event.target.id === "f-evidence-files"
  )
    updateSourceCount();
  if (event.target.dataset.colorPurpose !== undefined) {
    const input = $(`#f-color-meaning-${event.target.dataset.colorPurpose}`);
    const color = event.target.dataset.color,
      target = event.target.dataset.target;
    const suggestion =
      event.target.value === "identify"
        ? `${color} identifies ${target}.`
        : event.target.value === "styling"
          ? `${color} distinguishes ${target} for visual clarity.`
          : "";
    if (!input.value.trim() || input.value === input.dataset.suggestion) {
      input.value = suggestion;
      input.dataset.suggestion = suggestion;
    }
    input.focus();
  }
  if (event.target.id === "f-evidence_kind") {
    evidenceHints();
  }
  if (event.target.id === "f-limitation-preset" && event.target.value) {
    const preset = limitationOptions[event.target.value];
    const input = $("#f-statement");
    if (!input.value.trim()) {
      input.value = preset.statement;
      $("#f-category").value = preset.category;
    } else {
      $("#limitation-suggestion").hidden = false;
      $("#limitation-suggestion").textContent = preset.statement;
    }
    input.focus();
  }
  if (event.target.id === "f-role" || event.target.id === "f-files") {
    const box = $("#attachment-scene"),
      type = $("#f-role")?.value;
    if (box && type) {
      const files = [...($("#f-files")?.files || [])];
      box.hidden = !(
        type === "render_image" ||
        (type === "auto" &&
          files.length &&
          files.some((f) =>
            /\.(png|jpe?g|tiff?|webp|gif|svg|pml|cxc|mvsj|mvsx)$/i.test(f.name),
          ))
      );
    }
  }
  if (event.target.id === "f-files") {
    const native = [...event.target.files].some((f) =>
      /\.(pml|cxc|mvsj|mvsx)$/i.test(f.name),
    );
    if (
      native &&
      list(activeScene()?.native_artifact_ids).length &&
      $("#f-scene_id")
    )
      $("#f-scene_id").value = "";
  }
  if (event.target.id === "mobile-claim-select") {
    state.claimId = event.target.value || null;
    if (!state.claimId) state.view = "prepare";
    else if (state.view === "export") state.view = "review";
    state.sceneId = null;
    state.renderId = null;
    state.issues = false;
    updateDetail();
    $("#mobile-claim-select")?.focus({ preventScroll: true });
  }
  if (event.target.id === "import-files") {
    importFiles([...event.target.files]);
    event.target.value = "";
  }
  if (event.target.id === "scene-select") {
    state.sceneId = event.target.value;
    state.renderId = null;
    state.sourceId = null;
    updateDetail();
    $("#scene-select")?.focus({ preventScroll: true });
  }
  if (event.target.id === "source-select") loadSource(event.target.value);
});
document.addEventListener(
  "toggle",
  (event) => {
    if (
      event.target.id === "source-panel" &&
      event.target.open &&
      !state.sourceId
    )
      loadSource($("#source-select")?.value);
  },
  true,
);
document.addEventListener("keydown", (event) => {
  if (
    event.target.getAttribute("role") !== "tab" ||
    !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
  )
    return;
  const tabs = $$("[role=tab]"),
    index = tabs.indexOf(event.target);
  const next =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? tabs.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) %
          tabs.length;
  event.preventDefault();
  const id = tabs[next].dataset.tab;
  setTab(id);
  $(`#tab-${id}`)?.focus();
});
document.addEventListener(
  "error",
  (event) => {
    if (event.target.matches?.("[data-render-image],.preview-image")) {
      const note = document.createElement("p");
      note.className = "form-error";
      note.textContent = "Download the original file to view this figure.";
      event.target.replaceWith(note);
    }
  },
  true,
);
$("#dialog").addEventListener("close", restoreDialogFocus);
$("#dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  closeDialog();
});
window.addEventListener("beforeunload", (event) => {
  if (!hasUnsavedDialog()) return;
  event.preventDefault();
  event.returnValue = "";
});
(async () => {
  try {
    acceptData(await api("/api/state"));
  } catch (e) {
    $("#main").innerHTML =
      `<div class="loading-screen"><p>Start the local ClaimTrace server, then try again.</p><p class="micro-note">${esc(e.message)}</p><button class="button secondary" data-action="reload">Try again</button></div>`;
  }
})();

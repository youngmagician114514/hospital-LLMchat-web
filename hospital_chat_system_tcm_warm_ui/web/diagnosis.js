const caseForm = document.getElementById("caseForm");
const diagnoseBtn = document.getElementById("diagnoseBtn");
const clearBtn = document.getElementById("clearBtn");
const fillDemoBtn = document.getElementById("fillDemoBtn");
const importSampleCaseBtn = document.getElementById("importSampleCaseBtn");
const bulkImportModal = document.getElementById("bulkImportModal");
const bulkImportInput = document.getElementById("bulkImportInput");
const bulkImportBtn = document.getElementById("bulkImportBtn");
const bulkImportSampleBtn = document.getElementById("bulkImportSampleBtn");
const bulkImportClearBtn = document.getElementById("bulkImportClearBtn");
const bulkImportStatus = document.getElementById("bulkImportStatus");
const bulkImportPreview = document.getElementById("bulkImportPreview");
const bulkImportStream = document.getElementById("bulkImportStream");
const closeBulkImportModal = document.getElementById("closeBulkImportModal");
const copyBtn = document.getElementById("copyBtn");
const copyResultBiz = document.getElementById("copyResultBiz");
const modelChip = document.getElementById("modelChip");
const resultMeta = document.getElementById("resultMeta");
const generationBadge = document.getElementById("generationBadge");
const formStatus = document.getElementById("formStatus");
const summaryConclusion = document.getElementById("summaryConclusion");
const summaryHint = document.getElementById("summaryHint");
const followupSection = document.getElementById("sec-followup");
const streamDraft = document.getElementById("streamDraft");
const streamBox = document.getElementById("streamBox");
const diagnosisReasoning = StreamUI.createReasoningPanel();
document.getElementById("diagnosisReasoning").append(diagnosisReasoning.element);
const importReasoning = StreamUI.createReasoningPanel();
document.getElementById("bulkImportReasoning").append(importReasoning.element);

const emptyState = document.getElementById("emptyState");
const skeletonState = document.getElementById("skeletonState");
const resultGrid = document.getElementById("resultGrid");

const outDiagnosis = document.getElementById("outDiagnosis");
const outMain = document.getElementById("outMain");
const outSecondary = document.getElementById("outSecondary");
const outPrescription = document.getElementById("outPrescription");
const outReason = document.getElementById("outReason");

const tongueImageInput = document.getElementById("tongueImageInput");
const imagingFileInput = document.getElementById("imagingFileInput");
const tongueImageList = document.getElementById("tongueImageList");
const imagingFileList = document.getElementById("imagingFileList");
const tonguePreview = document.getElementById("tonguePreview");
const imagingPreview = document.getElementById("imagingPreview");

const sectionNav = document.getElementById("sectionNav");
const navChips = Array.from(document.querySelectorAll(".nav-chip"));
const visitOptions = Array.from(document.querySelectorAll(".visit-option"));
const copyBlockButtons = Array.from(document.querySelectorAll(".mini-copy"));

const currentTimeNode = document.getElementById("currentTime");
const summaryVisitNo = document.getElementById("summaryVisitNo");
const summaryVisitType = document.getElementById("summaryVisitType");
const summaryGenderAge = document.getElementById("summaryGenderAge");
const summaryChief = document.getElementById("summaryChief");
const summaryUpdatedAt = document.getElementById("summaryUpdatedAt");

const assistSyndromeBtn = document.getElementById("assistSyndromeBtn");
const assistPrescriptionBtn = document.getElementById("assistPrescriptionBtn");
const doctorConfirmBtn = document.getElementById("doctorConfirmBtn");

const assistModal = document.getElementById("assistModal");
const assistModalTitle = document.getElementById("assistModalTitle");
const modalSyndrome = document.getElementById("modalSyndrome");
const modalBasis = document.getElementById("modalBasis");
const modalPrescription = document.getElementById("modalPrescription");
const modalComposition = document.getElementById("modalComposition");
const closeAssistModal = document.getElementById("closeAssistModal");

const aiChatLog = document.getElementById("aiChatLog");
const aiChatForm = document.getElementById("aiChatForm");
const aiMessageInput = document.getElementById("aiMessageInput");
const aiSendBtn = document.getElementById("aiSendBtn");
const aiNewChatBtn = document.getElementById("aiNewChatBtn");
const aiChatStatus = document.getElementById("aiChatStatus");
const chatUploadBtn = document.getElementById("chatUploadBtn");

const openAvatarBtn = document.getElementById("openAvatarBtn");
const openHistoryBtn = document.getElementById("openHistoryBtn");
const openStructuredBtn = document.getElementById("openStructuredBtn");
const resultAnchor = document.getElementById("resultAnchor");

const DRAFT_KEY = "hospital_diag_form_draft_v3";
const WORKSPACE_DIALOGUE_SESSION_KEY = "hospital_workspace_dialogue_session_id";
const CHAT_PAGE_MARKER_KEY = "hospital_last_chat_page";
const CHAT_PAGE_CURRENT = "diagnosis_workspace";
const previewUrlStore = { tongue: [], imaging: [] };
const LONG_TEXT_IMPORT_SAMPLE = [
  "性别：男\t年龄：56岁",
  "主诉：右后背疼痛，伴右上肢牵掣疼痛反复5月",
  "现病史：患者曾行针灸，推拿，热敷等治疗，症状未见明显缓解，高血压病史",
  "流行病学史：无特殊。",
  "查体：颈后仰受限，转颈右侧卡压，C6/7棘突旁右侧压痛(+)。",
  "专科检查：上肢腱反射未引出，右臂丛牵拉试验(-)，前屈(-)，双侧霍夫曼(-)，右侧大粗隆压痛(-)。",
  "中医四诊分析：大便2-3日1行，夜寐尚可，苔薄质黯红胖，边有齿痕，脉沉。",
  "辅助检查：颈椎MRI：颈椎生理弧度变直，C5/6、C6/7轻度突出，C6/7后缘偏右侧增生明显。"
].join("\n");

let diagnosisSessionId = localStorage.getItem("hospital_diagnosis_session_id");
let dialogueSessionId = localStorage.getItem(WORKSPACE_DIALOGUE_SESSION_KEY);
let dialogueHistory = [];
let lastResultText = "";
let resultStale = false;
let isRequesting = false;
let bulkImportRequesting = false;
let chatRequesting = false;
let saveDraftTimer = null;
let doctorConfirmed = false;
let shouldForceNewWorkspaceChat = false;

function generateSessionId() {
  const cryptoObj = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (cryptoObj && typeof cryptoObj.getRandomValues === "function") {
    try {
      const bytes = new Uint8Array(16);
      cryptoObj.getRandomValues(bytes);
      return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    } catch (_) {}
  }
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2, 14)}`;
}

if (!diagnosisSessionId) {
  diagnosisSessionId = generateSessionId();
  localStorage.setItem("hospital_diagnosis_session_id", diagnosisSessionId);
}
if (!dialogueSessionId) {
  dialogueSessionId = generateSessionId();
  localStorage.setItem(WORKSPACE_DIALOGUE_SESSION_KEY, dialogueSessionId);
}
const lastChatPage = sessionStorage.getItem(CHAT_PAGE_MARKER_KEY);
shouldForceNewWorkspaceChat = lastChatPage !== CHAT_PAGE_CURRENT;
sessionStorage.setItem(CHAT_PAGE_MARKER_KEY, CHAT_PAGE_CURRENT);

function refreshPrimaryActions() {
  const formBusy = isRequesting || bulkImportRequesting || chatRequesting;
  diagnoseBtn.disabled = formBusy;
  clearBtn.disabled = formBusy;
  fillDemoBtn.disabled = formBusy;
  importSampleCaseBtn.disabled = formBusy;
  ModelControls.setBusy(formBusy);
  caseForm.querySelectorAll("input, select, textarea").forEach(node => {
    node.disabled = formBusy;
  });
  caseForm.querySelectorAll(".field-expand").forEach(button => { button.disabled = formBusy; });
  document.querySelectorAll("#quickQuestions button").forEach(node => {
    node.disabled = formBusy;
  });

  if (bulkImportBtn) {
    bulkImportBtn.disabled = formBusy || !bulkImportInput.value.trim();
  }
  if (bulkImportClearBtn) {
    bulkImportClearBtn.disabled = formBusy || !bulkImportInput.value.trim();
  }
  if (bulkImportSampleBtn) {
    bulkImportSampleBtn.disabled = formBusy;
  }
  if (closeBulkImportModal) {
    closeBulkImportModal.disabled = bulkImportRequesting;
  }
}

function setBusyState(busy) {
  isRequesting = busy;
  refreshPrimaryActions();
}

function setBulkImportBusy(busy) {
  bulkImportRequesting = busy;
  bulkImportModal.classList.toggle("is-recognizing", busy);
  bulkImportInput.disabled = busy;
  refreshPrimaryActions();
}

function openBulkImportDialog() {
  if (!bulkImportModal) return;
  if (typeof bulkImportModal.showModal === "function") {
    bulkImportModal.showModal();
  } else {
    bulkImportModal.setAttribute("open", "open");
  }
  if (bulkImportInput) {
    bulkImportInput.focus();
    const position = bulkImportInput.value.length;
    bulkImportInput.setSelectionRange(position, position);
  }
}

function closeBulkImportDialog() {
  if (!bulkImportModal) return;
  if (typeof bulkImportModal.close === "function") {
    bulkImportModal.close();
  } else {
    bulkImportModal.removeAttribute("open");
  }
}

function showGenerating(show) {
  generationBadge.classList.toggle("hidden", !show);
}

function setStreamDraft(text) {
  const clean = `${text || ""}`;
  streamDraft.textContent = clean.trim() ? clean : "-";
}

function setResultView(mode) {
  if (mode === "generating" || mode === "done") showReviewPanel("resultAnchor");
  const state = document.getElementById("resultState");
  const generating = mode === "generating" || mode === "streaming";
  if (state) state.textContent = generating ? "生成中" : mode === "done" && lastResultText ? "已生成" : "待生成";
  resultAnchor.classList.toggle("is-streaming", mode === "streaming");
  if (streamBox) {
    streamBox.open = mode === "streaming";
    streamBox.hidden = mode === "generating" || mode === "empty";
  }
  copyBtn.disabled = mode !== "done" || !lastResultText || resultStale;
  copyBlockButtons.forEach(button => { button.disabled = copyBtn.disabled; });
  emptyState.classList.toggle("hidden", mode !== "empty");
  skeletonState.classList.toggle("hidden", mode !== "generating");
  resultGrid.classList.toggle("hidden", mode !== "done");
}

function getVisitType() {
  const checked = caseForm.querySelector("input[name='visitType']:checked");
  return checked ? checked.value : "初诊";
}

function updateVisitTypeUI(type) {
  visitOptions.forEach((node) => {
    node.classList.toggle("is-active", node.dataset.type === type);
  });
  followupSection.hidden = type !== "复诊";
  document.getElementById("followupTab").disabled = type !== "复诊";
  setActiveGroup("sec-visit");
  updatePatientSummary();
}

function setActiveGroup(sectionId) {
  const panelId = sectionId === "sec-followup" ? "followupPanel"
    : sectionId === "sec-images" ? "imagesPanel"
    : ["recordPanel", "followupPanel", "imagesPanel"].includes(sectionId) ? sectionId : "recordPanel";
  const selected = panelId === "followupPanel" && getVisitType() !== "复诊" ? "recordPanel" : panelId;
  document.querySelectorAll(".case-panel").forEach(panel => { panel.hidden = panel.id !== selected; });
  navChips.forEach(chip => {
    const active = chip.dataset.target === selected;
    chip.classList.toggle("is-active", active);
    chip.setAttribute("aria-selected", String(active));
    chip.tabIndex = active ? 0 : -1;
  });
  caseForm.scrollTop = 0;
  autoResizeTextareas();
}

function autoResizeTextareas() {
  const narrow = window.matchMedia("(max-width: 700px)").matches;
  caseForm.querySelectorAll("textarea").forEach(ta => {
    ta.style.height = "";
    if (narrow && ta.offsetParent !== null) {
      ta.style.height = "auto";
      ta.style.height = `${Math.min(ta.scrollHeight, 220)}px`;
    }
  });
}

function showReviewPanel(panelId) {
  const selected = panelId === "chatPanel" ? "chatPanel" : "resultAnchor";
  for (const id of ["resultAnchor", "chatPanel"]) {
    document.getElementById(id).hidden = id !== selected;
  }
  document.querySelectorAll("#reviewNav button").forEach(button => {
    const active = button.dataset.panel === selected;
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  if (selected === "chatPanel") {
    resizeAiInput();
    scrollAiChatBottom();
  }
}

function escapeRegExp(source) {
  return source.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function extractField(raw, label, nextLabel) {
  const tail = nextLabel ? `(?=${escapeRegExp(nextLabel)}[:：])` : "$";
  const reg = new RegExp(`${escapeRegExp(label)}[:：]\\s*([\\s\\S]*?)\\s*${tail}`);
  const match = raw.match(reg);
  return match ? match[1].trim() : "";
}

function parseStructuredReply(rawText) {
  const source = `${rawText || ""}`.trim();
  const labels = ["西医诊断", "主证", "兼证", "方药", "理由"];
  const output = {
    "西医诊断": "",
    "主证": "",
    "兼证": "",
    "方药": "",
    "理由": ""
  };

  labels.forEach((label, index) => {
    const nextLabel = labels[index + 1] || null;
    output[label] = extractField(source, label, nextLabel);
  });

  const hasAny = Object.values(output).some((item) => item);
  if (!hasAny) {
    output["西医诊断"] = "未明确";
    output["主证"] = "未明确";
    output["兼证"] = "未明确";
    output["方药"] = "未明确";
    output["理由"] = source || "未明确";
    return output;
  }

  labels.forEach((label) => {
    if (!output[label]) output[label] = "未明确";
  });
  return output;
}

function renderOutput(structured) {
  outDiagnosis.textContent = structured["西医诊断"];
  outMain.textContent = structured["主证"];
  outSecondary.textContent = structured["兼证"];
  outPrescription.textContent = structured["方药"];
  outReason.textContent = structured["理由"];
}

function renderError(detail) {
  outDiagnosis.textContent = "请求失败";
  outMain.textContent = "-";
  outSecondary.textContent = "-";
  outPrescription.textContent = "-";
  outReason.textContent = detail || "未知错误";
}

function clearOutput() {
  diagnosisReasoning.reset();
  resultStale = false;
  resultAnchor.classList.remove("has-stale-result");
  outDiagnosis.textContent = "-";
  outMain.textContent = "-";
  outSecondary.textContent = "-";
  outPrescription.textContent = "-";
  outReason.textContent = "-";
  setStreamDraft("-");
  summaryConclusion.textContent = "待生成";
  summaryHint.textContent = "依据本次病历";
  resultMeta.textContent = "";
  lastResultText = "";
  doctorConfirmed = false;
  if (doctorConfirmBtn) {
    doctorConfirmBtn.classList.remove("is-confirmed");
    doctorConfirmBtn.textContent = "医生确认";
  }
  setResultView("empty");
}

function buildFullResultText(structured) {
  return [
    `西医诊断：${structured["西医诊断"]}`,
    `主证：${structured["主证"]}`,
    `兼证：${structured["兼证"]}`,
    `方药：${structured["方药"]}`,
    `理由：${structured["理由"]}`
  ].join("\n");
}

function formatBytes(size) {
  if (size < 1024) return `${size}B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`;
  return `${(size / (1024 * 1024)).toFixed(2)}MB`;
}

function formatDate(timestamp) {
  const d = new Date(timestamp);
  const yy = d.getFullYear();
  const mm = `${d.getMonth() + 1}`.padStart(2, "0");
  const dd = `${d.getDate()}`.padStart(2, "0");
  const hh = `${d.getHours()}`.padStart(2, "0");
  const mi = `${d.getMinutes()}`.padStart(2, "0");
  return `${yy}-${mm}-${dd} ${hh}:${mi}`;
}

function clearPreviewUrls(kind) {
  const urls = previewUrlStore[kind];
  urls.forEach((url) => URL.revokeObjectURL(url));
  previewUrlStore[kind] = [];
}

function renderUploadPanel(inputNode, listNode, previewNode, kind) {
  const files = Array.from(inputNode.files || []);
  listNode.innerHTML = "";
  previewNode.innerHTML = "";
  clearPreviewUrls(kind);

  if (!files.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "未上传";
    listNode.appendChild(empty);
    return;
  }

  files.forEach((file) => {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.className = "file-item-name";
    name.textContent = file.name;
    const meta = document.createElement("span");
    meta.className = "file-item-meta";
    meta.textContent = `${formatBytes(file.size)} · ${formatDate(file.lastModified)}`;
    li.appendChild(name);
    li.appendChild(meta);
    listNode.appendChild(li);

    if (file.type.startsWith("image/")) {
      const url = URL.createObjectURL(file);
      previewUrlStore[kind].push(url);

      const card = document.createElement("figure");
      card.className = "preview-item";

      const img = document.createElement("img");
      img.src = url;
      img.alt = file.name;
      img.loading = "lazy";

      const cap = document.createElement("figcaption");
      cap.textContent = file.name;

      card.appendChild(img);
      card.appendChild(cap);
      previewNode.appendChild(card);
    }
  });
}

function collectFileInfos(inputNode) {
  const files = Array.from(inputNode.files || []);
  if (!files.length) return "未上传";
  return files
    .map((file, idx) => `${idx + 1}. ${file.name}（${formatBytes(file.size)}，${formatDate(file.lastModified)}）`)
    .join("\n");
}

function readValue(id) {
  const node = document.getElementById(id);
  return node ? node.value.trim() : "";
}

function collectFormData() {
  return {
    visitType: getVisitType(),
    firstVisitDate: readValue("firstVisitDate"),
    firstVisitDiagnosis: readValue("firstVisitDiagnosis"),
    firstVisitPrescription: readValue("firstVisitPrescription"),
    afterChange: readValue("afterChange"),
    patientGender: document.getElementById("patientGender").value || "",
    patientAge: readValue("patientAge"),
    chiefComplaint: readValue("chiefComplaint"),
    presentIllness: readValue("presentIllness"),
    physicalExam: readValue("physicalExam"),
    imagingFindings: readValue("imagingFindings"),
    tonguePulse: readValue("tonguePulse"),
    historyAllergy: readValue("historyAllergy")
  };
}
function applyFormData(data) {
  if (!data) return;
  const setIfExist = (id, value) => {
    const node = document.getElementById(id);
    if (node && typeof value === "string") node.value = value;
  };

  if (data.visitType === "复诊" || data.visitType === "初诊") {
    const radio = caseForm.querySelector(`input[name='visitType'][value='${data.visitType}']`);
    if (radio) radio.checked = true;
    updateVisitTypeUI(data.visitType);
  }

  setIfExist("firstVisitDate", data.firstVisitDate);
  setIfExist("firstVisitDiagnosis", data.firstVisitDiagnosis);
  setIfExist("firstVisitPrescription", data.firstVisitPrescription);
  setIfExist("afterChange", data.afterChange);
  setIfExist("patientAge", data.patientAge);
  setIfExist("chiefComplaint", data.chiefComplaint);
  setIfExist("presentIllness", data.presentIllness);
  setIfExist("physicalExam", data.physicalExam);
  setIfExist("imagingFindings", data.imagingFindings);
  setIfExist("tonguePulse", data.tonguePulse);
  setIfExist("historyAllergy", data.historyAllergy);

  const gender = document.getElementById("patientGender");
  if (gender && typeof data.patientGender === "string") {
    gender.value = data.patientGender;
  }
}

function hasMeaningfulAutofillData(data) {
  if (!data) return false;
  return Object.entries(data).some(([key, value]) => key !== "visitType" && `${value || ""}`.trim());
}

function refreshVisitNumber() {
  if (!summaryVisitNo) return;
  summaryVisitNo.textContent = `OP-${diagnosisSessionId.slice(0, 8).toUpperCase()}`;
}

function clearUploadInputs() {
  if (tongueImageInput) tongueImageInput.value = "";
  if (imagingFileInput) imagingFileInput.value = "";
  renderUploadPanel(tongueImageInput, tongueImageList, tonguePreview, "tongue");
  renderUploadPanel(imagingFileInput, imagingFileList, imagingPreview, "imaging");
}

function resetCaseFormState({ clearImportText = false } = {}) {
  caseForm.reset();
  caseForm.scrollTop = 0;
  updateVisitTypeUI("初诊");
  clearUploadInputs();
  localStorage.removeItem(DRAFT_KEY);
  if (summaryUpdatedAt) summaryUpdatedAt.textContent = "—";
  clearOutput();
  updatePatientSummary();
  autoResizeTextareas();

  if (clearImportText && bulkImportInput) {
    bulkImportInput.value = "";
    importReasoning.reset();
  }
  if (clearImportText && bulkImportStatus) {
    bulkImportStatus.textContent = "待粘贴";
  }
  refreshPrimaryActions();
}

function updatePatientSummary() {
  const fields = ["patientGender", "patientAge", "chiefComplaint", "presentIllness", "physicalExam", "imagingFindings", "tonguePulse", "historyAllergy"];
  const count = fields.filter(id => readValue(id)).length;
  const completion = document.getElementById("caseCompletion");
  if (completion) completion.textContent = `${count} / ${fields.length} 项`;
  if (!summaryVisitType || !summaryGenderAge || !summaryChief || !summaryUpdatedAt) return;
  const formData = collectFormData();
  summaryVisitType.textContent = formData.visitType;

  if (!formData.patientGender && !formData.patientAge) {
    summaryGenderAge.textContent = "未填写";
  } else {
    const ageText = formData.patientAge ? `${formData.patientAge}岁` : "年龄未填";
    summaryGenderAge.textContent = `${formData.patientGender || "性别未填"} / ${ageText}`;
  }

  summaryChief.textContent = formData.chiefComplaint || "待填写";
  summaryChief.title = formData.chiefComplaint || "";
}

function saveDraft() {
  try {
    const savedAt = new Date();
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ ...collectFormData(), savedAt: savedAt.toISOString() }));
    const savedTime = savedAt.toLocaleTimeString("zh-CN", { hour12: false });
    if (summaryUpdatedAt) summaryUpdatedAt.textContent = savedTime;
    formStatus.textContent = `已保存至本机 ${savedTime}`;
  } catch (_) {
    formStatus.textContent = "草稿保存失败";
  }
}

function scheduleSaveDraft() {
  if (saveDraftTimer) clearTimeout(saveDraftTimer);
  saveDraftTimer = setTimeout(saveDraft, 280);
}

function loadDraft() {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return;
    const draft = JSON.parse(raw);
    applyFormData(draft);
    if (summaryUpdatedAt && draft.savedAt) {
      const savedAt = new Date(draft.savedAt);
      if (!Number.isNaN(savedAt.getTime())) summaryUpdatedAt.textContent = savedAt.toLocaleTimeString("zh-CN", { hour12: false });
    }
    formStatus.textContent = "已恢复本地草稿";
  } catch (_) {
    formStatus.textContent = "本机草稿读取失败";
  }
}

function buildCaseMessage() {
  const data = collectFormData();
  if (!data.chiefComplaint && !data.presentIllness) {
    return { error: "请填写主诉或现病史。" };
  }

  const lines = [
    "【病历审核信息】",
    `就诊类型：${data.visitType}`,
    "【基础资料】",
    `性别：${data.patientGender || "未填写"}`,
    `年龄：${data.patientAge || "未填写"}`,
    "【现病史】",
    `主诉：${data.chiefComplaint || "未填写"}`,
    `现病史：${data.presentIllness || "未填写"}`,
    "【检查资料】",
    `查体：${data.physicalExam || "未填写"}`,
    `影像学/检验：${data.imagingFindings || "未填写"}`,
    "【中医补充】",
    `舌脉：${data.tonguePulse || "未填写"}`,
    `既往史/家族史/过敏史/补充：${data.historyAllergy || "未填写"}`
  ];

  if (data.visitType === "复诊") {
    lines.push(
      "【复诊关联信息】",
      `初诊时间：${data.firstVisitDate || "未填写"}`,
      `初诊诊断：${data.firstVisitDiagnosis || "未填写"}`,
      `初诊方药与剂量：${data.firstVisitPrescription || "未填写"}`,
      `服药后变化：${data.afterChange || "未填写"}`
    );
  }

  lines.push(
    "【上传资料】",
    `舌相图片：\n${collectFileInfos(tongueImageInput)}`,
    `检查影像图片：\n${collectFileInfos(imagingFileInput)}`
  );

  return { message: lines.join("\n") };
}

function buildWorkspaceDialogueCaseContext() {
  const data = collectFormData();
  const lines = [
    `就诊类型：${data.visitType}`,
    `性别：${data.patientGender || "未填写"}`,
    `年龄：${data.patientAge || "未填写"}`,
    `主诉：${data.chiefComplaint || "未填写"}`,
    `现病史：${data.presentIllness || "未填写"}`,
    `查体：${data.physicalExam || "未填写"}`,
    `影像学/检验：${data.imagingFindings || "未填写"}`,
    `舌脉：${data.tonguePulse || "未填写"}`,
    `既往史/家族史/过敏史/补充：${data.historyAllergy || "未填写"}`
  ];

  if (data.visitType === "复诊") {
    lines.push(
      `初诊时间：${data.firstVisitDate || "未填写"}`,
      `初诊诊断：${data.firstVisitDiagnosis || "未填写"}`,
      `初诊方药与剂量：${data.firstVisitPrescription || "未填写"}`,
      `服药后变化：${data.afterChange || "未填写"}`
    );
  }

  lines.push(
    `舌相图片：\n${collectFileInfos(tongueImageInput)}`,
    `检查影像图片：\n${collectFileInfos(imagingFileInput)}`
  );

  return lines.join("\n");
}


async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (_) {
      ok = false;
    }
    document.body.removeChild(ta);
    return ok;
  }
}

async function fallbackChatOnce(payload) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return await res.json();
}

async function diagnose() {
  if (isRequesting || bulkImportRequesting || chatRequesting) return;
  const invalidField = caseForm.querySelector(":invalid");
  if (invalidField) {
    setActiveGroup(invalidField.closest(".case-panel")?.id || "recordPanel");
    invalidField.reportValidity();
    return;
  }
  const payload = buildCaseMessage();
  if (payload.error) {
    formStatus.textContent = payload.error;
    setActiveGroup("recordPanel");
    document.getElementById("chiefComplaint").focus();
    return;
  }

  const reqBody = {
    session_id: diagnosisSessionId,
    message: payload.message,
    history: [],
    use_server_history: false,
    thinking_level: ModelControls.getThinkingLevel()
  };

  clearOutput();
  setResultView("generating");
  setBusyState(true);
  showGenerating(true);
  resultMeta.textContent = reqBody.thinking_level === "off" ? "生成中…" : "思考中…";
  summaryConclusion.textContent = "正在生成建议…";
  summaryHint.textContent = "";

  let streamBuffer = "";
  const writer = StreamUI.createWriter(text => {
    if (!resultAnchor.classList.contains("is-streaming")) {
      setResultView("streaming");
      resultMeta.textContent = "生成中…";
    }
    setStreamDraft(text);
  });
  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "text/event-stream"
      },
      body: JSON.stringify(reqBody)
    });

    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const data = await res.json();
        detail = data.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }

    if (!res.body) {
      const oneShot = await fallbackChatOnce(reqBody);
      const finalText = `${oneShot.reply || ""}`.trim();
      if (!finalText) throw new Error("模型未返回有效内容");
      writer.push(finalText);
      await writer.finish();
      setStreamDraft(finalText);
      const structured = parseStructuredReply(finalText);
      renderOutput(structured);
      lastResultText = buildFullResultText(structured);

      if (oneShot.session_id) {
        diagnosisSessionId = oneShot.session_id;
        localStorage.setItem("hospital_diagnosis_session_id", diagnosisSessionId);
      }

      summaryConclusion.textContent = structured["西医诊断"];
      summaryHint.textContent = `主证：${structured["主证"]}`;
      resultMeta.textContent = ModelControls.formatMeta(oneShot);
      setResultView("done");
      return;
    }

    let doneEvent = null;
    for await (const event of StreamUI.readEvents(res)) {
      if (event.type === "reasoning" && typeof event.delta === "string") {
        diagnosisReasoning.push(event.delta);
        skeletonState.classList.add("hidden");
        document.getElementById("resultState").textContent = "思考中";
      } else if (event.type === "token" && typeof event.delta === "string") {
        diagnosisReasoning.complete();
        streamBuffer += event.delta;
        writer.push(event.delta);
      } else if (event.type === "error") {
        throw new Error(event.detail || "生成连接中断");
      } else if (event.type === "done") {
        doneEvent = event;
      }
    }
    if (!doneEvent) throw new Error("生成连接中断，请重试");
    const finalText = doneEvent && typeof doneEvent.reply === "string"
      ? doneEvent.reply.trim()
      : streamBuffer.trim();
    if (!finalText) throw new Error("模型未返回有效内容");
    if (!streamBuffer) writer.push(finalText);
    await diagnosisReasoning.finish();
    await writer.finish();

    setStreamDraft(finalText);
    const structured = parseStructuredReply(finalText);
    renderOutput(structured);
    lastResultText = buildFullResultText(structured);

    summaryConclusion.textContent = structured["西医诊断"];
    summaryHint.textContent = `主证：${structured["主证"]}`;
    setResultView("done");

    if (doneEvent && doneEvent.session_id) {
      diagnosisSessionId = doneEvent.session_id;
      localStorage.setItem("hospital_diagnosis_session_id", diagnosisSessionId);
    }
    resultMeta.textContent = doneEvent
      ? ModelControls.formatMeta(doneEvent)
      : "已完成";
  } catch (err) {
    diagnosisReasoning.fail();
    writer.stop();
    renderError(err.message || "请求失败");
    setStreamDraft(streamBuffer || "生成失败");
    summaryConclusion.textContent = "本次生成失败";
    summaryHint.textContent = "生成失败，请重试。";
    resultMeta.textContent = "生成失败";
    setResultView("done");
    lastResultText = "";
    const state = document.getElementById("resultState");
    if (state) state.textContent = "生成失败";
  } finally {
    writer.stop();
    showGenerating(false);
    setBusyState(false);
  }
}
async function clearDiagnosisSession() {
  try {
    await fetch("/api/session/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: diagnosisSessionId })
    });
  } catch (_) {}
}

async function renewDiagnosisSession() {
  await clearDiagnosisSession();
  diagnosisSessionId = generateSessionId();
  localStorage.setItem("hospital_diagnosis_session_id", diagnosisSessionId);
  refreshVisitNumber();
}

async function runBulkImport({ statusPrefix = "识别完成" } = {}) {
  if (!bulkImportInput) return;
  if (isRequesting || bulkImportRequesting || chatRequesting) {
    if (bulkImportStatus) {
      bulkImportStatus.textContent = "当前仍有请求在处理中，请稍后再导入";
    }
    return;
  }
  const sourceText = bulkImportInput.value.trim();
  if (!sourceText) {
    if (bulkImportStatus) bulkImportStatus.textContent = "请粘贴病例";
    refreshPrimaryActions();
    return;
  }

  setBulkImportBusy(true);
  importReasoning.reset();
  if (bulkImportStatus) bulkImportStatus.textContent = ModelControls.getThinkingLevel() === "off" ? "识别中…" : "思考中…";
  bulkImportPreview.hidden = false;
  bulkImportPreview.classList.add("is-streaming");
  bulkImportStream.textContent = "";
  const labels = { visitType: "就诊类型", patientGender: "性别", patientAge: "年龄", chiefComplaint: "主诉", presentIllness: "现病史", physicalExam: "查体", imagingFindings: "影像学/检验", tonguePulse: "舌脉", historyAllergy: "既往史与过敏史", firstVisitDate: "初诊时间", firstVisitDiagnosis: "初诊诊断", firstVisitPrescription: "初诊方药", afterChange: "服药后变化" };
  const writer = StreamUI.createWriter(text => {
    bulkImportStream.textContent = text;
    bulkImportStream.scrollTop = bulkImportStream.scrollHeight;
    bulkImportStatus.textContent = "识别中…";
  });

  try {
    const res = await fetch("/api/form/autofill/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_text: sourceText, thinking_level: ModelControls.getThinkingLevel() })
    });

    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const payload = await res.json();
        detail = payload.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }

    let payload = null;
    for await (const event of StreamUI.readEvents(res)) {
      if (event.type === "reasoning" && event.delta) {
        importReasoning.push(event.delta);
      } else if (event.type === "field" && labels[event.field] && event.value) {
        importReasoning.complete();
        writer.push(`${labels[event.field]}：${event.value}\n`);
      } else if (event.type === "done") {
        payload = event;
      } else if (event.type === "error") {
        throw new Error(event.detail || "识别连接中断");
      }
    }
    if (!payload) throw new Error("识别连接中断，请重试");
    await importReasoning.finish();
    await writer.finish();
    const data = payload.data || {};
    if (!hasMeaningfulAutofillData(data)) {
      throw new Error("未识别到可填充字段，请检查原文标签是否完整");
    }

    await renewDiagnosisSession();
    resetCaseFormState();
    applyFormData(data);
    autoResizeTextareas();
    updatePatientSummary();
    saveDraft();
    await resetWorkspaceChatForNewCase({
      introText: "病历已导入，可继续提问。",
      statusText: "已切换到本次病历"
    });

    formStatus.textContent = "病历已导入";
    if (bulkImportStatus) {
      bulkImportStatus.textContent = `${statusPrefix} · ${ModelControls.formatMeta(payload)}`;
    }
    closeBulkImportDialog();
  } catch (err) {
    importReasoning.fail();
    writer.stop();
    if (bulkImportStatus) {
      bulkImportStatus.textContent = `识别失败：${err.message || "未知错误"}`;
    }
  } finally {
    writer.stop();
    bulkImportPreview.classList.remove("is-streaming");
    setBulkImportBusy(false);
  }
}

async function clearAll() {
  if (isRequesting || bulkImportRequesting || chatRequesting) return;
  await renewDiagnosisSession();
  resetCaseFormState({ clearImportText: true });
  await resetWorkspaceChatForNewCase({
    introText: "可结合当前病历提问。",
    statusText: "新会话"
  });
  formStatus.textContent = "新病历";
}

function loadBulkImportSample() {
  if (!bulkImportInput || isRequesting || bulkImportRequesting || chatRequesting) return;
  bulkImportInput.value = LONG_TEXT_IMPORT_SAMPLE;
  bulkImportPreview.hidden = true;
  if (bulkImportStatus) bulkImportStatus.textContent = "示例已载入";
  refreshPrimaryActions();
  bulkImportInput.focus();
  bulkImportInput.setSelectionRange(bulkImportInput.value.length, bulkImportInput.value.length);
}

function fillDemo() {
  if (isRequesting || bulkImportRequesting || chatRequesting) return;
  openBulkImportDialog();
}

async function copyAllResult() {
  if (!lastResultText || resultStale) {
    resultMeta.textContent = "暂无可复制的结果";
    return;
  }
  const ok = await copyText(lastResultText);
  const old = copyBtn.textContent;
  copyBtn.textContent = ok ? "已复制" : "复制失败";
  if (copyResultBiz) {
    const bizOld = copyResultBiz.textContent;
    copyResultBiz.textContent = ok ? "已复制" : "复制失败";
    setTimeout(() => {
      copyResultBiz.textContent = bizOld;
    }, 1200);
  }
  setTimeout(() => {
    copyBtn.textContent = old;
  }, 1200);
}

async function copySingleBlock(targetId, button) {
  if (!lastResultText || resultStale || isRequesting) return;
  const node = document.getElementById(targetId);
  if (!node) return;
  const text = node.textContent ? node.textContent.trim() : "";
  if (!text || text === "-") return;
  const ok = await copyText(text);
  const old = button.textContent;
  button.textContent = ok ? "已复制" : "失败";
  setTimeout(() => {
    button.textContent = old;
  }, 900);
}

function bindSectionNav() {
  sectionNav.addEventListener("click", (event) => {
    const button = event.target.closest(".nav-chip");
    if (button && !button.disabled) setActiveGroup(button.dataset.target);
  });
  document.getElementById("reviewNav").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-panel]");
    if (button) showReviewPanel(button.dataset.panel);
  });
  for (const nav of [sectionNav, document.getElementById("reviewNav")]) {
    nav.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      const buttons = Array.from(nav.querySelectorAll("button:not(:disabled)"));
      const index = buttons.indexOf(event.target);
      if (index < 0) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next].click();
      buttons[next].focus();
    });
  }
}

function openAssistDialog() {
  if (!assistModal) return;
  if (typeof assistModal.showModal === "function") {
    assistModal.showModal();
  } else {
    assistModal.setAttribute("open", "open");
  }
}

function closeAssistDialog() {
  if (!assistModal) return;
  if (typeof assistModal.close === "function") {
    assistModal.close();
  } else {
    assistModal.removeAttribute("open");
  }
}

function openAssistModal(mode) {
  const diagnosisText = outDiagnosis.textContent.trim();
  const mainText = outMain.textContent.trim();
  const secondaryText = outSecondary.textContent.trim();
  const prescriptionText = outPrescription.textContent.trim();
  const reasonText = outReason.textContent.trim();

  if (mode === "syndrome") {
    assistModalTitle.textContent = "辅助辨证结果";
    modalSyndrome.textContent = `主证：${mainText}\n兼证：${secondaryText}`;
    modalBasis.textContent = reasonText;
    modalPrescription.textContent = diagnosisText;
    modalComposition.textContent = prescriptionText;
  } else {
    assistModalTitle.textContent = "辅助开方结果";
    modalSyndrome.textContent = `中医辨证：${mainText}；${secondaryText}`;
    modalBasis.textContent = reasonText;
    modalPrescription.textContent = `西医诊断：${diagnosisText}`;
    modalComposition.textContent = prescriptionText;
  }

  openAssistDialog();
}

function toggleDoctorConfirm() {
  if (!doctorConfirmBtn) return;
  doctorConfirmed = !doctorConfirmed;
  doctorConfirmBtn.classList.toggle("is-confirmed", doctorConfirmed);
  doctorConfirmBtn.textContent = doctorConfirmed ? "已确认" : "医生确认";
  resultMeta.textContent = doctorConfirmed
    ? `医生已确认 · ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`
    : resultMeta.textContent;
}

function refreshClock() {
  if (!currentTimeNode) return;
  currentTimeNode.textContent = new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" });
}

async function refreshHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    modelChip.textContent = data.provider === "stub-test" ? "演示模式" : data.provider;
    modelChip.title = data.provider === "stub-test" ? "仅演示页面流程，未调用模型" : "当前配置的模型；实际可用性以请求结果为准";
    modelChip.classList.remove("is-offline");
  } catch (_) {
    modelChip.textContent = "服务未连接";
    modelChip.classList.add("is-offline");
  }
}

function setChatBusy(busy) {
  chatRequesting = busy;
  if (aiNewChatBtn) aiNewChatBtn.disabled = busy;
  refreshPrimaryActions();
  refreshAiSendStyle();
}

function resizeAiInput() {
  aiMessageInput.style.height = "auto";
  aiMessageInput.style.height = `${Math.min(aiMessageInput.scrollHeight, 180)}px`;
}

function refreshAiSendStyle() {
  const hasText = aiMessageInput.value.trim().length > 0;
  aiSendBtn.disabled = chatRequesting || !hasText;
}

function scrollAiChatBottom() {
  aiChatLog.scrollTop = aiChatLog.scrollHeight;
}

function appendAiMessage(role, text, meta = "") {
  const row = document.createElement("div");
  aiChatLog.querySelector(".chat-welcome")?.remove();
  row.className = `chat-row ${role}`;

  const avatar = document.createElement("div");
  avatar.className = `chat-avatar ${role}`;
  avatar.textContent = role === "assistant" ? "AI" : "医";

  const wrap = document.createElement("div");
  wrap.className = "chat-bubble-wrap";

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  bubble.textContent = text;
  wrap.appendChild(bubble);

  if (meta) {
    const metaDiv = document.createElement("div");
    metaDiv.className = "chat-meta";
    metaDiv.textContent = meta;
    wrap.appendChild(metaDiv);
  }

  row.appendChild(avatar);
  row.appendChild(wrap);
  aiChatLog.appendChild(row);
  scrollAiChatBottom();

  return { row, wrap, bubble };
}

function createStreamingAiBubble(initialText = "回复中…") {
  const node = appendAiMessage("assistant", initialText, "");
  const reasoning = StreamUI.createReasoningPanel({ onUpdate: scrollAiChatBottom });
  node.wrap.prepend(reasoning.element);
  node.bubble.classList.add("streaming");
  const writer = StreamUI.createWriter(text => {
    node.bubble.textContent = text;
    scrollAiChatBottom();
  });

  return {
    pushReasoning(delta) {
      if (!writer.getText()) node.bubble.hidden = true;
      reasoning.push(delta);
    },
    push(delta) {
      reasoning.complete();
      node.bubble.hidden = false;
      writer.push(delta);
    },
    async finalize(text, meta) {
      await reasoning.finish();
      if (!writer.getText() && text) writer.push(text);
      await writer.finish();
      node.bubble.classList.remove("streaming");
      node.bubble.hidden = false;
      node.bubble.textContent = text;
      if (meta) {
        const metaDiv = document.createElement("div");
        metaDiv.className = "chat-meta";
        metaDiv.textContent = meta;
        node.wrap.appendChild(metaDiv);
      }
      scrollAiChatBottom();
    },
    fail(detail) {
      reasoning.fail();
      writer.stop();
      node.bubble.classList.remove("streaming");
      node.bubble.hidden = false;
      node.bubble.textContent = [writer.getText(), detail].filter(Boolean).join("\n\n");
      scrollAiChatBottom();
    }
  };
}

async function clearDialogueSession() {
  try {
    await fetch("/api/workspace/session/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: dialogueSessionId })
    });
  } catch (_) {}
}

async function streamDialogueReply(userText) {
  setChatBusy(true);
  appendAiMessage("user", userText, "");
  const waitingText = ModelControls.getThinkingLevel() === "off" ? "回复中…" : "思考中…";
  const streamNode = createStreamingAiBubble(waitingText);
  aiChatStatus.textContent = waitingText;
  const caseContext = buildWorkspaceDialogueCaseContext();
  const composedMessage = [
    "【当前病历信息】",
    caseContext,
    "【本轮医生追问】",
    userText,
    "请基于以上病历继续给出追问建议。"
  ].join("\n");

  try {
    const res = await fetch("/api/workspace/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: dialogueSessionId,
        message: composedMessage,
        history: dialogueHistory,
        use_server_history: false,
        thinking_level: ModelControls.getThinkingLevel()
      })
    });

    if (!res.ok || !res.body) {
      let detail = `HTTP ${res.status}`;
      try {
        const payload = await res.json();
        detail = payload.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }

    let doneEvent = null;
    for await (const event of StreamUI.readEvents(res)) {
      if (event.type === "reasoning" && event.delta) {
        streamNode.pushReasoning(event.delta);
      } else if (event.type === "token" && event.delta) {
        streamNode.push(event.delta);
        aiChatStatus.textContent = "回复中…";
      } else if (event.type === "done") {
        doneEvent = event;
      } else if (event.type === "error") {
        throw new Error(event.detail || "问诊连接中断");
      }
    }

    if (!doneEvent) throw new Error("问诊流中断");

    dialogueSessionId = doneEvent.session_id || dialogueSessionId;
    localStorage.setItem(WORKSPACE_DIALOGUE_SESSION_KEY, dialogueSessionId);
    dialogueHistory = doneEvent.history || [];
    const meta = ModelControls.formatMeta(doneEvent);
    await streamNode.finalize(doneEvent.reply || "", meta);
    aiChatStatus.textContent = "Enter 发送 · Shift + Enter 换行";
  } catch (err) {
    streamNode.fail(`请求失败：${err.message}`);
    aiChatStatus.textContent = "请求失败，请重试";
  } finally {
    setChatBusy(false);
    aiMessageInput.focus();
    resizeAiInput();
  }
}

async function sendAiMessage() {
  if (chatRequesting) return;
  const text = aiMessageInput.value.trim();
  if (!text) return;
  aiMessageInput.value = "";
  resizeAiInput();
  refreshAiSendStyle();
  await streamDialogueReply(text);
}

async function resetWorkspaceChatForNewCase({
  introText = "可结合当前病历提问。",
  statusText = "Enter 发送 · Shift + Enter 换行"
} = {}) {
  if (chatRequesting) return false;
  await clearDialogueSession();
  dialogueSessionId = generateSessionId();
  localStorage.setItem(WORKSPACE_DIALOGUE_SESSION_KEY, dialogueSessionId);
  dialogueHistory = [];
  aiChatLog.innerHTML = "";
  aiMessageInput.value = "";
  resizeAiInput();
  appendInitialAiMessage();
  aiChatStatus.textContent = statusText;
  refreshAiSendStyle();
  return true;
}

async function startNewAiChat() {
  await resetWorkspaceChatForNewCase();
}

function appendInitialAiMessage() {
  aiChatLog.innerHTML = "";
  const welcome = document.createElement("div");
  welcome.className = "chat-welcome";
  const icon = document.createElement("span");
  icon.className = "welcome-icon";
  icon.textContent = "✳";
  icon.setAttribute("aria-hidden", "true");
  const title = document.createElement("h3");
  title.textContent = "本次问诊";
  const hint = document.createElement("p");
  hint.textContent = "可结合病历补充询问。";
  welcome.append(icon, title, hint);
  aiChatLog.appendChild(welcome);
}

function markResultStale() {
  if (!lastResultText) return;
  resultStale = true;
  resultAnchor.classList.add("has-stale-result");
  document.getElementById("resultState").textContent = "需重新生成";
  summaryHint.textContent = "病历已修改，请重新生成建议。";
  copyBtn.disabled = true;
  copyBlockButtons.forEach(button => { button.disabled = true; });
}

caseForm.addEventListener("change", (event) => {
  markResultStale();
  const target = event.target;
  if (target.name === "visitType") {
    updateVisitTypeUI(target.value);
  }
  updatePatientSummary();
  scheduleSaveDraft();
});

caseForm.addEventListener("input", (event) => {
  markResultStale();
  if (event.target.tagName === "TEXTAREA") {
    autoResizeTextareas();
  }
  updatePatientSummary();
  scheduleSaveDraft();
});

caseForm.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    diagnose();
  }
});

tongueImageInput.addEventListener("change", () => {
  renderUploadPanel(tongueImageInput, tongueImageList, tonguePreview, "tongue");
  scheduleSaveDraft();
});

imagingFileInput.addEventListener("change", () => {
  renderUploadPanel(imagingFileInput, imagingFileList, imagingPreview, "imaging");
  scheduleSaveDraft();
});

if (bulkImportInput) {
  bulkImportInput.addEventListener("input", () => {
    if (!bulkImportRequesting) bulkImportPreview.hidden = true;
    if (!bulkImportRequesting && bulkImportStatus) {
      bulkImportStatus.textContent = bulkImportInput.value.trim()
        ? "待识别"
        : "待粘贴";
    }
    refreshPrimaryActions();
  });
}

if (bulkImportBtn) {
  bulkImportBtn.addEventListener("click", () => {
    runBulkImport();
  });
}

if (bulkImportSampleBtn) {
  bulkImportSampleBtn.addEventListener("click", loadBulkImportSample);
}

if (bulkImportClearBtn) {
  bulkImportClearBtn.addEventListener("click", () => {
    if (isRequesting || bulkImportRequesting) return;
    bulkImportInput.value = "";
    bulkImportPreview.hidden = true;
    if (bulkImportStatus) bulkImportStatus.textContent = "待粘贴";
    refreshPrimaryActions();
    bulkImportInput.focus();
  });
}

copyBlockButtons.forEach((btn) => {
  btn.addEventListener("click", async () => {
    await copySingleBlock(btn.dataset.copy, btn);
  });
});

diagnoseBtn.addEventListener("click", diagnose);
clearBtn.addEventListener("click", clearAll);
fillDemoBtn.addEventListener("click", fillDemo);
importSampleCaseBtn.addEventListener("click", () => {
  if (isRequesting || bulkImportRequesting || chatRequesting) return;
  openBulkImportDialog();
  loadBulkImportSample();
});
copyBtn.addEventListener("click", copyAllResult);
if (copyResultBiz) copyResultBiz.addEventListener("click", copyAllResult);

if (assistSyndromeBtn) {
  assistSyndromeBtn.addEventListener("click", () => openAssistModal("syndrome"));
}
if (assistPrescriptionBtn) {
  assistPrescriptionBtn.addEventListener("click", () => openAssistModal("prescription"));
}
if (doctorConfirmBtn) {
  doctorConfirmBtn.addEventListener("click", toggleDoctorConfirm);
}
if (closeAssistModal) {
  closeAssistModal.addEventListener("click", closeAssistDialog);
}
if (assistModal) {
  assistModal.addEventListener("click", (event) => {
    if (event.target === assistModal) closeAssistDialog();
  });
}

if (closeBulkImportModal) {
  closeBulkImportModal.addEventListener("click", closeBulkImportDialog);
}
if (bulkImportModal) {
  bulkImportModal.addEventListener("click", (event) => {
    if (event.target === bulkImportModal && !bulkImportRequesting) {
      closeBulkImportDialog();
    }
  });
}

aiChatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendAiMessage();
});

aiMessageInput.addEventListener("input", () => {
  resizeAiInput();
  refreshAiSendStyle();
});

aiMessageInput.addEventListener("keydown", async (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    await sendAiMessage();
  }
});

if (aiNewChatBtn) {
  aiNewChatBtn.addEventListener("click", startNewAiChat);
}

chatUploadBtn.addEventListener("click", () => {
  setActiveGroup("imagesPanel");
  tongueImageInput.focus();
});

if (openAvatarBtn) {
  openAvatarBtn.addEventListener("click", () => {
    window.open("/dialogue", "_blank", "noopener");
  });
}

if (openHistoryBtn) {
  openHistoryBtn.addEventListener("click", () => {
    setActiveGroup("recordPanel");
    document.getElementById("chiefComplaint").focus();
  });
}

if (openStructuredBtn) {
  openStructuredBtn.addEventListener("click", () => {
    showReviewPanel("resultAnchor");
  });
}

window.addEventListener("beforeunload", () => {
  clearPreviewUrls("tongue");
  clearPreviewUrls("imaging");
});

updateVisitTypeUI(getVisitType());
loadDraft();
autoResizeTextareas();
bindSectionNav();
setActiveGroup("sec-visit");
renderUploadPanel(tongueImageInput, tongueImageList, tonguePreview, "tongue");
renderUploadPanel(imagingFileInput, imagingFileList, imagingPreview, "imaging");
clearOutput();
refreshVisitNumber();
updatePatientSummary();
if (shouldForceNewWorkspaceChat) {
  startNewAiChat();
} else {
  appendInitialAiMessage();
}
resizeAiInput();
refreshPrimaryActions();
refreshAiSendStyle();
refreshHealth();
refreshClock();

setInterval(refreshHealth, 20000);
setInterval(refreshClock, 1000);


document.getElementById("quickQuestions")?.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-question]");
  if (!button || chatRequesting) return;
  aiMessageInput.value = button.dataset.question;
  resizeAiInput();
  refreshAiSendStyle();
  aiMessageInput.focus();
});

const fieldEditor = document.getElementById("fieldEditor");
const fieldEditorInput = document.getElementById("fieldEditorInput");
let editingField = null;

function closeFieldEditor() {
  fieldEditor.close();
  editingField = null;
}

function saveExpandedField() {
  if (!editingField || isRequesting || bulkImportRequesting || chatRequesting) return;
  editingField.value = fieldEditorInput.value;
  editingField.dispatchEvent(new Event("input", { bubbles: true }));
  closeFieldEditor();
}

caseForm.addEventListener("click", (event) => {
  const button = event.target.closest(".field-expand");
  if (!button || button.disabled) return;
  editingField = document.getElementById(button.dataset.field);
  document.getElementById("fieldEditorTitle").textContent = button.closest(".field-heading").querySelector("label").textContent;
  fieldEditorInput.value = editingField.value;
  fieldEditor.showModal();
  fieldEditorInput.focus();
});

document.getElementById("closeFieldEditor").addEventListener("click", closeFieldEditor);
document.getElementById("cancelFieldEditor").addEventListener("click", closeFieldEditor);
document.getElementById("saveFieldEditor").addEventListener("click", saveExpandedField);
fieldEditor.addEventListener("close", () => { editingField = null; });
fieldEditorInput.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    saveExpandedField();
  }
});

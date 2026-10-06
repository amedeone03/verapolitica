(() => {
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("document-file");
  const selected = document.getElementById("selected-file");
  const analyze = document.getElementById("analyze-button");
  const progressPanel = document.getElementById("progress-panel");
  const progressCopy = document.getElementById("progress-copy");
  const uploadForm = document.getElementById("upload-form");
  const modeField = document.getElementById("mode-field");
  const sourceUrl = document.getElementById("source-url");
  const chooseButton = document.getElementById("choose-file-button");
  if (!dropZone || !fileInput || !selected || !analyze || !uploadForm || !sourceUrl) {
    return;
  }

  const CLIENT_TIMEOUT_MS = 200000;
  let chosen = null;
  let inFlight = false;

  function currentMode() {
    const checked = document.querySelector("input[name='extract-mode']:checked");
    return checked ? checked.value : "fake";
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    const kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1).replace(/\.0$/, "") + " KB";
    return (kb / 1024).toFixed(1).replace(/\.0$/, "") + " MB";
  }

  function allowedFile(file) {
    const name = (file && file.name ? file.name : "").toLowerCase();
    return name.endsWith(".pdf") || name.endsWith(".html") || name.endsWith(".htm");
  }

  function canAnalyze() {
    if (!chosen || inFlight) return false;
    if (currentMode() === "local") {
      return (sourceUrl.value || "").trim().toLowerCase().startsWith("https://");
    }
    return true;
  }

  function updateAnalyze() {
    analyze.disabled = !canAnalyze();
  }

  function showNotice(message, isError) {
    let banner = document.querySelector(".notice");
    if (!banner) {
      banner = document.createElement("div");
      banner.setAttribute("role", "status");
      document.querySelector("main").prepend(banner);
    }
    banner.className = "notice is-visible" + (isError ? " is-error" : "");
    banner.textContent = message;
  }

  function setFile(file) {
    if (file && !allowedFile(file)) {
      chosen = null;
      fileInput.value = "";
      selected.textContent = "No file selected.";
      updateAnalyze();
      showNotice("Unsupported file type", true);
      return;
    }
    chosen = file || null;
    if (chosen) {
      selected.textContent = "Selected: " + chosen.name + " (" + formatSize(chosen.size) + ")";
      const banner = document.querySelector(".notice");
      if (banner) {
        banner.classList.remove("is-visible", "is-error");
        banner.textContent = "";
      }
    } else {
      selected.textContent = "No file selected.";
    }
    updateAnalyze();
  }

  function triggerPicker() {
    if (typeof fileInput.showPicker === "function") {
      try {
        fileInput.showPicker();
        return;
      } catch (err) {
        // Fall back to click() when showPicker rejects the gesture.
      }
    }
    fileInput.click();
  }

  function openPicker(event) {
    if (event && event.target && event.target.closest && event.target.closest("label[for='document-file']")) {
      return;
    }
    triggerPicker();
  }

  function markStep(name, label) {
    const item = document.querySelector('[data-step="' + name + '"]');
    if (!item) return;
    item.classList.remove("is-active", "is-failed");
    item.classList.add("is-complete");
    if (label) item.textContent = label;
  }

  function activate(name, label) {
    document.querySelectorAll(".progress-steps li").forEach((item) => {
      item.classList.remove("is-active");
    });
    const item = document.querySelector('[data-step="' + name + '"]');
    if (!item) return;
    item.classList.remove("is-failed", "is-complete");
    item.classList.add("is-active");
    if (label) item.textContent = label;
    if (progressCopy) progressCopy.textContent = label || item.textContent;
  }

  function failStep(name, label) {
    document.querySelectorAll(".progress-steps li").forEach((item) => {
      item.classList.remove("is-active");
    });
    const item = document.querySelector('[data-step="' + name + '"]');
    if (item) {
      item.classList.remove("is-complete");
      item.classList.add("is-failed");
      if (label) item.textContent = label;
    }
    if (progressCopy) progressCopy.textContent = label || "Local AI analysis failed.";
  }

  function stopLoading() {
    inFlight = false;
    analyze.textContent = "Analyze";
    updateAnalyze();
  }

  function errorFromPayload(payload, fallback) {
    if (!payload) return fallback;
    if (typeof payload.message === "string" && payload.message.trim()) return payload.message;
    if (typeof payload.error === "string" && payload.error.trim()) return payload.error;
    if (payload.error && typeof payload.error.message === "string") return payload.error.message;
    return fallback;
  }

  async function fetchJson(url, options) {
    const controller = new AbortController();
    const timer = window.setTimeout(function () {
      controller.abort();
    }, CLIENT_TIMEOUT_MS);
    try {
      const response = await fetch(url, Object.assign({}, options || {}, { signal: controller.signal }));
      const text = await response.text();
      let payload = null;
      try {
        payload = JSON.parse(text);
      } catch (err) {
        throw new Error(response.ok ? "Upload could not be saved" : "Document analysis failed.");
      }
      if (!response.ok || payload.status === "error" || payload.error) {
        throw new Error(errorFromPayload(payload, "Document analysis failed."));
      }
      return payload;
    } catch (err) {
      if (err && err.name === "AbortError") {
        throw new Error("Local AI analysis did not complete in time. Please retry.");
      }
      throw err;
    } finally {
      window.clearTimeout(timer);
    }
  }

  document.querySelectorAll("input[name='extract-mode']").forEach((input) => {
    input.addEventListener("change", () => {
      document.querySelectorAll(".mode-card").forEach((card) => card.classList.remove("is-selected"));
      input.closest(".mode-card").classList.add("is-selected");
      if (modeField) modeField.value = input.value;
      updateAnalyze();
    });
  });
  sourceUrl.addEventListener("input", updateAnalyze);
  if (chooseButton) {
    chooseButton.addEventListener("click", (event) => event.stopPropagation());
    chooseButton.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        event.stopPropagation();
        triggerPicker();
      }
    });
  }
  dropZone.addEventListener("click", openPicker);
  dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openPicker(event);
    }
  });
  dropZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropZone.classList.add("is-active");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("is-active"));
  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropZone.classList.remove("is-active");
    const file = event.dataTransfer.files[0];
    if (file) setFile(file);
  });
  fileInput.addEventListener("change", () => setFile(fileInput.files[0] || null));
  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!chosen || inFlight) return;
    inFlight = true;
    analyze.disabled = true;
    analyze.textContent = "Working…";
    if (progressPanel) progressPanel.hidden = false;
    document.querySelectorAll(".progress-steps li").forEach((item) => {
      item.classList.remove("is-complete", "is-active", "is-failed");
    });
    let failedStep = "extract";
    try {
      failedStep = "ingest";
      activate("ingest", "Preparing official document");
      const form = new FormData();
      form.append("document", chosen, chosen.name);
      form.append("source_url", document.getElementById("source-url").value);
      form.append("source_name", document.getElementById("source-name").value);
      form.append("mode", currentMode());
      const ingested = await fetchJson("/demo/ai-upload/ingest", {
        method: "POST",
        body: form,
      });
      const pages = ingested.page_count || 0;
      markStep("ingest", "Preparing official document");
      if (pages) {
        markStep(
          "pages",
          "Full document: " + pages.toLocaleString() + (pages === 1 ? " page" : " pages")
        );
      } else {
        const sections = ingested.chunk_count || 0;
        markStep(
          "pages",
          "Full document: " + sections.toLocaleString() + (sections === 1 ? " section" : " sections")
        );
      }
      failedStep = "select";
      activate("select", "Selecting relevant evidence");
      const selectedSections = await fetchJson("/demo/ai-upload/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_document_id: ingested.raw_document_id }),
      });
      markStep("select", "Selecting relevant evidence");
      const sentCount = (selectedSections.sent_chunk_indexes || selectedSections.selected_chunk_indexes || []).length;
      const purpose = selectedSections.extraction_purpose || "";
      const sectionLabel = purpose === "canonical_proposal"
        ? " relevant metadata section"
        : " relevant section";
      markStep(
        "selected",
        "Evidence selected: " + sentCount + sectionLabel + (sentCount === 1 ? "" : "s")
      );
      const summary = selectedSections.evidence_summary || [];
      if (summary.length && progressCopy) {
        progressCopy.textContent = "Evidence selected: " + summary.join(", ");
      }
      failedStep = "extract";
      const extractLabel = ingested.mode === "local"
        ? "Running local AI — this can take around 2–3 minutes"
        : "Running deterministic fallback";
      activate("extract", extractLabel);
      if (progressCopy && ingested.mode === "local") {
        progressCopy.textContent = "Local AI is working on this computer. A second pass can happen automatically. The result is a draft, not a publication.";
      }
      const extracted = await fetchJson("/demo/ai-upload/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          raw_document_id: ingested.raw_document_id,
          filename: ingested.filename,
          mode: ingested.mode,
          fixture_key: ingested.fixture_key || "",
          source_url: ingested.source_url,
          source_name: ingested.source_name,
          force_rerun: Boolean(document.getElementById("force-rerun") && document.getElementById("force-rerun").checked),
        }),
      });
      markStep("extract", ingested.mode === "local" ? "Running local AI" : "Running deterministic fallback");
      markStep("validate", "Validating evidence");
      markStep("draft", "Preparing draft");
      if (progressCopy) {
        progressCopy.textContent = "Preparing unpublished draft. Human review is required.";
      }
      if (!extracted.redirect) {
        throw new Error("Document analysis failed.");
      }
      window.location = extracted.redirect;
    } catch (err) {
      const message = (err && err.message) || "Document analysis failed.";
      failStep(failedStep, message);
      showNotice(message, true);
    } finally {
      stopLoading();
    }
  });
})();

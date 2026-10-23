// IntelliResearch Dashboard Application - Day 8 Integrated Client
document.addEventListener("DOMContentLoaded", () => {
  // DOM Elements
  const questionInput = document.getElementById("questionInput");
  const subqueriesSelect = document.getElementById("subqueriesSelect");
  const sourcesSelect = document.getElementById("sourcesSelect");
  const useLlmCheckbox = document.getElementById("useLlmCheckbox");
  const startResearchBtn = document.getElementById("startResearchBtn");
  const btnSpinner = document.getElementById("btnSpinner");
  const btnText = document.getElementById("btnText");
  const reportContainer = document.getElementById("reportContainer");
  const historyList = document.getElementById("historyList");
  const historySearch = document.getElementById("historySearch");
  const refreshHistoryBtn = document.getElementById("refreshHistoryBtn");
  const compareBtn = document.getElementById("compareBtn");
  const compareModal = document.getElementById("compareModal");
  const closeCompareModal = document.getElementById("closeCompareModal");
  const comparisonBody = document.getElementById("comparisonBody");
  const comparisonTitle = document.getElementById("comparisonTitle");

  // State
  let savedRecords = [];
  let selectedForCompare = new Set();
  let currentActiveId = null;
  let isSubmitting = false;

  // Helpers
  function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function formatDate(isoStr) {
    if (!isoStr) return "";
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return isoStr;
    }
  }

  function formatErrorMessage(errData, fallbackStatus) {
    if (!errData) return `Server error (HTTP ${fallbackStatus})`;
    if (typeof errData === "string") return errData;
    if (errData.detail) {
      if (Array.isArray(errData.detail)) {
        return errData.detail.map(d => {
          const field = d.loc ? d.loc.slice(1).join(".") : "";
          return field ? `${field}: ${d.msg}` : d.msg;
        }).join("; ");
      }
      if (typeof errData.detail === "string") return errData.detail;
      return JSON.stringify(errData.detail);
    }
    return `Server error (HTTP ${fallbackStatus})`;
  }

  function setLoading(isLoading) {
    isSubmitting = isLoading;
    startResearchBtn.disabled = isLoading;
    questionInput.disabled = isLoading;
    if (isLoading) {
      btnSpinner.style.display = "block";
      btnText.textContent = "Synthesizing Evidence...";
    } else {
      btnSpinner.style.display = "none";
      btnText.textContent = "Start Research";
    }
  }

  function showToast(msg, isError = false) {
    const toast = document.createElement("div");
    toast.className = `status-pill ${isError ? 'danger' : 'success'}`;
    toast.style.position = "fixed";
    toast.style.bottom = "1.5rem";
    toast.style.right = "1.5rem";
    toast.style.zIndex = "999";
    toast.style.padding = "0.6rem 1.25rem";
    toast.style.fontSize = "0.85rem";
    toast.style.boxShadow = "0 10px 15px -3px rgba(0, 0, 0, 0.5)";
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  // ============================================================================
  // API Calls
  // ============================================================================

  async function fetchHistory() {
    try {
      const res = await fetch("/api/research?limit=30");
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(formatErrorMessage(errData, res.status));
      }
      const data = await res.json();
      savedRecords = data.records || [];
      renderHistoryList(savedRecords);
    } catch (err) {
      console.error("Failed to load history:", err);
      historyList.innerHTML = `<div class="empty-state" style="padding: 1.5rem 0.5rem; font-size: 0.8rem; color: var(--danger);"><p>Unable to load history: ${escapeHtml(err.message)}</p></div>`;
    }
  }

  async function searchHistoryApi(q) {
    const term = q ? q.trim() : "";
    if (term.length < 2) {
      fetchHistory();
      return;
    }
    try {
      const res = await fetch(`/api/research/search?q=${encodeURIComponent(term)}`);
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(formatErrorMessage(errData, res.status));
      }
      const results = await res.json();
      renderHistoryList(results, term);
    } catch (err) {
      console.error("Search failed:", err);
      historyList.innerHTML = `<div class="empty-state" style="padding: 1rem; color: var(--danger);"><p>Search error: ${escapeHtml(err.message)}</p></div>`;
    }
  }

  async function loadReport(id) {
    try {
      currentActiveId = id;
      renderHistoryList(savedRecords);
      reportContainer.innerHTML = `
        <div class="empty-state">
          <div class="spinner" style="margin: 0 auto 1rem; width: 2rem; height: 2rem; border-color: var(--accent-primary); border-top-color: transparent;"></div>
          <p>Retrieving report record...</p>
        </div>
      `;
      const res = await fetch(`/api/research/${encodeURIComponent(id)}`);
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(formatErrorMessage(errData, res.status));
      }
      const data = await res.json();
      renderReportView(data.report, data.created_at, data.id);
    } catch (err) {
      reportContainer.innerHTML = `
        <div class="empty-state" style="color: var(--danger);">
          <div class="empty-icon">⚠️</div>
          <h3 style="margin-bottom: 0.5rem;">Failed to Load Report</h3>
          <p>${escapeHtml(err.message)}</p>
        </div>
      `;
    }
  }

  async function deleteReport(id, question) {
    const confirmed = confirm(`Are you sure you want to delete this research record?\n\n"${question}"`);
    if (!confirmed) return;

    try {
      const res = await fetch(`/api/research/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(formatErrorMessage(errData, res.status));
      }
      selectedForCompare.delete(id);
      updateCompareButtonState();
      if (currentActiveId === id) {
        currentActiveId = null;
        renderEmptyState();
      }
      showToast("Research record deleted successfully");
      fetchHistory();
    } catch (err) {
      alert(`Failed to delete record: ${err.message}`);
    }
  }

  async function executeResearch() {
    if (isSubmitting) return; // Prevent duplicate submissions

    const question = questionInput.value.trim();
    if (!question || question.length < 4) {
      alert("Please provide a research question with at least 4 characters.");
      questionInput.focus();
      return;
    }
    if (question.length > 500) {
      alert("Research question exceeds maximum length of 500 characters.");
      questionInput.focus();
      return;
    }

    const payload = {
      question: question,
      max_subqueries: parseInt(subqueriesSelect.value, 10),
      max_sources: parseInt(sourcesSelect.value, 10),
      use_llm: useLlmCheckbox.checked,
    };

    setLoading(true);
    reportContainer.innerHTML = `
      <div class="empty-state">
        <div class="spinner" style="margin: 0 auto 1.5rem; width: 2.5rem; height: 2.5rem; border-color: var(--accent-primary); border-top-color: transparent;"></div>
        <h3 style="color: var(--text-primary); margin-bottom: 0.5rem;">Conducting Evidence-Based Research</h3>
        <p>Planning subqueries, collecting evidence sources, and evaluating claims...</p>
      </div>
    `;

    // 45-second abort controller for network timeout safety
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 45000);

    try {
      const res = await fetch("/api/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(formatErrorMessage(errData, res.status));
      }

      const data = await res.json();
      currentActiveId = data.id;
      renderReportView(data.report, data.created_at, data.id);
      showToast("Research completed & persisted to memory!");
      fetchHistory();
    } catch (err) {
      clearTimeout(timeoutId);
      const isTimeout = err.name === "AbortError";
      const errorText = isTimeout
        ? "Research request timed out after 45 seconds. The backend or model took too long to respond."
        : err.message;

      reportContainer.innerHTML = `
        <div class="empty-state" style="color: var(--danger);">
          <div class="empty-icon">${isTimeout ? '⏱️' : '⚠️'}</div>
          <h3 style="margin-bottom: 0.5rem;">Research Failed</h3>
          <p>${escapeHtml(errorText)}</p>
        </div>
      `;
    } finally {
      setLoading(false);
    }
  }

  async function runComparison() {
    const ids = Array.from(selectedForCompare);
    if (ids.length !== 2) {
      alert("Please select exactly 2 reports from history to compare.");
      return;
    }

    comparisonTitle.textContent = "Comparing Selected Research Reports";
    comparisonBody.innerHTML = `<div class="empty-state"><div class="spinner" style="margin: 0 auto 1rem;"></div><p>Calculating findings comparison...</p></div>`;
    compareModal.style.display = "flex";

    try {
      const res = await fetch(`/api/research/compare?id_a=${encodeURIComponent(ids[0])}&id_b=${encodeURIComponent(ids[1])}`);
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(formatErrorMessage(errData, res.status));
      }
      const data = await res.json();
      renderComparisonView(data);
    } catch (err) {
      comparisonBody.innerHTML = `<div class="empty-state" style="color: var(--danger);"><p>Comparison error: ${escapeHtml(err.message)}</p></div>`;
    }
  }

  // ============================================================================
  // Rendering Helpers
  // ============================================================================

  function renderEmptyState() {
    reportContainer.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🔬</div>
        <h3 style="margin-bottom: 0.5rem; color: var(--text-primary);">No Report Loaded</h3>
        <p>Type a research question above and click <strong>"Start Research"</strong> or pick an existing investigation from history.</p>
      </div>
    `;
  }

  function renderHistoryList(records, searchTerm = "") {
    historyList.innerHTML = "";
    if (!records || records.length === 0) {
      const emptyMsg = searchTerm
        ? `No research records found matching "${escapeHtml(searchTerm)}".`
        : "No research history found in library.";
      historyList.innerHTML = `<div class="empty-state" style="padding: 2rem 0.5rem; font-size: 0.85rem;"><p>${emptyMsg}</p></div>`;
      return;
    }

    records.forEach(rec => {
      const card = document.createElement("div");
      card.className = `history-card ${currentActiveId === rec.id ? 'active' : ''}`;

      const isChecked = selectedForCompare.has(rec.id);
      const isSuccess = rec.status === "completed";

      card.innerHTML = `
        <div class="history-card-header">
          <span class="history-question" title="${escapeHtml(rec.question)}">${escapeHtml(rec.question)}</span>
          <span class="status-pill ${isSuccess ? 'success' : 'warning'}">${escapeHtml(rec.status)}</span>
        </div>
        <div class="history-meta">
          <span>${formatDate(rec.created_at)}</span>
          <span>${rec.findings_count || 0} findings • ${rec.sources_count || 0} sources</span>
        </div>
        <div class="history-actions">
          <label class="compare-checkbox-label" title="Select for comparison">
            <input type="checkbox" class="compare-chk" data-id="${rec.id}" ${isChecked ? 'checked' : ''} />
            Compare
          </label>
          <div style="flex: 1;"></div>
          <button class="btn-icon delete-btn" data-id="${rec.id}" title="Delete research report">🗑️</button>
        </div>
      `;

      // Select / open report on card click
      card.addEventListener("click", (e) => {
        if (e.target.closest(".compare-chk") || e.target.closest(".delete-btn")) return;
        loadReport(rec.id);
      });

      // Compare checkbox event
      const chk = card.querySelector(".compare-chk");
      chk.addEventListener("change", (e) => {
        if (e.target.checked) {
          if (selectedForCompare.size >= 2) {
            e.target.checked = false;
            alert("You can select up to 2 reports for comparison. Uncheck one first.");
            return;
          }
          selectedForCompare.add(rec.id);
        } else {
          selectedForCompare.delete(rec.id);
        }
        updateCompareButtonState();
      });

      // Delete event
      const delBtn = card.querySelector(".delete-btn");
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteReport(rec.id, rec.question);
      });

      historyList.appendChild(card);
    });
  }

  function updateCompareButtonState() {
    const count = selectedForCompare.size;
    compareBtn.textContent = `⚖️ Compare (${count}/2)`;
    compareBtn.disabled = count !== 2;
  }

  function renderReportView(report, createdAt, reportId) {
    if (!report) {
      renderEmptyState();
      return;
    }

    const isSufficient = report.sources_sufficient;
    const isMock = report.sources && report.sources.some(s => s.is_mock);
    const provenancePill = isMock
      ? '<span class="status-pill warning">🧪 Offline Mock Corpus</span>'
      : '<span class="status-pill success">🌐 Live Web Evidence</span>';

    const quality = report.evidence_quality || (isSufficient ? 'moderate' : 'insufficient');
    const qualityClass = quality === 'high' ? 'success' : (quality === 'insufficient' ? 'danger' : 'warning');
    const qualityPill = `<span class="status-pill ${qualityClass}">Quality: ${escapeHtml(quality.toUpperCase())}</span>`;

    let qualitySignalsHtml = "";
    if (report.quality_signals && report.quality_signals.length > 0) {
      qualitySignalsHtml = `
        <div class="section-box" style="border-left: 3px solid var(--accent-primary);">
          <div class="section-heading">🔍 Evidence Quality & Traceability Signals</div>
          <ul style="padding-left: 1.25rem; font-size: 0.85rem; color: var(--text-secondary); display: flex; flex-direction: column; gap: 0.35rem;">
            ${report.quality_signals.map(s => `<li>${escapeHtml(s)}</li>`).join("")}
          </ul>
        </div>
      `;
    }

    let subqueriesHtml = "";
    if (report.subqueries && report.subqueries.length > 0) {
      subqueriesHtml = `
        <div class="section-box">
          <div class="section-heading">🔍 Decomposed Subqueries (${report.subqueries.length})</div>
          <div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
            ${report.subqueries.map(sq => `
              <span class="badge-tag" title="${escapeHtml(sq.intent)}">${escapeHtml(sq.id)}: ${escapeHtml(sq.query_text)}</span>
            `).join("")}
          </div>
        </div>
      `;
    }

    let findingsHtml = "";
    if (report.key_findings && report.key_findings.length > 0) {
      findingsHtml = `
        <div class="section-box">
          <div class="section-heading">💡 Key Verified Findings</div>
          <ul class="findings-list">
            ${report.key_findings.map(f => {
              let formatted = escapeHtml(f);
              if (formatted.startsWith("Fact: ")) {
                formatted = `<span class="badge-tag" style="background: rgba(56, 189, 248, 0.15); color: var(--accent-primary); margin-right: 0.35rem;">FACT</span>` + formatted.substring(6);
              } else if (formatted.startsWith("Synthesis: ")) {
                formatted = `<span class="badge-tag" style="background: rgba(16, 185, 129, 0.15); color: var(--success); margin-right: 0.35rem;">SYNTHESIS</span>` + formatted.substring(11);
              }
              const withCitations = formatted
                .replace(/\[(S\d+|WEB-\d+|TAVILY-\d+|MOCK-\d+)\]/g, '<span class="citation-tag">[$1]</span>')
                .replace(/\[Unsupported[^\]]*\]/g, '<span class="citation-tag" style="color: var(--danger); background: var(--danger-bg); border-color: rgba(239, 68, 68, 0.4);">$1</span>');
              return `<li class="finding-item">${withCitations}</li>`;
            }).join("")}
          </ul>
        </div>
      `;
    }

    let conflictsHtml = "";
    if (report.conflicting_evidence && report.conflicting_evidence.length > 0) {
      conflictsHtml = `
        <div class="section-box" style="border-color: rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.05);">
          <div class="section-heading" style="color: var(--warning);">⚠️ Conflicting Claims (${report.conflicting_evidence.length})</div>
          <ul class="findings-list">
            ${report.conflicting_evidence.map(c => {
              const isPotential = c.status === "potential_conflict";
              const label = isPotential ? "Potential Scope Contrast" : "Factual Dispute";
              const tagStyle = isPotential
                ? "background: rgba(56, 189, 248, 0.15); color: var(--accent-primary);"
                : "background: rgba(245, 158, 11, 0.15); color: var(--warning);";
              return `
              <li class="finding-item" style="border-left-color: ${isPotential ? 'var(--accent-primary)' : 'var(--warning)'};">
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;">
                  <span class="badge-tag" style="${tagStyle}">${label}</span>
                  <strong>Claim:</strong>
                </div>
                <div>${escapeHtml(c.claim_text)}</div>
                <div style="font-size: 0.8rem; margin-top: 0.35rem; color: var(--text-secondary);">
                  Supporting: ${c.supporting_source_ids.map(id => `<span class="citation-tag">${escapeHtml(id)}</span>`).join(" ")}
                  ${c.contradicting_source_ids && c.contradicting_source_ids.length > 0 ? `| Contradicting: ${c.contradicting_source_ids.map(id => `<span class="citation-tag" style="color: var(--warning);">${escapeHtml(id)}</span>`).join(" ")}` : ''}
                </div>
              </li>
              `;
            }).join("")}
          </ul>
        </div>
      `;
    }

    let sourcesHtml = "";
    if (report.sources && report.sources.length > 0) {
      sourcesHtml = `
        <div class="section-box">
          <div class="section-heading">📚 Evidence Sources (${report.sources.length})</div>
          <div class="sources-grid">
            ${report.sources.map(src => `
              <div class="source-card">
                <div class="source-header">
                  <span class="source-id-badge">[${escapeHtml(src.id)}]</span>
                  <span class="status-pill ${src.retrieval_status === 'success' ? 'success' : 'danger'}">${escapeHtml(src.retrieval_status)}</span>
                </div>
                <a href="${escapeHtml(src.url)}" target="_blank" rel="noopener noreferrer" class="source-link" title="${escapeHtml(src.title)}">
                  ${escapeHtml(src.title)} ↗
                </a>
                <div class="source-snippet">${escapeHtml(src.snippet)}</div>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }

    let caveatsHtml = "";
    const limitations = report.limitations || [];
    const unanswered = report.unanswered_questions || [];

    if (limitations.length > 0 || unanswered.length > 0) {
      caveatsHtml = `
        <div class="section-box">
          <div class="section-heading">⚠️ Limitations & Unanswered Facets</div>
          ${unanswered.length > 0 ? `
            <div style="margin-bottom: 0.75rem;">
              <strong style="font-size: 0.85rem; color: var(--text-secondary);">Unanswered Questions:</strong>
              <ul style="padding-left: 1.25rem; font-size: 0.85rem; margin-top: 0.25rem; color: var(--text-secondary);">
                ${unanswered.map(u => `<li>${escapeHtml(u)}</li>`).join("")}
              </ul>
            </div>
          ` : ''}
          ${limitations.length > 0 ? `
            <div>
              <strong style="font-size: 0.85rem; color: var(--text-secondary);">Methodological Caveats:</strong>
              <ul style="padding-left: 1.25rem; font-size: 0.85rem; margin-top: 0.25rem; color: var(--text-muted);">
                ${limitations.map(l => `<li>${escapeHtml(l)}</li>`).join("")}
              </ul>
            </div>
          ` : ''}
        </div>
      `;
    }

    reportContainer.innerHTML = `
      <div class="report-view">
        <div class="report-header-banner">
          <h2 class="report-question">${escapeHtml(report.research_question)}</h2>
          <div class="report-meta-row">
            ${reportId ? `<span>ID: <code>${escapeHtml(reportId)}</code></span>` : ''}
            ${createdAt ? `<span>Saved: ${formatDate(createdAt)}</span>` : ''}
            ${provenancePill}
            ${qualityPill}
            <span class="status-pill ${isSufficient ? 'success' : 'warning'}">
              ${isSufficient ? '✓ Evidence Sufficient' : '⚠️ Insufficient Evidence'}
            </span>
          </div>
        </div>

        <div class="section-box" style="background: rgba(56, 189, 248, 0.05); border-color: rgba(56, 189, 248, 0.2);">
          <div class="section-heading" style="color: var(--accent-primary);">📋 Executive Summary</div>
          <p style="font-size: 0.95rem; line-height: 1.6;">${escapeHtml(report.executive_summary)}</p>
        </div>

        ${qualitySignalsHtml}
        ${subqueriesHtml}
        ${findingsHtml}
        ${conflictsHtml}
        ${sourcesHtml}
        ${caveatsHtml}
      </div>
    `;
  }

  function renderComparisonView(comp) {
    comparisonTitle.textContent = `Report Comparison`;

    const sourcesAHtml = comp.sources_a && comp.sources_a.length > 0
      ? `<div style="margin-top: 0.5rem; font-size: 0.775rem;"><strong>Sources (${comp.sources_a.length}):</strong> ${comp.sources_a.map(s => `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer" style="color: var(--accent-primary); margin-right: 0.35rem;">${escapeHtml(s.title || s.id)} ↗</a>`).join("")}</div>`
      : '';

    const sourcesBHtml = comp.sources_b && comp.sources_b.length > 0
      ? `<div style="margin-top: 0.5rem; font-size: 0.775rem;"><strong>Sources (${comp.sources_b.length}):</strong> ${comp.sources_b.map(s => `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer" style="color: var(--accent-primary); margin-right: 0.35rem;">${escapeHtml(s.title || s.id)} ↗</a>`).join("")}</div>`
      : '';

    const limitationsAHtml = comp.limitations_a && comp.limitations_a.length > 0
      ? `<div style="margin-top: 0.35rem; font-size: 0.75rem; color: var(--text-muted);"><em>Limitations:</em> ${comp.limitations_a.map(l => escapeHtml(l)).join("; ")}</div>`
      : '';

    const limitationsBHtml = comp.limitations_b && comp.limitations_b.length > 0
      ? `<div style="margin-top: 0.35rem; font-size: 0.75rem; color: var(--text-muted);"><em>Limitations:</em> ${comp.limitations_b.map(l => escapeHtml(l)).join("; ")}</div>`
      : '';

    comparisonBody.innerHTML = `
      <div class="report-header-banner" style="margin-bottom: 0.5rem;">
        <div style="font-weight: 600; margin-bottom: 0.35rem; color: var(--accent-primary);">⚖️ Comparison Synthesis:</div>
        <div style="font-size: 0.9rem; line-height: 1.5;">${escapeHtml(comp.comparison_summary)}</div>
      </div>

      <div class="comparison-grid">
        <div class="section-box">
          <div class="section-heading">📘 Report A: ${escapeHtml(comp.question_a)}</div>
          <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.5rem;">ID: <code>${escapeHtml(comp.id_a)}</code></div>
          <strong>Unique Findings (${comp.findings_only_in_a.length}):</strong>
          <ul style="padding-left: 1.25rem; margin-top: 0.35rem; font-size: 0.85rem;">
            ${comp.findings_only_in_a.map(f => `<li>${escapeHtml(f)}</li>`).join("") || '<li>None</li>'}
          </ul>
          ${sourcesAHtml}
          ${limitationsAHtml}
        </div>

        <div class="section-box">
          <div class="section-heading">📙 Report B: ${escapeHtml(comp.question_b)}</div>
          <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.5rem;">ID: <code>${escapeHtml(comp.id_b)}</code></div>
          <strong>Unique Findings (${comp.findings_only_in_b.length}):</strong>
          <ul style="padding-left: 1.25rem; margin-top: 0.35rem; font-size: 0.85rem;">
            ${comp.findings_only_in_b.map(f => `<li>${escapeHtml(f)}</li>`).join("") || '<li>None</li>'}
          </ul>
          ${sourcesBHtml}
          ${limitationsBHtml}
        </div>
      </div>

      <div class="section-box">
        <div class="section-heading">🤝 Shared Findings Across Both Reports (${comp.shared_findings.length})</div>
        <ul style="padding-left: 1.25rem; font-size: 0.9rem;">
          ${comp.shared_findings.map(f => `<li>${escapeHtml(f)}</li>`).join("") || '<li>No identical shared findings detected.</li>'}
        </ul>
      </div>

      ${comp.conflicting_claims && comp.conflicting_claims.length > 0 ? `
        <div class="section-box" style="border-color: rgba(245, 158, 11, 0.4);">
          <div class="section-heading" style="color: var(--warning);">⚠️ Conflicting Claims Requiring Review</div>
          <ul style="padding-left: 1.25rem; font-size: 0.85rem;">
            ${comp.conflicting_claims.map(c => `<li>${escapeHtml(c.claim_text)}</li>`).join("")}
          </ul>
        </div>
      ` : ''}
    `;
  }

  // ============================================================================
  // Event Listeners
  // ============================================================================

  startResearchBtn.addEventListener("click", executeResearch);

  questionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      executeResearch();
    }
  });

  refreshHistoryBtn.addEventListener("click", fetchHistory);

  let searchTimeout;
  historySearch.addEventListener("input", (e) => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      searchHistoryApi(e.target.value);
    }, 250);
  });

  compareBtn.addEventListener("click", runComparison);

  closeCompareModal.addEventListener("click", () => {
    compareModal.style.display = "none";
  });

  window.addEventListener("click", (e) => {
    if (e.target === compareModal) {
      compareModal.style.display = "none";
    }
  });

  // Initial Load
  renderEmptyState();
  fetchHistory();
});

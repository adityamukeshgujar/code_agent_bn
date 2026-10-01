import { useEffect, useRef, useState } from "react";

const STAGE_LABELS = {
  repo_synced: "Synced from GitHub",
  installing_dependencies: "Installing dependencies (npm install)",
  intent_parsed: "Parsed request",
  skill_matched: "Matched skill",
  identified: "Located target code",
  skill_match_failed: "No skill matched",
  patch_generated: "Generated patch",
  patch_applied: "Applied patch",
  validated: "Validated (lint/build)",
  pr_result: "Opened PR",
  reverted: "Reverted",
  error: "Error",
};

function summarizeStage(s) {
  switch (s.stage) {
    case "repo_synced":
      return s.root;
    case "intent_parsed": {
      const i = s.intent;
      return `${i.action || "?"} on "${i.element || "?"}" (${i.page || "?"})`;
    }
    case "skill_matched":
      return `${s.skill} (${s.change_type})`;
    case "identified": {
      const r = s.identification;
      return r.ok ? `${r.file_path}:${r.line}` : r.note || "not found";
    }
    case "patch_generated":
      return `${s.target_file} — ${s.description}`;
    case "validated":
      return s.ok ? `${s.side} OK` : `${s.side} FAILED`;
    case "pr_result":
      return s.ok ? s.pr_url : s.error;
    default:
      return "";
  }
}

const DEFAULT_REPO_URL = "https://github.com/shreyashwinig/PAT_POC";

const EXAMPLES = [
  { label: "🟢 Submit button → green", text: "Change the color of the submit button in Assessment Page to green" },
  { label: "🟣 Sign In button → purple", text: "Change the Sign In button color on the login page to purple" },
  { label: "🔴 PDF viewer close button → red", text: "In the PDF viewer, change the close button color to red" },
  {
    label: "✏️ Relabel “Generate Action Plan”",
    text: "On the Assessment page, change the 'Generate Action Plan' button text to 'Finish Review'",
  },
  {
    label: "🔒 Disable Sign In until filled",
    text: "On the login page, disable the Sign In button until all fields are filled in",
  },
  {
    label: "🔍 Disable zoom-in at max",
    text: "In the PDF viewer, disable the zoom in button when it hits the max zoom level",
  },
];

const TERMINAL_STATUSES = new Set([
  "awaiting_confirmation",
  "done",
  "needs_clarification",
  "identified_only",
  "rejected",
  "failed",
]);

function Spinner() {
  return <span className="spinner" aria-label="Loading" />;
}

// Pretty Light-Mode Diff Viewer
function DiffViewer({ diff }) {
  if (!diff) return null;
  const lines = diff.split("\n");
  return (
    <pre className="diff-container">
      {lines.map((line, idx) => {
        let type = "normal";
        if (line.startsWith("+") && !line.startsWith("+++")) type = "add";
        else if (line.startsWith("-") && !line.startsWith("---")) type = "remove";
        else if (line.startsWith("@@")) type = "hunk";
        return (
          <div key={idx} className={`diff-line diff-${type}`}>
            {line}
          </div>
        );
      })}
    </pre>
  );
}

export default function App() {
  const [copied, setCopied] = useState(false);
  const [requestText, setRequestText] = useState("");
  const [repoUrl] = useState(DEFAULT_REPO_URL);
  const [showRepoLockNotice, setShowRepoLockNotice] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [stages, setStages] = useState([]);
  const [status, setStatus] = useState(null);
  const [message, setMessage] = useState("");
  const [prUrl, setPrUrl] = useState(null);
  const [running, setRunning] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const handleCopyPrUrl = () => {
    if (prUrl) {
      navigator.clipboard.writeText(prUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    }
  };

  const pollRef = useRef(null);
  const noticeTimerRef = useRef(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const poll = async (id) => {
    const res = await fetch(`/api/status/${id}`);
    const data = await res.json();
    setStages(data.stages);
    setStatus(data.status);
    setMessage(data.message);
    setPrUrl(data.pr_url);
    if (TERMINAL_STATUSES.has(data.status)) {
      stopPolling();
      setRunning(false);
    }
  };

  useEffect(() => {
    return () => {
      stopPolling();
      if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current);
    };
  }, []);

  const handleRun = async (e) => {
    e.preventDefault();
    if (!requestText.trim() || !repoUrl.trim()) return;

    setRunning(true);
    setStages([]);
    setStatus("running");
    setMessage("");
    setPrUrl(null);
    stopPolling();

    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request: requestText, repo_url: repoUrl }),
    });
    const data = await res.json();
    if (data.error) {
      setStatus("failed");
      setMessage(data.error);
      setRunning(false);
      return;
    }
    setJobId(data.job_id);
    pollRef.current = setInterval(() => poll(data.job_id), 1000);
  };

  const handleConfirm = async () => {
    setConfirming(true);
    await fetch(`/api/confirm/${jobId}`, { method: "POST" });
    setStatus("pushing");
    pollRef.current = setInterval(() => poll(jobId), 1000);
  };

  const handleReject = async () => {
    setConfirming(true);
    await fetch(`/api/reject/${jobId}`, { method: "POST" });
    await poll(jobId);
    setConfirming(false);
  };

  const handleRepoUrlAttempt = () => {
    setShowRepoLockNotice(true);
    if (noticeTimerRef.current) clearTimeout(noticeTimerRef.current);
    noticeTimerRef.current = setTimeout(() => setShowRepoLockNotice(false), 4000);
  };

  const patchStage = stages.find((s) => s.stage === "patch_generated");
  const identifyStage = stages.find((s) => s.stage === "identified");
  const isShared = identifyStage?.identification?.is_shared;
  const isBusy = status === "running" || status === "pushing";

  return (
    <div className="wrap">
      {/* Header & Status */}
      <header className="header-area">
        <div className="header-top">
          <div className="logo-tag">
            <div className="logo-icon">⚡</div>
            <h1>Codebase Change Agent</h1>
          </div>
          <div className="status-badge">
            <span className="status-dot"></span>
            Agent Ready
          </div>
        </div>
        <p className="sub">
          Automates UI changes in <strong>AI Policy Review</strong> directly from plain-English instructions.
          Provide your request, preview the generated Git diff, and auto-submit Pull Requests.
        </p>
      </header>

      {/* Main Request Form */}
      <form className="card" onSubmit={handleRun}>
        <div className="label-row">
          <label htmlFor="request">Change Request</label>
          {requestText && (
            <div className="label-actions">
              <span className="char-count">{requestText.length} characters</span>
              <button
                type="button"
                className="text-btn"
                onClick={() => setRequestText("")}
              >
                Clear
              </button>
            </div>
          )}
        </div>
        <textarea
          id="request"
          placeholder="e.g. Change the color of the submit button in Assessment Page to green"
          value={requestText}
          onChange={(e) => setRequestText(e.target.value)}
        />

        <div className="examples">
          <span className="examples-label">Try an example prompt:</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              type="button"
              className="chip"
              onClick={() => setRequestText(ex.text)}
            >
              {ex.label}
            </button>
          ))}
        </div>

        <label htmlFor="repo-url">GitHub Repository URL</label>
        <div className="repo-input-wrapper">
          <input
            id="repo-url"
            type="text"
            value={repoUrl}
            readOnly
            onFocus={handleRepoUrlAttempt}
            onMouseDown={handleRepoUrlAttempt}
            className="locked"
          />
          <span className="repo-tag">branch: main</span>
        </div>
        {showRepoLockNotice ? (
          <div className="banner warn small">
            🔒 Repository input is locked while in early testing preview.
          </div>
        ) : (
          <div className="hint">
            <span>🔒</span> Target repository locked to preset test repo.
          </div>
        )}

        <button type="submit" disabled={running}>
          {running ? (
            <>
              <Spinner /> Executing Agent Pipeline…
            </>
          ) : (
            "Run Agent Process"
          )}
        </button>
      </form>
      {!status && (
        <div className="card guide-card">
          <div className="guide-title">💡 How the Codebase Agent works</div>
          <div className="guide-steps">
            <div className="guide-step">
              <span className="step-num">1</span>
              <div><strong>Enter Prompt:</strong> Type your request or choose an example prompt above.</div>
            </div>
            <div className="guide-step">
              <span className="step-num">2</span>
              <div><strong>Code Identification:</strong> Agent scans repo source files & matches changes.</div>
            </div>
            <div className="guide-step">
              <span className="step-num">3</span>
              <div><strong>Diff Review:</strong> Preview proposed code diff before making any push.</div>
            </div>
            <div className="guide-step">
              <span className="step-num">4</span>
              <div><strong>Auto PR:</strong> Confirm to push directly to GitHub.</div>
            </div>
          </div>
        </div>
      )}

      {/* Execution Status & Pipeline Timeline */}
      {status && (
        <div className="card">
          {isBusy && (
            <div className="banner busy">
              <Spinner /> {status === "pushing" ? "Pushing patch to GitHub…" : "Analyzing codebase & generating patch…"}
            </div>
          )}
          {status === "awaiting_confirmation" && isShared && (
            <div className="banner warn">⚠️ {identifyStage.identification.shared_note}</div>
          )}
          {status === "done" && (
            <div className="banner ok done-banner">
              <div>
                ✅ Patch applied successfully —{" "}
                <a href={prUrl} target="_blank" rel="noreferrer">
                  View GitHub Pull Request
                </a>
              </div>
              <button type="button" className="copy-btn" onClick={handleCopyPrUrl}>
                {copied ? "✓ Copied!" : "📋 Copy Link"}
              </button>
            </div>
          )}
          {status === "needs_clarification" && <div className="banner warn">Needs clarification: {message}</div>}
          {status === "identified_only" && <div className="banner warn">{message}</div>}
          {status === "rejected" && <div className="banner warn">{message}</div>}
          {status === "failed" && <div className="banner bad">❌ {message}</div>}

          <ul className="stage-timeline">
            {stages.map((s, i) => {
              const isLast = i === stages.length - 1 && isBusy;
              return (
                <li key={i} className="stage-item">
                  <span className={`stage-marker ${isLast ? 'active-pulse' : 'completed'}`}>
                    {!isLast && "✓"}
                  </span>
                  <div className="stage-header">
                    <span className="stage-name">{STAGE_LABELS[s.stage] || s.stage}</span>
                    {summarizeStage(s) && (
                      <span className="stage-detail">{summarizeStage(s)}</span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

        </div>
      )}

      {/* Proposed Patch & Diff Review Card */}
      {status === "awaiting_confirmation" && patchStage && (
        <div className="card">
          <div className="diff-card-title">
            Proposed Change: <span style={{ color: "#475569", fontWeight: 400 }}>{patchStage.description}</span>
          </div>
          <DiffViewer diff={patchStage.diff} />
          <div className="row">
            <button onClick={handleConfirm} disabled={confirming}>
              {confirming || status === "pushing" ? (
                <>
                  <Spinner /> Pushing to GitHub…
                </>
              ) : (
                "Confirm & Push PR"
              )}
            </button>
            <button className="secondary" onClick={handleReject} disabled={confirming}>
              Reject Change
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

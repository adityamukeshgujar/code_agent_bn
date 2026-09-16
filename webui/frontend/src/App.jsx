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
const TERMINAL_STATUSES = new Set([
  "awaiting_confirmation",
  "done",
  "needs_clarification",
  "identified_only",
  "rejected",
  "failed",
]);

export default function App() {
  const [requestText, setRequestText] = useState("");
  const [repoUrl, setRepoUrl] = useState(DEFAULT_REPO_URL);
  const [jobId, setJobId] = useState(null);
  const [stages, setStages] = useState([]);
  const [status, setStatus] = useState(null);
  const [message, setMessage] = useState("");
  const [prUrl, setPrUrl] = useState(null);
  const [running, setRunning] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const pollRef = useRef(null);

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

  useEffect(() => stopPolling, []); // clean up on unmount

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

  const patchStage = stages.find((s) => s.stage === "patch_generated");
  const identifyStage = stages.find((s) => s.stage === "identified");
  const isShared = identifyStage?.identification?.is_shared;

  return (
    <div className="wrap">
      <h1>codebase-change-agent</h1>
      <p className="sub">
        Give a GitHub repo URL — it's cloned/pulled automatically, no local checkout needed.
        Only button-color requests can go all the way to a push today.
      </p>

      <form className="card" onSubmit={handleRun}>
        <label htmlFor="request">Change request</label>
        <textarea
          id="request"
          placeholder='e.g. Change the color of the submit button in Assessment Page to green'
          value={requestText}
          onChange={(e) => setRequestText(e.target.value)}
        />
        <label htmlFor="repo-url">GitHub repo URL</label>
        <input
          id="repo-url"
          type="text"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
        />
        <button type="submit" disabled={running}>
          Run
        </button>
      </form>

      {status && (
        <div className="card">
          {status === "awaiting_confirmation" && isShared && (
            <div className="banner warn">⚠️ {identifyStage.identification.shared_note}</div>
          )}
          {status === "done" && (
            <div className="banner ok">
              ✅ Change made —{" "}
              <a href={prUrl} target="_blank" rel="noreferrer">
                check the PR
              </a>
              .
            </div>
          )}
          {status === "needs_clarification" && <div className="banner warn">Needs clarification: {message}</div>}
          {status === "identified_only" && <div className="banner warn">{message}</div>}
          {status === "rejected" && <div className="banner warn">{message}</div>}
          {status === "failed" && <div className="banner bad">❌ {message}</div>}

          <ul className="stage-list">
            {stages.map((s, i) => (
              <li key={i}>
                <span className="stage-name">{STAGE_LABELS[s.stage] || s.stage}</span>
                <span className="stage-detail">{summarizeStage(s)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {status === "awaiting_confirmation" && patchStage && (
        <div className="card">
          <div style={{ marginBottom: "0.6rem" }}>
            <strong>Proposed change:</strong> {patchStage.description}
          </div>
          <pre>{patchStage.diff}</pre>
          <div className="row">
            <button onClick={handleConfirm} disabled={confirming}>
              Confirm &amp; Push
            </button>
            <button className="secondary" onClick={handleReject} disabled={confirming}>
              Reject
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { Connection, WorkflowDefinition, WorkflowRun } from "@/lib/types";

import { Check, LoaderCircle, Plus, RefreshCw, ShieldAlert, Trash2 } from "./icons";

const INCIDENT_TEMPLATE = {
  name: "Incident Triage & Approval",
  description: "Search runbooks, draft remediation plan, wait for human approval, then verify system health.",
  trigger_type: "manual",
  steps: [
    {
      id: "search_sop",
      type: "knowledge_search",
      name: "Search Runbook",
      query_template: "{{input.incident}}",
      top_k: 4,
      min_score: 0.1,
    },
    {
      id: "triage_plan",
      type: "llm_step",
      name: "Draft Triage Summary",
      system_prompt: "You are an operations engineer. Summarize root cause and safe next steps concisely.",
      prompt_template: "Incident: {{input.incident}}\n\nRunbook context:\n{{steps.search_sop.output}}",
      temperature: 0.1,
    },
    {
      id: "approve_action",
      type: "human_approval",
      name: "Operator Approval",
      message_template: "Review triage plan before running diagnostics:\n{{steps.triage_plan.output}}",
    },
    {
      id: "health_check",
      type: "tool_call",
      name: "Verify System Health",
      tool_name: "get_system_health",
      arguments_template: {},
      allow_mutating: false,
    },
  ],
};

export function WorkflowsView({ connection }: { connection: Connection }) {
  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [incidentInput, setIncidentInput] = useState("Database failover replica promotion");

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [wfList, runList] = await Promise.all([
        api<WorkflowDefinition[]>("workflows", connection),
        api<WorkflowRun[]>("workflows/runs", connection),
      ]);
      setWorkflows(wfList);
      setRuns(runList);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load workflows.");
    } finally {
      setLoading(false);
    }
  }, [connection]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  async function createTemplate() {
    setBusyId("create");
    setError(null);
    try {
      await api<WorkflowDefinition>("workflows", connection, {
        method: "POST",
        body: INCIDENT_TEMPLATE,
      });
      await loadAll();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create workflow.");
    } finally {
      setBusyId(null);
    }
  }

  async function runWorkflow(workflowId: string) {
    setBusyId(workflowId);
    setError(null);
    try {
      await api<WorkflowRun>(`workflows/${workflowId}/runs`, connection, {
        method: "POST",
        body: { input: { incident: incidentInput } },
      });
      await loadAll();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Workflow run failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function deleteWorkflow(workflowId: string) {
    setBusyId(`del-${workflowId}`);
    setError(null);
    try {
      await api<void>(`workflows/${workflowId}`, connection, { method: "DELETE" });
      await loadAll();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete workflow.");
    } finally {
      setBusyId(null);
    }
  }

  async function decideRun(runId: string, decision: "approve" | "reject") {
    setBusyId(`${decision}-${runId}`);
    setError(null);
    try {
      await api<WorkflowRun>(`workflows/runs/${runId}/approve`, connection, {
        method: "POST",
        body: { decision },
      });
      await loadAll();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not submit approval decision.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="v-page v-workflows">
      <div className="v-page-head">
        <div>
          <h1>Workflows</h1>
          <p className="v-page-sub">
            Automate multi-step operational pipelines with human approval checkpoints.
          </p>
        </div>
        <div className="wf-head-actions">
          <button
            type="button"
            className="button secondary"
            onClick={() => void loadAll()}
            disabled={loading}
          >
            <RefreshCw size={15} aria-hidden="true" />
            Refresh
          </button>
          <button
            type="button"
            className="button"
            onClick={() => void createTemplate()}
            disabled={busyId === "create"}
          >
            {busyId === "create" ? (
              <LoaderCircle size={15} className="spin" aria-hidden="true" />
            ) : (
              <Plus size={15} aria-hidden="true" />
            )}
            New Incident Triage
          </button>
        </div>
      </div>

      {error && (
        <div className="form-message error" role="alert">
          <p>{error}</p>
        </div>
      )}

      <section className="wf-section">
        <div className="wf-section-head">
          <h2>Workflow Definitions ({workflows.length})</h2>
          <label className="wf-input-inline">
            <span>Run input</span>
            <input
              type="text"
              value={incidentInput}
              onChange={(e) => setIncidentInput(e.target.value)}
              placeholder="Incident or query..."
            />
          </label>
        </div>

        {loading && workflows.length === 0 ? (
          <div className="wf-empty">Loading workflows...</div>
        ) : workflows.length === 0 ? (
          <div className="wf-empty">
            No workflows yet. Click <strong>New Incident Triage</strong> to create your first pipeline.
          </div>
        ) : (
          <div className="wf-grid">
            {workflows.map((wf) => (
              <article className="wf-card" key={wf.id}>
                <div className="wf-card-top">
                  <div>
                    <h3>{wf.name}</h3>
                    <p>{wf.description || "Manual operational workflow."}</p>
                  </div>
                  <div className="wf-card-actions">
                    <button
                      type="button"
                      className="button"
                      onClick={() => void runWorkflow(wf.id)}
                      disabled={busyId === wf.id}
                    >
                      {busyId === wf.id ? (
                        <LoaderCircle size={14} className="spin" aria-hidden="true" />
                      ) : null}
                      Run
                    </button>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={`Delete ${wf.name}`}
                      onClick={() => void deleteWorkflow(wf.id)}
                      disabled={busyId === `del-${wf.id}`}
                    >
                      <Trash2 size={15} aria-hidden="true" />
                    </button>
                  </div>
                </div>
                <div className="wf-steps-row">
                  {wf.steps.map((step, idx) => (
                    <span className="wf-step-pill" key={step.id}>
                      {idx + 1}. {step.name} <small>({step.type})</small>
                    </span>
                  ))}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="wf-section">
        <h2>Execution Runs &amp; Approvals ({runs.length})</h2>
        {runs.length === 0 ? (
          <div className="wf-empty">No workflow runs recorded yet.</div>
        ) : (
          <div className="wf-runs">
            {runs.map((run) => (
              <article className="wf-card" key={run.id}>
                <div className="wf-card-top">
                  <div>
                    <h3>{run.workflow_name}</h3>
                    <p>
                      Triggered by <strong>{run.triggered_by}</strong> &middot;{" "}
                      {formatDateTime(run.started_at)}
                    </p>
                  </div>
                  <div className="wf-card-actions">
                    <span className={`wf-status ${run.status}`}>{run.status}</span>
                    {run.status === "waiting_approval" && (
                      <>
                        <button
                          type="button"
                          className="button"
                          onClick={() => void decideRun(run.id, "approve")}
                          disabled={busyId === `approve-${run.id}`}
                        >
                          <Check size={14} aria-hidden="true" />
                          Approve
                        </button>
                        <button
                          type="button"
                          className="button secondary"
                          onClick={() => void decideRun(run.id, "reject")}
                          disabled={busyId === `reject-${run.id}`}
                        >
                          <ShieldAlert size={14} aria-hidden="true" />
                          Reject
                        </button>
                      </>
                    )}
                  </div>
                </div>
                <div className="wf-logs">
                  {run.step_logs.map((log) => (
                    <div className="wf-log-row" key={`${run.id}-${log.step_id}`}>
                      <div className="wf-log-head">
                        <strong>{log.step_name}</strong>
                        <span className={`wf-status ${log.status}`}>{log.status}</span>
                      </div>
                      {log.output && <pre className="wf-log-out">{log.output}</pre>}
                      {log.error && <p className="wf-log-err">{log.error}</p>}
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

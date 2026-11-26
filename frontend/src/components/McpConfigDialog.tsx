import { useState } from "react";
import { api } from "../api";
import { ModalDialog } from "./ModalDialog";

interface McpConfigDialogProps {
  open: boolean;
  onClose: () => void;
  apiKey: string;
  onApiKeyGenerated?: (newKey: string) => void;
}

export function McpConfigDialog({
  open,
  onClose,
  apiKey,
  onApiKeyGenerated,
}: McpConfigDialogProps) {
  const [copied, setCopied] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost:8000";
  const backendOrigin = origin.includes(":5173") ? "http://localhost:8000" : origin;

  const configSnippet = JSON.stringify(
    {
      mcpServers: {
        recruise: {
          url: `${backendOrigin}/mcp`,
          headers: {
            "X-API-Key": apiKey || "<GENERATE_OR_PASTE_MCP_API_KEY>",
          },
        },
      },
    },
    null,
    2
  );

  const handleCopy = async () => {
    await navigator.clipboard.writeText(configSnippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const handleGenerateKey = async () => {
    setRotating(true);
    setError(null);
    try {
      const res = await api.auth.rotateMcpKey(apiKey || undefined);
      onApiKeyGenerated?.(res.api_key);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate MCP API key.");
    } finally {
      setRotating(false);
    }
  };

  return (
    <ModalDialog
      open={open}
      onClose={onClose}
      title="MCP Configuration"
      subtitle="Connect Claude Desktop or Cursor to query shortlisted candidates and code."
      maxWidthClass="max-w-2xl"
    >
      <div className="space-y-4 text-sm">
        <div className="wire-card flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="editorial-note text-xs text-[var(--ink-primary)]">
            Generate or rotate your workspace API key for headless MCP clients.
          </div>
          <button
            type="button"
            disabled={rotating}
            onClick={handleGenerateKey}
            className="wire-btn-primary h-9 px-3.5 text-[11px] uppercase tracking-[0.06em] disabled:opacity-50"
          >
            {rotating ? "Generating..." : apiKey ? "Rotate Key" : "Generate Key"}
          </button>
        </div>

        {error && (
          <p role="alert" className="spec-mono border border-[#FF2A6D] bg-[var(--surface-bg)] px-3 py-2 text-xs text-[#FF2A6D]">
            {error}
          </p>
        )}

        <p className="editorial-note text-xs leading-relaxed text-[var(--ink-muted)]">
          Add this configuration to{" "}
          <code className="spec-mono wire-tag px-1.5 py-0.5 text-[11px] not-italic">
            .cursor/mcp.json
          </code>{" "}
          or Claude Desktop. SSE endpoint:{" "}
          <code className="spec-mono wire-tag px-1.5 py-0.5 text-[11px] not-italic">
            {backendOrigin}/mcp-sse
          </code>
          .
        </p>

        <div className="relative">
          <pre className="wire-terminal overflow-x-auto p-4 text-xs">
            <code>{configSnippet}</code>
          </pre>
          <button
            type="button"
            onClick={handleCopy}
            className="wire-btn absolute top-3 right-3 px-3 py-1.5 text-[11px] uppercase tracking-[0.06em]"
          >
            {copied ? "Copied" : "Copy JSON"}
          </button>
        </div>

        <div className="wire-card p-4">
          <h2 className="sui-spec-label border-b border-[var(--divider-rule)] pb-2 text-[var(--ink-primary)]">
            AVAILABLE MCP TOOLS
          </h2>
          <ul className="spec-mono mt-2.5 space-y-1.5 text-xs text-[var(--ink-primary)]">
            <li>• list_shortlisted_candidates(job_id)</li>
            <li>• get_candidate_resume(application_id)</li>
            <li>• list_job_candidates(job_id, shortlisted_only=false)</li>
            <li>• search_candidate_code(application_id, query, top_k=5)</li>
            <li>• get_candidate_evaluation(application_id)</li>
            <li>• get_file_chunks(application_id, file_path)</li>
            <li>• get_candidate_interview_probes(application_id)</li>
          </ul>
        </div>
      </div>
    </ModalDialog>
  );
}

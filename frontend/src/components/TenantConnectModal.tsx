import { useId, useState, type FormEvent } from "react";
import { KeyRound, Building2, Eye, EyeOff, Copy, Check } from "lucide-react";
import { api } from "../api";
import type { Company } from "../types";
import { ModalDialog } from "./ModalDialog";

interface TenantConnectModalProps {
  open: boolean;
  onClose: () => void;
  onAuthenticated: (apiKey: string, company: Company) => void;
}

export function TenantConnectModal({
  open,
  onClose,
  onAuthenticated,
}: TenantConnectModalProps) {
  const [mode, setMode] = useState<"create" | "connect">("create");
  const [companyName, setCompanyName] = useState("");
  const [slug, setSlug] = useState("");
  const [existingKey, setExistingKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nameId = useId();
  const slugId = useId();
  const keyId = useId();
  const errorId = useId();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (mode === "create") {
        const res = await api.createCompany(companyName.trim(), slug.trim() || undefined);
        setCreatedKey(res.api_key);
        onAuthenticated(res.api_key, {
          id: res.id,
          name: res.name,
          slug: res.slug,
          created_at: res.created_at,
        });
      } else {
        const key = existingKey.trim();
        const company = await api.getMyCompany(key);
        onAuthenticated(key, company);
        onClose();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setLoading(false);
    }
  };

  const copyCreatedKey = async () => {
    if (!createdKey) return;
    await navigator.clipboard.writeText(createdKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <ModalDialog
      open={open}
      onClose={onClose}
      title="Tenant Workspace Authentication"
      subtitle="Create an isolated company workspace or sign in with an existing tenant API key."
      maxWidthClass="max-w-lg"
    >
      <div className="mb-5 flex gap-1.5 rounded-lg border border-slate-200 bg-slate-100/70 p-1 dark:border-white/[0.08] dark:bg-zinc-900">
        <button
          type="button"
          onClick={() => {
            setMode("create");
            setError(null);
          }}
          className={`flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium transition duration-150 ${
            mode === "create"
              ? "bg-white text-[#0F172A] shadow-xs dark:bg-zinc-800 dark:text-[#F8FAFC]"
              : "text-slate-600 dark:text-zinc-400"
          }`}
        >
          <Building2 className="h-3.5 w-3.5" />
          New Workspace
        </button>
        <button
          type="button"
          onClick={() => {
            setMode("connect");
            setError(null);
            setCreatedKey(null);
          }}
          className={`flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium transition duration-150 ${
            mode === "connect"
              ? "bg-white text-[#0F172A] shadow-xs dark:bg-zinc-800 dark:text-[#F8FAFC]"
              : "text-slate-600 dark:text-zinc-400"
          }`}
        >
          <KeyRound className="h-3.5 w-3.5" />
          Use API Key
        </button>
      </div>

      {createdKey ? (
        <div className="space-y-4">
          <div className="rounded-xl border border-emerald-200 bg-emerald-50/80 p-4 dark:border-emerald-500/20 dark:bg-emerald-500/10">
            <p className="text-sm font-semibold text-emerald-900 dark:text-emerald-200">
              Workspace created and connected
            </p>
            <p className="mt-1 text-xs text-emerald-800 dark:text-emerald-300">
              Save this API key now. It is hashed with SHA-256 on the server and cannot be retrieved again.
            </p>
            <div className="mt-3 flex items-center gap-2">
              <code className="flex-1 overflow-x-auto rounded-lg bg-[#09090B] px-3 py-2 font-mono text-xs text-emerald-300">
                {createdKey}
              </code>
              <button
                type="button"
                onClick={copyCreatedKey}
                className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#09090B] px-3 text-xs font-medium text-white transition duration-150 hover:bg-zinc-800"
              >
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              setCreatedKey(null);
              onClose();
            }}
            className="h-10 w-full rounded-lg bg-[#4F46E5] px-4 text-sm font-medium text-white transition duration-150 hover:bg-[#4338CA] dark:bg-[#6366F1] dark:hover:bg-[#4F46E5]"
          >
            Continue to Dashboard
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === "create" ? (
            <>
              <div>
                <label htmlFor={nameId} className="block text-xs font-medium text-slate-700 dark:text-zinc-300">
                  Company Name <span aria-hidden="true" className="text-red-500">*</span>
                </label>
                <input
                  id={nameId}
                  name="company_name"
                  type="text"
                  required
                  minLength={2}
                  autoFocus
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  placeholder="Linear Labs Inc."
                  className="mt-1.5 h-11 w-full rounded-lg border border-slate-200 bg-white px-3.5 text-sm transition duration-150 dark:border-white/[0.08] dark:bg-zinc-950"
                />
              </div>
              <div>
                <label htmlFor={slugId} className="block text-xs font-medium text-slate-700 dark:text-zinc-300">
                  Workspace Slug (optional)
                </label>
                <input
                  id={slugId}
                  name="company_slug"
                  type="text"
                  autoCorrect="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="linear-labs"
                  className="mt-1.5 h-11 w-full rounded-lg border border-slate-200 bg-white px-3.5 text-sm transition duration-150 dark:border-white/[0.08] dark:bg-zinc-950"
                />
              </div>
            </>
          ) : (
            <div>
              <label htmlFor={keyId} className="block text-xs font-medium text-slate-700 dark:text-zinc-300">
                Tenant API Key <span aria-hidden="true" className="text-red-500">*</span>
              </label>
              <div className="relative mt-1.5">
                <input
                  id={keyId}
                  name="api_key"
                  type={showKey ? "text" : "password"}
                  required
                  autoFocus
                  autoComplete="current-password"
                  autoCorrect="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={existingKey}
                  onChange={(e) => setExistingKey(e.target.value)}
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? errorId : undefined}
                  placeholder="air_..."
                  className="h-11 w-full rounded-lg border border-slate-200 bg-white pr-11 pl-3.5 font-mono text-xs transition duration-150 dark:border-white/[0.08] dark:bg-zinc-950"
                />
                <button
                  type="button"
                  onClick={() => setShowKey((s) => !s)}
                  aria-pressed={showKey}
                  aria-label={showKey ? "Hide API key" : "Show API key"}
                  className="absolute inset-y-0 right-1 my-auto inline-flex h-9 w-9 items-center justify-center rounded-md text-slate-500 transition duration-150 hover:text-slate-900 dark:hover:text-white"
                >
                  {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
          )}

          {error && (
            <p
              id={errorId}
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300"
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="h-10 w-full rounded-lg bg-[#4F46E5] px-4 text-sm font-medium text-white transition duration-150 hover:bg-[#4338CA] disabled:opacity-60 dark:bg-[#6366F1] dark:hover:bg-[#4F46E5]"
          >
            {loading
              ? "Authenticating..."
              : mode === "create"
                ? "Create Tenant & Generate API Key"
                : "Connect Workspace"}
          </button>
        </form>
      )}
    </ModalDialog>
  );
}

<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api/client.ts";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import StatusBlock from "#lib/components/StatusBlock.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { _, locale } from "svelte-i18n";
  import { fmtBytes, fmtLocalDateTime } from "#lib/format.ts";

  interface HealthPayload {
    version: {
      current: string;
      latest_known: string | null;
      latest_release_url: string | null;
      latest_checked_at: string | null;
      is_outdated: boolean;
    };
    audit_retention_days: number;
    storage_roots: Array<{
      id: string;
      name: string;
      host_path: string;
      last_health_check_at: string | null;
      last_health_status: string;
      default_for_ingest: boolean;
      free_bytes?: number;
      used_bytes?: number;
      total_bytes?: number;
    }>;
    connectors: Array<{
      id: string;
      name: string;
      kind: string;
      enabled: boolean;
      last_used_at: string | null;
      last_status: string | null;
    }>;
    providers: Array<{
      kind: string;
      name: string;
      enabled: boolean;
      priority: number;
    }>;
    tokens: { total: number; active: number; revoked: number };
  }

  let data: HealthPayload | null = null;
  let loading = true;
  let error: string | null = null;

  async function load() {
    loading = true;
    try {
      data = await api<HealthPayload>("/api/admin/health");
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "load failed";
    } finally {
      loading = false;
    }
  }

  function fmtPct(used: number | undefined, total: number | undefined): string {
    if (!used || !total) return "";
    return `${((used / total) * 100).toFixed(0)}%`;
  }

  function statusClass(s: string): string {
    if (s === "ok") return "ok";
    if (s === "near_full") return "warn";
    return "bad";
  }

  onMount(load);
</script>

<section class="health">
  <header><h2>Health</h2></header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  {#if loading}
    <p class="loading">{$_("common.loading")}</p>
  {:else if data}
    <StatusBlock title="Version">
      <div class="stat-line"><span class="k">Running</span><span class="v mono">{data.version.current}</span></div>
      <div class="stat-line">
        <span class="k">Latest known</span>
        <span class="v mono">
          {data.version.latest_known ?? "—"}
          {#if data.version.is_outdated && data.version.latest_release_url}
            — <a href={data.version.latest_release_url} target="_blank" rel="noopener">release notes →</a>
          {/if}
        </span>
      </div>
      <div class="stat-line"><span class="k">Last checked</span><span class="v mono">{fmtLocalDateTime(data.version.latest_checked_at, $locale) || "—"}</span></div>
      <div class="stat-line"><span class="k">Audit retention</span><span class="v mono">{data.audit_retention_days} days</span></div>
    </StatusBlock>

    <div class="table-section">
      <h3>Storage roots</h3>
      <AdminTable
        columns={["Name", "Path", "Status", "Free", "Used", "Capacity"]}
      >
        {#each data.storage_roots as r (r.id)}
          <tr>
            <td>{r.name}{r.default_for_ingest ? " ★" : ""}</td>
            <td class="mono">{r.host_path}</td>
            <td class={statusClass(r.last_health_status)}>{r.last_health_status}</td>
            <td class="mono">{fmtBytes(r.free_bytes)}</td>
            <td class="mono">{fmtBytes(r.used_bytes)} {fmtPct(r.used_bytes, r.total_bytes)}</td>
            <td class="mono">{fmtBytes(r.total_bytes)}</td>
          </tr>
        {/each}
      </AdminTable>
    </div>

    <div class="table-section">
      <h3>Connectors</h3>
      {#if data.connectors.length === 0}
        <EmptyState message="No connectors configured." />
      {:else}
        <AdminTable
          columns={["Name", "Kind", "Enabled", "Last used", "Status"]}
        >
          {#each data.connectors as c (c.id)}
            <tr>
              <td>{c.name}</td>
              <td class="mono">{c.kind}</td>
              <td>{c.enabled ? "✓" : "—"}</td>
              <td class="mono">{fmtLocalDateTime(c.last_used_at, $locale) || "—"}</td>
              <td class="mono">{c.last_status ?? "—"}</td>
            </tr>
          {/each}
        </AdminTable>
      {/if}
    </div>

    <div class="table-section">
      <h3>Providers</h3>
      {#if data.providers.length === 0}
        <EmptyState message="No providers configured." />
      {:else}
        <AdminTable columns={["Kind", "Name", "Enabled", "Priority"]}>
          {#each data.providers as p (p.kind)}
            <tr>
              <td class="mono">{p.kind}</td>
              <td>{p.name}</td>
              <td>{p.enabled ? "✓" : "—"}</td>
              <td class="mono">{p.priority}</td>
            </tr>
          {/each}
        </AdminTable>
      {/if}
    </div>

    <StatusBlock
      title="API tokens"
      rows={[
        { label: "Total", value: String(data.tokens.total) },
        { label: "Active", value: String(data.tokens.active) },
        { label: "Revoked", value: String(data.tokens.revoked) },
      ]}
    />
  {/if}
</section>

<style>
  .health { display: grid; gap: var(--sp-3); }
  .table-section { display: grid; gap: var(--sp-2); }
  .table-section h3 { margin: 0; font-size: var(--ts-md); color: var(--text-strong); }
  .loading { color: var(--text-faint); }
  .ok { color: var(--accent); }
  .warn { color: var(--accent-warning); }
  .bad { color: var(--accent-error); }
</style>

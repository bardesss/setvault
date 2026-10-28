<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api/client.ts";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { _, locale } from "svelte-i18n";
  import { fmtLocalDateTime } from "#lib/format.ts";

  interface ScheduledTask {
    id: string;
    func_name: string;
    short_name: string;
    next_run_at: string | null;
    interval_seconds: number | null;
    last_run_at: string | null;
    last_status: string | null;
  }

  let items: ScheduledTask[] = [];
  let loading = true;
  let error: string | null = null;
  let busy: Record<string, boolean> = {};
  let notice: string | null = null;

  async function load() {
    loading = true;
    try {
      const r = await api<{ items: ScheduledTask[] }>("/api/admin/tasks");
      items = r.items;
    } catch (e) {
      error = e instanceof ApiError ? e.detail : $_("admin.common.load_failed");
    } finally {
      loading = false;
    }
  }

  async function runNow(funcName: string) {
    busy[funcName] = true;
    busy = busy;
    notice = null;
    try {
      await api("/api/admin/tasks/run-now", {
        method: "POST",
        body: JSON.stringify({ func_name: funcName }),
      });
      notice = $_("admin.tasks.queued", { values: { name: funcName.split(".").pop() ?? funcName } });
    } catch (e) {
      error = e instanceof ApiError ? e.detail : $_("admin.tasks.run_now_failed");
    } finally {
      busy[funcName] = false;
      busy = busy;
    }
  }

  function fmtInterval(secs: number | null, t: typeof $_): string {
    if (!secs) return "—";
    if (secs < 60) return t("admin.tasks.interval_s", { values: { n: secs } });
    if (secs < 3600) return t("admin.tasks.interval_m", { values: { n: Math.round(secs / 60) } });
    if (secs < 86400) return t("admin.tasks.interval_h", { values: { n: Math.round(secs / 3600) } });
    return t("admin.tasks.interval_d", { values: { n: Math.round(secs / 86400) } });
  }

  onMount(load);
</script>

<section class="tasks">
  <header>
    <h2>{$_("admin.tasks.title")}</h2>
    <p class="muted">{$_("admin.tasks.intro")}</p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}
  {#if notice}<p class="admin-msg is-success" role="status">{notice}</p>{/if}

  {#if loading}
    <p class="loading">{$_("common.loading")}</p>
  {:else if items.length === 0}
    <EmptyState message={$_("admin.tasks.empty")} />
  {:else}
    <AdminTable
      columns={[$_("admin.tasks.col_job"), $_("admin.tasks.col_interval"), $_("admin.tasks.col_next_run"), $_("admin.tasks.col_last_run"), $_("admin.tasks.col_status"), ""]}
    >
      {#each items as task (task.id)}
        <tr>
          <td class="mono">{task.short_name}</td>
          <td class="mono">{fmtInterval(task.interval_seconds, $_)}</td>
          <td class="mono">{fmtLocalDateTime(task.next_run_at, $locale) || "—"}</td>
          <td class="mono">{fmtLocalDateTime(task.last_run_at, $locale) || "—"}</td>
          <td class="mono">{task.last_status ?? "—"}</td>
          <td class="cell-actions">
            <button
              type="button"
              class="btn btn-sm"
              disabled={busy[task.func_name]}
              on:click={() => runNow(task.func_name)}
            >{$_("admin.tasks.run_now")}</button>
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</section>

<style>
  .tasks { display: grid; gap: var(--sp-3); }
  header { display: grid; gap: var(--sp-1); }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); margin: 0; }
  .loading { color: var(--text-faint); }
</style>

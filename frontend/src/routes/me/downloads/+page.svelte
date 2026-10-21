<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import RipJobRow from "#lib/components/RipJobRow.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import {
    listMyRipJobs,
    hasActiveRips,
    isRipActive,
    replaceRipJob,
    deleteRipJob,
    clearFinishedRipJobs,
    type RipJob,
  } from "#lib/api/url_rip.ts";

  let jobs: RipJob[] = [];
  let loaded = false;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  $: hasFinished = jobs.some((j) => !isRipActive(j));

  async function remove(id: string) {
    await deleteRipJob(id);
    jobs = jobs.filter((j) => j.id !== id);
  }

  async function clearFinished() {
    await clearFinishedRipJobs();
    jobs = jobs.filter(isRipActive);
  }

  async function refresh() {
    try {
      jobs = await listMyRipJobs("all");
    } catch {
      /* best-effort: keep the last good list on a transient error */
    } finally {
      loaded = true;
    }
  }

  onMount(async () => {
    await refresh();
    // Poll while anything is still in flight so progress updates live; idle
    // once every job has reached a terminal state.
    pollTimer = setInterval(() => {
      if (hasActiveRips(jobs)) void refresh();
    }, 4000);
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  function onRetried(previousId: string, fresh: RipJob) {
    jobs = replaceRipJob(jobs, previousId, fresh);
  }
</script>

<svelte:head><title>{$_("downloads.title")} — SetVault</title></svelte:head>

<header class="downloads-head">
  <h2>{$_("downloads.title")}</h2>
  {#if hasFinished}
    <button type="button" class="btn btn-ghost" on:click={clearFinished}>
      {$_("downloads.clear_finished")}
    </button>
  {/if}
</header>

{#if loaded && jobs.length === 0}
  <EmptyState message={$_("downloads.empty")} />
{:else}
  <ul class="downloads-list">
    {#each jobs as job (job.id)}
      <li class="download-item">
        <RipJobRow {job} on:retried={(e) => onRetried(e.detail.previousId, e.detail.job)} />
        <button
          type="button"
          class="remove"
          aria-label={$_("downloads.remove")}
          title={$_("downloads.remove")}
          on:click={() => remove(job.id)}
        >×</button>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .downloads-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
  }
  .downloads-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--sp-2);
  }
  .download-item {
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: start;
    gap: var(--sp-2);
  }
  .remove {
    background: none;
    border: none;
    color: var(--text-faint);
    font-size: var(--ts-lg);
    line-height: 1;
    cursor: pointer;
    padding: var(--sp-1);
  }
  .remove:hover { color: var(--text-default); }
</style>

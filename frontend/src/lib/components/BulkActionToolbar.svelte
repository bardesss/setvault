<script lang="ts">
  import { _ } from "svelte-i18n";
  import { api, ApiError } from "#lib/api/client.ts";

  export let selectedIds: string[];
  export let onCleared: () => void;
  export let onSubmitted: (action: string) => void;

  interface MediaRoot {
    id: string;
    name: string;
  }

  let mode: "idle" | "retag" | "move" = "idle";
  let busy = false;
  let error: string | null = null;
  let retagAdd = "";
  let retagRemove = "";
  let moveTarget = "";
  let roots: MediaRoot[] = [];

  async function loadRoots() {
    try {
      const r = await api<{ items: MediaRoot[] }>("/api/media-roots");
      roots = r.items;
      if (!moveTarget && roots[0]) moveTarget = roots[0].id;
    } catch (e) {
      error = e instanceof ApiError ? e.detail : $_("bulk.load_roots_failed");
    }
  }

  async function submit(action: string, params: Record<string, unknown> = {}) {
    busy = true;
    error = null;
    try {
      await api("/api/sets/bulk-action", {
        method: "POST",
        body: JSON.stringify({
          action,
          set_ids: selectedIds,
          params,
        }),
      });
      mode = "idle";
      onSubmitted(action);
    } catch (e) {
      error = e instanceof ApiError ? e.detail : $_("bulk.submit_failed");
    } finally {
      busy = false;
    }
  }

  function confirmSoftDelete() {
    if (!confirm($_("bulk.confirm_delete", { values: { count: selectedIds.length } }))) {
      return;
    }
    void submit("soft_delete");
  }

  async function openMove() {
    if (roots.length === 0) await loadRoots();
    mode = "move";
  }

  function submitRetag() {
    const add = retagAdd.split(/[,\s]+/).map((t) => t.trim()).filter(Boolean);
    const remove = retagRemove.split(/[,\s]+/).map((t) => t.trim()).filter(Boolean);
    if (add.length === 0 && remove.length === 0) {
      error = $_("bulk.retag_empty");
      return;
    }
    void submit("retag", { add, remove });
  }

  function submitMove() {
    if (!moveTarget) {
      error = $_("bulk.pick_root");
      return;
    }
    void submit("move_root", { target_media_root_id: moveTarget });
  }
</script>

<aside class="toolbar" role="region" aria-label={$_("bulk.label")}>
  <div class="count">
    <strong>{selectedIds.length}</strong> {$_("bulk.selected")}
  </div>

  {#if error}<p class="error" role="alert">{error}</p>{/if}

  {#if mode === "idle"}
    <button type="button" disabled={busy} on:click={confirmSoftDelete}>{$_("bulk.delete")}</button>
    <button type="button" disabled={busy} on:click={() => { mode = "retag"; }}>{$_("bulk.retag")}</button>
    <button type="button" disabled={busy} on:click={openMove}>{$_("bulk.move_root")}</button>
    <button type="button" class="ghost" on:click={onCleared}>{$_("bulk.clear_selection")}</button>
  {:else if mode === "retag"}
    <label class="inline">
      {$_("bulk.add")}
      <input type="text" placeholder={$_("bulk.tags_placeholder")} bind:value={retagAdd} />
    </label>
    <label class="inline">
      {$_("bulk.remove")}
      <input type="text" placeholder={$_("bulk.tags_placeholder")} bind:value={retagRemove} />
    </label>
    <button type="button" disabled={busy} on:click={submitRetag}>{$_("bulk.apply_retag")}</button>
    <button type="button" class="ghost" on:click={() => { mode = "idle"; }}>{$_("common.cancel")}</button>
  {:else if mode === "move"}
    <label class="inline">
      {$_("bulk.target_root")}
      <select bind:value={moveTarget}>
        {#each roots as r (r.id)}
          <option value={r.id}>{r.name}</option>
        {/each}
      </select>
    </label>
    <button type="button" disabled={busy} on:click={submitMove}>{$_("bulk.apply_move")}</button>
    <button type="button" class="ghost" on:click={() => { mode = "idle"; }}>{$_("common.cancel")}</button>
  {/if}
</aside>

<style>
  .toolbar {
    position: sticky;
    top: var(--sp-2);
    z-index: 30;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: var(--sp-2) var(--sp-3);
    background: var(--bg-surface);
    border: 1px solid var(--accent);
    border-radius: var(--r-md);
    flex-wrap: wrap;
  }
  .count { font-size: var(--ts-sm); color: var(--text-faint); }
  .toolbar button {
    padding: var(--sp-1) var(--sp-2);
    background: transparent;
    border: 1px solid var(--border-default);
    color: inherit;
    border-radius: var(--r-sm);
    cursor: pointer;
  }
  .toolbar button:disabled { opacity: 0.5; cursor: not-allowed; }
  .toolbar button.ghost { border-style: dashed; }
  .inline { display: inline-flex; align-items: center; gap: var(--sp-1);
            font-size: var(--ts-sm); color: var(--text-faint); }
  .inline input, .inline select {
    padding: var(--sp-1);
    background: var(--bg-base);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    color: inherit;
    font: inherit;
  }
  .error { color: var(--accent-error); font-size: var(--ts-sm); margin: 0; }
</style>

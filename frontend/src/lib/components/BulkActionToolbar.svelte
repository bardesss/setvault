<script lang="ts">
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
      error = e instanceof ApiError ? e.detail : "could not load media roots";
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
      error = e instanceof ApiError ? e.detail : "submission failed";
    } finally {
      busy = false;
    }
  }

  function confirmSoftDelete() {
    if (!confirm(`Move ${selectedIds.length} set(s) to the recycle bin?`)) {
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
      error = "add or remove tags first";
      return;
    }
    void submit("retag", { add, remove });
  }

  function submitMove() {
    if (!moveTarget) {
      error = "pick a target root";
      return;
    }
    void submit("move_root", { target_media_root_id: moveTarget });
  }
</script>

<aside class="toolbar" role="region" aria-label="bulk actions">
  <div class="count">
    <strong>{selectedIds.length}</strong> selected
  </div>

  {#if error}<p class="error" role="alert">{error}</p>{/if}

  {#if mode === "idle"}
    <button type="button" disabled={busy} on:click={confirmSoftDelete}>Delete</button>
    <button type="button" disabled={busy} on:click={() => { mode = "retag"; }}>Retag…</button>
    <button type="button" disabled={busy} on:click={openMove}>Move root…</button>
    <button type="button" class="ghost" on:click={onCleared}>Clear selection</button>
  {:else if mode === "retag"}
    <label class="inline">
      Add
      <input type="text" placeholder="comma or space separated" bind:value={retagAdd} />
    </label>
    <label class="inline">
      Remove
      <input type="text" placeholder="comma or space separated" bind:value={retagRemove} />
    </label>
    <button type="button" disabled={busy} on:click={submitRetag}>Apply retag</button>
    <button type="button" class="ghost" on:click={() => { mode = "idle"; }}>Cancel</button>
  {:else if mode === "move"}
    <label class="inline">
      Target root
      <select bind:value={moveTarget}>
        {#each roots as r (r.id)}
          <option value={r.id}>{r.name}</option>
        {/each}
      </select>
    </label>
    <button type="button" disabled={busy} on:click={submitMove}>Apply move</button>
    <button type="button" class="ghost" on:click={() => { mode = "idle"; }}>Cancel</button>
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
  .error { color: #c33; font-size: var(--ts-sm); margin: 0; }
</style>

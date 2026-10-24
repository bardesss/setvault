<script lang="ts">
  import { _ } from "svelte-i18n";
  import { ApiError } from "#lib/api/client.ts";
  import { createMonitor, deleteMonitor } from "#lib/api/monitors.ts";
  import { toast } from "#lib/stores/toast.ts";

  export let kind: "artist" | "party" | "venue";
  export let entityId: string;
  export let name: string;
  export let monitor: { id: string; enabled: boolean } | null;

  let busy = false;

  $: pressed = !!monitor && monitor.enabled;

  async function toggle() {
    if (busy) return;
    busy = true;
    const prev = monitor;
    try {
      if (prev && prev.enabled) {
        monitor = null; // optimistic
        try {
          await deleteMonitor(prev.id);
        } catch (e) {
          // Already deleted elsewhere: the outcome the user asked for.
          if (!(e instanceof ApiError && e.status === 404)) throw e;
        }
        toast.success($_("monitors.stopped", { values: { name } }));
      } else {
        monitor = { id: prev?.id ?? "", enabled: true }; // optimistic
        const m = await createMonitor({
          kind: "query",
          query_text: name,
          catalog_kind: kind,
          catalog_id: entityId,
        });
        monitor = { id: m.id, enabled: m.enabled };
        toast.success($_("monitors.started", { values: { name } }));
      }
    } catch {
      monitor = prev; // revert
      toast.error($_("monitors.toggle_error"));
    } finally {
      busy = false;
    }
  }
</script>

<button
  type="button"
  class="monitor-btn"
  on:click={toggle}
  aria-pressed={pressed}
  disabled={busy}
>
  {pressed ? $_("monitors.monitoring") : $_("monitors.monitor")}
</button>

<style>
  .monitor-btn {
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    background: var(--bg-surface);
    cursor: pointer;
    color: var(--text-default);
    font: inherit;
  }
  .monitor-btn[aria-pressed="true"] { color: var(--accent); border-color: var(--accent); }
  .monitor-btn:disabled { opacity: 0.6; cursor: default; }
</style>

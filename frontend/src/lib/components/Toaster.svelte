<script lang="ts">
  import { _ } from "svelte-i18n";
  import { toast, toasts } from "#lib/stores/toast.ts";
</script>

<div class="toaster" aria-live="polite">
  {#each $toasts as t (t.id)}
    <div class="toast-item {t.kind}" role={t.kind === "error" ? "alert" : "status"}>
      <span class="msg">{t.message}</span>
      <button
        type="button"
        class="x"
        aria-label={$_("common.dismiss")}
        on:click={() => toast.dismiss(t.id)}>×</button
      >
    </div>
  {/each}
</div>

<style>
  .toaster {
    position: fixed;
    right: var(--sp-4);
    bottom: var(--sp-4);
    display: grid;
    gap: var(--sp-2);
    max-width: min(420px, calc(100vw - 2 * var(--sp-4)));
    z-index: var(--z-toast);
    pointer-events: none;
  }
  .toast-item {
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4);
    background: var(--bg-elevated);
    color: var(--text-default);
    border: 1px solid var(--border-strong);
    border-left-width: 3px;
    border-radius: var(--r-md);
    box-shadow: var(--shadow-md);
    font-size: var(--ts-md);
  }
  .toast-item.success { border-left-color: var(--accent-success); }
  .toast-item.error { border-left-color: var(--accent-error); }
  .msg { flex: 1; }
  .x {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: var(--ts-lg);
    line-height: 1;
  }
  .x:hover { color: var(--text-strong); }
  @media (max-width: 600px) {
    .toaster { bottom: calc(72px + env(safe-area-inset-bottom, 0px)); }
  }
</style>

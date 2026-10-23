<script lang="ts">
  import { createEventDispatcher, tick } from "svelte";
  import { _ } from "svelte-i18n";

  export let open = false;
  export let title: string;

  const dispatch = createEventDispatcher<{ close: void }>();
  const FOCUSABLE =
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  let dialogEl: HTMLElement | undefined;
  let opener: HTMLElement | null = null;
  let wasOpen = false;

  $: if (open !== wasOpen) {
    wasOpen = open;
    if (open) {
      opener = document.activeElement as HTMLElement | null;
      void tick().then(() => {
        const first = dialogEl?.querySelector<HTMLElement>(FOCUSABLE);
        (first ?? dialogEl)?.focus();
      });
    } else {
      opener?.focus?.();
      opener = null;
    }
  }

  function close() {
    dispatch("close");
  }

  function onKeydown(ev: KeyboardEvent) {
    if (!open) return;
    if (ev.key === "Escape") {
      ev.preventDefault();
      close();
    } else if (ev.key === "Tab" && dialogEl) {
      const items = Array.from(dialogEl.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        ev.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (ev.shiftKey && (active === first || active === dialogEl)) {
        ev.preventDefault();
        last.focus();
      } else if (!ev.shiftKey && active === last) {
        ev.preventDefault();
        first.focus();
      }
    }
  }

  function onBackdrop(ev: MouseEvent) {
    if (ev.target === ev.currentTarget) close();
  }
</script>

<svelte:window on:keydown={onKeydown} />

{#if open}
  <div class="backdrop" on:click={onBackdrop} role="presentation">
    <div
      class="dialog modal"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      tabindex="-1"
      bind:this={dialogEl}
    >
      <div class="dialog-header">
        <h2 class="dialog-title">{title}</h2>
        <button
          type="button"
          class="btn btn-ghost btn-icon btn-sm"
          aria-label={$_("common.close")}
          on:click={close}>×</button
        >
      </div>
      <div class="dialog-body"><slot /></div>
      {#if $$slots.actions}
        <div class="dialog-actions"><slot name="actions" /></div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 12vh var(--sp-4) var(--sp-4);
    background: rgba(0, 0, 0, 0.5);
    z-index: var(--z-modal);
    overflow-y: auto;
  }
  .modal {
    outline: none;
  }
</style>

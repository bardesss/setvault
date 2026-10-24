<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { _ } from "svelte-i18n";
  import Modal from "#lib/components/Modal.svelte";

  export let open = false;
  export let title: string;
  export let message: string;
  export let confirmLabel: string = "";
  export let danger = false;

  const dispatch = createEventDispatcher<{ confirm: void; cancel: void }>();
</script>

<Modal {open} {title} on:close={() => dispatch("cancel")}>
  <p>{message}</p>
  <svelte:fragment slot="actions">
    <button type="button" class="btn" on:click={() => dispatch("cancel")}>
      {$_("common.cancel")}
    </button>
    <button
      type="button"
      class="btn"
      class:btn-danger={danger}
      class:btn-primary={!danger}
      on:click={() => dispatch("confirm")}
    >
      {confirmLabel || $_("common.confirm")}
    </button>
  </svelte:fragment>
</Modal>

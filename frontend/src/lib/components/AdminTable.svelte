<script lang="ts">
  export let columns: string[];
  export let caption: string | null = null;
</script>

<!-- The wrapper scrolls a table that still can't fit, so the page itself never does. -->
<div class="admin-table-wrap">
  <table class="admin-table">
    {#if caption}<caption class="sr-only">{caption}</caption>{/if}
    <thead>
      <tr>
        {#each columns as c (c)}<th>{c}</th>{/each}
      </tr>
    </thead>
    <tbody>
      <slot />
    </tbody>
  </table>
</div>

<style>
  .admin-table-wrap { max-width: 100%; overflow-x: auto; }
  .sr-only {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
  }
</style>

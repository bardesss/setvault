<script lang="ts">
  import { _ } from "svelte-i18n";
  export let title: string;
  export let subMeta: string | null = null;
  export let moreHref: string | null = null;
  export let moreLabel: string | null = null;
</script>

<div class="section-head">
  <div>
    <h2>{title}</h2>
    {#if subMeta}<p class="sub-meta">{subMeta}</p>{/if}
  </div>
  {#if moreHref}
    <a class="show-more" href={moreHref}>{moreLabel ?? $_("components.view_all")}</a>
  {/if}
</div>

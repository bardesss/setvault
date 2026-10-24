<script lang="ts">
  import EntityBrowse from "#lib/components/EntityBrowse.svelte";
  import { _ } from "svelte-i18n";
  import type { PageData } from "./$types";

  export let data: PageData;
</script>

<EntityBrowse kind="venues" title={$_("browse.venues")} {data} />

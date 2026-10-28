<script lang="ts">
  import { _ } from "svelte-i18n";
  export let message: string | null = null;
</script>

<p class="empty-state" role="status"><slot>{message ?? $_("components.empty_default")}</slot></p>

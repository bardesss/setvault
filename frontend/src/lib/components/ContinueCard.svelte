<script lang="ts">
  import { fmtDuration } from "#lib/format.ts";
  export let slug: string;
  export let title: string;
  export let artist: string = "";
  export let positionSeconds: number;
  export let durationSeconds: number | null;

  $: pct = durationSeconds && durationSeconds > 0
    ? Math.min(100, Math.max(0, (positionSeconds / durationSeconds) * 100))
    : 0;
</script>

<a class="continue-card" href={`/sets/${slug}`}>
  <div class="continue-cover" aria-hidden="true"></div>
  <div class="body">
    <div class="ttl">{title}</div>
    {#if artist}<div class="artist">{artist}</div>{/if}
    <div class="progress-time">
      {fmtDuration(positionSeconds)} / {durationSeconds ? fmtDuration(durationSeconds) : "?"}
      {#if pct > 0} · {pct.toFixed(0)}% played{/if}
    </div>
    <div class="progress-bar"><div class="progress-fill" style="width: {pct}%"></div></div>
  </div>
</a>

<script lang="ts">
  import { _ } from "svelte-i18n";
  export let slug: string;
  export let title: string;
  export let artist: string = "";
  export let venue: string = "";
  export let durationSeconds: number | null = null;
  export let date: string | null = null;

  function fmt(s: number): string {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (h > 0) return $_("cards.duration_hm", { values: { h, m } });
    return $_("cards.duration_m", { values: { m } });
  }
</script>

<a class="set-row" href={`/sets/${slug}`}>
  <div class="set-cover" aria-hidden="true"></div>
  <div>
    <div class="set-title">{title}</div>
    {#if artist}<div class="set-artist">{artist}</div>{/if}
  </div>
  <div class="set-venue">{venue || ""}</div>
  <div class="set-duration">{durationSeconds != null ? fmt(durationSeconds) : ""}</div>
  <div class="set-duration">{date || ""}</div>
</a>

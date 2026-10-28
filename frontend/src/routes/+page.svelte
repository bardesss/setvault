<script lang="ts">
  import SectionHeader from "#lib/components/SectionHeader.svelte";
  import KpiGrid from "#lib/components/KpiGrid.svelte";
  import Kpi from "#lib/components/Kpi.svelte";
  import ContinueCard from "#lib/components/ContinueCard.svelte";
  import RecentCard from "#lib/components/RecentCard.svelte";
  import { _, locale } from "svelte-i18n";
  import { fmtBytes, fmtAgo } from "#lib/format.ts";
  import { jobKindLabel } from "#lib/jobKind.ts";
  import type { PageData } from "./$types";

  export let data: PageData;

  function fmtNumber(n: number): string {
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return n.toString();
  }
  function fmtDelta(n: number): string {
    const sign = n === 0 ? "—" : n > 0 ? "▲" : "▼";
    return $_("home.delta_this_week", { values: { sign, count: Math.abs(n) } });
  }

  $: greeting = (() => {
    const h = new Date().getHours();
    if (h < 12) return $_("home.greeting.morning");
    if (h < 18) return $_("home.greeting.afternoon");
    return $_("home.greeting.evening");
  })();

  $: userName =
    data.user?.display_name?.split(" ")[0] ||
    data.user?.email?.split("@")[0] ||
    "";
  $: summary = data.homeSummary;

  const ACTIVITY_ICON = { set_published: "♫", discovery: "◎", job_failed: "!" };

  const NEW_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;
  function isNewSet(createdAt: string | undefined): boolean {
    if (!createdAt) return false;
    const t = Date.parse(createdAt);
    return !Number.isNaN(t) && Date.now() - t < NEW_WINDOW_MS;
  }
</script>

<svelte:head><title>SetVault</title></svelte:head>

{#if !data.user}
  <section class="anon">
    <h1>SetVault</h1>
    <p><a href="/login">{$_("home.anon_sign_in")}</a> {$_("home.anon_access_library")}</p>
  </section>
{:else}
  <header class="greet">
    <h1>
      {greeting}, <span class="accent">{userName}</span>.
      {#if summary && summary.sets_delta > 0}
        <b>{$_("home.new_sets_landed", { values: { count: summary.sets_delta, days: summary.deltas_window_days } })}</b>
      {/if}
    </h1>
    {#if summary}
      <p class="sub">
        <b>{$_("home.summary_sets", { values: { count: fmtNumber(summary.sets_count) } })}</b> · <b>{$_("home.summary_tracks_resolved", { values: { count: fmtNumber(summary.tracks_resolved_count) } })}</b>
      </p>

      <KpiGrid>
        <Kpi
          value={fmtNumber(summary.sets_count)}
          label={$_("home.kpi.sets")}
          delta={fmtDelta(summary.sets_delta)}
          deltaUp={summary.sets_delta > 0}
          accent={true}
        />
        <Kpi
          value={fmtNumber(summary.tracks_resolved_count)}
          label={$_("home.kpi.tracks_resolved")}
          delta={fmtDelta(summary.tracks_resolved_delta)}
          deltaUp={summary.tracks_resolved_delta > 0}
        />
        <Kpi
          value={fmtNumber(summary.tracks_needing_ids_count)}
          label={$_("home.kpi.tracks_needing_ids")}
          delta={fmtDelta(summary.tracks_needing_ids_delta)}
        />
        <Kpi
          value={fmtBytes(summary.audio_bytes, $locale)}
          label={$_("home.kpi.audio_storage")}
        />
      </KpiGrid>
    {/if}
  </header>

  {#if data.continueListening.length}
    <section class="home-section">
      <SectionHeader
        title={$_("home.continue_title")}
        subMeta={$_("home.continue_meta", { values: { count: data.continueListening.length } })}
      />
      <div class="continue">
        {#each data.continueListening as item (item.slug)}
          <ContinueCard
            slug={item.slug}
            title={item.title}
            positionSeconds={item.position_seconds}
            durationSeconds={item.duration_seconds}
          />
        {/each}
      </div>
    </section>
  {/if}

  <section class="home-section">
    <SectionHeader
      title={$_("home.recent_title")}
      subMeta={$_("home.recent_meta", { values: { count: data.recent.length } })}
      moreHref="/sets"
      moreLabel={$_("home.browse_library")}
    />
    <div class="recent-grid">
      {#each data.recent as s (s.slug)}
        <RecentCard
          slug={s.slug}
          title={s.title}
          artist={Array.isArray(s.artists) && s.artists.length ? s.artists[0].name : ""}
          venue={s.venue?.name ?? ""}
          isNew={isNewSet(s.created_at)}
          year={s.date ? new Date(s.date).getFullYear() : null}
        />
      {/each}
    </div>
  </section>

  <section class="home-section" data-testid="home-activity">
    <SectionHeader title={$_("home.activity.title")} />
    {#if data.activity.length}
      <ul class="activity">
        {#each data.activity as a (a.id)}
          <li class="activity-row kind-{a.kind}">
            <span class="activity-icon" aria-hidden="true">{ACTIVITY_ICON[a.kind]}</span>
            <a href={a.href}>
              <span class="activity-kind">{$_(`home.activity.${a.kind}`)}</span>
              {a.kind === "job_failed" && a.job_kind ? jobKindLabel(a.job_kind, $_) : a.title}
            </a>
            <time datetime={a.at} title={a.at}>{fmtAgo(a.at, $locale)}</time>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="activity-empty">{$_("home.activity.empty")}</p>
    {/if}
    {#if data.user.role === "admin"}
      <a class="activity-jobs" href="/admin/jobs">{$_("home.activity.view_jobs")} →</a>
    {/if}
  </section>
{/if}

<style>
  .anon {
    padding: var(--sp-8) var(--sp-6);
    display: grid;
    gap: var(--sp-3);
    max-width: 720px;
    margin: 0 auto;
  }
  .anon h1 {
    font-size: var(--ts-3xl);
    letter-spacing: var(--ls-tight);
    margin: 0;
  }
  .home-section {
    padding: var(--sp-6) var(--sp-8);
    border-bottom: 1px solid var(--border-subtle);
  }
  .activity {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--sp-2);
  }
  .activity-row {
    display: grid;
    grid-template-columns: 1.5rem 1fr auto;
    align-items: baseline;
    gap: var(--sp-3);
  }
  .activity-icon {
    color: var(--text-muted);
    text-align: center;
  }
  .kind-job_failed .activity-icon {
    color: var(--accent-error);
  }
  .activity-kind {
    color: var(--text-muted);
    margin-right: var(--sp-2);
  }
  .activity-row time,
  .activity-empty {
    color: var(--text-muted);
  }
  .activity-jobs {
    display: inline-block;
    margin-top: var(--sp-3);
  }
</style>

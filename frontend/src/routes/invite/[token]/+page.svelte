<script lang="ts">
  import { page } from "$app/state";
  import { refreshAll, goto } from "$app/navigation";
  import { _ } from "svelte-i18n";
  import { api, ApiError } from "#lib/api/client.ts";
  let username = "", display_name = "", password = "", error: string | null = null;

  async function accept() {
    error = null;
    try {
      await api(`/api/invites/${page.params.token}/redeem`, {
        method: "POST",
        body: JSON.stringify({ username, display_name, password }),
      });
      await refreshAll();
      await goto("/");
    } catch (e) {
      error = e instanceof ApiError ? e.detail : $_("auth.invite.unknown_error");
    }
  }
</script>

<svelte:head><title>{$_("auth.invite.heading")} — SetVault</title></svelte:head>

<section class="auth-shell">
  <form class="auth-card" on:submit|preventDefault={accept}>
    <div class="auth-brand">
      <span class="brand-dot"></span>
      <span class="brand-name">SETVAULT</span>
    </div>

    <h1>{$_("auth.invite.heading")}</h1>
    <p class="auth-caption">// {$_("auth.invite.caption")}</p>

    <label>
      <span>{$_("auth.invite.username")}</span>
      <input bind:value={username} required minlength="2" />
    </label>

    <label>
      <span>{$_("auth.invite.display_name")}</span>
      <input bind:value={display_name} required />
    </label>

    <label>
      <span>{$_("auth.invite.password")}</span>
      <input type="password" bind:value={password} required minlength="12" />
    </label>

    {#if error}<p class="auth-error" role="alert">{error}</p>{/if}

    <button class="btn btn-primary" type="submit">{$_("auth.invite.accept_invite")}</button>
  </form>
</section>

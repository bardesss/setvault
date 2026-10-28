<script lang="ts">
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { _ } from "svelte-i18n";
  import { api, ApiError } from "#lib/api/client.ts";
  let password = "", error: string | null = null;

  async function submit() {
    error = null;
    try {
      await api(`/api/password-reset/${page.params.token}/redeem`, {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      await goto("/login");
    } catch (e) {
      error = e instanceof ApiError ? e.detail : $_("auth.reset.unknown_error");
    }
  }
</script>

<svelte:head><title>{$_("auth.reset.heading")} — SetVault</title></svelte:head>

<section class="auth-shell">
  <form class="auth-card" on:submit|preventDefault={submit}>
    <div class="auth-brand">
      <span class="brand-dot"></span>
      <span class="brand-name">SETVAULT</span>
    </div>

    <h1>{$_("auth.reset.heading")}</h1>
    <p class="auth-caption">// {$_("auth.reset.caption")}</p>

    <label>
      <span>{$_("auth.reset.new_password")}</span>
      <input type="password" bind:value={password} required minlength="12" />
    </label>

    {#if error}<p class="auth-error" role="alert">{error}</p>{/if}

    <button class="btn btn-primary" type="submit">{$_("auth.reset.submit")}</button>
  </form>
</section>

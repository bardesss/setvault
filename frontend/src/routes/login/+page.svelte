<script lang="ts">
  import { goto } from "$app/navigation";
  import { refreshAll } from "$app/navigation";
  import { _ } from "svelte-i18n";
  import { login } from "#lib/api/auth.ts";
  import { ApiError } from "#lib/api/client.ts";
  let email = "";
  let password = "";
  let error: string | null = null;
  let busy = false;

  async function submit() {
    error = null; busy = true;
    try {
      await login(email, password);
      await refreshAll();
      await goto("/");
    } catch (e) {
      error = e instanceof ApiError && e.status === 429
        ? $_("auth.login.rate_limited")
        : $_("auth.login.invalid_credentials");
    } finally { busy = false; }
  }
</script>

<svelte:head><title>{$_("auth.login.heading")} — SetVault</title></svelte:head>

<section class="auth-shell">
  <form class="auth-card" on:submit|preventDefault={submit}>
    <div class="auth-brand">
      <span class="brand-dot"></span>
      <span class="brand-name">SETVAULT</span>
    </div>

    <h1>{$_("auth.login.heading")}</h1>
    <p class="auth-caption">// access your vault</p>

    <label>
      <span>{$_("auth.login.email")}</span>
      <input type="email" bind:value={email} required autocomplete="email" />
    </label>

    <label>
      <span>{$_("auth.login.password")}</span>
      <input type="password" bind:value={password} required autocomplete="current-password" />
    </label>

    {#if error}<p class="auth-error" role="alert">{error}</p>{/if}

    <button class="btn btn-primary" type="submit" disabled={busy}>
      {busy ? $_("auth.login.submitting") : $_("auth.login.submit")}
    </button>
  </form>
</section>

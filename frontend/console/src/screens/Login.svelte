<script lang="ts">
  import { onMount } from 'svelte'
  import Mark from '../lib/Mark.svelte'
  import Wordmark from '../lib/Wordmark.svelte'
  import Icon from '../lib/Icon.svelte'
  import { api, ApiError } from '../lib/api'
  import { login } from '../lib/session'
  import { t, toggleLang, lang } from '../lib/i18n'
  import { theme, toggleTheme } from '../lib/theme'
  import { opName, loadProviders, providers } from '../lib/format'

  // `reachable=false` at boot means the API itself was down - lead with that, not "wrong password".
  let { reachable = true }: { reachable?: boolean } = $props()

  let mode = $state<'signin' | 'signup'>('signin')

  // --- sign in ---
  let username = $state('')
  let password = $state('')
  let busy = $state(false)
  let error = $state('')
  // A login attempt's error wins; otherwise, if the API was down at boot, lead with that.
  const shownError = $derived(error || (reachable ? '' : $t.login_unreachable))
  let demos = $state<{ username: string; password: string; provider: string | null }[]>([])

  // --- sign up ---
  let su = $state({ name: '', msisdn: '', provider: 'AIRTEL_COD', till: '', username: '', pass: '' })
  let suBusy = $state(false)
  let suError = $state('')
  let suOk = $state(false)

  onMount(() => {
    loadProviders()
    // Demo chips only exist in sandbox; prod returns [] and we render nothing.
    api
      .demoCredentials()
      .then((list) => (demos = Array.isArray(list) ? list : []))
      .catch(() => (demos = []))
  })

  async function submit(user: string, pass: string) {
    if (busy) return
    busy = true
    error = ''
    try {
      await login(user.trim(), pass)
    } catch (err) {
      error = err instanceof ApiError && err.status === 0 ? $t.login_unreachable : $t.login_err
      password = ''
    } finally {
      busy = false
    }
  }

  async function submitSignup() {
    if (suBusy) return
    suBusy = true
    suError = ''
    try {
      await api.signup({
        name: su.name.trim(),
        settlement_msisdn: su.msisdn.replace(/\s/g, ''),
        settlement_provider: su.provider || null,
        operator_till: su.till.trim() || null,
        username: su.username.trim(),
        password: su.pass,
      })
      suOk = true
    } catch (err) {
      // 409 = username taken; 0 = API down; anything else = validation/other → generic + check-details.
      if (err instanceof ApiError && err.status === 409) suError = $t.signup_taken
      else if (err instanceof ApiError && err.status === 0) suError = $t.login_unreachable
      else suError = $t.signup_fail
    } finally {
      suBusy = false
    }
  }

  function toSignin() {
    mode = 'signin'
    suOk = false
    suError = ''
  }
</script>

<div class="wrap">
  <div class="topbar">
    <button class="pill" onclick={toggleLang}>{$lang === 'fr' ? 'EN' : 'FR'}</button>
    <button class="pill" onclick={toggleTheme} aria-label="Toggle theme">
      <Icon name={$theme === 'dark' ? 'sun' : 'moon'} size={16} />
    </button>
  </div>

  <div class="card">
    <div class="brand"><Mark size={34} /><Wordmark size={22} /></div>

    {#if mode === 'signin'}
      <form onsubmit={(e) => (e.preventDefault(), submit(username, password))}>
        <h1 class="display">{$t.login_title}</h1>
        <p class="sub">{$t.login_sub}</p>

        <label class="lbl" for="u">{$t.login_user}</label>
        <input id="u" bind:value={username} autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" />

        <label class="lbl" for="p">{$t.login_pass}</label>
        <input id="p" type="password" bind:value={password} autocomplete="current-password" />

        {#if shownError}<div class="err" role="alert">{shownError}</div>{/if}

        <button class="btn btn-primary submit" type="submit" disabled={busy}>
          {busy ? $t.login_busy : $t.login_btn}
        </button>
      </form>

      {#if demos.length}
        <div class="demo">
          <div class="demo-cap">{$t.login_demo}</div>
          <div class="chips">
            {#each demos as d}
              <button type="button" class="chip" onclick={() => submit(d.username, d.password)}>
                <b>{d.username}</b>
                {#if d.provider}<span class="net">{$opName(d.provider)}</span>{/if}
              </button>
            {/each}
          </div>
        </div>
      {/if}

      <div class="swap">
        <button type="button" onclick={() => (mode = 'signup')}>{$t.to_signup}</button>
      </div>
    {:else if suOk}
      <div class="ok-state">
        <div class="tick"><Icon name="check" size={30} stroke={2.4} /></div>
        <p class="ok-msg">{$t.signup_ok}</p>
        <button class="btn btn-primary submit" onclick={toSignin}>{$t.login_btn}</button>
      </div>
    {:else}
      <form onsubmit={(e) => (e.preventDefault(), submitSignup())}>
        <h1 class="display">{$t.signup_title}</h1>
        <p class="sub">{$t.signup_sub}</p>

        <label class="lbl" for="s-name">{$t.signup_name}</label>
        <input id="s-name" bind:value={su.name} maxlength="80" required />

        <label class="lbl" for="s-msisdn">{$t.signup_msisdn}</label>
        <input id="s-msisdn" bind:value={su.msisdn} inputmode="tel" placeholder="243XXXXXXXXX" required />

        <label class="lbl" for="s-net">{$t.signup_provider}</label>
        <select id="s-net" bind:value={su.provider}>
          {#each Object.entries($providers) as [code, name]}
            <option value={code}>{name}</option>
          {/each}
        </select>

        <label class="lbl" for="s-till">{$t.signup_till}</label>
        <input id="s-till" bind:value={su.till} inputmode="numeric" />

        <label class="lbl" for="s-user">{$t.login_user}</label>
        <input id="s-user" bind:value={su.username} autocapitalize="none" autocorrect="off" spellcheck="false" required />

        <label class="lbl" for="s-pass">{$t.signup_pass}</label>
        <input id="s-pass" type="password" bind:value={su.pass} minlength="8" required />

        {#if suError}<div class="err" role="alert">{suError}</div>{/if}

        <button class="btn btn-primary submit" type="submit" disabled={suBusy}>
          {suBusy ? $t.signup_busy : $t.signup_btn}
        </button>
      </form>

      <div class="swap">
        <button type="button" onclick={toSignin}>{$t.to_login}</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .wrap {
    min-height: 100dvh;
    display: grid;
    place-items: center;
    padding: 20px;
    position: relative;
  }
  .topbar {
    position: absolute;
    top: 16px;
    right: 16px;
    display: flex;
    gap: 8px;
  }
  .pill {
    min-width: 34px;
    height: 34px;
    padding: 0 10px;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--muted);
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
    display: grid;
    place-items: center;
  }
  .pill:hover {
    color: var(--ink);
    border-color: var(--line2);
  }
  .card {
    width: 100%;
    max-width: 380px;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 20px;
    padding: 30px 26px;
    box-shadow: var(--shadow);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 9px;
    margin-bottom: 20px;
  }
  h1 {
    font-size: 24px;
    font-weight: 600;
    color: var(--ink);
  }
  .sub {
    font-size: 13.5px;
    color: var(--muted);
    line-height: 1.5;
    margin: 6px 0 18px;
  }
  .lbl {
    display: block;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--muted);
    margin: 12px 0 6px;
  }
  input,
  select {
    width: 100%;
    border: 1.5px solid var(--line2);
    border-radius: 12px;
    padding: 12px 14px;
    background: var(--inputbg);
    color: var(--ink);
    font-size: 16px; /* 16px min - anything smaller triggers iOS Safari zoom-on-focus */
    outline: none;
  }
  input:focus,
  select:focus {
    border-color: var(--brand);
  }
  .err {
    margin-top: 14px;
    font-size: 13px;
    font-weight: 600;
    color: var(--danger);
    background: var(--dangerbg);
    border-radius: 10px;
    padding: 10px 12px;
  }
  .submit {
    width: 100%;
    padding: 14px;
    font-size: 15.5px;
    border-radius: 12px;
    margin-top: 18px;
  }
  .swap {
    margin-top: 16px;
    text-align: center;
  }
  .swap button {
    background: none;
    border: none;
    color: var(--brand-text);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  .demo {
    margin-top: 18px;
    border-top: 1px solid var(--line);
    padding-top: 14px;
  }
  .demo-cap {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--muted);
  }
  .chips {
    display: flex;
    gap: 8px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  .chip {
    flex: 1;
    min-width: 90px;
    border: 1px solid var(--line2);
    background: var(--inputbg);
    border-radius: 12px;
    padding: 9px 8px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    color: var(--ink);
  }
  .chip:hover {
    border-color: var(--brand);
    color: var(--brand-text);
  }
  .chip b {
    font-size: 13px;
    font-weight: 700;
  }
  .chip .net {
    font-size: 10px;
    color: var(--muted);
  }
  .ok-state {
    text-align: center;
    padding: 10px 0;
  }
  .tick {
    width: 60px;
    height: 60px;
    border-radius: 50%;
    background: var(--okbg);
    color: var(--ok);
    display: grid;
    place-items: center;
    margin: 0 auto 14px;
  }
  .ok-msg {
    font-size: 14px;
    color: var(--ink);
    line-height: 1.55;
  }
</style>

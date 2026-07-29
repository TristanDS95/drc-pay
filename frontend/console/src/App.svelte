<script lang="ts">
  import { onMount } from 'svelte'
  import TopNav from './lib/TopNav.svelte'
  import TabBar from './lib/TabBar.svelte'
  import Overview from './screens/Overview.svelte'
  import Payments from './screens/Payments.svelte'
  import Customers from './screens/Customers.svelte'
  import Settings from './screens/Settings.svelte'
  import Login from './screens/Login.svelte'
  import Mark from './lib/Mark.svelte'
  import { session, bootSession } from './lib/session'
  import { loadProviders } from './lib/format'
  import { startFeed, stopFeed } from './lib/feed'
  import { route } from './lib/route'

  onMount(() => {
    loadProviders()
    bootSession()
  })

  // The transaction feed lives for as long as a merchant is signed in.
  $effect(() => {
    if ($session.status === 'authed') startFeed()
    else stopFeed()
  })
</script>

{#if $session.status === 'loading'}
  <div class="splash"><Mark size={40} /></div>
{:else if $session.status === 'anon'}
  <Login reachable={$session.reachable} />
{:else}
  <TopNav merchant={$session.merchant} active={$route} />
  {#if $route === 'payments'}
    <Payments />
  {:else if $route === 'customers'}
    <Customers />
  {:else if $route === 'settings'}
    <Settings merchant={$session.merchant} />
  {:else}
    <Overview merchant={$session.merchant} />
  {/if}
  <TabBar active={$route === 'overview' ? 'home' : $route} />
{/if}

<style>
  .splash {
    min-height: 100dvh;
    display: grid;
    place-items: center;
    /* a quiet pulse so a slow boot reads as "loading", never "frozen" */
    animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse {
    0%,
    100% {
      opacity: 0.55;
    }
    50% {
      opacity: 1;
    }
  }
</style>

<script lang="ts">
  import { onMount } from 'svelte'
  import TopNav from './lib/TopNav.svelte'
  import TabBar from './lib/TabBar.svelte'
  import Overview from './screens/Overview.svelte'
  import Login from './screens/Login.svelte'
  import Mark from './lib/Mark.svelte'
  import { session, bootSession } from './lib/session'
  import { loadProviders } from './lib/format'

  onMount(() => {
    loadProviders()
    bootSession()
  })
</script>

{#if $session.status === 'loading'}
  <div class="splash"><Mark size={40} /></div>
{:else if $session.status === 'anon'}
  <Login reachable={$session.reachable} />
{:else}
  <TopNav merchant={$session.merchant} active="Overview" />
  <Overview merchant={$session.merchant} />
  <TabBar active="home" />
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

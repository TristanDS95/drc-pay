<script lang="ts">
  import TopNav from './lib/TopNav.svelte'
  import TabBar from './lib/TabBar.svelte'
  import Overview from './screens/Overview.svelte'
</script>

<TopNav merchant="Alpha Gas Station" active="Overview" />
<Overview />
<TabBar active="home" />

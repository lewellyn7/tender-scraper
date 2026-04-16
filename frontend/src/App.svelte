<script>
  import { onMount } from 'svelte'
  import Navbar from './components/Navbar.svelte'
  import Dashboard from './pages/Dashboard.svelte'
  import DataPage from './pages/Data.svelte'
  import FavoritesPage from './pages/Favorites.svelte'
  import AnalyticsPage from './pages/Analytics.svelte'
  import TasksPage from './pages/Tasks.svelte'
  import SettingsPage from './pages/Settings.svelte'
  import LoginPage from './pages/Login.svelte'
  import CmdPalette from './components/CmdPalette.svelte'

  let route = '/data'
  let user = null
  let loading = true

  // Simple hash-based router
  function getRoute() {
    const hash = window.location.hash.replace('#', '') || '/data'
    return hash
  }

  onMount(async () => {
    route = getRoute()
    window.addEventListener('hashchange', () => {
      route = getRoute()
    })

    // Load user info
    try {
      const res = await fetch('/api/user/me')
      if (res.ok) {
        user = await res.json()
      }
    } catch (e) {
      console.warn('Not logged in')
    }
    loading = false

    // Global keyboard: Cmd+K → Cmd palette
    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        window.dispatchEvent(new CustomEvent('open-cmd-palette'))
      }
    })
  })

  $: if (typeof window !== 'undefined') {
    window.route = route
  }
</script>

{#if loading}
  <div class="flex items-center justify-center h-screen">
    <div class="text-gray-400">Loading...</div>
  </div>
{:else if route === '/login'}
  <LoginPage />
{:else}
  <div class="min-h-screen bg-gray-50 dark:bg-[#0f1011]">
    <Navbar {route} {user} />
    <main class="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
      {#if route === '/data' || route === '/'}
        <Dashboard />
      {:else if route === '/content'}
        <DataPage />
      {:else if route === '/favorites'}
        <FavoritesPage />
      {:else if route === '/analytics'}
        <AnalyticsPage />
      {:else if route === '/tasks'}
        <TasksPage />
      {:else if route === '/settings'}
        <SettingsPage />
      {:else}
        <DataPage />
      {/if}
    </main>
    <CmdPalette />
  </div>
{/if}

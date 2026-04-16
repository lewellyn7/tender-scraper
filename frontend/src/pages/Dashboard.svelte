<script>
  import { onMount } from 'svelte'

  let stats = { total: 0, today: 0, favorites: 0, running: 0 }
  let projects = []
  let loading = true

  onMount(async () => {
    try {
      const res = await fetch('/api/stats/dashboard')
      if (res.ok) {
        const data = await res.json()
        stats = data.stats || stats
        projects = data.recent || []
      }
    } catch (e) {
      console.warn('Dashboard API not available:', e)
    }
    loading = false
  })

  const statCards = [
    { key: 'total', label: '总采集', color: 'text-blue-600 dark:text-blue-400' },
    { key: 'today', label: '今日新增', color: 'text-green-600 dark:text-green-400' },
    { key: 'favorites', label: '我的收藏', color: 'text-amber-600 dark:text-amber-400' },
    { key: 'running', label: '采集中', color: 'text-purple-600 dark:text-purple-400' }
  ]
</script>

<div class="space-y-6">
  <!-- Stat Cards -->
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
    {#each statCards as card}
      <div class="bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 rounded-lg p-4 hover:bg-gray-50 dark:hover:bg-white/8 transition-colors duration-100">
        <div class="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-1">{card.label}</div>
        <p class="text-5xl font-bold tracking-tight {card.color}">{stats[card.key] ?? 0}</p>
      </div>
    {/each}
  </div>

  <!-- Recent Projects -->
  <div class="bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 rounded-xl p-5">
    <h2 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">最近采集</h2>
    {#if loading}
      <div class="text-gray-400 text-sm">加载中...</div>
    {:else if projects.length === 0}
      <div class="text-gray-400 text-sm">暂无数据</div>
    {:else}
      <div class="space-y-2">
        {#each projects.slice(0, 10) as item}
          <a href="{item.project_url}" target="_blank" class="group flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-gray-50 dark:hover:bg-white/5 transition-colors duration-100">
            <span class="w-2 h-2 rounded-full flex-shrink-0 bg-blue-400"></span>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium text-gray-900 dark:text-white truncate">{item.title || '—'}</div>
              <div class="text-xs text-gray-400">{item.tender_type || item.source || ''}</div>
            </div>
            {#if item.budget}
              <span class="text-xs text-amber-600 dark:text-amber-400 font-medium shrink-0">{item.budget}</span>
            {/if}
          </a>
        {/each}
      </div>
    {/if}
  </div>
</div>

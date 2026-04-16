<script>
  import { onMount } from 'svelte'

  let stats = { total: 0, gov: 0, eng: 0, budget: 0 }
  let loading = true

  onMount(async () => {
    try {
      const res = await fetch('/api/stats/user')
      if (res.ok) {
        const data = await res.json()
        stats = { total: data.total || 0, gov: data.gov_count || 0, eng: data.eng_count || 0, budget: data.budget_count || 0 }
      }
    } catch (e) {
      console.warn('Stats API:', e)
    }
    loading = false
  })
</script>

<div class="space-y-6">
  <h1 class="text-2xl font-bold text-gray-900 dark:text-white">数据分析</h1>
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
    <div class="bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 rounded-lg p-4">
      <div class="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">采集项目</div>
      <p class="text-5xl font-bold tracking-tight text-blue-600 dark:text-blue-400">{stats.total}</p>
    </div>
    <div class="bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 rounded-lg p-4">
      <div class="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">政府项目</div>
      <p class="text-5xl font-bold tracking-tight text-green-600 dark:text-green-400">{stats.gov}</p>
    </div>
    <div class="bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 rounded-lg p-4">
      <div class="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">工程项目</div>
      <p class="text-5xl font-bold tracking-tight text-purple-600 dark:text-purple-400">{stats.eng}</p>
    </div>
    <div class="bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 rounded-lg p-4">
      <div class="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">有预算</div>
      <p class="text-5xl font-bold tracking-tight text-amber-600 dark:text-amber-400">{stats.budget}</p>
    </div>
  </div>
</div>

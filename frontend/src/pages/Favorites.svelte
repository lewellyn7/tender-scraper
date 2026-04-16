<script>
  import { onMount } from 'svelte'

  let items = []
  let loading = true

  onMount(async () => {
    try {
      const res = await fetch('/api/favorites')
      if (res.ok) {
        const data = await res.json()
        items = data.items || data || []
      }
    } catch (e) {
      console.warn('Favorites API:', e)
    }
    loading = false
  })

  function getStatusColor(status) {
    return { pending: 'bg-yellow-400', tracking: 'bg-blue-400', archived: 'bg-gray-400' }[status] || 'bg-gray-300'
  }
</script>

<div class="space-y-4">
  <h1 class="text-2xl font-bold text-gray-900 dark:text-white">我的收藏</h1>

  {#if loading}
    <div class="text-gray-400">加载中...</div>
  {:else if items.length === 0}
    <div class="text-gray-400 text-sm">暂无收藏</div>
  {:else}
    <div class="space-y-2">
      {#each items as item}
        <div class="group flex items-center gap-3 px-4 py-3 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 rounded-lg hover:bg-gray-50 dark:hover:bg-white/8 transition-colors duration-100">
          <span class="w-2 h-2 rounded-full flex-shrink-0 {getStatusColor(item.status)}"></span>
          <div class="flex-1 min-w-0">
            <div class="text-sm font-medium text-gray-900 dark:text-white truncate">{item.title || '—'}</div>
            <div class="text-xs text-gray-500 mt-0.5">
              <span>{item.tender_type || '-'}</span>
              <span class="ml-2">{item.publish_date || '-'}</span>
            </div>
          </div>
          <div class="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity duration-100">
            <a href="{item.project_url || '#'}" target="_blank" class="text-gray-400 hover:text-blue-500 p-1.5 rounded hover:bg-white/10">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
            </a>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<script>
  import { onMount } from 'svelte'

  let items = []
  let loading = true
  let view = 'card'

  onMount(async () => {
    try {
      const res = await fetch('/api/projects?limit=50')
      if (res.ok) {
        const data = await res.json()
        items = data.projects || data.items || []
      }
    } catch (e) {
      console.warn('Projects API:', e)
    }
    loading = false
  })

  function getStatusColor(status) {
    return { pending: 'bg-yellow-400', tracking: 'bg-blue-400', archived: 'bg-gray-400' }[status] || 'bg-gray-300'
  }
  function getStatusLabel(status) {
    return { pending: '待跟进', tracking: '跟踪中', archived: '已归档' }[status] || status
  }
</script>

<div class="space-y-4">
  <div class="flex justify-between items-center">
    <h1 class="text-2xl font-bold text-gray-900 dark:text-white">采集内容</h1>
    <div class="flex gap-2">
      <input type="text" placeholder="搜索..." class="border rounded px-3 py-1.5 text-sm bg-white dark:bg-gray-800 dark:border-gray-600" />
    </div>
  </div>

  {#if loading}
    <div class="text-gray-400">加载中...</div>
  {:else if items.length === 0}
    <div class="text-gray-400 text-sm">暂无数据 — 采集系统正在运行中</div>
  {:else}
    <div class="space-y-2">
      {#each items as item}
        <div class="group flex items-center gap-3 px-4 py-3 bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 rounded-lg hover:bg-gray-50 dark:hover:bg-white/8 transition-colors duration-100 cursor-pointer">
          <span class="w-2 h-2 rounded-full flex-shrink-0 {getStatusColor(item.status)}"></span>
          <div class="flex-1 min-w-0">
            <div class="text-sm font-medium text-gray-900 dark:text-white truncate">{item.title || '—'}</div>
            <div class="flex items-center gap-3 text-xs text-gray-500 mt-0.5">
              <span>{item.tender_type || item.source || '-'}</span>
              <span>{item.publish_date || item.created_at || '-'}</span>
            </div>
          </div>
          <div class="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity duration-100">
            <a href="{item.project_url || '#'}" target="_blank" class="text-gray-400 hover:text-blue-500 p-1.5 rounded hover:bg-white/10" title="查看">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
            </a>
            <button class="text-red-400 hover:text-red-600 p-1.5 rounded hover:bg-white/10" title="收藏">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"/></svg>
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

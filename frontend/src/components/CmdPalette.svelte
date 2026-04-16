<script>
  import { onMount } from 'svelte'

  let open = false
  let query = ''
  let selected = 0

  const commands = [
    { label: '采集内容', action: () => navigate('/data'), icon: '📋' },
    { label: '我的收藏', action: () => navigate('/favorites'), icon: '⭐' },
    { label: '数据分析', action: () => navigate('/analytics'), icon: '📈' },
    { label: '任务管理', action: () => navigate('/tasks'), icon: '📅' },
    { label: '系统设置', action: () => navigate('/settings'), icon: '⚙️' }
  ]

  let filtered = commands

  onMount(() => {
    window.addEventListener('open-cmd-palette', () => { open = true })
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  })

  function handleKey(e) {
    if (!open) return
    if (e.key === 'Escape') open = false
    if (e.key === 'ArrowDown') { selected = Math.min(selected + 1, filtered.length - 1) }
    if (e.key === 'ArrowUp') { selected = Math.max(selected - 1, 0) }
    if (e.key === 'Enter' && filtered[selected]) { execute(filtered[selected]) }
  }

  function execute(cmd) {
    cmd.action()
    open = false
    query = ''
  }

  function navigate(href) {
    window.location.hash = href
  }

  $: filtered = query
    ? commands.filter(c => c.label.includes(query))
    : commands
</script>

{#if open}
  <div class="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]" onclick|self={() => open = false}>
    <div class="absolute inset-0 bg-black/40 backdrop-blur-sm"></div>
    <div class="relative w-full max-w-lg bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-white/10 rounded-xl shadow-2xl overflow-hidden" style="animation: slideDown 150ms ease-out">
      <div class="flex items-center gap-3 px-4 py-3 border-b border-gray-100 dark:border-white/5">
        <svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
        <input
          bind:value={query}
          placeholder="输入命令..."
          class="flex-1 bg-transparent text-sm text-gray-900 dark:text-white outline-none placeholder-gray-400"
          autofocus
        />
        <kbd class="text-xs text-gray-400 bg-gray-100 dark:bg-white/5 px-1.5 py-0.5 rounded">Esc</kbd>
      </div>
      <div class="py-2 max-h-80 overflow-y-auto">
        {#each filtered as cmd, i}
          <button
            on:click={() => execute(cmd)}
            class="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left transition-colors duration-75 {i === selected ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400' : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5'}"
          >
            <span class="w-5 text-center">{cmd.icon}</span>
            <span>{cmd.label}</span>
          </button>
        {/each}
        {#if filtered.length === 0}
          <div class="px-4 py-6 text-center text-sm text-gray-400">无结果</div>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  @keyframes slideDown {
    from { opacity: 0; transform: translateY(-8px); }
    to { opacity: 1; transform: translateY(0); }
  }
</style>

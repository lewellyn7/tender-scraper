<script>
  export let route = '/data'
  export let user = null

  const navItems = [
    { href: '/data', label: '采集内容' },
    { href: '/favorites', label: '收藏' },
    { href: '/analytics', label: '分析' },
    { href: '/tasks', label: '任务' },
    { href: '/logs', label: '日志' },
    { href: '/settings', label: '设置' }
  ]

  function navigate(href) {
    window.location.hash = href
    route = href
  }
</script>

<nav class="bg-white dark:bg-[#0f1011] border-b border-gray-200 dark:border-white/5 sticky top-0 z-40">
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <div class="flex items-center h-12 gap-1">
      <button on:click={() => navigate('/data')} class="flex items-center gap-2 pr-4 border-r border-gray-200 dark:border-white/10 mr-2 flex-shrink-0">
        <span class="text-lg">📊</span>
        <span class="text-sm font-semibold text-gray-900 dark:text-white hidden sm:block">采集系统</span>
      </button>
      <div class="hidden md:flex items-center gap-0.5">
        {#each navItems as item}
          <button
            on:click={() => navigate(item.href)}
            class="px-2.5 py-1 text-sm font-normal rounded-md transition-all duration-100 {route === item.href
              ? 'bg-blue-600 text-white'
              : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-white/5'}"
          >
            {item.label}
          </button>
        {/each}
      </div>
      <div class="flex-1"></div>
      <button
        on:click={() => window.dispatchEvent(new CustomEvent('open-cmd-palette'))}
        class="hidden sm:flex items-center gap-1.5 px-2.5 py-1 text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 bg-gray-100 dark:bg-white/5 hover:bg-gray-200 dark:hover:bg-white/10 rounded-md transition-colors duration-100 border border-gray-200 dark:border-white/10"
      >
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
        <span>⌘K</span>
      </button>
      {#if user}
        <div class="flex items-center gap-1.5 px-2 py-1 rounded-md">
          <div class="w-5 h-5 rounded-full bg-blue-600 flex items-center justify-center text-xs font-medium text-white">
            {user.display_name?.[0] || user.username?.[0] || '?'}
          </div>
          <span class="text-xs text-gray-600 dark:text-gray-400 hidden md:block">{user.display_name || user.username}</span>
        </div>
      {:else}
        <button on:click={() => navigate('/login')} class="text-xs text-blue-600 hover:text-blue-500 font-medium">登录</button>
      {/if}
    </div>
  </div>
</nav>

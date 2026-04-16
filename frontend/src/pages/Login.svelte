<script>
  import { onMount } from 'svelte'
  let username = ''
  let password = ''
  let error = ''

  async function login() {
    try {
      const res = await fetch('/api/users/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      })
      const data = await res.json()
      if (res.ok) {
        window.location.hash = '/data'
        window.location.reload()
      } else {
        error = data.detail || '登录失败'
      }
    } catch (e) {
      error = '登录失败'
    }
  }
</script>

<div class="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-[#0f1011]">
  <div class="w-full max-w-sm bg-white dark:bg-white/5 border border-gray-200 dark:border-white/10 rounded-xl p-8">
    <h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-6">登录</h1>
    {#if error}
      <div class="mb-4 text-sm text-red-500">{error}</div>
    {/if}
    <form on:submit|preventDefault={login} class="space-y-4">
      <input bind:value={username} type="text" placeholder="用户名" class="w-full border rounded-lg px-3 py-2 bg-white dark:bg-gray-800 dark:border-gray-600 text-sm" />
      <input bind:value={password} type="password" placeholder="密码" class="w-full border rounded-lg px-3 py-2 bg-white dark:bg-gray-800 dark:border-gray-600 text-sm" />
      <button type="submit" class="w-full bg-blue-600 text-white rounded-lg py-2 text-sm font-medium hover:bg-blue-700">登录</button>
    </form>
  </div>
</div>

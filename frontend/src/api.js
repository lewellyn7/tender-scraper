const API_BASE = '/api'

export async function getUser() {
  const res = await fetch(`${API_BASE}/user/me`)
  return res.ok ? res.json() : null
}

export async function getProjects(params = {}) {
  const qs = new URLSearchParams(params).toString()
  const res = await fetch(`${API_BASE}/projects?${qs}`)
  return res.ok ? res.json() : { projects: [] }
}

export async function getFavorites() {
  const res = await fetch(`${API_BASE}/favorites`)
  return res.ok ? res.json() : []
}

export async function getStats() {
  const res = await fetch(`${API_BASE}/stats/user`)
  return res.ok ? res.json() : {}
}

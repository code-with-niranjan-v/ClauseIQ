const { chromium } = require('playwright')
const { writeFile } = require('node:fs/promises')

const [output, target, maxBytes, ...hosts] = process.argv.slice(2)
const limit = Number(maxBytes)

function allowed(value) {
  const url = new URL(value)
  return url.protocol === 'https:' && !url.port && !url.username && !url.password
    && hosts.includes(url.hostname)
}

async function download() {
  if (!allowed(target)) throw new Error('PDF URL is outside the configured HTTPS allowlist')
  const browser = await chromium.launch({ timeout: 5000 })
  try {
    const context = await browser.newContext({ serviceWorkers: 'block' })
    await context.routeWebSocket('**/*', socket => socket.close())
    let complete
    const pdf = new Promise(resolve => { complete = resolve })
    await context.route('**/*', async route => {
      const request = route.request()
      if (!allowed(request.url())) return route.abort()
      try {
        const response = await route.fetch({ maxRedirects: 0, timeout: 4000 })
        try {
          const status = response.status()
          const headers = response.headers()
          // Playwright only routes the first hop. Keep redirects outside this browser fallback.
          if ((status >= 300 && status < 400) || Number(headers['content-length']) > limit) {
            return await route.abort()
          }
          const contentType = headers['content-type'] ?? ''
          if (status === 200 && (request.isNavigationRequest() || /^application\/pdf\b/i.test(contentType))) {
            const bytes = await response.body()
            if (bytes.length > limit) return await route.abort()
            if (bytes.subarray(0, 5).toString('ascii') === '%PDF-') {
              complete(bytes)
              return await route.abort()
            }
          }
          await route.fulfill({ response })
        } finally {
          await response.dispose()
        }
      } catch {
        await route.abort().catch(() => {})
      }
    })
    const page = await context.newPage()
    const navigation = page.goto(target, { waitUntil: 'commit', timeout: 7000 }).catch(() => {})
    const timer = new Promise(resolve => setTimeout(() => resolve(null), 8500).unref())
    const bytes = await Promise.race([pdf, timer])
    if (!bytes) throw new Error('Browser did not receive PDF bytes')
    await navigation
    await writeFile(output, bytes)
  } finally {
    await browser.close()
  }
}

download().catch(error => {
  console.error(error.message)
  process.exitCode = 1
})

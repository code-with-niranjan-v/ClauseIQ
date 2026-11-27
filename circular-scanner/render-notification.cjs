const { chromium } = require('playwright')
const { readFile } = require('node:fs/promises')

async function render() {
  const [output, input] = process.argv.slice(2)
  const html = await readFile(input, 'utf8')
  const browser = await chromium.launch({ timeout: 5000 })
  try {
    const context = await browser.newContext({ offline: true, javaScriptEnabled: false })
    const page = await context.newPage()
    await page.setContent(`<meta charset="utf-8"><style>
      body { font: 11pt sans-serif; line-height: 1.4 }
      table { border-collapse: collapse; max-width: 100% }
      td, th { padding: 0.2em; overflow-wrap: anywhere }
      img { display: none }
    </style>${html}`, { timeout: 5000 })
    await page.pdf({ path: output, format: 'A4', margin: {
      top: '15mm', bottom: '15mm', left: '15mm', right: '15mm',
    } })
  } finally {
    await browser.close()
  }
}

render().catch(error => {
  console.error(error.message)
  process.exitCode = 1
})

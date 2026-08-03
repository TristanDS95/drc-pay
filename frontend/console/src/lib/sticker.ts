// Opens a print-ready USSD sticker in a new window: the dial code big, the static-till QR, and
// plain-language instructions. Ported from the live console. All text is passed in already
// translated; `body` is trusted literal markup (never user data), so it's written as-is.

interface StickerText {
  title: string
  lead: string
  body: string
}

export function printSticker(merchant: { id: string; name: string; ussd_string: string }, s: StickerText): void {
  // Absolute URL: the print window is about:blank with no base, so a relative path won't resolve.
  const qrUrl = `${location.origin}/merchants/${merchant.id}/qr.svg`
  const esc = (v: string) => v.replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`)
  const w = window.open('', 'sticker', 'width=440,height=640')
  if (!w) return // popup blocked - the merchant can retry
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(s.title)}</title>
<style>
  *{box-sizing:border-box;margin:0;font-family:-apple-system,system-ui,sans-serif}
  body{padding:30px 26px;text-align:center;color:#111}
  .brand{font-weight:800;font-size:15px;letter-spacing:-.01em;color:#c6432b}
  .lead{font-size:13px;color:#555;margin:6px 0 18px;line-height:1.45}
  .name{font-size:20px;font-weight:800;margin-bottom:14px}
  img{width:230px;height:230px;display:block;margin:0 auto}
  .code{font-size:30px;font-weight:800;letter-spacing:.02em;margin:16px 0 4px}
  .body{font-size:12.5px;color:#444;line-height:1.5;margin-top:10px}
  @media print{body{padding:12px}}
</style></head><body>
  <div class="brand">InterPay</div>
  <p class="lead">${esc(s.lead)}</p>
  <div class="name">${esc(merchant.name)}</div>
  <img src="${qrUrl}" alt="">
  <div class="code">${esc(merchant.ussd_string)}</div>
  <p class="body">${s.body}</p>
</body></html>`)
  w.document.close()
  // Print once the QR image has loaded (or errored) - never a half-rendered sticker.
  const img = w.document.querySelector('img')
  const go = () => w.print()
  if (img && !img.complete) {
    img.addEventListener('load', go)
    img.addEventListener('error', go)
  } else {
    w.setTimeout(go, 200)
  }
}

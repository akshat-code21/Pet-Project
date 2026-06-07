'use client'
import { Streamdown } from 'streamdown'
import { ScrollArea } from '@/components/ui/scroll-area'

function cleanMarkdown(content: string): string {
  if (!content) return ''
  let cleaned = content.trim()
  
  // 1. Remove markdown code block fences if present
  cleaned = cleaned.replace(/^```markdown\s*/i, '')
  cleaned = cleaned.replace(/```$/, '')
  cleaned = cleaned.trim()

  // 2. Strip redundant metadata header if it exists
  const hrIndex = cleaned.search(/^(?:---|___|\*\*\*)\s*$/m)
  if (hrIndex !== -1 && hrIndex < 500) {
    const afterHr = cleaned.slice(hrIndex).replace(/^(?:---|___|\*\*\*)\s*$/m, '').trim()
    return afterHr
  }

  return cleaned
}

export function ReportViewer({ markdown }: { markdown: string }) {
  return (
    <ScrollArea className="max-h-[70vh]">
      <div className="p-6 prose-custom">
        <Streamdown>{cleanMarkdown(markdown)}</Streamdown>
      </div>
    </ScrollArea>
  )
}


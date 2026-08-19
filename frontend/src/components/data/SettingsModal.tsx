import { Modal as MantineModal } from '@mantine/core'
import { X } from 'lucide-react'

export function SettingsModal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <MantineModal
      opened
      onClose={onClose}
      withCloseButton={false}
      centered
      padding={0}
      transitionProps={{ duration: 150 }}
      overlayProps={{ backgroundOpacity: 0.6, blur: 4 }}
      classNames={{ content: 'rounded-card border border-border bg-surface shadow-2xl mx-4 w-full max-w-md overflow-hidden' }}
      styles={{ content: { flex: '0 1 auto' } }}
    >
      <div className="flex items-center justify-between px-5 py-3 border-b border-border">
        <h3 className="text-sm font-medium text-foreground">{title}</h3>
        <button onClick={onClose} className="p-0.5 rounded hover:bg-elevated text-secondary">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="p-5">
        {children}
      </div>
    </MantineModal>
  )
}

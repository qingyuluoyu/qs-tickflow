import { useAskDialogState, useAskDialogTask } from '@/lib/askAiStore'
import { AskAiDialog } from './AskAiDialog'

export function AskAiHost() {
  const task = useAskDialogTask()
  const state = useAskDialogState()
  return <AskAiDialog task={task} minimized={state.minimized} />
}

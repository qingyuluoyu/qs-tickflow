import { useEffect, type ReactNode } from 'react'
import { Modal as MantineModal } from '@mantine/core'

/**
 * 共享模态对话框原语 — 基于 Mantine Modal 实现:
 * - role="dialog" + aria-modal 由 Mantine 提供
 * - ESC 关闭 / Tab 焦点陷阱 / 关闭后还原焦点 / 点击遮罩关闭 均由 Mantine 内置处理
 *   (遮罩与面板是兄弟节点, 面板内拖选文本松开在遮罩上不会误关 — 无需手写防穿透)
 *
 * 视觉: panelClassName 定制面板 (尺寸/背景/圆角等);
 * overlayClassName 仅保留透明度/模糊语义 (旧的 fixed/flex 布局类由 Mantine 接管, 会被忽略)。
 */
export interface ModalProps {
  onClose: () => void
  children: ReactNode
  /** 对话框标题元素 id (用于 aria-labelledby; 标题元素仍由调用方渲染) */
  labelledBy?: string
  /** 无可见标题时的无障碍名称 */
  ariaLabel?: string
  /** 面板 className (尺寸/背景/圆角等) */
  panelClassName?: string
  /** 遮罩 className (仅解析 bg-black/40 透明度与 backdrop-blur 语义) */
  overlayClassName?: string
  /** 打开时聚焦的元素; 不传则 Mantine 焦点陷阱聚焦面板内首个可聚焦元素 */
  initialFocusRef?: React.RefObject<HTMLElement | null>
  /** 点击遮罩是否关闭 (默认 true) */
  closeOnBackdrop?: boolean
}

export function Modal({
  onClose,
  children,
  labelledBy,
  ariaLabel,
  panelClassName = 'w-[92vw] max-w-lg bg-surface border border-border rounded-card shadow-xl',
  overlayClassName,
  initialFocusRef,
  closeOnBackdrop = true,
}: ModalProps) {
  // Mantine 仅在挂载了 Modal.Title 时才输出 aria-labelledby; 这里直接在内容元素上
  // 补齐, 保持原有 labelledBy 契约 (可见标题元素由调用方渲染, id 即 labelledBy)。
  const contentRef = (el: HTMLDivElement | null) => {
    if (!labelledBy) return
    el?.querySelector('[role="dialog"]')?.setAttribute('aria-labelledby', labelledBy)
  }

  // initialFocusRef: Mantine 焦点陷阱默认聚焦首个可聚焦元素; 传了 ref 则改聚焦它
  useEffect(() => {
    if (!initialFocusRef) return
    const raf = requestAnimationFrame(() => initialFocusRef.current?.focus())
    return () => cancelAnimationFrame(raf)
  }, [initialFocusRef])

  return (
    <MantineModal
      opened
      onClose={onClose}
      ref={contentRef}
      withCloseButton={false}
      closeOnClickOutside={closeOnBackdrop}
      centered
      padding={0}
      transitionProps={{ duration: 150 }}
      overlayProps={{
        backgroundOpacity: overlayClassName?.includes('bg-black/40') ? 0.4 : 0.5,
        blur: overlayClassName && !overlayClassName.includes('backdrop-blur') ? 0 : 4,
      }}
      classNames={{
        content: panelClassName,
        // 面板为 flex 列布局时让 body 撑满高度, 保持头部/底部固定、内容区内部滚动
        body: 'flex min-h-0 flex-1 flex-col',
      }}
      // 宽度完全交给 panelClassName 的 w-*/max-w-* 控制 (默认 flex-basis 会覆盖 width)
      styles={{ content: { flex: '0 1 auto' } }}
      attributes={ariaLabel && !labelledBy ? { content: { 'aria-label': ariaLabel } } : undefined}
    >
      {children}
    </MantineModal>
  )
}

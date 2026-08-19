import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { storage, storageForUser } from '@/lib/storage'

export function useStrategyPool(userId?: string) {
  const poolStorage = useMemo(
    () => userId ? storageForUser(userId).strategyPool : storage.strategyPool,
    [userId],
  )
  const [pool, setPool] = useState<string[]>(() => poolStorage.get([]))
  const skipPersist = useRef(true)

  // 账户切换时先读取该账户的策略池,避免把上一个账户的池写入新账户。
  useEffect(() => {
    skipPersist.current = true
    setPool(poolStorage.get([]))
  }, [poolStorage])

  // 同步写入当前账户自己的 localStorage 命名空间。
  useEffect(() => {
    if (skipPersist.current) {
      skipPersist.current = false
      return
    }
    poolStorage.set(pool)
  }, [pool, poolStorage])

  const addToPool = useCallback((id: string) => {
    setPool(prev => prev.includes(id) ? prev : [...prev, id])
  }, [])

  const removeFromPool = useCallback((id: string) => {
    setPool(prev => prev.filter(x => x !== id))
  }, [])

  const reorderPool = useCallback((newOrder: string[]) => {
    setPool(newOrder)
  }, [])

  // 清除池中不存在于 validIds 的失效策略(如本地开发残留的自定义策略)。
  // 仅当确实有失效项时才更新,避免无谓重渲染。
  const prune = useCallback((validIds: Iterable<string>) => {
    const validSet = validIds instanceof Set ? validIds : new Set(validIds)
    setPool(prev => {
      if (prev.length === 0) return prev
      const next = prev.filter(id => validSet.has(id))
      return next.length === prev.length ? prev : next
    })
  }, [])

  const isInPool = useCallback((id: string) => pool.includes(id), [pool])

  return { pool, addToPool, removeFromPool, reorderPool, prune, isInPool }
}

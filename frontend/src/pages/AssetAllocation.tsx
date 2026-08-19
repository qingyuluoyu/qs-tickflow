import { useState } from 'react'

/**
 * React 子路由只负责复用主工作台外壳；教学内容继续由已有静态页面承载，
 * 避免维护第二套页面结构，同时保留 /asset-allocation.html 作为独立兼容入口。
 */
export function AssetAllocation() {
  const [loaded, setLoaded] = useState(false)

  return (
    <div className="relative h-[calc(100dvh-52px)] min-h-0 overflow-hidden bg-base">
      {!loaded && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-base text-sm text-muted">
          正在加载资产配置教学内容…
        </div>
      )}
      <iframe
        title="资产配置教学"
        src="/asset-allocation.html?embed=1"
        onLoad={() => setLoaded(true)}
        className="block h-full w-full border-0"
      />
    </div>
  )
}

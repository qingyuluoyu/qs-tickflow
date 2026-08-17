/**
 * A restarted dev server can leave an already-open tab with a stale lazy
 * module graph. Keep this hook-free so it can still render when the original
 * error was an invalid-hook-call caused by that stale graph.
 */
export function RouteErrorFallback() {
  return (
    <main className="min-h-screen bg-base flex items-center justify-center px-6 text-center">
      <section className="max-w-md rounded-card border border-border bg-elevated p-6 shadow-card">
        <h1 className="text-lg font-semibold text-foreground">页面需要重新加载</h1>
        <p className="mt-2 text-sm leading-relaxed text-secondary">
          页面资源刚刚更新，重新加载后即可继续使用。你的账户和已保存的数据不会受影响。
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-5 rounded-btn bg-accent px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
        >
          重新加载
        </button>
      </section>
    </main>
  )
}

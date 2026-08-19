const NAV_ROUTE_ALIASES: Readonly<Record<string, string>> = {
  '/asset-allocation.html': '/asset-allocation',
}

export function canonicalNavRoute(route: string) {
  return NAV_ROUTE_ALIASES[route] ?? route
}

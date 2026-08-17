interface LogoProps {
  className?: string
  size?: number
  style?: React.CSSProperties
}

export function Logo({ className, size = 32, style }: LogoProps) {
  return (
    <img
      src="/brand-icon.png"
      alt="清数智算"
      width={size}
      height={size}
      className={className}
      style={style}
    />
  )
}

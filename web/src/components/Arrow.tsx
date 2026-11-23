// The two arrows the landing page uses, drawn inline (an icon package for two arrows weighed 149 MB).
export function ArrowDown({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M18 9.5 12 15.5 6 9.5" />
    </svg>
  );
}

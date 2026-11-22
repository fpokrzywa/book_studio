/**
 * The ONLY place the UI inserts HTML (docs/SECURITY.md section 2).
 *
 * The markup comes from Core's renderer: every text value is escaped, links with unsafe schemes
 * are inert, external images are not loaded, and the result is cleaned again by nh3 (ammonia)
 * with an allowlist before it leaves Core. Nothing else may pass HTML to this component.
 */
export function SanitizedHtml({
  html,
  className,
  label,
}: {
  html: string;
  className?: string;
  label: string;
}) {
  return (
    <div
      className={className}
      role="document"
      aria-label={label}
      // eslint-disable-next-line no-restricted-syntax -- Core-sanitized markup only; see the comment above.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

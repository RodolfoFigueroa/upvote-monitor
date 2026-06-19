export type SecretPreview = {
  configured: boolean;
  prefix: string | null;
  suffix: string | null;
};

export function secretPlaceholder(
  secretsAvailable: boolean,
  preview: SecretPreview
): string {
  if (!secretsAvailable) return 'secrets unavailable';
  if (!preview.configured) return 'not configured';
  if (preview.prefix && preview.suffix) return `${preview.prefix}...${preview.suffix}`;
  if (preview.prefix) return `${preview.prefix}...`;
  if (preview.suffix) return `...${preview.suffix}`;
  return 'configured';
}

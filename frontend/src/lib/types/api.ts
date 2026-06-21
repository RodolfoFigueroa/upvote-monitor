export type ApprovalStatus = 'rejected' | 'approved' | 'under_review';
export type DownloadStatus = 'pending' | 'in_progress' | 'completed' | 'failed';
export type AnalysisStatus = 'completed' | 'failed' | 'skipped';
export type ApprovalMode = 'auto' | 'manual';
export type RuleTargetType = 'community' | 'author';
export type IllustrationLabel = 'unlabeled' | 'yes' | 'no' | 'unsure';

export interface AnalysisProfile {
  id: string;
  name: string;
  model_name: string;
  model_version: string;
  scoring_version: string;
  general_tag_storage_threshold: number;
  character_tag_storage_threshold: number;
  general_tag_display_threshold: number;
  character_tag_display_threshold: number;
  auto_approve_threshold: number;
  enabled: boolean;
}

export interface MediaAnalysis {
  analysis_profile_id: string;
  status: AnalysisStatus;
  model_name: string;
  model_version: string;
  scoring_version: string;
  illustration_score: number | null;
  general_tags: Record<string, number>;
  character_tags: Record<string, number>;
  ratings: Record<string, number>;
  stored_general_tag_count: number;
  stored_character_tag_count: number;
  error: string | null;
  analyzed_at: string | null;
}

export interface MediaAttachment {
  id: number;
  item_id: string;
  sort_index: number;
  media_type: string;
  content_type: string | null;
  download_url: string;
  preview_url: string | null;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  extension: string | null;
  download_strategy: string;
  approval_status: ApprovalStatus;
  illustration_label: IllustrationLabel;
  analysis: MediaAnalysis | null;
  analyses: MediaAnalysis[];
}

export interface ItemSummary {
  id: string;
  source: string;
  source_item_id: string;
  title: string;
  author_name: string | null;
  author_label: string | null;
  community_name: string | null;
  community_label: string | null;
  item_kind: string;
  approval_status: ApprovalStatus;
  download_status: DownloadStatus;
  created_at: string;
  source_url: string;
  media_count: number;
  discovered_at: string;
  downloaded_at: string | null;
  preview_urls: string[];
  analysis_status: AnalysisStatus | null;
  illustration_score: number | null;
  media_approved_count: number;
  media_rejected_count: number;
  media_under_review_count: number;
  media_unlabeled_count: number;
}

export interface ItemDetail extends ItemSummary {
  download_error: string | null;
  source_urls: string[];
  media: MediaAttachment[];
}

export interface ItemListResponse {
  items: ItemSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface MediaItem {
  id: number;
  item_id: string;
  item_title: string;
  source: string;
  source_item_id: string;
  source_url: string;
  author_name: string | null;
  author_label: string | null;
  community_name: string | null;
  community_label: string | null;
  item_kind: string;
  item_created_at: string;
  discovered_at: string;
  item_approval_status: ApprovalStatus;
  item_download_status: DownloadStatus;
  sort_index: number;
  media_type: string;
  content_type: string | null;
  download_url: string;
  preview_url: string | null;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  extension: string | null;
  download_strategy: string;
  approval_status: ApprovalStatus;
  illustration_label: IllustrationLabel;
  analysis: MediaAnalysis | null;
  analyses: MediaAnalysis[];
}

export interface MediaListResponse {
  media: MediaItem[];
  total: number;
  limit: number;
  offset: number;
  next_cursor: string | null;
}

export interface MediaUpdate {
  approval_status?: ApprovalStatus;
  illustration_label?: IllustrationLabel;
}

export interface ItemFile {
  filename: string;
  url: string;
  media_type: string;
}

export interface ItemFilesResponse {
  item_id: string;
  files: ItemFile[];
}

export interface SettingsResponse {
  approval_mode: ApprovalMode;
  refresh_cron: string;
  refresh_enabled: boolean;
  download_base_dir: string;
  illustration_tagger_enabled: boolean;
  illustration_auto_approve_enabled: boolean;
  active_analysis_profile_id: string;
  general_tag_display_threshold: number;
  character_tag_display_threshold: number;
  analysis_profiles: AnalysisProfile[];
  sources: SourceSettingsResponse;
}

export interface SettingsUpdate {
  approval_mode?: ApprovalMode;
  refresh_cron?: string;
  refresh_enabled?: boolean;
  download_base_dir?: string;
  illustration_tagger_enabled?: boolean;
  illustration_auto_approve_enabled?: boolean;
  active_analysis_profile_id?: string;
  general_tag_display_threshold?: number;
  character_tag_display_threshold?: number;
  sources?: SourceSettingsUpdate;
}

export interface RedditSourceSettingsResponse {
  enabled: boolean;
  username: string;
  page_limit: number;
  page_size: number;
  user_agent: string;
  session_cookie_configured: boolean;
  session_cookie_prefix: string | null;
  session_cookie_suffix: string | null;
  secrets_available: boolean;
}

export interface XSourceSettingsResponse {
  enabled: boolean;
  page_limit: number;
  page_size: number;
  user_agent: string;
  auth_token_configured: boolean;
  auth_token_prefix: string | null;
  auth_token_suffix: string | null;
  ct0_configured: boolean;
  ct0_prefix: string | null;
  ct0_suffix: string | null;
  twid_configured: boolean;
  twid_prefix: string | null;
  twid_suffix: string | null;
  bearer_token_configured: boolean;
  bearer_token_prefix: string | null;
  bearer_token_suffix: string | null;
  secrets_available: boolean;
}

export interface SourceSettingsResponse {
  reddit: RedditSourceSettingsResponse;
  x: XSourceSettingsResponse;
}

export interface RedditSourceSettingsUpdate {
  enabled?: boolean;
  username?: string;
  page_limit?: number;
  user_agent?: string;
  session_cookie?: string;
}

export interface XSourceSettingsUpdate {
  enabled?: boolean;
  page_limit?: number;
  page_size?: number;
  user_agent?: string;
  auth_token?: string;
  ct0?: string;
  twid?: string;
  bearer_token?: string;
}

export interface SourceSettingsUpdate {
  reddit?: RedditSourceSettingsUpdate;
  x?: XSourceSettingsUpdate;
}

export interface RuleEntry {
  source: string;
  target_type: RuleTargetType;
  target_value: string;
  target_label: string;
}

export interface RuleListsResponse {
  whitelist: RuleEntry[];
  blacklist: RuleEntry[];
}

export interface RuleEntryRequest {
  source?: string;
  target_type?: RuleTargetType;
  target_value: string;
}

export interface RefreshRunResponse {
  id: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  new_items: number;
  skipped: number;
  downloads_triggered: number;
  downloads_failed: number;
  error: string | null;
}

export interface RefreshStartResponse {
  run_id: string;
  status: string;
}

export interface RefreshStatusResponse {
  is_running: boolean;
  latest_run: RefreshRunResponse | null;
}

export interface ItemListParams {
  approval_status?: ApprovalStatus;
  download_status?: DownloadStatus;
  source?: string | string[];
  community?: string;
  author?: string;
  limit?: number;
  offset?: number;
}

export interface MediaListParams {
  approval_status?: ApprovalStatus;
  illustration_label?: IllustrationLabel;
  download_status?: DownloadStatus;
  item_id?: string;
  media_id?: number;
  source?: string | string[];
  community?: string;
  author?: string;
  limit?: number;
  offset?: number;
  cursor?: string;
}

export interface ItemUpdatedEvent {
  item_id: string;
  download_status: DownloadStatus;
  approval_status: ApprovalStatus;
}

export interface ReviewQueueChangedEvent {
  source?: string;
  target_type?: RuleTargetType;
  target_value?: string;
  media_id?: number;
  reason?: string;
}

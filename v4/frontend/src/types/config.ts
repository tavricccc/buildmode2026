export interface ConfigVersion {
  id: string;
  base_version: string | null;
  created_by: string;
  created_at: string;
  activated_at: string | null;
  rolled_back_from: string | null;
}

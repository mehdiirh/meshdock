export type Role = "entry" | "exit" | "both";
export type Method = string;
export type Policy = "roundrobin" | "leastconn" | "failover";
export interface SSHJump {
  host: string;
  ssh_port: number;
  username: string;
  credential_id: string;
  fingerprint: string;
}
export interface Server {
  id: string;
  name: string;
  host: string;
  ssh_port: number;
  ssh_jump?: SSHJump | null;
  role: Role;
  address: string;
  credential_id: string;
  fingerprint: string;
  region: string;
  position: { x: number; y: number };
}
export interface Port {
  public: number | string;
  target: number | string;
  exclude?: (number | string)[];
  host: string;
}
export interface Link {
  id: string;
  entry_id: string;
  exit_id: string;
  method: Method;
  enabled: boolean;
  control_port?: number | null;
  ports: Port[];
  policy: Policy;
  weight: number;
  settings?: MethodSettings;
}
export type SettingValue = string | number | boolean;
export type MethodSettings = Record<string, SettingValue>;
export type SettingCondition = Record<string, SettingValue[]>;
export interface SettingField {
  type: "integer" | "boolean" | "string";
  default: SettingValue;
  enum?: SettingValue[];
  minimum?: number;
  maximum?: number;
  scope: "server" | "client" | "both";
  unit?: string;
  when?: SettingCondition;
}
export interface SettingsSchema {
  version: number;
  properties: Record<string, SettingField>;
  rules: {
    left: string;
    right: string;
    operator: "lt" | "lte";
    when?: SettingCondition;
  }[];
}
export interface PendingRemoval {
  link: Link;
  status:
    | "failed"
    | "cancelled"
    | "pending"
    | "removing"
    | "retrying"
    | "recovery_required";
}
export interface Topology {
  revision: number;
  applied_revision: number;
  pending_removals?: PendingRemoval[];
  removal_servers?: Server[];
  namespace: string;
  servers: Server[];
  links: Link[];
}
export interface Credential {
  id: string;
  name: string;
  kind: "password" | "key";
}
export interface MethodInfo {
  id: Method;
  name: string;
  encrypted: boolean;
  direction: string;
  protocols: string[];
  requirements: string[];
  mapping: {
    ranges: boolean;
    exceptions: boolean;
    native_ranges: boolean;
    max_ports: number;
    max_listener_ports: number;
    capacity_basis: "kernel" | "system_resources";
    forwards_per_session?: number | null;
    protocols: string[];
    platforms: string[];
  };
  control_protocol?: "tcp" | "udp" | null;
  priority?: number;
  score?: number;
  caveat?: string;
  settings_schema?: SettingsSchema;
  transports?: Record<
    string,
    {
      architectures?: string[];
      encrypted: boolean;
      control_protocols: ("tcp" | "udp")[];
      tls_mode: "none" | "verified_native" | "verified_bridge";
    }
  >;
}
export interface ForceDeletion {
  server_id: string;
  server_name: string;
  can_skip: boolean;
  hosts: {
    server_id: string;
    name: string;
    host: string;
    status: string;
    error_code?: string | null;
    error_message?: string | null;
  }[];
}
export interface Job {
  force_delete?: ForceDeletion;
  id: string;
  revision: number;
  kind: string;
  status: string;
  attempt: number;
  created: number;
  error_code: string | null;
  error_message?: string | null;
  cancel_requested?: number;
  link_ids?: string[];
  failure?: { server_id: string | null; code: string; detail: string } | null;
}
export interface Log {
  id: number;
  level: string;
  code: string;
  message: string;
  detail: string;
  server_id: string | null;
  created: number;
}
export interface Session {
  username: string;
  csrf: string;
  demo: boolean;
}
export interface Key {
  id: string;
  name: string;
  prefix: string;
  scope: string;
  revoked: number;
}
export const newId = () => crypto.randomUUID().replaceAll("-", "");

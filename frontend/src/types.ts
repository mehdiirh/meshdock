export type Role = "entry" | "exit" | "both";
export type Method = string;
export type Policy = "roundrobin" | "leastconn" | "failover";
export interface Server {
  id: string;
  name: string;
  host: string;
  ssh_port: number;
  role: Role;
  address: string;
  credential_id: string;
  fingerprint: string;
  region: string;
  position: { x: number; y: number };
}
export interface Port {
  public: number;
  target: number;
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
}
export interface Topology {
  revision: number;
  applied_revision: number;
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
  control_protocol?: "tcp" | "udp" | null;
  priority?: number;
  score?: number;
  caveat?: string;
}
export interface Job {
  id: string;
  revision: number;
  kind: string;
  status: string;
  attempt: number;
  created: number;
  error_code: string | null;
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

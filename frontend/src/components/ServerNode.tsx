import { memo } from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ArrowLeftRight,
  MoreHorizontal,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Server } from "../types";
export type ServerFlowNode = Node<
  { server: Server; status: string; edit: () => void },
  "server"
>;
export const ServerNode = memo(function ServerNode({
  data,
  selected,
}: NodeProps<ServerFlowNode>) {
  const { t } = useTranslation();
  const { server, status } = data;
  const Icon =
    server.role === "entry"
      ? ArrowDownToLine
      : server.role === "exit"
        ? ArrowUpFromLine
        : ArrowLeftRight;
  return (
    <div
      className={"server-node " + server.role + (selected ? " selected" : "")}
    >
      <Handle
        type="target"
        position={Position.Left}
        isConnectable={server.role !== "entry"}
        className={server.role === "entry" ? "hidden-handle" : ""}
      />
      <div className="node-header">
        <div className="node-icon">
          <Icon size={20} />
        </div>
        <span className="node-role">{t(server.role)}</span>
        <button
          className="nodrag icon-button"
          onClick={data.edit}
          aria-label={t("editServer")}
        >
          <MoreHorizontal size={18} />
        </button>
      </div>
      <strong>{server.name}</strong>
      <div className="node-address mono">{server.address}</div>
      <div className="node-footer">
        <span>
          <i className={"status-dot " + status} />
          {server.region || t(server.role)}
        </span>
        <span className="node-protocol">IPv4</span>
      </div>
      <Handle
        type="source"
        position={Position.Right}
        isConnectable={server.role !== "exit"}
        className={server.role === "exit" ? "hidden-handle" : ""}
      />
    </div>
  );
});
